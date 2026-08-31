import sys
import os
import re
import json
import csv
import random
import subprocess
import importlib
import math
import statistics
import time
from datetime import datetime

from PyQt5.QtWidgets import QApplication
from PyQt5.QtWidgets import QWidget
from PyQt5.QtWidgets import QLabel
from PyQt5.QtWidgets import QPushButton
from PyQt5.QtWidgets import QVBoxLayout
from PyQt5.QtWidgets import QHBoxLayout
from PyQt5.QtWidgets import QStackedWidget
from PyQt5.QtWidgets import QInputDialog
from PyQt5.QtWidgets import QLineEdit
from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtWidgets import QFrame
from PyQt5.QtWidgets import QGraphicsDropShadowEffect
from PyQt5.QtWidgets import QGridLayout
from PyQt5.QtWidgets import QProgressBar
from PyQt5.QtWidgets import QShortcut

from PyQt5.QtCore import Qt, QEvent, QTimer, QPointF, QRectF, QProcess
from PyQt5.QtGui import QColor, QPainter, QPen, QFont, QPainterPath, QLinearGradient, QIntValidator, QDoubleValidator, QImage, QPolygonF, QKeySequence


IDLE = "IDLE"
USER_SELECT = "USER_SELECT"
DRIVE = "DRIVE"
PARK_SAFE = "PARK_SAFE"
REPORT = "REPORT"

# 라즈베리파이에서 실제 디스플레이 출력까지 끄고/켜고 싶으면 True로 변경
# 개발용 노트북에서는 False 유지 추천
USE_REAL_DISPLAY_POWER = False

# Raspberry Pi Touch Display 2를 가로(Landscape)로 회전해서 사용하는 기준 크기.
# 제품 자체 해상도는 720x1280이지만, 프로젝트 UI는 가로 배치가 적합하므로 1280x720을 기본값으로 둔다.
# 예: SEAT_ID_SCREEN_WIDTH=1280 SEAT_ID_SCREEN_HEIGHT=720 SEAT_ID_FULLSCREEN=1 python3 app.py
TOUCH_DISPLAY_WIDTH = int(os.environ.get("SEAT_ID_SCREEN_WIDTH", "1280"))
TOUCH_DISPLAY_HEIGHT = int(os.environ.get("SEAT_ID_SCREEN_HEIGHT", "720"))

# 라즈베리파이 터치스크린에서는 전체화면을 기본으로 사용한다.
# 개발용 노트북에서 창 모드로 보고 싶으면 SEAT_ID_FULLSCREEN=0 으로 실행한다.
USE_TOUCH_DISPLAY_FULLSCREEN = os.environ.get("SEAT_ID_FULLSCREEN", "1").strip() != "0"

# 사용자 프로필을 저장할 파일.
# 하드웨어 제어부와 맞추기 위해 user_profile.csv를 기준으로 사용한다.
APP_DIR = os.path.dirname(os.path.abspath(__file__))
USER_PROFILES_FILE = os.path.join(APP_DIR, "user_profile.csv")
LEGACY_USERS_JSON_FILE = os.path.join(APP_DIR, "users.json")
LOG_DIR = os.path.join(APP_DIR, "logs")
HARDWARE_COMMAND_FILE = os.path.join(APP_DIR, "hardware_command.csv")
PRESSURE_REGISTRATION_FILE = os.path.join(APP_DIR, "pressure_user_registration.csv")
PRESSURE_SAMPLE_CSV = os.path.join(APP_DIR, "pressure_data", "current_pressure.csv")
SELECTED_SENSOR_POSITIONS_FILE = os.path.join(APP_DIR, "selected_sensor_positions.csv")


def load_selected_sensor_positions():
    """
    selected_sensor_positions.csv의 행 순서를 유지한 채 16개 센서 좌표를 읽는다.

    실시간 corrected_sensor 16개 값도 이 CSV 순서와 같은 순서로 들어온다는
    현재 SVM/Arduino 데이터 구조를 기준으로 한다.

    좌표 방향:
        Row 0  = 좌석 앞쪽(발을 뻗는 방향)
        Row 11 = 좌석 뒤쪽(등받이 방향)
        Column 0 = 운전자 기준 왼쪽
        Column 11 = 운전자 기준 오른쪽
    """

    fallback_positions = [
        (0, 2),
        (4, 6),
        (5, 3),
        (5, 5),
        (5, 8),
        (6, 3),
        (6, 5),
        (6, 8),
        (6, 9),
        (6, 10),
        (7, 3),
        (7, 4),
        (7, 8),
        (7, 9),
        (8, 3),
        (11, 0),
    ]

    if not os.path.exists(SELECTED_SENSOR_POSITIONS_FILE):
        print(
            "센서 위치 파일이 없어 기본 SFS 좌표를 사용합니다: "
            f"{SELECTED_SENSOR_POSITIONS_FILE}"
        )
        return fallback_positions

    try:
        with open(
            SELECTED_SENSOR_POSITIONS_FILE,
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as file:
            reader = csv.DictReader(file)
            positions = []

            for row in reader:
                row_value = row.get("Row", row.get("row", ""))
                column_value = row.get("Column", row.get("column", ""))

                grid_row = int(float(str(row_value).strip()))
                grid_column = int(float(str(column_value).strip()))

                if not (0 <= grid_row <= 11 and 0 <= grid_column <= 11):
                    raise ValueError(
                        f"센서 좌표가 12x12 범위를 벗어났습니다: "
                        f"({grid_row}, {grid_column})"
                    )

                positions.append((grid_row, grid_column))

        if len(positions) != 16:
            raise ValueError(
                f"센서 위치는 16개여야 하지만 {len(positions)}개입니다."
            )

        return positions

    except (OSError, TypeError, ValueError) as error:
        print(f"센서 위치 파일 읽기 실패, 기본 SFS 좌표 사용: {error}")
        return fallback_positions

# 체압 센서/SVM 연동 설정
# real_time_prediction_rasp.py가 같은 폴더에 있으면 실제 센서 예측을 우선 사용하고,
# 파일/포트/센서가 준비되지 않았으면 자동으로 기존 mock 데이터로 fallback한다.
USE_REAL_PRESSURE_SENSOR = True
PRESSURE_IDENTIFICATION_CONFIDENCE_THRESHOLD = 0.55
PRESSURE_IDENTIFICATION_MIN_USER_SAMPLES = 5
PRESSURE_IDENTIFICATION_MAX_USER_SAMPLES = 12
PRESSURE_IDENTIFICATION_MIN_CONSENSUS = 0.60

# S 버튼 입력 후 바로 사용자 식별을 하지 않고,
# 사용자가 바른 자세로 안정되게 앉을 시간을 확보한다.
# START(S) 시 체압 + 등 초음파 + 목 초음파 기준 측정을 함께 진행한다.
# 세 센서 중 하나라도 기준 측정에 실패하면 대시보드로 넘어가지 않는다.
# 초음파 모니터는 느린 출력 환경에서 기준값을 최대 10초까지 모을 수 있으므로
# 2초 안정화와 처리 여유를 포함해 한 회차의 최대 확인 시간을 14초로 둔다.
PRESSURE_IDENTIFICATION_MEASUREMENT_MS = 14000
PRESSURE_IDENTIFICATION_PROGRESS_INTERVAL_MS = 100
SENSOR_CALIBRATION_SETTLE_MS = 2000
SENSOR_CALIBRATION_MEASURE_MS = 5000
SENSOR_MEASUREMENT_TRIGGER_FILE = os.path.join(APP_DIR, "sensor_measurement_trigger.json")
SENSOR_READINESS_POLL_INTERVAL_MS = 250
SENSOR_RETRY_DELAY_MS = 1500

# 대시보드에서는 압력분포 히트맵과 SVM 자세 판단 주기를 분리한다.
# 히트맵은 최신 센서값만 빠르게 보여주고, 점수/자세 판단은 기존처럼 안정적으로 1초마다 갱신한다.
PRESSURE_HEATMAP_UPDATE_INTERVAL_MS = 150
PRESSURE_HEATMAP_MAX_WAIT_SEC = 0.03
PRESSURE_PREDICTION_MAX_WAIT_SEC = 0.25
DASHBOARD_ANALYSIS_INTERVAL_MS = 1000

# 초음파 등 곡률 모니터링 설정.
# spine_curve_monitor_4ch_no_s4.py가 같은 폴더의 posture_feedback.json을 계속 갱신하고,
# app.py는 이 파일을 읽어 왼쪽 위 카드에 등 구부러짐 정도를 시각화한다.
ULTRASONIC_POSTURE_FEEDBACK_FILE = os.environ.get(
    "SEAT_ID_ULTRASONIC_FEEDBACK",
    os.path.join(APP_DIR, "posture_feedback.json"),
)
ULTRASONIC_FEEDBACK_MAX_AGE_SEC = 6.0
ULTRASONIC_BACK_CURVE_UPDATE_INTERVAL_MS = 300

# 목/헤드 초음파 모니터링 설정.
# neck_cva_monitor_2ch.py가 neck_posture_feedback.json을 계속 갱신하고,
# app.py는 이 파일을 읽어 목 전방 이동 정도와 졸음 의심 상태를 표시한다.
NECK_POSTURE_FEEDBACK_FILE = os.environ.get(
    "SEAT_ID_NECK_FEEDBACK",
    os.path.join(APP_DIR, "neck_posture_feedback.json"),
)
NECK_FEEDBACK_MAX_AGE_SEC = 6.0
NECK_POSTURE_UPDATE_INTERVAL_MS = 300

def clear_sensor_measurement_trigger():
    """이전 실행에서 남은 START 측정 신호를 지운다."""
    try:
        if os.path.exists(SENSOR_MEASUREMENT_TRIGGER_FILE):
            os.remove(SENSOR_MEASUREMENT_TRIGGER_FILE)
    except OSError as error:
        print(f"센서 측정 트리거 초기화 실패: {error}")


def send_sensor_measurement_trigger():
    """등/목 초음파 모니터에 START 기준 측정 시작 신호를 원자적으로 보낸다."""
    payload = {
        "token": str(time.time_ns()),
        "timestamp": time.time(),
        "event": "START_MEASUREMENT",
    }
    temporary_path = SENSOR_MEASUREMENT_TRIGGER_FILE + ".tmp"
    try:
        with open(temporary_path, "w", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2)
        os.replace(temporary_path, SENSOR_MEASUREMENT_TRIGGER_FILE)
        print(f"체압/등/목 동시 측정 시작 신호 전송: {payload['token']}")
        return payload["token"]
    except OSError as error:
        print(f"센서 측정 시작 신호 저장 실패: {error}")
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass
        return None


# 점수 경고 기준.
# 나중에 점수 계산 공식이나 기준 점수가 바뀌면 우선 이 값을 기준으로 수정하면 된다.
SCORE_WARNING_THRESHOLD = 75

# 센서 기반 경고 조건.
# 체압 하중 쏠림과 초음파 자세 이상이 충분히 오래 유지될 때만 경고 화면을 띄운다.
PRESSURE_LOAD_SHIFT_BALANCE_THRESHOLD = 20.0
PRESSURE_LOAD_SHIFT_ALERT_HOLD_SEC = 5.0
ULTRASONIC_BACK_BEND_ALERT_HOLD_SEC = 8.0
BACK_WARNING_RECOVERY_PERCENT = 65.0
BACK_WARNING_RECOVERY_HOLD_SEC = 5.0

# 목 전방 이동도 일반 목 자세 경고는 8초 이상 유지될 때 띄운다.
NECK_FORWARD_ALERT_HOLD_SEC = 8.0
NECK_WARNING_RECOVERY_PERCENT = 60.0
NECK_WARNING_RECOVERY_HOLD_SEC = 5.0

# 고개 돌림/짧은 숙임을 졸음으로 오인하지 않도록 큰 전방 변화가 2초 이상
# 안정적으로 유지될 때만 졸음 운전 의심으로 본다.
NECK_DROWSY_ANGLE_DROP_THRESHOLD_DEG = 21.0
NECK_DROWSY_ALERT_HOLD_SEC = 2.0
NECK_DROWSY_RECOVERY_ANGLE_DEG = 8.0
NECK_DROWSY_RECOVERY_HOLD_SEC = 5.0

# 경고 화면이 반복해서 뜨지 않도록 하는 쿨다운 시간.
WARNING_POPUP_COOLDOWN_SEC = 10.0
BACK_WARNING_POPUP_COOLDOWN_SEC = 120.0
NECK_WARNING_POPUP_COOLDOWN_SEC = 90.0
NECK_DROWSY_POPUP_COOLDOWN_SEC = 45.0

# 연속 자세 점수는 센서값 변화에 따라 서서히 변하되, 실제 WARNING과
# 졸음 의심에서는 빠르게 떨어지도록 한 번의 1초 갱신 변화량을 제한한다.
POSTURE_SCORE_MAX_NORMAL_FALL_PER_SEC = 6.0
POSTURE_SCORE_MAX_WARNING_FALL_PER_SEC = 15.0
POSTURE_SCORE_MAX_RISE_PER_SEC = 3.0

PRESSURE_REGISTRATION_SCRIPT = os.path.join(APP_DIR, "pressure_database.py")
PRESSURE_REGISTRATION_LOG = os.path.join(LOG_DIR, "pressure_registration.log")
TRAIN_USER_MODEL_SCRIPT = os.path.join(APP_DIR, "train_user_model.py")
USER_MODEL_FILE = os.path.join(APP_DIR, "user_model.pkl")
USER_SCALER_FILE = os.path.join(APP_DIR, "user_scaler.pkl")
PRESSURE_DATABASE_FILE = os.path.join(APP_DIR, "pressure_database.csv")
REGISTRATION_PIPELINE_LOG = os.path.join(LOG_DIR, "user_registration_pipeline.log")

# 압력 센서 Arduino 포트. 액추에이터 Arduino까지 함께 연결하면
# auto 대신 /dev/ttyACM1처럼 압력 센서 포트를 명시하는 것이 안전하다.
PRESSURE_SENSOR_PORT = os.environ.get("SEAT_ID_PRESSURE_PORT", "auto")
RUN_PRESSURE_REGISTRATION_ON_NEW_USER = True

# 액추에이터 물리 사양과 맞춘 UI 입력 범위
SEAT_POSITION_MIN_MM = -20.0
SEAT_POSITION_MAX_MM = 20.0
BACKREST_ANGLE_MIN_DEG = 90.0
BACKREST_ANGLE_MAX_DEG = 130.0

# user_id는 SVM·체압 DB·액추에이터가 공유하는 내부 식별자다.
# pressure_database.csv에 이미 존재하는 ID는 UI 사용자 목록이 비어 있어도 예약된 ID로 간주한다.
# 화면에는 이 내부 ID 대신, 현재 UI에 등록된 사용자 순서(1번, 2번...)를 표시한다.
USER_ID_START = 1

# UI에서 관리할 수 있는 최대 사용자 수.
# Touch Display 2를 가로 1280x720으로 사용할 때
# 기존 7인치 가로 UI와 비슷한 카드 비율을 유지한다.
MAX_USER_PROFILES = 4
PROFILE_CARD_WIDTH = 150
PROFILE_CARD_HEIGHT = 150
PROFILE_CARD_SPACING = 24


def get_user_limit_message():
    return f"사용자는 최대 {MAX_USER_PROFILES}명까지만 등록할 수 있습니다."


def normalize_user_name(name):
    """
    사용자 이름 비교용 정규화 함수.
    앞뒤 공백, 연속 공백, 영문 대소문자 차이로 중복 사용자가 생기는 것을 막는다.
    """

    if not isinstance(name, str):
        return ""

    return " ".join(name.strip().split()).casefold()


def clean_user_name(name):
    if not isinstance(name, str):
        return ""

    return " ".join(name.strip().split())


def make_default_seat_env():
    return "전후 0 / 등받이 100"


def make_seat_env(seat_forward, backrest_angle):
    seat_forward = str(seat_forward).strip()
    backrest_angle = str(backrest_angle).strip()
    return f"전후 {seat_forward} / 등받이 {backrest_angle}"


def extract_number_after_keyword(text, keyword):
    """기존 seat_env 문자열에서 전후/등받이 숫자를 최대한 찾아낸다."""

    text = str(text or "")
    keyword_index = text.find(keyword)

    if keyword_index == -1:
        return ""

    number = ""
    started = False

    for char in text[keyword_index + len(keyword):]:
        if char.isdigit() or (char == "-" and not started):
            number += char
            started = True
        elif started:
            break

    return number


def normalize_number_text(value):
    value = str(value or "").strip().replace(",", ".")
    if value == "":
        return ""

    try:
        number = float(value)
    except ValueError:
        return ""

    if number.is_integer():
        return str(int(number))

    return f"{number:.2f}".rstrip("0").rstrip(".")


def normalize_profile_record(record, fallback_index=1):
    """
    사용자 파일의 한 행을 UI 내부에서 쓰는 공통 딕셔너리 형식으로 변환한다.

    새 기준 파일은 user_profile.csv이고 열 이름은 다음과 같다.
    user_id,nickname,seat_position,backrest_angle

    예전 users.json 형식이 남아 있어도 최대한 읽을 수 있게 호환한다.
    """

    if isinstance(record, str):
        name = clean_user_name(record)
        if name == "":
            return None

        user_id = str(fallback_index)
        seat_forward = "0"
        backrest_angle = "100"

        return {
            "user_id": user_id,
            "name": name,
            "nickname": name,
            "seat_position": seat_forward,
            "seat_forward": seat_forward,
            "backrest_angle": backrest_angle,
            "seat_env": make_seat_env(seat_forward, backrest_angle),
            "created_at": ""
        }

    if not isinstance(record, dict):
        return None

    raw_user_id = str(record.get("user_id", "")).strip()

    # 예전 U001 형식이 남아 있으면 1 형식으로 변환한다.
    if len(raw_user_id) >= 2 and raw_user_id[0].upper() == "U" and raw_user_id[1:].isdigit():
        user_id = str(int(raw_user_id[1:]))
    elif raw_user_id.isdigit():
        user_id = str(int(raw_user_id))
    else:
        user_id = str(fallback_index)

    name = clean_user_name(
        record.get("name", "")
        or record.get("nickname", "")
        or f"사용자{user_id}"
    )

    if name == "":
        return None

    seat_env = str(record.get("seat_env", "")).strip()

    # 하드웨어 담당 파일명 기준: seat_position
    # UI 내부 호환명: seat_forward
    seat_forward = normalize_number_text(
        record.get("seat_position", record.get("seat_forward", ""))
    )
    backrest_angle = normalize_number_text(
        record.get("backrest_angle", record.get("seat_back_angle", ""))
    )

    # 이전 버전에서 seat_env 문자열만 저장된 경우 최대한 숫자를 추출한다.
    if seat_forward == "" and seat_env != "":
        seat_forward = normalize_number_text(extract_number_after_keyword(seat_env, "전후"))

    if backrest_angle == "" and seat_env != "":
        backrest_angle = normalize_number_text(extract_number_after_keyword(seat_env, "등받이"))

    if seat_forward == "":
        seat_forward = "0"

    if backrest_angle == "":
        backrest_angle = "100"

    seat_env = make_seat_env(seat_forward, backrest_angle)
    created_at = str(record.get("created_at", "")).strip()

    return {
        "user_id": user_id,
        "name": name,
        "nickname": name,
        "seat_position": seat_forward,
        "seat_forward": seat_forward,
        "backrest_angle": backrest_angle,
        "seat_env": seat_env,
        "created_at": created_at
    }


def load_legacy_user_records_from_json():
    """기존 users.json이 남아 있으면 user_profile.csv로 옮길 수 있도록 읽어온다."""

    if not os.path.exists(LEGACY_USERS_JSON_FILE):
        return []

    try:
        with open(LEGACY_USERS_JSON_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
    except (json.JSONDecodeError, OSError):
        return []

    if isinstance(data, dict):
        raw_profiles = data.get("profiles", [])
    elif isinstance(data, list):
        raw_profiles = data
    else:
        return []

    records = []
    for index, raw_record in enumerate(raw_profiles, start=1):
        record = normalize_profile_record(raw_record, index)
        if record is not None:
            records.append(record)

    return records


def load_user_profile_records():
    """
    user_profile.csv에서 사용자 전체 정보를 불러온다.
    파일이 없으면 빈 목록으로 시작한다.

    CSV 열 구조:
    user_id,nickname,seat_position,backrest_angle
    """

    raw_records = []

    if os.path.exists(USER_PROFILES_FILE):
        try:
            with open(USER_PROFILES_FILE, "r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                raw_records = list(reader)
        except OSError:
            raw_records = []
    else:
        # 기존 버전에서 쓰던 users.json이 있으면 최초 1회 호환 로딩한다.
        raw_records = load_legacy_user_records_from_json()

    records = []
    used_names = set()
    used_ids = set()

    for index, raw_record in enumerate(raw_records, start=1):
        record = normalize_profile_record(raw_record, index)

        if record is None:
            continue

        normalized_name = normalize_user_name(record["name"])
        if normalized_name in used_names:
            continue

        if record["user_id"] in used_ids:
            record["user_id"] = generate_next_user_id(records)

        used_names.add(normalized_name)
        used_ids.add(record["user_id"])
        records.append(record)

    # 화면과 입력 흐름은 최대 4명까지만 보여주도록 제한한다.
    # pressure_database.csv에 남아 있는 과거 학습 ID는 예약 ID 계산에는 계속 사용된다.
    if len(records) > MAX_USER_PROFILES:
        records = records[:MAX_USER_PROFILES]

    # 기존 users.json에서 읽어온 경우에는 같은 내용을 새 user_profile.csv로 자동 변환해 둔다.
    if not os.path.exists(USER_PROFILES_FILE) and len(records) > 0:
        save_user_profile_records(records)

    return records


def save_user_profile_records(records):
    """
    사용자 전체 정보를 user_profile.csv에 저장한다.

    하드웨어 제어부와 맞추기 위해 CSV 열 이름은
    user_id,nickname,seat_position,backrest_angle만 사용한다.
    """

    cleaned_records = []
    used_names = set()
    used_ids = set()

    for index, raw_record in enumerate(records, start=1):
        record = normalize_profile_record(raw_record, index)

        if record is None:
            continue

        normalized_name = normalize_user_name(record["name"])
        if normalized_name in used_names:
            continue

        if record["user_id"] in used_ids:
            record["user_id"] = generate_next_user_id(cleaned_records)

        used_names.add(normalized_name)
        used_ids.add(record["user_id"])
        cleaned_records.append(record)

    if len(cleaned_records) > MAX_USER_PROFILES:
        cleaned_records = cleaned_records[:MAX_USER_PROFILES]

    fieldnames = ["user_id", "nickname", "seat_position", "backrest_angle"]

    try:
        with open(USER_PROFILES_FILE, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            writer.writeheader()
            for record in cleaned_records:
                writer.writerow(
                    {
                        "user_id": record.get("user_id", ""),
                        "nickname": record.get("name", record.get("nickname", "")),
                        "seat_position": record.get("seat_forward", record.get("seat_position", "")),
                        "backrest_angle": record.get("backrest_angle", "")
                    }
                )
    except OSError as error:
        print(f"사용자 파일 저장 실패: {error}")


def load_user_profiles():
    """
    기존 UI 호환을 위해 이름 목록만 반환한다.
    실제 user_id/seat_position/backrest_angle은 load_user_profile_records()에서 관리한다.
    """

    return [record["name"] for record in load_user_profile_records()]


def save_user_profiles(profile_names):
    """
    기존 코드 호환용 저장 함수.
    이름 목록을 저장하되, 이미 있던 user_id/seat_position/backrest_angle은 유지한다.
    """

    existing_records = load_user_profile_records()
    new_records = []

    for name in profile_names:
        name = clean_user_name(name)
        if name == "":
            continue

        existing = find_user_record_by_name(name, existing_records)
        if existing is not None:
            new_records.append(existing)
        else:
            new_records.append(create_user_record(name, make_default_seat_env(), existing_records + new_records))

    save_user_profile_records(new_records)


def is_duplicate_profile(new_name, profiles):
    normalized_new_name = normalize_user_name(new_name)

    if normalized_new_name == "":
        return False

    for profile in profiles:
        if isinstance(profile, dict):
            profile_name = profile.get("name", profile.get("nickname", ""))
        else:
            profile_name = profile

        if normalize_user_name(profile_name) == normalized_new_name:
            return True

    return False


def _normalize_numeric_user_id(value):
    """user_id 값을 정수로 바꿀 수 있으면 반환하고, 아니면 None을 반환한다."""

    raw_value = str(value or "").strip()

    if raw_value == "":
        return None

    if len(raw_value) >= 2 and raw_value[0].upper() == "U" and raw_value[1:].isdigit():
        return int(raw_value[1:])

    try:
        number = float(raw_value)
    except (TypeError, ValueError):
        return None

    if not number.is_integer() or number < 0:
        return None

    return int(number)


def get_reserved_user_ids(existing_records=None):
    """
    UI 프로필과 pressure_database.csv에서 이미 사용 중인 내부 user_id를 모은다.

    팀원 3명의 체압 데이터가 ID 0~2로 남아 있고 user_profile.csv가 비어 있어도,
    0~2는 예약된 ID로 처리되어 신규 사용자는 내부 ID 3부터 배정된다.
    """

    reserved_ids = set()
    records = list(existing_records) if existing_records is not None else load_user_profile_records()

    for record in records:
        if not isinstance(record, dict):
            continue

        numeric_id = _normalize_numeric_user_id(record.get("user_id", ""))
        if numeric_id is not None:
            reserved_ids.add(numeric_id)

    if os.path.exists(PRESSURE_DATABASE_FILE):
        try:
            with open(PRESSURE_DATABASE_FILE, "r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)

                if reader.fieldnames and "user_id" in reader.fieldnames:
                    for row in reader:
                        numeric_id = _normalize_numeric_user_id(row.get("user_id", ""))
                        if numeric_id is not None:
                            reserved_ids.add(numeric_id)
        except OSError as error:
            print(f"체압 DB의 예약 ID 확인 실패: {error}")

    return reserved_ids


def generate_next_user_id(existing_records=None):
    """UI와 체압 DB 양쪽에서 사용되지 않은 가장 작은 내부 ID를 생성한다."""

    reserved_ids = get_reserved_user_ids(existing_records)
    candidate = USER_ID_START

    while candidate in reserved_ids:
        candidate += 1

    return str(candidate)


def get_user_display_number(user_id, records=None):
    """
    사용자에게 보여줄 1부터 시작하는 화면용 번호를 반환한다.

    내부 SVM ID가 3이어도 UI에 처음 등록된 사용자라면 1번으로 표시한다.
    이 값은 화면 표시용이며 CSV·SVM·Arduino 통신에는 사용하지 않는다.
    """

    target_id = _normalize_numeric_user_id(user_id)
    records = load_user_profile_records() if records is None else list(records)

    visible_ids = []
    for record in records:
        if not isinstance(record, dict):
            continue

        numeric_id = _normalize_numeric_user_id(record.get("user_id", ""))
        if numeric_id is not None and numeric_id not in visible_ids:
            visible_ids.append(numeric_id)

    visible_ids.sort()

    if target_id in visible_ids:
        return visible_ids.index(target_id) + 1

    return len(visible_ids) + 1


def create_user_record(user_name, seat_env=None, existing_records=None):
    user_name = clean_user_name(user_name)
    seat_env = str(seat_env or "").strip()

    seat_forward = "0"
    backrest_angle = "100"

    if seat_env != "":
        parsed_forward = normalize_number_text(extract_number_after_keyword(seat_env, "전후"))
        parsed_backrest = normalize_number_text(extract_number_after_keyword(seat_env, "등받이"))

        if parsed_forward != "":
            seat_forward = parsed_forward

        if parsed_backrest != "":
            backrest_angle = parsed_backrest

    seat_env = make_seat_env(seat_forward, backrest_angle)

    return {
        "user_id": generate_next_user_id(existing_records),
        "name": user_name,
        "nickname": user_name,
        "seat_position": seat_forward,
        "seat_forward": seat_forward,
        "backrest_angle": backrest_angle,
        "seat_env": seat_env,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }


def find_user_record_by_name(user_name, records=None):
    records = load_user_profile_records() if records is None else records
    normalized_name = normalize_user_name(user_name)

    for record in records:
        if normalize_user_name(record.get("name", record.get("nickname", ""))) == normalized_name:
            return dict(record)

    return None


def find_user_record_by_id(user_id, records=None):
    records = load_user_profile_records() if records is None else records
    user_id = str(user_id).strip()

    if len(user_id) >= 2 and user_id[0].upper() == "U" and user_id[1:].isdigit():
        user_id = str(int(user_id[1:]))
    elif user_id.isdigit():
        user_id = str(int(user_id))

    for record in records:
        record_id = str(record.get("user_id", "")).strip()
        if len(record_id) >= 2 and record_id[0].upper() == "U" and record_id[1:].isdigit():
            record_id = str(int(record_id[1:]))
        elif record_id.isdigit():
            record_id = str(int(record_id))

        if record_id == user_id:
            return dict(record)

    return None


def get_user_id_by_name(user_name):
    record = find_user_record_by_name(user_name)
    if record is None:
        return ""

    return record.get("user_id", "")


def add_user_profile_record(user_name, seat_env):
    records = load_user_profile_records()

    if len(records) >= MAX_USER_PROFILES:
        return None

    if is_duplicate_profile(user_name, records):
        return None

    record = create_user_record(user_name, seat_env, records)
    records.append(record)
    save_user_profile_records(records)
    return record


def update_user_seat_profile_record(user_id, seat_position, backrest_angle):
    """기존 사용자의 시트 위치/등받이 각도를 수정하고 저장된 record를 반환한다."""

    user_id = str(user_id or "").strip()
    seat_position = normalize_number_text(seat_position)
    backrest_angle = normalize_number_text(backrest_angle)

    records = load_user_profile_records()
    updated_record = None

    for index, record in enumerate(records):
        record_id = str(record.get("user_id", "")).strip()

        if len(record_id) >= 2 and record_id[0].upper() == "U" and record_id[1:].isdigit():
            record_id = str(int(record_id[1:]))
        elif record_id.isdigit():
            record_id = str(int(record_id))

        if record_id == user_id:
            record["seat_position"] = seat_position
            record["seat_forward"] = seat_position
            record["backrest_angle"] = backrest_angle
            record["seat_env"] = make_seat_env(seat_position, backrest_angle)
            updated_record = normalize_profile_record(record, index + 1)
            records[index] = updated_record
            break

    if updated_record is None:
        return None

    save_user_profile_records(records)
    return updated_record


def append_csv_row(file_path, fieldnames, row):
    file_exists = os.path.exists(file_path)

    try:
        parent = os.path.dirname(file_path)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(file_path, "a", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
    except OSError as error:
        print(f"CSV 기록 실패: {file_path} / {error}")


def send_user_id_to_hardware(user_id, user_name="", event="USER_SELECTED"):
    """
    하드웨어에게 user_id를 보내는 자리.
    지금은 실제 시리얼 통신 대신 hardware_command.csv에 명령을 남겨둔다.
    나중에 아두이노/라즈베리파이 시리얼 통신으로 바꿀 때 이 함수만 교체하면 된다.
    """

    user_id = str(user_id or "").strip()
    user_name = str(user_name or "").strip()

    if user_id == "":
        print("하드웨어 전송 생략: user_id가 없습니다.")
        return

    fieldnames = ["timestamp", "event", "user_id", "user_name"]
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "user_id": user_id,
        "user_name": user_name
    }

    append_csv_row(HARDWARE_COMMAND_FILE, fieldnames, row)
    print(f"하드웨어 전송: event={event}, user_id={user_id}, user_name={user_name}")


def send_hardware_event(event, user_id="", user_name=""):
    """
    PARK_SAFE, SESSION_END처럼 하드웨어 상태만 바꿔야 하는 이벤트를 기록한다.

    hardware_bridge.py는 PARK_SAFE/P/SESSION_END 이벤트를 먼저 확인한 뒤
    기준 위치 복귀를 수행하므로, reset 이벤트는 user_id가 비어 있어도 기록되어야 한다.
    """

    event = str(event or "").strip()
    user_id = str(user_id or "").strip()
    user_name = str(user_name or "").strip()

    if event == "":
        print("하드웨어 이벤트 전송 생략: event가 없습니다.")
        return

    fieldnames = ["timestamp", "event", "user_id", "user_name"]
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "event": event,
        "user_id": user_id,
        "user_name": user_name
    }

    append_csv_row(HARDWARE_COMMAND_FILE, fieldnames, row)
    print(f"하드웨어 이벤트 전송: event={event}, user_id={user_id}, user_name={user_name}")


def start_pressure_registration_process(record):
    """
    신규 사용자 등록 직후 압력 센서 등록 코드를 별도 프로세스로 실행한다.

    pressure_database.py는 UI가 만든 user_id를 인자로 받아
    pressure_database.csv에 같은 user_id로 체압 대표 샘플을 저장한다.
    별도 프로세스로 실행하는 이유는 100개 샘플 수집 동안 PyQt UI가 멈추는 것을 막기 위해서다.
    """

    if not RUN_PRESSURE_REGISTRATION_ON_NEW_USER:
        return

    if not isinstance(record, dict):
        return

    if not os.path.exists(PRESSURE_REGISTRATION_SCRIPT):
        print(f"체압 등록 스크립트 없음: {PRESSURE_REGISTRATION_SCRIPT}")
        return

    user_id = str(record.get("user_id", "")).strip()
    user_name = str(record.get("name", record.get("nickname", ""))).strip()

    if user_id == "" or user_name == "":
        return

    # 실시간 예측 서비스가 같은 압력 센서 포트를 열고 있으면
    # 신규 체압 등록 프로세스가 포트를 열 수 없으므로 먼저 닫는다.
    try:
        module = importlib.import_module("real_time_prediction_rasp")
        if hasattr(module, "close_service"):
            module.close_service()
    except Exception:
        pass

    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        log_file = open(PRESSURE_REGISTRATION_LOG, "a", encoding="utf-8")
        subprocess.Popen(
            [
                sys.executable,
                PRESSURE_REGISTRATION_SCRIPT,
                "--user-id", user_id,
                "--nickname", user_name,
                "--port", str(PRESSURE_SENSOR_PORT)
            ],
            cwd=APP_DIR,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL
        )
        print(f"체압 등록 프로세스 시작: user_id={user_id}, nickname={user_name}")
    except Exception as error:
        print(f"체압 등록 프로세스 시작 실패: {error}")


def send_new_user_to_pressure_processor(record, source_csv=PRESSURE_SAMPLE_CSV):
    """
    신규 사용자 등록 시 UI가 생성한 user_id를 체압 데이터 처리부와 공유한다.

    pressure_user_registration.csv에 신규 등록 요청 이력을 남긴다.
    실제 체압 수집과 SVM 재학습은 MainWindow의 QProcess 파이프라인이 담당한다.
    """

    if not isinstance(record, dict):
        return

    fieldnames = [
        "timestamp",
        "user_id",
        "nickname",
        "seat_position",
        "backrest_angle",
        "pressure_csv"
    ]
    row = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user_id": record.get("user_id", ""),
        "nickname": record.get("name", record.get("nickname", "")),
        "seat_position": record.get("seat_position", record.get("seat_forward", "")),
        "backrest_angle": record.get("backrest_angle", ""),
        "pressure_csv": source_csv
    }

    append_csv_row(PRESSURE_REGISTRATION_FILE, fieldnames, row)
    print(f"체압 데이터 처리부 등록 요청: user_id={row['user_id']}, pressure_csv={source_csv}")

    # 실제 체압 수집과 SVM 재학습은 MainWindow의 QProcess 파이프라인에서
    # 순서대로 실행한다. 여기서는 요청 이력만 남긴다.


_pressure_prediction_error_printed = False
_latest_pressure_sensor_cache = None
_pressure_background_started = False


def ensure_pressure_background_service():
    """압력 시리얼 수집을 UI 스레드 밖에서 시작한다."""

    global _pressure_background_started
    global _pressure_prediction_error_printed

    if not USE_REAL_PRESSURE_SENSOR:
        return None

    try:
        module = importlib.import_module("real_time_prediction_rasp")
        if hasattr(module, "start_background_service"):
            module.start_background_service(port=PRESSURE_SENSOR_PORT)
            _pressure_background_started = True
        return module
    except Exception as error:
        if not _pressure_prediction_error_printed:
            print(f"체압 백그라운드 수집기 시작 실패: {error}")
            _pressure_prediction_error_printed = True
        return None


def _cache_pressure_sensor_values(result):
    """예측 유효 여부와 관계없이 실제 16채널 압력값을 히트맵용으로 보관한다."""
    global _latest_pressure_sensor_cache

    if not isinstance(result, dict):
        return None

    values = result.get("corrected_sensor", result.get("raw_sensor"))
    if not isinstance(values, list) or len(values) != 16:
        return None

    try:
        converted = [float(value) for value in values]
    except (TypeError, ValueError):
        return None

    if not all(math.isfinite(value) for value in converted):
        return None

    _latest_pressure_sensor_cache = converted
    return list(converted)


def get_pressure_prediction_once():
    """UI를 막지 않고 최신 체압/SVM 캐시를 가져온다."""

    global _pressure_prediction_error_printed

    if not USE_REAL_PRESSURE_SENSOR:
        return None

    try:
        module = ensure_pressure_background_service()
        if module is None:
            return None

        if hasattr(module, "get_cached_pressure_prediction"):
            result = module.get_cached_pressure_prediction(
                max_age_sec=3.0,
                port=PRESSURE_SENSOR_PORT,
            )
            _cache_pressure_sensor_values(result)
            if result is not None:
                _pressure_prediction_error_printed = False
            return result

        if not hasattr(module, "predict_once"):
            raise AttributeError("real_time_prediction_rasp.py에 predict_once() 함수가 없습니다.")

        # 신규 사용자 등록과 대시보드가 동일한 체압 센서 Arduino를 사용하도록
        # 명시적으로 포트를 전달한다. 구버전 predict_once()와의 호환성도 유지한다.
        try:
            result = module.predict_once(
                max_wait_sec=PRESSURE_PREDICTION_MAX_WAIT_SEC,
                port=PRESSURE_SENSOR_PORT,
            )
            _cache_pressure_sensor_values(result)
            return result
        except TypeError as error:
            if "port" not in str(error):
                raise
            result = module.predict_once(max_wait_sec=PRESSURE_PREDICTION_MAX_WAIT_SEC)
            _cache_pressure_sensor_values(result)
            return result

    except Exception as error:
        # 센서/시리얼이 없는 개발 환경에서는 매초 같은 에러를 반복 출력하지 않는다.
        if not _pressure_prediction_error_printed:
            print(f"체압 센서 예측 사용 불가, mock 데이터로 대체: {error}")
            _pressure_prediction_error_printed = True
        return None


_latest_pressure_error_printed = False


def get_latest_pressure_sensor_values():
    """
    대시보드 히트맵용 실제 압력값을 반환한다.

    우선 real_time_prediction_rasp.py의 빠른 get_latest_pressure_sample()을 사용하고,
    해당 함수가 없거나 순간적으로 실패하면 마지막 predict_once()에서 받은
    실제 16채널 값을 사용한다.
    """
    global _latest_pressure_error_printed
    global _latest_pressure_sensor_cache

    if not USE_REAL_PRESSURE_SENSOR:
        return None

    try:
        module = ensure_pressure_background_service()
        if module is None:
            return list(_latest_pressure_sensor_cache) if _latest_pressure_sensor_cache is not None else None

        if hasattr(module, "get_cached_pressure_sample"):
            result = module.get_cached_pressure_sample(
                max_age_sec=3.0,
                port=PRESSURE_SENSOR_PORT,
            )
            values = _cache_pressure_sensor_values(result)
            if values is not None:
                _latest_pressure_error_printed = False
                return values
            if _latest_pressure_sensor_cache is not None:
                return list(_latest_pressure_sensor_cache)
            return None

        if hasattr(module, "get_latest_pressure_sample"):
            try:
                result = module.get_latest_pressure_sample(
                    max_wait_sec=PRESSURE_HEATMAP_MAX_WAIT_SEC,
                    port=PRESSURE_SENSOR_PORT,
                )
                values = _cache_pressure_sensor_values(result)
                if values is not None:
                    _latest_pressure_error_printed = False
                    return values
            except Exception as error:
                if not _latest_pressure_error_printed:
                    print(f"히트맵 빠른 체압 읽기 실패, 최근 실측값 사용: {error}")
                    _latest_pressure_error_printed = True

        if _latest_pressure_sensor_cache is not None:
            return list(_latest_pressure_sensor_cache)

        return None

    except Exception as error:
        if not _latest_pressure_error_printed:
            print(f"히트맵용 최신 체압값 사용 불가: {error}")
            _latest_pressure_error_printed = True
        if _latest_pressure_sensor_cache is not None:
            return list(_latest_pressure_sensor_cache)
        return None


def load_ultrasonic_posture_feedback():
    """
    초음파 등 곡률 모니터가 생성한 posture_feedback.json을 읽는다.

    파일이 없거나 오래되었거나 JSON 형식이 깨져 있으면 None을 반환한다.
    """

    file_path = ULTRASONIC_POSTURE_FEEDBACK_FILE

    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, TypeError) as error:
        print(f"초음파 자세 파일 읽기 실패: {error}")
        return None

    if not isinstance(payload, dict):
        return None

    try:
        timestamp = float(payload.get("timestamp", 0.0))
    except (TypeError, ValueError):
        timestamp = 0.0

    if timestamp > 0.0:
        age_sec = time.time() - timestamp
        payload["_age_sec"] = age_sec

        if age_sec > ULTRASONIC_FEEDBACK_MAX_AGE_SEC:
            payload["_stale"] = True
    else:
        payload["_stale"] = True

    return payload


def calculate_back_bend_percent(payload):
    """
    초음파 곡률 손실값을 UI용 0~100% 등 구부러짐 정도로 변환한다.

    curvature_loss가 threshold와 같으면 100%로 표시한다.
    threshold를 넘는 더 나쁜 자세도 화면에서는 100%에 고정한다.
    """

    if not isinstance(payload, dict):
        return 0

    try:
        curvature_loss = float(payload.get("curvature_loss_mm_inv", 0.0))
    except (TypeError, ValueError):
        curvature_loss = 0.0

    try:
        threshold = float(payload.get("b_loss_threshold_mm_inv", 0.0006))
    except (TypeError, ValueError):
        threshold = 0.0006

    threshold = max(1.0e-9, abs(threshold))
    percent = max(0.0, curvature_loss / threshold * 100.0)

    return int(round(max(0.0, min(100.0, percent))))



def load_neck_posture_feedback():
    """
    목/헤드 초음파 모니터가 생성한 neck_posture_feedback.json을 읽는다.

    파일이 없거나 오래되었거나 JSON 형식이 깨져 있으면 None을 반환한다.
    """

    file_path = NECK_POSTURE_FEEDBACK_FILE

    if not os.path.exists(file_path):
        return None

    try:
        with open(file_path, "r", encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError, TypeError) as error:
        print(f"목 자세 파일 읽기 실패: {error}")
        return None

    if not isinstance(payload, dict):
        return None

    try:
        timestamp = float(payload.get("timestamp", 0.0))
    except (TypeError, ValueError):
        timestamp = 0.0

    if timestamp > 0.0:
        age_sec = time.time() - timestamp
        payload["_age_sec"] = age_sec

        if age_sec > NECK_FEEDBACK_MAX_AGE_SEC:
            payload["_stale"] = True
    else:
        payload["_stale"] = True

    return payload


STARTUP_BACK_READY_STATES = {"NORMAL", "WARNING"}
STARTUP_NECK_READY_STATES = {
    "NORMAL", "PENDING", "WARNING", "RECOVERING", "RECOVERED"
}
STARTUP_SENSOR_ERROR_STATES = {
    "CALIBRATION_ERROR", "MEASUREMENT_ERROR", "SIGNAL_LOST"
}


def _valid_pressure_vector(prediction):
    if not isinstance(prediction, dict):
        return False
    values = prediction.get("corrected_sensor", prediction.get("raw_sensor"))
    if not isinstance(values, list) or len(values) != 16:
        return False
    try:
        return all(math.isfinite(float(value)) for value in values)
    except (TypeError, ValueError):
        return False


def evaluate_startup_sensor_readiness(
    measurement_token,
    pressure_start_sample_id,
    pressure_prediction,
    back_payload,
    neck_payload,
):
    """현재 START 회차의 체압·등·목 측정 성공 여부를 한 번에 판정한다."""

    result = {}

    if not isinstance(pressure_prediction, dict) or not _valid_pressure_vector(pressure_prediction):
        result["pressure"] = {
            "ready": False,
            "phase": "waiting",
            "label": "체압 연결 대기",
        }
    else:
        sample_id = pressure_prediction.get("sample_id")
        is_new_sample = (
            pressure_start_sample_id is None
            or sample_id is None
            or sample_id != pressure_start_sample_id
        )
        cache_age = float(pressure_prediction.get("_cache_age_sec", 0.0) or 0.0)
        if not is_new_sample or cache_age > 3.0:
            result["pressure"] = {
                "ready": False,
                "phase": "measuring",
                "label": "체압 새 데이터 측정 중",
            }
        elif not bool(pressure_prediction.get("is_valid", True)):
            result["pressure"] = {
                "ready": False,
                "phase": "error",
                "label": "좌석 중앙에 다시 앉아주세요",
            }
        else:
            result["pressure"] = {
                "ready": True,
                "phase": "ready",
                "label": "체압 측정 완료",
            }

    def evaluate_ultrasonic(payload, ready_states, required_keys, sensor_name):
        if not isinstance(payload, dict) or payload.get("_stale"):
            return {"ready": False, "phase": "waiting", "label": f"{sensor_name} 연결 대기"}

        payload_token = str(payload.get("measurement_token", "")).strip()
        if not measurement_token or payload_token != str(measurement_token):
            return {"ready": False, "phase": "waiting", "label": f"{sensor_name} START 수신 대기"}

        state = str(payload.get("state", "")).strip().upper()
        if state in ready_states and payload.get("signal_ok", True):
            if all(payload.get(key) is not None for key in required_keys):
                return {"ready": True, "phase": "ready", "label": f"{sensor_name} 측정 완료"}

        if state in STARTUP_SENSOR_ERROR_STATES:
            message = str(payload.get("message", "")).strip()
            return {
                "ready": False,
                "phase": "error",
                "label": message or f"{sensor_name} 측정 실패",
            }

        if state == "CALIBRATING":
            return {"ready": False, "phase": "measuring", "label": f"{sensor_name} 기준 측정 중"}

        return {"ready": False, "phase": "waiting", "label": f"{sensor_name} 측정 대기"}

    result["back"] = evaluate_ultrasonic(
        back_payload,
        STARTUP_BACK_READY_STATES,
        ("distances_mm", "baseline_distances_mm"),
        "등",
    )
    result["neck"] = evaluate_ultrasonic(
        neck_payload,
        STARTUP_NECK_READY_STATES,
        ("corrected_mm", "baseline"),
        "목",
    )
    result["all_ready"] = all(result[key]["ready"] for key in ("pressure", "back", "neck"))
    return result


def calculate_neck_forward_percent(payload):
    """
    목/헤드 초음파의 기준 대비 각도 감소량을 UI용 0~100%로 변환한다.

    angle_drop이 angle_drop_threshold와 같으면 100%로 표시한다.
    threshold를 넘는 더 나쁜 자세도 화면에서는 100%에 고정한다.
    """

    if not isinstance(payload, dict):
        return 0

    try:
        angle_drop = float(payload.get("angle_drop_deg", 0.0))
    except (TypeError, ValueError):
        angle_drop = 0.0

    try:
        threshold = float(payload.get("angle_drop_threshold_deg", 5.0))
    except (TypeError, ValueError):
        threshold = 5.0

    threshold = max(1.0e-9, abs(threshold))
    percent = max(0.0, angle_drop / threshold * 100.0)

    return int(round(max(0.0, min(100.0, percent))))


def get_neck_angle_drop(payload):
    if not isinstance(payload, dict):
        return 0.0

    try:
        angle_drop = float(payload.get("angle_drop_deg", 0.0))
    except (TypeError, ValueError):
        angle_drop = 0.0

    if not math.isfinite(angle_drop):
        return 0.0

    return angle_drop


def is_neck_drowsy_problem(payload):
    """
    목이 크게 앞으로 떨어진 상태인지 판단한다.

    기본 기준은 12도 이상 감소이며, 목 코드에서 설정한 일반 임계값이 더 클 경우에는
    일반 임계값의 2.4배를 강한 전방 이동 기준으로 사용한다.
    """

    if not isinstance(payload, dict) or bool(payload.get("_stale", False)):
        return False

    angle_drop = get_neck_angle_drop(payload)

    try:
        normal_threshold = float(payload.get("angle_drop_threshold_deg", 5.0))
    except (TypeError, ValueError):
        normal_threshold = 5.0

    severe_threshold = max(NECK_DROWSY_ANGLE_DROP_THRESHOLD_DEG, abs(normal_threshold) * 3.0)

    return angle_drop >= severe_threshold



def confidence_to_ratio(confidence):
    try:
        value = float(confidence)
    except (TypeError, ValueError):
        return 0.0

    if value > 1.0:
        value = value / 100.0

    return max(0.0, min(1.0, value))


def posture_to_score(posture, confidence_value):
    """자세 SVM 결과를 UI 점수 그래프용 0~100 점수로 변환한다."""

    posture = str(posture or "").strip().lower()
    confidence = confidence_to_ratio(confidence_value)

    if posture == "normal":
        return int(round(86 + confidence * 11))

    if posture in ["left_shift", "right_shift", "forward_lean", "backward_lean"]:
        return int(round(74 - confidence * 10))

    return 75


def _progressive_ultrasonic_penalty(
    percent,
    warning=False,
    warning_penalty=20.0,
):
    """정상→주의 구간은 완만하게, WARNING은 크게 감점한다."""

    try:
        severity = float(percent)
    except (TypeError, ValueError):
        severity = 0.0

    severity = max(0.0, min(100.0, severity))
    if warning:
        return float(warning_penalty)

    caution_start = 30.0
    if severity <= caution_start:
        return 1.5 * severity / caution_start

    progress = (severity - caution_start) / (100.0 - caution_start)
    return 1.5 + 10.5 * math.pow(progress, 1.25)


def calculate_integrated_posture_score(
    prediction,
    back_payload=None,
    neck_payload=None,
    previous_score=None,
):
    """
    체압·등·목의 연속 심각도를 종합해 0~100 자세 점수를 만든다.

    SVM 클래스가 바뀌는 순간 점수가 수십 점 뛰지 않도록 압력 불균형을
    연속 감점하고, 등/목은 정상→주의에서 완만하게 감점한 뒤 실제 WARNING
    또는 졸음 상태에서 큰 감점을 적용한다.
    """

    prediction = prediction if isinstance(prediction, dict) else {}
    target_score = 98.0

    try:
        balance_index = float(prediction.get("balance_index", 0.0))
    except (TypeError, ValueError):
        balance_index = 0.0
    balance_index = max(0.0, min(100.0, balance_index))
    pressure_penalty = 28.0 * math.pow(balance_index / 100.0, 1.35)

    posture = str(prediction.get("posture", "")).strip().lower()
    posture_confidence = confidence_to_ratio(
        prediction.get("posture_confidence", prediction.get("confidence_value", 0.0))
    )
    if posture in {"left_shift", "right_shift", "forward_lean", "backward_lean"}:
        # 이산 SVM 분류는 보조 신호로만 사용해 경계에서의 급격한 점프를 막는다.
        pressure_penalty += 1.0 + 3.0 * posture_confidence

    back_valid = isinstance(back_payload, dict) and not bool(back_payload.get("_stale", False))
    back_percent = calculate_back_bend_percent(back_payload) if back_valid else 0
    back_warning = back_valid and (
        bool(back_payload.get("warning", False))
        or str(back_payload.get("state", "")).upper() == "WARNING"
    )
    back_penalty = _progressive_ultrasonic_penalty(
        back_percent,
        warning=back_warning,
        warning_penalty=20.0,
    )

    neck_valid = isinstance(neck_payload, dict) and not bool(neck_payload.get("_stale", False))
    neck_percent = calculate_neck_forward_percent(neck_payload) if neck_valid else 0
    neck_warning = neck_valid and (
        bool(neck_payload.get("warning", False))
        or str(neck_payload.get("state", "")).upper() == "WARNING"
    )
    drowsy_warning = neck_valid and is_neck_drowsy_problem(neck_payload)
    neck_penalty = _progressive_ultrasonic_penalty(
        neck_percent,
        warning=neck_warning,
        warning_penalty=16.0,
    )
    if drowsy_warning:
        neck_penalty = max(neck_penalty, 28.0)

    target_score -= pressure_penalty + back_penalty + neck_penalty
    target_score = max(25.0, min(98.0, target_score))

    try:
        previous = float(previous_score)
    except (TypeError, ValueError):
        previous = target_score

    severe = bool(
        back_warning
        or neck_warning
        or drowsy_warning
        or balance_index >= 50.0
    )
    maximum_fall = (
        POSTURE_SCORE_MAX_WARNING_FALL_PER_SEC
        if severe
        else POSTURE_SCORE_MAX_NORMAL_FALL_PER_SEC
    )
    delta = target_score - previous
    delta = max(-maximum_fall, min(POSTURE_SCORE_MAX_RISE_PER_SEC, delta))
    return int(round(max(0.0, min(100.0, previous + delta))))


def aggregate_pressure_identification_samples(samples, fallback_prediction=None):
    """여러 체압 SVM 결과를 다수결과 신뢰도 중앙값으로 통합한다."""

    valid_samples = []
    for sample in list(samples or []):
        if not isinstance(sample, dict) or not bool(sample.get("is_valid", True)):
            continue
        user_id = str(sample.get("user_id", "")).strip()
        confidence = confidence_to_ratio(
            sample.get("user_confidence", sample.get("confidence", 0.0))
        )
        if user_id and confidence > 0.0:
            valid_samples.append((user_id, confidence, sample))

    if not valid_samples:
        return fallback_prediction

    grouped = {}
    for user_id, confidence, sample in valid_samples:
        grouped.setdefault(user_id, []).append((confidence, sample))

    best_user_id, best_values = max(
        grouped.items(),
        key=lambda item: (
            len(item[1]),
            sum(value[0] for value in item[1]),
        ),
    )
    consensus = len(best_values) / len(valid_samples)
    median_confidence = statistics.median(value[0] for value in best_values)
    combined_confidence = median_confidence * (0.60 + 0.40 * consensus)
    if consensus < PRESSURE_IDENTIFICATION_MIN_CONSENSUS:
        combined_confidence *= consensus / PRESSURE_IDENTIFICATION_MIN_CONSENSUS

    representative = max(best_values, key=lambda value: value[0])[1]
    result = dict(representative)
    result["user_id"] = best_user_id
    result["user_confidence"] = round(combined_confidence * 100.0, 3)
    result["identification_sample_count"] = len(valid_samples)
    result["identification_consensus"] = round(consensus, 4)
    return result


def posture_to_korean_state(posture, score):
    posture = str(posture or "").strip().lower()

    label_map = {
        "normal": "정상 자세",
        "left_shift": "좌측 쏠림",
        "right_shift": "우측 쏠림",
        "forward_lean": "전방 기울어짐",
        "backward_lean": "후방 기울어짐"
    }

    if posture in label_map:
        return label_map[posture]

    return get_score_state(score)


def identify_user_from_pressure_csv(profile_names, prediction=None):
    """
    체압 센서 + 사용자 SVM으로 사용자를 식별한다.

    real_time_prediction_rasp.predict_once()가 사용 가능하면 실제 예측 결과를 사용한다.
    센서/모델/포트가 준비되지 않은 개발 환경에서는 mock 결과로 fallback한다.
    """

    profile_names = list(profile_names or [])

    if prediction is None:
        prediction = get_pressure_prediction_once()

    if prediction is not None and prediction.get("is_valid", True):
        predicted_user_id = str(prediction.get("user_id", "")).strip()
        confidence = confidence_to_ratio(prediction.get("user_confidence", prediction.get("confidence", 0.0)))
        record = find_user_record_by_id(predicted_user_id)

        try:
            consensus = float(prediction.get("identification_consensus", 0.0))
        except (TypeError, ValueError):
            consensus = 0.0
        try:
            sample_count = int(prediction.get("identification_sample_count", 0))
        except (TypeError, ValueError):
            sample_count = 0

        registered_candidate = bool(
            prediction.get("user_candidate_is_registered", False)
            or str(prediction.get("user_match_scope", "")) == "registered_profiles"
        )
        stable_registered_candidate = bool(
            registered_candidate
            and sample_count >= PRESSURE_IDENTIFICATION_MIN_USER_SAMPLES
            and consensus >= PRESSURE_IDENTIFICATION_MIN_CONSENSUS
        )

        if record is not None and (
            confidence >= PRESSURE_IDENTIFICATION_CONFIDENCE_THRESHOLD
            or stable_registered_candidate
        ):
            return {
                "is_new_user": False,
                "user_name": record.get("name", record.get("nickname", "")),
                "user_id": record.get("user_id", predicted_user_id),
                "confidence": confidence,
                "source_csv": "serial_pressure_sensor",
                "match_reason": (
                    "registered_profile_consensus"
                    if stable_registered_candidate
                    else "svm_confidence"
                ),
            }

        # 사용자 모델 파일이 오래되어 현재 유일한 등록 ID가 classes_에 없더라도,
        # 충분한 실측 샘플을 모았다면 목록의 유일한 사용자를 확인 후보로 먼저 보여준다.
        # 이 화면은 자동 확정이 아니라 'OOO 님 맞으신가요?' 확인 단계이므로,
        # 아니라면 기존 흐름대로 사용자가 거절하고 신규 등록으로 갈 수 있다.
        records = load_user_profile_records()
        if (
            len(records) == 1
            and sample_count >= PRESSURE_IDENTIFICATION_MIN_USER_SAMPLES
            and consensus >= PRESSURE_IDENTIFICATION_MIN_CONSENSUS
        ):
            sole_record = records[0]
            return {
                "is_new_user": False,
                "user_name": sole_record.get("name", sole_record.get("nickname", "")),
                "user_id": sole_record.get("user_id", ""),
                "confidence": confidence,
                "source_csv": "registered_user_confirmation_fallback",
                "match_reason": "single_registered_user_confirmation",
            }

        # SVM은 어떤 ID를 예측했지만, UI 사용자 파일에 없거나 신뢰도가 낮으면 신규/수동 확인 흐름으로 보낸다.
        return {
            "is_new_user": True,
            "user_name": "",
            "user_id": predicted_user_id,
            "confidence": confidence,
            "source_csv": "serial_pressure_sensor"
        }

    if len(profile_names) == 0:
        return {
            "is_new_user": True,
            "user_name": "",
            "user_id": "",
            "confidence": 0.0,
            "source_csv": PRESSURE_SAMPLE_CSV
        }

    # 실제 장비 모드에서는 센서 판정 실패를 임의 사용자로 대체하지 않는다.
    if USE_REAL_PRESSURE_SENSOR:
        return {
            "is_new_user": True,
            "user_name": "",
            "user_id": "",
            "confidence": 0.0,
            "source_csv": "serial_pressure_sensor_unavailable",
        }

    # 센서 없는 명시적 UI 데모 모드에서만 mock 사용자를 선택한다.
    predicted_name = random.choice(profile_names)
    record = find_user_record_by_name(predicted_name)
    confidence = round(random.uniform(0.86, 0.97), 2)

    return {
        "is_new_user": False,
        "user_name": predicted_name,
        "user_id": record.get("user_id", "") if record else "",
        "confidence": confidence,
        "source_csv": PRESSURE_SAMPLE_CSV
    }


def user_model_contains_user_id(model_path, user_id):
    """재학습된 사용자 모델 classes_에 방금 등록한 ID가 실제로 들어갔는지 확인한다."""

    numeric_id = _normalize_numeric_user_id(user_id)
    if numeric_id is None or not os.path.exists(model_path):
        return False

    try:
        import joblib

        model = joblib.load(model_path)
        classes = {
            parsed
            for parsed in (
                _normalize_numeric_user_id(value)
                for value in getattr(model, "classes_", [])
            )
            if parsed is not None
        }
    except Exception as error:
        print(f"사용자 모델 classes_ 확인 실패: {error}")
        return False

    return numeric_id in classes


def get_score_state(score):
    """점수에 따른 자세 상태 문자열을 반환한다."""

    if score >= 85:
        return "정상 자세"
    elif score >= SCORE_WARNING_THRESHOLD:
        return "자세 주의"
    else:
        return "자세 불안정"


class DriveSession:
    def __init__(self):
        self.segments = []
        self.active_segment = None
        self.running = False
        self.session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_rows = []
        self.total_sample_count = 0
        self.saved_log_path = None

    def _now(self):
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def start_or_resume_user(self, user_name):
        """
        같은 사용자면 기존 구간을 이어서 사용.
        다른 사용자면 기존 구간을 닫고 새 구간 생성.
        """

        if self.active_segment is not None:
            if self.active_segment["user"] == user_name:
                self.running = True
                return

            self.active_segment["end_time"] = self._now()

        user_record = find_user_record_by_name(user_name)
        user_id = user_record.get("user_id", "") if user_record else ""
        seat_env = user_record.get("seat_env", "") if user_record else ""

        new_segment = {
            "user": user_name,
            "user_id": user_id,
            "seat_env": seat_env,
            "start_time": self._now(),
            "end_time": None,
            "scores": [],
            "warning_indices": [],
            "log_rows": []
        }

        self.segments.append(new_segment)
        self.active_segment = new_segment
        self.running = True

    def pause(self):
        self.running = False

    def finish(self):
        if self.active_segment is not None:
            self.active_segment["end_time"] = self._now()

        self.running = False

    def add_score(self, score):
        """
        현재 활성 사용자 구간에 점수를 저장하고,
        저장된 점수의 index를 반환한다.

        동시에 logs/session_*.csv로 저장할 원본 로그 row도 메모리에 쌓아둔다.
        실제 파일 저장은 E 키로 세션이 종료될 때 save_csv_log()에서 수행한다.
        """

        if self.running and self.active_segment is not None:
            local_index = len(self.active_segment["scores"])
            global_time_sec = self.total_sample_count
            state = get_score_state(score)

            self.active_segment["scores"].append(score)

            log_row = {
                "time_sec": global_time_sec,
                "segment_time_sec": local_index,
                "user_id": self.active_segment.get("user_id", ""),
                "user": self.active_segment["user"],
                "seat_env": self.active_segment.get("seat_env", ""),
                "score": score,
                "state": state,
                "is_warning": 1 if score < SCORE_WARNING_THRESHOLD else 0,
                "warning_event": 0,
                "timestamp": self._now()
            }

            self.active_segment["log_rows"].append(log_row)
            self.log_rows.append(log_row)
            self.total_sample_count += 1

            return local_index

        return None

    def add_warning(self, point_index=None):
        """
        경고가 울린 시점을 현재 사용자 구간의 점수 index로 저장한다.
        point_index가 없으면 가장 최근 점수를 경고 시점으로 사용한다.

        CSV 로그에서는 warning_event=1로 표시한다.
        is_warning은 점수가 75점 미만인 구간 전체를 의미하고,
        warning_event는 경고가 실제로 울린 순간을 의미한다.
        """

        if self.active_segment is None:
            return None

        scores = self.active_segment["scores"]

        if len(scores) == 0:
            return None

        if point_index is None:
            point_index = len(scores) - 1

        if point_index < 0 or point_index >= len(scores):
            return None

        warning_indices = self.active_segment.setdefault("warning_indices", [])

        if point_index not in warning_indices:
            warning_indices.append(point_index)
            warning_indices.sort()

        log_rows = self.active_segment.get("log_rows", [])
        if point_index < len(log_rows):
            log_rows[point_index]["warning_event"] = 1

        return point_index

    def get_active_scores(self):
        if self.active_segment is None:
            return []

        return self.active_segment["scores"]

    def get_active_warning_indices(self):
        if self.active_segment is None:
            return []

        return self.active_segment.get("warning_indices", [])

    def get_summaries(self):
        summaries = []

        for segment in self.segments:
            scores = segment["scores"]

            if len(scores) == 0:
                avg_score = "-"
                min_score = "-"
            else:
                avg_score = round(sum(scores) / len(scores))
                min_score = min(scores)

            summaries.append(
                {
                    "user": segment["user"],
                    "user_id": segment.get("user_id", ""),
                    "seat_env": segment.get("seat_env", ""),
                    "avg_score": avg_score,
                    "min_score": min_score,
                    "scores": scores,
                    "warning_indices": segment.get("warning_indices", []),
                    "start_time": segment["start_time"],
                    "end_time": segment["end_time"]
                }
            )

        return summaries

    def save_csv_log(self, log_dir=LOG_DIR):
        """
        현재 세션의 주행 분석 로그를 CSV 파일로 저장한다.
        저장 위치: logs/session_YYYYMMDD_HHMMSS.csv
        """

        if len(self.log_rows) == 0:
            self.saved_log_path = None
            return None

        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as error:
            print(f"로그 폴더 생성 실패: {error}")
            self.saved_log_path = None
            return None

        file_name = f"session_{self.session_id}.csv"
        file_path = os.path.join(log_dir, file_name)

        fieldnames = [
            "time_sec",
            "segment_time_sec",
            "user_id",
            "user",
            "seat_env",
            "score",
            "state",
            "is_warning",
            "warning_event",
            "timestamp"
        ]

        try:
            with open(file_path, "w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(self.log_rows)
        except OSError as error:
            print(f"주행 로그 저장 실패: {error}")
            self.saved_log_path = None
            return None

        self.saved_log_path = file_path
        return file_path

class ScreenOffWindow(QWidget):
    """
    실제 전원을 완전히 끄기 전 단계의 화면 꺼짐 상태.
    앱은 계속 실행되지만 사용자에게는 검은 화면만 보인다.
    """

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.init_ui()

    def init_ui(self):
        self.setObjectName("ScreenOffWindow")
        self.setStyleSheet(
            """
            QWidget#ScreenOffWindow {
                background-color: #000000;
            }
            """
        )

        # 최종 시연에서는 아무 문구 없이 검은 화면으로 두는 게 자연스럽다.
        layout = QVBoxLayout()
        self.setLayout(layout)


class PressureIdentificationMeasureWindow(QWidget):
    """
    S 버튼 입력 후 기존 사용자 식별 전에 보여주는 체압 측정 안내 화면.
    사용자가 막 앉거나 자세를 잡는 동안 바로 SVM 예측을 하지 않도록
    짧은 안정화 시간을 제공한다.
    """

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.duration_ms = PRESSURE_IDENTIFICATION_MEASUREMENT_MS
        self.elapsed_ms = 0
        self.timer = QTimer(self)
        self.timer.setInterval(PRESSURE_IDENTIFICATION_PROGRESS_INTERVAL_MS)
        self.timer.timeout.connect(self.update_progress)
        self.init_ui()

    def init_ui(self):
        self.setObjectName("PressureIdentificationMeasureWindow")
        self.setStyleSheet(
            """
            QWidget#PressureIdentificationMeasureWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QLabel, QProgressBar {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        title_label = QLabel("Seat ID")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            """
            background-color: transparent;
            font-size: 32px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        subtitle_label = QLabel("사용자 식별을 준비하고 있습니다")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(
            """
            background-color: transparent;
            font-size: 15px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        card = QFrame()
        card.setObjectName("PressureMeasureCard")
        card.setStyleSheet(
            """
            QFrame#PressureMeasureCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 28px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(26)
        shadow.setXOffset(0)
        shadow.setYOffset(9)
        shadow.setColor(QColor(0, 0, 0, 26))
        card.setGraphicsEffect(shadow)

        self.icon_label = QLabel("↧")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(56, 56)
        self.icon_label.setStyleSheet(
            """
            background-color: #EEF4FF;
            color: #3C6FEA;
            border-radius: 28px;
            font-size: 30px;
            font-weight: 500;
            padding-bottom: 6px;
            """
        )

        self.status_label = QLabel("체압 · 등 · 목 자세 측정을 준비하고 있습니다")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet(
            """
            background-color: transparent;
            font-size: 22px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        self.detail_label = QLabel("바른 자세로 앉아 등받이에 자연스럽게 기대주세요.")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet(
            """
            background-color: transparent;
            font-size: 15px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #EEF2FA;
                border: none;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: #3C6FEA;
                border-radius: 6px;
            }
            """
        )

        self.count_label = QLabel("")
        self.count_label.setAlignment(Qt.AlignCenter)
        self.count_label.setStyleSheet(
            """
            background-color: transparent;
            font-size: 13px;
            font-weight: 400;
            color: #8A94A6;
            """
        )

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(42, 36, 42, 34)
        card_layout.setSpacing(16)
        card_layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        card_layout.addWidget(self.status_label)
        card_layout.addWidget(self.detail_label)
        card_layout.addSpacing(6)
        card_layout.addWidget(self.progress_bar)
        card_layout.addWidget(self.count_label)
        card.setLayout(card_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(70, 44, 70, 44)
        layout.addStretch(1)
        layout.addWidget(title_label)
        layout.addSpacing(6)
        layout.addWidget(subtitle_label)
        layout.addSpacing(30)
        layout.addWidget(card)
        layout.addStretch(2)

        self.setLayout(layout)

    def start_measurement(self, duration_ms=PRESSURE_IDENTIFICATION_MEASUREMENT_MS, attempt_number=1):
        self.duration_ms = max(500, int(duration_ms))
        self.elapsed_ms = 0
        self.progress_bar.setValue(0)
        self.status_label.setText(f"체압 · 등 · 목 자세 측정을 준비하고 있습니다 (시도 {attempt_number})")
        self.detail_label.setText("바른 자세로 앉아 등받이에 자연스럽게 기대주세요.")
        self.update_count_label()
        self.timer.start()

    def stop_measurement(self):
        self.timer.stop()

    def show_sensor_status(self, readiness, attempt_number):
        labels = [readiness[key]["label"] for key in ("pressure", "back", "neck")]
        self.status_label.setText(f"센서 확인 중 · 시도 {attempt_number}")
        self.detail_label.setText("  ·  ".join(labels))

    def show_retry(self, reason, next_attempt):
        self.timer.stop()
        self.progress_bar.setValue(100)
        self.status_label.setText("세 센서 중 일부를 다시 측정합니다")
        self.detail_label.setText(
            f"{reason}\n바른 자세를 유지해주세요. 잠시 후 {next_attempt}번째 측정을 시작합니다."
        )
        self.count_label.setText("측정이 모두 성공해야 다음 화면으로 이동합니다")

    def update_progress(self):
        self.elapsed_ms += PRESSURE_IDENTIFICATION_PROGRESS_INTERVAL_MS
        ratio = min(1.0, self.elapsed_ms / max(1, self.duration_ms))
        self.progress_bar.setValue(int(round(ratio * 100)))

        if self.elapsed_ms < SENSOR_CALIBRATION_SETTLE_MS:
            self.status_label.setText("체압 · 등 · 목 자세 측정을 준비하고 있습니다")
            self.detail_label.setText("바른 자세로 앉아 등받이에 자연스럽게 기대주세요.")
        elif self.elapsed_ms < SENSOR_CALIBRATION_SETTLE_MS + SENSOR_CALIBRATION_MEASURE_MS:
            self.status_label.setText("체압 · 등 · 목 자세를 함께 측정 중입니다")
            self.detail_label.setText("기준 자세가 저장될 때까지 잠시 움직이지 마세요.")
        else:
            self.status_label.setText("측정 결과를 확인하고 있습니다")
            self.detail_label.setText("잠시만 기다려주세요.")

        self.update_count_label()

        if ratio >= 1.0:
            self.timer.stop()

    def update_count_label(self):
        remaining_ms = max(0, self.duration_ms - self.elapsed_ms)
        remaining_sec = max(1, int(math.ceil(remaining_ms / 1000.0))) if remaining_ms > 0 else 0

        if remaining_sec > 0:
            self.count_label.setText(f"최대 {remaining_sec}초 동안 이번 측정 결과를 확인합니다")
        else:
            self.count_label.setText("세 센서 결과를 확인하고 있습니다…")



class ScoreGraphWidget(QWidget):
    """
    점수 데이터를 앱 디자인에 맞게 부드러운 선 그래프로 그리는 위젯.
    - 대시보드: 최근 점수를 실시간으로 이어서 표시
    - 리포트: 전체 점수를 한 화면 너비 안에 압축해서 표시
    - 기준 점수 미만 구간은 그래프 데이터 선 아래를 주황색 반투명 영역으로 표시
    - 75점 아래로 내려간 시점과 다시 올라온 시점을 x축에 표시
    """

    def __init__(self, mode="dashboard", max_points=None, empty_text="점수 데이터가 없습니다."):
        super().__init__()

        self.mode = mode
        self.max_points = max_points
        self.empty_text = empty_text
        self.scores = []

        # 현재 화면에 표시되는 첫 번째 점수의 실제 시간 index.
        # 대시보드처럼 최근 30개만 보여줄 때도 x축 시간은 실제 주행 시간 기준으로 표시하기 위함.
        self.time_offset = 0

        # 기존 코드 호환용. 실제 표시할 경고 구간은 scores를 기준으로 다시 계산한다.
        self.warning_entries = []

        self.threshold_score = SCORE_WARNING_THRESHOLD

        self.setMinimumHeight(125)
        self.setStyleSheet("background-color: transparent; border: none;")

    def reset_scores(self):
        self.scores = []
        self.warning_entries = []
        self.time_offset = 0
        self.update()

    def set_scores(self, scores, warning_indices=None):
        scores = list(scores)
        warning_indices = list(warning_indices or [])

        cut_count = 0

        if self.max_points is not None and len(scores) > self.max_points:
            cut_count = len(scores) - self.max_points
            scores = scores[-self.max_points:]

        self.scores = scores
        self.time_offset = cut_count
        self.warning_entries = []

        for original_index in warning_indices:
            local_index = original_index - cut_count

            if 0 <= local_index < len(self.scores):
                self.warning_entries.append((local_index, original_index))

        self.update()

    def add_score(self, score, is_warning=False, warning_time=None):
        self.scores.append(score)

        if is_warning:
            local_index = len(self.scores) - 1

            if warning_time is None:
                warning_time = self.time_offset + local_index

            self.warning_entries.append((local_index, warning_time))

        if self.max_points is not None and len(self.scores) > self.max_points:
            self.scores = self.scores[-self.max_points:]
            self.time_offset += 1

            new_entries = []
            for local_index, time_value in self.warning_entries:
                local_index -= 1

                if local_index >= 0:
                    new_entries.append((local_index, time_value))

            self.warning_entries = new_entries

        self.update()

    def _score_to_y(self, score, graph_bottom, graph_height):
        y_min = 50
        y_max = 100
        clamped_score = max(y_min, min(y_max, score))
        ratio = (clamped_score - y_min) / (y_max - y_min)
        return graph_bottom - ratio * graph_height

    def _index_to_x(self, index, graph_left, graph_width, point_count):
        if point_count <= 1:
            return graph_left + graph_width

        return graph_left + (index / (point_count - 1)) * graph_width

    def _build_smooth_path(self, points):
        path = QPainterPath()

        if len(points) == 0:
            return path

        path.moveTo(points[0])

        if len(points) == 1:
            return path

        if len(points) == 2:
            path.lineTo(points[1])
            return path

        for i in range(1, len(points)):
            previous_point = points[i - 1]
            current_point = points[i]

            mid_x = (previous_point.x() + current_point.x()) / 2
            mid_y = (previous_point.y() + current_point.y()) / 2
            mid_point = QPointF(mid_x, mid_y)

            path.quadTo(previous_point, mid_point)

        path.quadTo(points[-2], points[-1])

        return path

    def _find_low_score_ranges(self):
        """
        기준 점수 미만으로 내려가 있는 구간을 찾는다.
        반환값 예시:
        [
            {"start": 3, "last_low": 7, "recovery": 8},
            {"start": 14, "last_low": 19, "recovery": None}
        ]
        """

        ranges = []
        start_index = None

        for index, score in enumerate(self.scores):
            is_low = score < self.threshold_score

            if is_low and start_index is None:
                start_index = index

            elif (not is_low) and start_index is not None:
                ranges.append(
                    {
                        "start": start_index,
                        "last_low": index - 1,
                        "recovery": index
                    }
                )
                start_index = None

        if start_index is not None:
            ranges.append(
                {
                    "start": start_index,
                    "last_low": len(self.scores) - 1,
                    "recovery": None
                }
            )

        return ranges

    def _build_warning_markers(self, low_ranges):
        """
        x축에 표시할 진입/회복 시점을 만든다.
        기준 점수 아래로 내려간 순간과 다시 올라온 순간을 각각 표시한다.
        """

        markers = []

        for low_range in low_ranges:
            start_index = low_range["start"]
            markers.append(
                {
                    "index": start_index,
                    "time": self.time_offset + start_index,
                    "kind": "start"
                }
            )

            recovery_index = low_range["recovery"]

            if recovery_index is not None:
                markers.append(
                    {
                        "index": recovery_index,
                        "time": self.time_offset + recovery_index,
                        "kind": "recovery"
                    }
                )

        return markers

    def _interpolate_threshold_point(self, first_index, second_index, points, scores, guide_y):
        """
        기준 점수 선과 그래프 선이 만나는 지점을 선형 보간으로 계산한다.
        경고 영역이 기준선 바깥까지 칠해지지 않도록 경계점을 정확히 잡기 위한 보조 함수다.
        """

        first_score = float(scores[first_index])
        second_score = float(scores[second_index])
        denominator = second_score - first_score

        if abs(denominator) < 1e-6:
            ratio = 0.0
        else:
            ratio = (self.threshold_score - first_score) / denominator
            ratio = max(0.0, min(1.0, ratio))

        first_point = points[first_index]
        second_point = points[second_index]

        x = first_point.x() + (second_point.x() - first_point.x()) * ratio
        return QPointF(x, guide_y)

    def _draw_warning_bands(self, painter, low_ranges, points, graph_bottom, guide_y, graph_width, graph_left, point_count):
        """
        기준 점수 미만 구간을 주황색 반투명 영역으로 표시한다.

        기존 방식은 기준선부터 x축까지 직사각형으로 칠했기 때문에
        실제 데이터 선 모양과 무관하게 넓은 세로 영역이 표시되었다.
        이 방식은 기준 점수 아래로 내려간 구간에서
        그래프 데이터 선 아래쪽 영역만 채운다.
        """

        if len(low_ranges) == 0 or len(points) == 0:
            return

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(242, 184, 75, 48))

        scores = list(self.scores)

        for low_range in low_ranges:
            start_index = low_range["start"]
            recovery_index = low_range["recovery"]
            last_low_index = low_range["last_low"]

            if not (0 <= start_index < len(points)):
                continue

            if point_count <= 1:
                point = points[start_index]
                warning_path = QPainterPath()
                warning_path.moveTo(graph_left, point.y())
                warning_path.lineTo(graph_left + graph_width, point.y())
                warning_path.lineTo(graph_left + graph_width, graph_bottom)
                warning_path.lineTo(graph_left, graph_bottom)
                warning_path.closeSubpath()
                painter.drawPath(warning_path)
                continue

            # 시작 경계: 직전 점이 기준 이상이면 두 점 사이에서 기준선과 만나는 지점을 사용한다.
            if start_index > 0 and scores[start_index - 1] >= self.threshold_score:
                start_point = self._interpolate_threshold_point(
                    start_index - 1,
                    start_index,
                    points,
                    scores,
                    guide_y,
                )
            else:
                start_point = points[start_index]

            # 종료 경계: 회복 점이 있으면 마지막 낮은 점과 회복 점 사이의 기준선 교차점을 사용한다.
            if recovery_index is not None and 0 <= recovery_index < len(points):
                end_point = self._interpolate_threshold_point(
                    last_low_index,
                    recovery_index,
                    points,
                    scores,
                    guide_y,
                )
            else:
                end_point = points[last_low_index]

                # 마지막까지 낮은 상태라면 영역이 점 하나에서 끊겨 보이지 않도록 반 칸 정도 오른쪽으로 확장한다.
                if last_low_index == len(points) - 1:
                    step_width = graph_width / max(1, point_count - 1)
                    end_point = QPointF(
                        min(graph_left + graph_width, end_point.x() + step_width * 0.45),
                        end_point.y(),
                    )

            warning_path = QPainterPath()
            warning_path.moveTo(start_point)

            for index in range(start_index, last_low_index + 1):
                if 0 <= index < len(points):
                    warning_path.lineTo(points[index])

            warning_path.lineTo(end_point)
            warning_path.lineTo(end_point.x(), graph_bottom)
            warning_path.lineTo(start_point.x(), graph_bottom)
            warning_path.closeSubpath()

            painter.drawPath(warning_path)

    def _draw_warning_lines_and_labels(self, painter, markers, points, graph_bottom, width, height):
        if len(markers) == 0:
            return

        line_pen = QPen(QColor("#9AA4B8"))
        line_pen.setWidth(1)
        line_pen.setStyle(Qt.SolidLine)
        line_pen.setCapStyle(Qt.RoundCap)

        label_font = QFont("Malgun Gothic", 7)
        label_color = QColor("#9AA4B8")
        label_width = 42
        label_height = 16
        label_y = height - 24

        label_items = []

        painter.setPen(line_pen)

        for marker in markers:
            index = marker["index"]

            if not (0 <= index < len(points)):
                continue

            point = points[index]

            # 세로선은 해당 점에서 아래로만 내려가게 한다.
            painter.drawLine(int(point.x()), int(point.y() + 5), int(point.x()), int(graph_bottom))

            label_x = point.x() - label_width / 2
            label_x = max(0, min(label_x, width - label_width))
            label_items.append((label_x, marker["time"]))

        # 점은 노란 링으로 표시한다.
        for marker in markers:
            index = marker["index"]

            if not (0 <= index < len(points)):
                continue

            point = points[index]
            painter.setPen(QPen(QColor("#F2B84B"), 2))
            painter.setBrush(QColor("#FFF4CC"))
            painter.drawEllipse(
                int(point.x() - 5),
                int(point.y() - 5),
                10,
                10
            )

        # x축 시간 표시. 글씨체와 크기는 y축 숫자와 동일하게 둔다.
        painter.setFont(label_font)
        painter.setPen(label_color)

        label_items.sort(key=lambda item: item[0])
        last_right = -999

        for label_x, time_value in label_items:
            # 시간이 너무 가까우면 글자가 겹치므로 살짝 오른쪽으로 밀어준다.
            if label_x < last_right + 2:
                label_x = last_right + 2
                label_x = min(label_x, width - label_width)

            label_rect = QRectF(label_x, label_y, label_width, label_height)
            painter.drawText(label_rect, Qt.AlignCenter, f"{time_value}초")
            last_right = label_x + label_width

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = self.width()
        height = self.height()

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F7FAFF"))
        painter.drawRoundedRect(0, 0, width, height, 15, 15)

        # y축 숫자가 잘리지 않도록 왼쪽/위/아래 여백을 넉넉하게 잡는다.
        left_margin = 52
        right_margin = 24
        top_margin = 26
        bottom_margin = 32

        graph_left = left_margin
        graph_right = width - right_margin
        graph_top = top_margin
        graph_bottom = height - bottom_margin
        graph_width = max(1, graph_right - graph_left)
        graph_height = max(1, graph_bottom - graph_top)

        if len(self.scores) == 0:
            painter.setPen(QColor("#9AA4B8"))
            painter.setFont(QFont("Malgun Gothic", 9))
            painter.drawText(self.rect(), Qt.AlignCenter, self.empty_text)
            return

        y_ticks = [50, self.threshold_score, 100]
        grid_pen = QPen(QColor("#E5EBF7"))
        grid_pen.setWidth(1)
        axis_font = QFont("Malgun Gothic", 7)
        axis_color = QColor("#9AA4B8")

        painter.setFont(axis_font)

        for value in y_ticks:
            y = self._score_to_y(value, graph_bottom, graph_height)

            painter.setPen(grid_pen)
            painter.drawLine(graph_left, int(y), graph_right, int(y))

            painter.setPen(axis_color)
            label_rect = QRectF(8, y - 8, graph_left - 14, 16)
            painter.drawText(label_rect, Qt.AlignRight | Qt.AlignVCenter, str(value))

        guide_y = self._score_to_y(self.threshold_score, graph_bottom, graph_height)
        guide_pen = QPen(QColor("#D3DEF4"))
        guide_pen.setWidth(1)
        guide_pen.setStyle(Qt.DashLine)
        painter.setPen(guide_pen)
        painter.drawLine(graph_left, int(guide_y), graph_right, int(guide_y))

        data = self.scores
        n = len(data)
        points = []

        for i, score in enumerate(data):
            x = self._index_to_x(i, graph_left, graph_width, n)
            y = self._score_to_y(score, graph_bottom, graph_height)
            points.append(QPointF(x, y))

        graph_path = self._build_smooth_path(points)

        if len(points) >= 2:
            fill_path = QPainterPath(graph_path)
            fill_path.lineTo(points[-1].x(), graph_bottom)
            fill_path.lineTo(points[0].x(), graph_bottom)
            fill_path.closeSubpath()

            gradient = QLinearGradient(0, graph_top, 0, graph_bottom)
            gradient.setColorAt(0.0, QColor(60, 111, 234, 30))
            gradient.setColorAt(1.0, QColor(60, 111, 234, 0))

            painter.setPen(Qt.NoPen)
            painter.setBrush(gradient)
            painter.drawPath(fill_path)

        low_ranges = self._find_low_score_ranges()
        self._draw_warning_bands(
            painter,
            low_ranges,
            points,
            graph_bottom,
            guide_y,
            graph_width,
            graph_left,
            n
        )

        line_pen = QPen(QColor("#3C6FEA"))
        line_pen.setWidth(3 if self.mode == "dashboard" else 2)
        line_pen.setCapStyle(Qt.RoundCap)
        line_pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(line_pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(graph_path)

        should_draw_points = self.mode == "dashboard" and n <= 35

        if should_draw_points:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor("#3C6FEA"))
            radius = 2

            for point in points:
                painter.drawEllipse(
                    int(point.x() - radius),
                    int(point.y() - radius),
                    radius * 2,
                    radius * 2
                )

        markers = self._build_warning_markers(low_ranges)
        self._draw_warning_lines_and_labels(painter, markers, points, graph_bottom, width, height)

        # 최신 점수 위치만 작은 파란 링으로 표시한다. 점수 텍스트는 표시하지 않는다.
        last_point = points[-1]
        outer_radius = 5 if self.mode == "dashboard" else 4
        inner_radius = 2

        painter.setPen(QPen(QColor("#3C6FEA"), 2))
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawEllipse(
            int(last_point.x() - outer_radius),
            int(last_point.y() - outer_radius),
            outer_radius * 2,
            outer_radius * 2
        )

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#3C6FEA"))
        painter.drawEllipse(
            int(last_point.x() - inner_radius),
            int(last_point.y() - inner_radius),
            inner_radius * 2,
            inner_radius * 2
        )

class ProfileCard(QFrame):
    def __init__(self, name, click_callback, is_add_card=False,
                 delete_callback=None, show_delete_button=False):
        super().__init__()

        self.name = name
        self.click_callback = click_callback
        self.is_add_card = is_add_card
        self.delete_callback = delete_callback
        self.show_delete_button = show_delete_button

        self.init_ui()

    def init_ui(self):
        self.setFixedSize(PROFILE_CARD_WIDTH, PROFILE_CARD_HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

        if self.is_add_card:
            self.setObjectName("AddProfileCard")
        else:
            self.setObjectName("ProfileCard")

        self.setStyleSheet(
            """
            QFrame#ProfileCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 24px;
            }

            QFrame#ProfileCard:hover {
                background-color: #F7F8FA;
            }

            QFrame#AddProfileCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 24px;
            }

            QFrame#AddProfileCard:hover {
                background-color: #F7F8FA;
            }

            QLabel {
                background-color: transparent;
                border: none;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(24)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 30))
        self.setGraphicsEffect(shadow)

        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(12, 10, 12, 14)
        main_layout.setSpacing(0)

        # 삭제 모드일 때만 카드 오른쪽 위에 작은 X 버튼 표시
        top_layout = QHBoxLayout()
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.addStretch(1)

        if self.show_delete_button and not self.is_add_card:
            self.delete_button = QPushButton("×")
            self.delete_button.setObjectName("ProfileDeleteButton")
            self.delete_button.setCursor(Qt.PointingHandCursor)
            self.delete_button.setFixedSize(24, 24)
            self.delete_button.setStyleSheet(
                """
                QPushButton#ProfileDeleteButton {
                    background-color: #FFF1F1;
                    color: #D84A4A;
                    border: 1px solid #FFD3D3;
                    border-radius: 12px;
                    font-size: 15px;
                    font-weight: 500;
                    padding-bottom: 2px;
                }

                QPushButton#ProfileDeleteButton:hover {
                    background-color: #FFE5E5;
                    border: 1px solid #FFB7B7;
                }
                """
            )
            self.delete_button.clicked.connect(self.on_delete_clicked)
            top_layout.addWidget(self.delete_button)
        else:
            # 삭제 버튼이 없을 때도 높이를 맞춰서 카드 내용 위치가 흔들리지 않게 함
            empty_space = QWidget()
            empty_space.setFixedSize(24, 24)
            empty_space.setStyleSheet("background-color: transparent; border: none;")
            top_layout.addWidget(empty_space)

        content_layout = QVBoxLayout()
        content_layout.setAlignment(Qt.AlignCenter)
        content_layout.setSpacing(12)
        content_layout.setContentsMargins(0, 0, 0, 0)

        if self.is_add_card:
            icon_label = QLabel("+")
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setFixedSize(56, 56)
            icon_label.setStyleSheet(
                """
                background-color: #EEF4FF;
                color: #3C6FEA;
                border-radius: 28px;
                font-size: 30px;
                font-weight: 400;
                padding-bottom: 10px;
                """
            )

            name_label = QLabel("새 사용자")
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet(
                """
                background-color: transparent;
                color: #1D1D1F;
                font-size: 16px;
                font-weight: 500;
                """
            )

        else:
            initial = self.name[0]

            icon_label = QLabel(initial)
            icon_label.setAlignment(Qt.AlignCenter)
            icon_label.setFixedSize(56, 56)
            icon_label.setStyleSheet(
                """
                background-color: #EEF4FF;
                color: #3C6FEA;
                border-radius: 28px;
                font-size: 24px;
                font-weight: 500;
                """
            )

            name_label = QLabel(self.name)
            name_label.setAlignment(Qt.AlignCenter)
            name_label.setStyleSheet(
                """
                background-color: transparent;
                color: #1D1D1F;
                font-size: 16px;
                font-weight: 500;
                """
            )

        content_layout.addWidget(icon_label, alignment=Qt.AlignCenter)
        content_layout.addWidget(name_label)

        main_layout.addLayout(top_layout)
        main_layout.addStretch(1)
        main_layout.addLayout(content_layout)
        main_layout.addStretch(2)

        self.setLayout(main_layout)

    def on_delete_clicked(self):
        if self.delete_callback is not None:
            self.delete_callback(self.name)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.click_callback(self.name)


class HomeWindow(QWidget):
    def __init__(self, stack):
        super().__init__()

        self.stack = stack

        # user_profile.csv에서 불러온 사용자 목록. 파일이 없으면 빈 목록으로 시작한다.
        self.profiles = load_user_profiles()

        # 삭제 모드: True일 때 각 사용자 카드 우측 상단에 X 버튼 표시
        self.delete_mode = False

        # 사용자 목록 보기 화면에서는 신규 사용자 카드를 숨길 수 있다.
        self.show_add_card = True

        self.init_ui()

    def init_ui(self):
        self.setObjectName("HomeWindow")
        self.setStyleSheet(
            """
            QWidget#HomeWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QLabel {
                background-color: transparent;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QPushButton {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        title_label = QLabel("Seat ID")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            """
            background-color: transparent;
            font-size: 36px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        self.exit_button = QPushButton("종료")
        self.exit_button.setObjectName("HomeExitButton")
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.setFixedSize(58, 30)
        self.exit_button.setStyleSheet(
            """
            QPushButton#HomeExitButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 11px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton#HomeExitButton:hover {
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }
            """
        )
        self.exit_button.clicked.connect(QApplication.quit)

        left_space = QWidget()
        left_space.setFixedSize(58, 30)
        left_space.setStyleSheet("background-color: transparent; border: none;")

        header_layout = QHBoxLayout()
        header_layout.addWidget(left_space)
        header_layout.addStretch(1)
        header_layout.addWidget(title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.exit_button)

        self.subtitle_label = QLabel("S 버튼을 눌러 시스템을 시작하세요")
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        self.subtitle_label.setStyleSheet(
            """
            background-color: transparent;
            font-size: 17px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        self.profile_layout = QHBoxLayout()
        self.profile_layout.setSpacing(PROFILE_CARD_SPACING)
        self.profile_layout.setAlignment(Qt.AlignCenter)

        self.delete_mode_button = QPushButton("사용자 삭제")
        self.delete_mode_button.setObjectName("DeleteModeButton")
        self.delete_mode_button.setCursor(Qt.PointingHandCursor)
        self.delete_mode_button.setFixedSize(118, 34)
        self.delete_mode_button.setStyleSheet(
            """
            QPushButton#DeleteModeButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 12px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton#DeleteModeButton:hover {
                background-color: #FFF1F1;
                color: #D84A4A;
                border: 1px solid #FFD3D3;
            }
            """
        )
        self.delete_mode_button.clicked.connect(self.toggle_delete_mode)

        self.edit_seat_button = QPushButton("시트 환경 수정")
        self.edit_seat_button.setObjectName("EditSeatButton")
        self.edit_seat_button.setCursor(Qt.PointingHandCursor)
        self.edit_seat_button.setFixedSize(130, 34)
        self.edit_seat_button.setStyleSheet(
            """
            QPushButton#EditSeatButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 12px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton#EditSeatButton:hover {
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }
            """
        )
        self.edit_seat_button.clicked.connect(self.open_seat_edit_dialog)

        delete_button_layout = QHBoxLayout()
        delete_button_layout.addStretch(1)
        delete_button_layout.addWidget(self.edit_seat_button)
        delete_button_layout.addSpacing(12)
        delete_button_layout.addWidget(self.delete_mode_button)
        delete_button_layout.addStretch(1)

        layout = QVBoxLayout()
        layout.setContentsMargins(60, 45, 60, 45)

        layout.addStretch(1)
        layout.addLayout(header_layout)
        layout.addSpacing(8)
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(45)
        layout.addLayout(self.profile_layout)
        layout.addSpacing(22)
        layout.addLayout(delete_button_layout)
        layout.addStretch(2)

        self.setLayout(layout)

        self.refresh_profile_buttons()

    def refresh_profile_buttons(self):
        """
        사용자 카드 영역을 다시 그린다.
        최대 사용자 수는 4명으로 제한하되,
        화면에는 현재 표시할 카드만 가운데 정렬한다.

        즉, 이전처럼 4칸을 고정해서 왼쪽부터 채우지 않고:
        - 사용자 1명 + 새 사용자 → 가운데
        - 사용자 2명 + 새 사용자 → 가운데
        - 사용자 3명 + 새 사용자 → 가운데
        - 사용자 4명 → 가운데
        로 배치한다.
        """

        while self.profile_layout.count():
            item = self.profile_layout.takeAt(0)
            widget = item.widget()

            if widget is not None:
                widget.deleteLater()

        visible_profiles = list(self.profiles[:MAX_USER_PROFILES])
        profile_count = len(visible_profiles)

        for name in visible_profiles:
            profile_card = ProfileCard(
                name=name,
                click_callback=self.select_profile,
                is_add_card=False,
                delete_callback=self.delete_profile,
                show_delete_button=self.delete_mode
            )

            self.profile_layout.addWidget(profile_card)

        can_show_add_card = (
            self.show_add_card
            and not self.delete_mode
            and profile_count < MAX_USER_PROFILES
        )

        if can_show_add_card:
            add_card = ProfileCard(
                name="새 사용자",
                click_callback=self.go_add_user,
                is_add_card=True
            )

            self.profile_layout.addWidget(add_card)

        # 카드 수가 달라도 항상 가운데 정렬을 유지한다.
        self.profile_layout.setAlignment(Qt.AlignCenter)

    def set_add_card_visible(self, visible):
        self.show_add_card = bool(visible)
        self.refresh_profile_buttons()

    def set_delete_button_normal_style(self):
        self.delete_mode_button.setText("사용자 삭제")
        self.delete_mode_button.setStyleSheet(
            """
            QPushButton#DeleteModeButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 12px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton#DeleteModeButton:hover {
                background-color: #FFF1F1;
                color: #D84A4A;
                border: 1px solid #FFD3D3;
            }
            """
        )

    def set_delete_button_active_style(self):
        self.delete_mode_button.setText("삭제 완료")
        self.delete_mode_button.setStyleSheet(
            """
            QPushButton#DeleteModeButton {
                background-color: #FFF1F1;
                color: #D84A4A;
                border: 1px solid #FFD3D3;
                border-radius: 12px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton#DeleteModeButton:hover {
                background-color: #FFE5E5;
                border: 1px solid #FFB7B7;
            }
            """
        )

    def update_delete_button_visibility(self, drive_state):
        """
        삭제할 사용자가 없으면 사용자 삭제 버튼을 숨긴다.
        사용자가 생기면 USER_SELECT/PARK_SAFE 상태에서만 보여준다.
        """

        can_show_delete_button = (
            drive_state in [USER_SELECT, PARK_SAFE]
            and len(self.profiles) > 0
        )

        self.delete_mode_button.setVisible(can_show_delete_button)

        can_show_edit_button = (
            drive_state in [USER_SELECT, PARK_SAFE]
            and len(self.profiles) > 0
            and not self.delete_mode
        )
        self.edit_seat_button.setVisible(can_show_edit_button)

        if not can_show_delete_button:
            self.delete_mode = False
            self.set_delete_button_normal_style()

    def update_subtitle_text(self, drive_state, current_user):
        if drive_state == IDLE:
            self.subtitle_label.setText("S 버튼을 눌러 시스템을 시작하세요")

        elif drive_state == USER_SELECT:
            if len(self.profiles) == 0:
                self.subtitle_label.setText("사용자를 추가하세요")
            elif len(self.profiles) >= MAX_USER_PROFILES:
                self.subtitle_label.setText("사용자 프로필을 선택하세요 · 최대 4명 등록됨")
            else:
                self.subtitle_label.setText("사용자 프로필을 선택하세요")

        elif drive_state == PARK_SAFE:
            if len(self.profiles) == 0:
                self.subtitle_label.setText("사용자를 추가하세요")
            elif current_user is None:
                self.subtitle_label.setText("안전모드 · 사용자 선택 및 시트 조절 가능")
            else:
                self.subtitle_label.setText(
                    f"안전모드 · 현재 사용자: {current_user} · 사용자 변경 가능"
                )

        elif drive_state == REPORT:
            self.subtitle_label.setText("리포트가 생성되었습니다")

        else:
            if len(self.profiles) == 0:
                self.subtitle_label.setText("사용자를 추가하세요")
            else:
                self.subtitle_label.setText("사용자 프로필을 선택하세요")

    def open_seat_edit_dialog(self):
        if self.stack.app.drive_state == IDLE:
            QMessageBox.information(
                self,
                "시스템 대기 중",
                "S 버튼을 눌러 시스템을 시작한 뒤 시트 환경을 수정할 수 있습니다."
            )
            return

        if self.stack.app.drive_state == DRIVE:
            QMessageBox.information(
                self,
                "수정 불가",
                "주행 분석 중에는 시트 환경을 수정할 수 없습니다.\nP 버튼을 눌러 안전모드로 전환한 뒤 수정해주세요."
            )
            return

        records = load_user_profile_records()
        if len(records) == 0:
            QMessageBox.information(self, "수정할 사용자 없음", "등록된 사용자가 없습니다.")
            return

        names = [record.get("name", record.get("nickname", "")) for record in records]
        names = [name for name in names if name]

        selected_name, ok = QInputDialog.getItem(
            self,
            "시트 환경 수정",
            "수정할 사용자를 선택하세요.",
            names,
            0,
            False
        )

        if not ok or not selected_name:
            return

        # 시트 환경 수정은 값만 저장하고 다시 사용자 목록으로 돌아간다.
        # 실제 액추에이터 구동은 사용자를 다시 선택했을 때 수행한다.
        self.stack.app.open_seat_edit(selected_name, start_after_confirm=False)

    def toggle_delete_mode(self):
        if self.stack.app.drive_state == IDLE:
            QMessageBox.information(
                self,
                "시스템 대기 중",
                "S 버튼을 눌러 시스템을 시작한 뒤 사용자를 삭제할 수 있습니다."
            )
            return

        if len(self.profiles) == 0:
            QMessageBox.information(
                self,
                "삭제할 사용자 없음",
                "등록된 사용자가 없습니다."
            )
            return

        self.delete_mode = not self.delete_mode

        if self.delete_mode:
            self.set_delete_button_active_style()
        else:
            self.set_delete_button_normal_style()

        self.update_delete_button_visibility(self.stack.app.drive_state)
        self.refresh_profile_buttons()

    def delete_profile(self, user_name):
        if self.stack.app.drive_state == DRIVE:
            QMessageBox.information(
                self,
                "삭제 불가",
                "주행 분석 중에는 사용자를 삭제할 수 없습니다.\nP 버튼을 눌러 안전모드로 전환한 뒤 삭제해주세요."
            )
            return

        if self.stack.app.current_user == user_name and self.stack.app.drive_state == PARK_SAFE:
            QMessageBox.information(
                self,
                "삭제 불가",
                "현재 주행 세션에서 사용 중인 사용자는 삭제할 수 없습니다.\n다른 사용자를 선택하거나 세션을 종료한 뒤 삭제해주세요."
            )
            return

        answer = QMessageBox.question(
            self,
            "사용자 삭제",
            f"'{user_name}' 사용자를 삭제할까요?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if answer != QMessageBox.Yes:
            return

        if user_name in self.profiles:
            self.profiles.remove(user_name)
            save_user_profiles(self.profiles)

        if len(self.profiles) == 0:
            self.delete_mode = False

        self.update_mode_view(self.stack.app.drive_state, self.stack.app.current_user)

    def select_profile(self, user_name):
        self.stack.app.select_user(user_name)

    def go_add_user(self, user_name=None):
        if self.stack.app.drive_state == IDLE:
            QMessageBox.information(
                self,
                "시스템 대기 중",
                "S 버튼을 눌러 시스템을 시작한 뒤 사용자를 추가할 수 있습니다."
            )
            return

        records = load_user_profile_records()
        if len(records) >= MAX_USER_PROFILES:
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            self.reload_profiles()
            self.update_mode_view(self.stack.app.drive_state, self.stack.app.current_user)
            return

        self.stack.app.open_new_user_registration(start_after_register=True)

    def add_profile(self, user_name):
        """기존 코드 호환용. 이름만 들어오면 기본 시트 환경으로 사용자 생성."""

        user_name = clean_user_name(user_name)

        if user_name == "":
            QMessageBox.warning(self, "입력 오류", "사용자 이름을 입력해주세요.")
            return None

        if len(load_user_profile_records()) >= MAX_USER_PROFILES:
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            return None

        if is_duplicate_profile(user_name, self.profiles):
            QMessageBox.warning(
                self,
                "중복 사용자",
                f"'{user_name}' 사용자는 이미 등록되어 있습니다.\n다른 이름을 입력해주세요."
            )
            return None

        record = add_user_profile_record(user_name, make_default_seat_env())
        self.reload_profiles()
        self.update_mode_view(self.stack.app.drive_state, self.stack.app.current_user)
        return record

    def reload_profiles(self):
        self.profiles = load_user_profiles()

    def update_mode_view(self, drive_state, current_user):
        if drive_state in [IDLE, REPORT]:
            self.delete_mode = False

        self.update_subtitle_text(drive_state, current_user)
        self.update_delete_button_visibility(drive_state)

        if self.delete_mode:
            self.set_delete_button_active_style()
        else:
            self.set_delete_button_normal_style()

        self.refresh_profile_buttons()



class IdentificationConfirmWindow(QWidget):
    """
    S 키 입력 후 체압 데이터 기반 사용자 식별 결과를 보여주는 화면.
    5초 동안 아무 버튼도 누르지 않으면 예측된 사용자가 맞다고 보고 DRIVE로 진입한다.
    """

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.predicted_user_name = None
        self.remaining_seconds = 5
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.update_countdown)
        self.init_ui()

    def init_ui(self):
        self.setObjectName("IdentificationConfirmWindow")
        self.setStyleSheet(
            """
            QWidget#IdentificationConfirmWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QLabel {
                background-color: transparent;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QPushButton {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        self.exit_button = QPushButton("종료")
        self.exit_button.setObjectName("IdentifyExitButton")
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.setFixedSize(58, 30)
        self.exit_button.setStyleSheet(
            """
            QPushButton#IdentifyExitButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 11px;
                font-size: 13px;
                font-weight: 500;
            }
            QPushButton#IdentifyExitButton:hover {
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }
            """
        )
        self.exit_button.clicked.connect(QApplication.quit)

        header_layout = QHBoxLayout()
        header_layout.addStretch(1)
        header_layout.addWidget(self.exit_button)

        card = QFrame()
        card.setObjectName("IdentifyCard")
        card.setStyleSheet(
            """
            QFrame#IdentifyCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 28px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(10)
        shadow.setColor(QColor(0, 0, 0, 32))
        card.setGraphicsEffect(shadow)

        self.icon_label = QLabel("ID")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(68, 68)
        self.icon_label.setStyleSheet(
            """
            background-color: #EEF4FF;
            color: #3C6FEA;
            border-radius: 34px;
            font-size: 22px;
            font-weight: 600;
            """
        )

        self.title_label = QLabel("사용자 확인 중")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(
            """
            font-size: 31px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        self.detail_label = QLabel("체압 데이터를 분석하고 있습니다.")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        self.countdown_label = QLabel("5초 후 자동으로 주행을 시작합니다")
        self.countdown_label.setAlignment(Qt.AlignCenter)
        self.countdown_label.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 500;
            color: #3C6FEA;
            """
        )

        self.user_list_button = QPushButton("사용자 목록 보기")
        self.user_list_button.setObjectName("UserListButton")
        self.user_list_button.setCursor(Qt.PointingHandCursor)
        self.user_list_button.setFixedSize(150, 42)
        self.user_list_button.setStyleSheet(self.secondary_button_style("UserListButton"))
        self.user_list_button.clicked.connect(self.go_user_list)

        self.new_user_button = QPushButton("신규 사용자 등록")
        self.new_user_button.setObjectName("NewUserButton")
        self.new_user_button.setCursor(Qt.PointingHandCursor)
        self.new_user_button.setFixedSize(150, 42)
        self.new_user_button.setStyleSheet(
            """
            QPushButton#NewUserButton {
                background-color: #3C6FEA;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }
            QPushButton#NewUserButton:hover {
                background-color: #2F5FD0;
            }
            """
        )
        self.new_user_button.clicked.connect(self.go_new_user)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(14)
        button_layout.addStretch(1)
        button_layout.addWidget(self.user_list_button)
        button_layout.addWidget(self.new_user_button)
        button_layout.addStretch(1)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(48, 40, 48, 40)
        card_layout.setSpacing(14)
        card_layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        card_layout.addSpacing(6)
        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.detail_label)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.countdown_label)
        card_layout.addSpacing(16)
        card_layout.addLayout(button_layout)
        card.setLayout(card_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(60, 40, 60, 55)
        layout.addLayout(header_layout)
        layout.addStretch(1)
        layout.addWidget(card)
        layout.addStretch(1)
        self.setLayout(layout)

    def secondary_button_style(self, object_name):
        return f"""
            QPushButton#{object_name} {{
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }}
            QPushButton#{object_name}:hover {{
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }}
        """

    def start_identification(self, result):
        self.stop_timer()

        self.predicted_user_name = result.get("user_name", "")
        confidence = result.get("confidence", 0)
        user_id = result.get("user_id", "")

        if result.get("is_new_user") or self.predicted_user_name == "":
            self.predicted_user_name = None
            self.title_label.setText("신규 사용자로 보입니다")
            self.detail_label.setText("등록된 사용자가 없거나 일치하는 사용자를 찾지 못했습니다.")
            self.countdown_label.setText("신규 사용자 등록을 진행해주세요")
            self.user_list_button.setVisible(True)
            self.new_user_button.setText("신규 사용자 등록")
            return

        self.title_label.setText(f"{self.predicted_user_name} 님 맞으신가요?")
        display_number = get_user_display_number(user_id)
        self.detail_label.setText(f"등록 사용자 {display_number}번 · 신뢰도 {int(confidence * 100)}%")
        self.remaining_seconds = 5
        self.countdown_label.setText("5초 후 자동으로 주행을 시작합니다")
        self.user_list_button.setVisible(True)
        self.new_user_button.setText("신규 사용자 등록")
        self.timer.start()

    def update_countdown(self):
        self.remaining_seconds -= 1

        if self.remaining_seconds <= 0:
            self.stop_timer()
            self.accept_prediction()
            return

        self.countdown_label.setText(f"{self.remaining_seconds}초 후 자동으로 주행을 시작합니다")

    def stop_timer(self):
        if self.timer.isActive():
            self.timer.stop()

    def accept_prediction(self):
        if self.predicted_user_name is not None:
            self.stack.app.confirm_identified_user(self.predicted_user_name)

    def go_user_list(self):
        self.stop_timer()
        # 사용자 목록 보기에서 선택한 사용자도 반드시
        # 액추에이터 적용 → 시트 환경 확인 → 대시보드 흐름을 거치도록 한다.
        self.stack.app.show_user_list_from_identification()

    def go_new_user(self):
        self.stop_timer()
        if len(load_user_profile_records()) >= MAX_USER_PROFILES:
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            self.stack.app.show_user_list(show_add_card=False)
            return

        self.stack.app.open_new_user_registration(start_after_register=True)


class AddUserWindow(QWidget):
    """신규 사용자 내부 ID 자동 생성 + 이름/시트 환경 입력 화면."""

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.generated_user_id = ""
        self.start_after_register = True
        self.init_ui()

    def init_ui(self):
        self.setObjectName("AddUserWindow")
        self.setStyleSheet(
            """
            QWidget#AddUserWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            QLabel, QLineEdit, QPushButton {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        title_label = QLabel("신규 사용자 등록")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            """
            font-size: 30px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        subtitle_label = QLabel("사용자 번호는 자동으로 생성됩니다")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        card = QFrame()
        card.setObjectName("AddUserCard")
        card.setStyleSheet(
            """
            QFrame#AddUserCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 26px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(26)
        shadow.setXOffset(0)
        shadow.setYOffset(9)
        shadow.setColor(QColor(0, 0, 0, 30))
        card.setGraphicsEffect(shadow)

        id_title = QLabel("사용자 번호")
        id_title.setStyleSheet("font-size: 14px; font-weight: 500; color: #6E6E73;")

        self.user_id_label = QLabel("1")
        self.user_id_label.setStyleSheet("font-size: 28px; font-weight: 600; color: #3C6FEA;")

        name_label = QLabel("사용자 이름")
        name_label.setStyleSheet("font-size: 14px; font-weight: 500; color: #6E6E73;")

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("예: 성호원")
        self.name_input.setFixedHeight(42)
        self.name_input.setStyleSheet(self.input_style())

        seat_forward_label = QLabel("전후 위치")
        seat_forward_label.setStyleSheet("font-size: 14px; font-weight: 500; color: #6E6E73;")

        self.seat_forward_input = QLineEdit()
        self.seat_forward_input.setPlaceholderText(f"예: 0  ({int(SEAT_POSITION_MIN_MM)}~{int(SEAT_POSITION_MAX_MM)})")
        self.seat_forward_input.setFixedHeight(42)
        self.seat_forward_input.setValidator(QDoubleValidator(SEAT_POSITION_MIN_MM, SEAT_POSITION_MAX_MM, 1, self))
        self.seat_forward_input.setInputMethodHints(Qt.ImhFormattedNumbersOnly)
        self.seat_forward_input.setStyleSheet(self.input_style())

        backrest_label = QLabel("등받이 각도")
        backrest_label.setStyleSheet("font-size: 14px; font-weight: 500; color: #6E6E73;")

        self.backrest_angle_input = QLineEdit()
        self.backrest_angle_input.setPlaceholderText("예: 105  (90~130)")
        self.backrest_angle_input.setFixedHeight(42)
        self.backrest_angle_input.setValidator(QDoubleValidator(BACKREST_ANGLE_MIN_DEG, BACKREST_ANGLE_MAX_DEG, 1, self))
        self.backrest_angle_input.setInputMethodHints(Qt.ImhFormattedNumbersOnly)
        self.backrest_angle_input.setStyleSheet(self.input_style())

        seat_input_layout = QHBoxLayout()
        seat_input_layout.setSpacing(14)

        forward_layout = QVBoxLayout()
        forward_layout.setSpacing(6)
        forward_layout.addWidget(seat_forward_label)
        forward_layout.addWidget(self.seat_forward_input)

        backrest_layout = QVBoxLayout()
        backrest_layout.setSpacing(6)
        backrest_layout.addWidget(backrest_label)
        backrest_layout.addWidget(self.backrest_angle_input)

        seat_input_layout.addLayout(forward_layout)
        seat_input_layout.addLayout(backrest_layout)

        self.back_button = QPushButton("이전")
        self.back_button.setObjectName("AddBackButton")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setFixedSize(110, 42)
        self.back_button.setStyleSheet(self.secondary_button_style("AddBackButton"))
        self.back_button.clicked.connect(self.go_back)

        self.save_button = QPushButton("등록")
        self.save_button.setObjectName("AddSaveButton")
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.setFixedSize(110, 42)
        self.save_button.setStyleSheet(
            """
            QPushButton#AddSaveButton {
                background-color: #3C6FEA;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }
            QPushButton#AddSaveButton:hover {
                background-color: #2F5FD0;
            }
            """
        )
        self.save_button.clicked.connect(self.submit_user)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.back_button)
        button_layout.addSpacing(12)
        button_layout.addWidget(self.save_button)
        button_layout.addStretch(1)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(42, 34, 42, 34)
        card_layout.setSpacing(10)
        card_layout.addWidget(id_title)
        card_layout.addWidget(self.user_id_label)
        card_layout.addSpacing(10)
        card_layout.addWidget(name_label)
        card_layout.addWidget(self.name_input)
        card_layout.addSpacing(8)
        card_layout.addLayout(seat_input_layout)
        card_layout.addSpacing(18)
        card_layout.addLayout(button_layout)
        card.setLayout(card_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(90, 50, 90, 55)
        layout.addStretch(1)
        layout.addWidget(title_label)
        layout.addSpacing(6)
        layout.addWidget(subtitle_label)
        layout.addSpacing(28)
        layout.addWidget(card)
        layout.addStretch(1)
        self.setLayout(layout)

    def input_style(self):
        return """
            QLineEdit {
                background-color: #F8FAFF;
                color: #1D1D1F;
                border: 1px solid #E5EBF7;
                border-radius: 13px;
                padding-left: 14px;
                padding-right: 14px;
                font-size: 15px;
                font-weight: 400;
            }
            QLineEdit:focus {
                border: 1px solid #B7CEFF;
                background-color: #FFFFFF;
            }
        """

    def secondary_button_style(self, object_name):
        return f"""
            QPushButton#{object_name} {{
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }}
            QPushButton#{object_name}:hover {{
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }}
        """

    def prepare(self, start_after_register=True):
        self.start_after_register = start_after_register

        # 실제 저장·학습·하드웨어 연동에는 pressure_database.csv와 충돌하지 않는 내부 ID를 사용한다.
        # 화면에는 UI에 등록된 사용자 순서만 1번부터 보여준다.
        records = load_user_profile_records()

        if len(records) >= MAX_USER_PROFILES:
            self.generated_user_id = ""
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            self.stack.app.show_user_list(show_add_card=False)
            return

        self.generated_user_id = generate_next_user_id(records)
        display_number = get_user_display_number(self.generated_user_id, records)
        self.user_id_label.setText(str(display_number))
        self.name_input.clear()
        self.seat_forward_input.clear()
        self.backrest_angle_input.clear()
        self.clearFocus()

    def submit_user(self):
        self.stack.app.hide_touch_keyboard()

        user_name = clean_user_name(self.name_input.text())
        seat_forward = normalize_number_text(self.seat_forward_input.text())
        backrest_angle = normalize_number_text(self.backrest_angle_input.text())

        if user_name == "":
            QMessageBox.warning(self, "입력 오류", "사용자 이름을 입력해주세요.")
            return

        if seat_forward == "":
            QMessageBox.warning(self, "입력 오류", "전후 위치를 숫자로 입력해주세요.")
            self.seat_forward_input.setFocus()
            return

        if backrest_angle == "":
            QMessageBox.warning(self, "입력 오류", "등받이 각도를 숫자로 입력해주세요.")
            self.backrest_angle_input.setFocus()
            return

        if not (SEAT_POSITION_MIN_MM <= float(seat_forward) <= SEAT_POSITION_MAX_MM):
            QMessageBox.warning(self, "입력 오류", f"전후 위치는 {int(SEAT_POSITION_MIN_MM)}부터 {int(SEAT_POSITION_MAX_MM)} 사이로 입력해주세요.")
            self.seat_forward_input.setFocus()
            return

        if not (BACKREST_ANGLE_MIN_DEG <= float(backrest_angle) <= BACKREST_ANGLE_MAX_DEG):
            QMessageBox.warning(self, "입력 오류", "등받이 각도는 90부터 130 사이로 입력해주세요.")
            self.backrest_angle_input.setFocus()
            return

        records = load_user_profile_records()

        if len(records) >= MAX_USER_PROFILES:
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            self.stack.app.show_user_list(show_add_card=False)
            return

        if is_duplicate_profile(user_name, records):
            QMessageBox.warning(
                self,
                "중복 사용자",
                f"'{user_name}' 사용자는 이미 등록되어 있습니다.\n다른 이름을 입력해주세요."
            )
            return

        seat_env = make_seat_env(seat_forward, backrest_angle)

        record = {
            "user_id": self.generated_user_id,
            "name": user_name,
            "nickname": user_name,
            "seat_position": seat_forward,
            "seat_forward": seat_forward,
            "backrest_angle": backrest_angle,
            "seat_env": seat_env,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        self.stack.app.register_new_user(record, start_after_register=self.start_after_register)

    def go_back(self):
        self.stack.app.show_user_list()



class UserRegistrationProgressWindow(QWidget):
    """체압 등록 → 사용자 SVM 재학습 과정을 표시하는 화면."""

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.init_ui()

    def init_ui(self):
        self.setObjectName("UserRegistrationProgressWindow")
        self.setStyleSheet(
            """
            QWidget#UserRegistrationProgressWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            QLabel, QPushButton, QProgressBar {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        title_label = QLabel("사용자 등록")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet("font-size: 30px; font-weight: 600; color: #1D1D1F;")

        self.subtitle_label = QLabel("체압 데이터와 사용자 인식 모델을 준비합니다")
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        self.subtitle_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #6E6E73;")

        card = QFrame()
        card.setObjectName("RegistrationProgressCard")
        card.setStyleSheet(
            """
            QFrame#RegistrationProgressCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 28px;
            }
            """
        )
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(26)
        shadow.setXOffset(0)
        shadow.setYOffset(9)
        shadow.setColor(QColor(0, 0, 0, 26))
        card.setGraphicsEffect(shadow)

        self.status_icon = QLabel("1")
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setFixedSize(48, 48)
        self.status_icon.setStyleSheet(
            """
            background-color: #EEF4FF;
            color: #3C6FEA;
            border-radius: 24px;
            font-size: 21px;
            font-weight: 600;
            """
        )

        self.status_label = QLabel("체압 데이터를 등록하고 있습니다…")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 20px; font-weight: 600; color: #1D1D1F;")

        self.detail_label = QLabel("바른 운전 자세로 앉아 잠시 움직이지 마세요.")
        self.detail_label.setAlignment(Qt.AlignCenter)
        self.detail_label.setWordWrap(True)
        self.detail_label.setStyleSheet("font-size: 14px; font-weight: 400; color: #6E6E73;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(12)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setStyleSheet(
            """
            QProgressBar {
                background-color: #EEF2FA;
                border: none;
                border-radius: 6px;
            }
            QProgressBar::chunk {
                background-color: #3C6FEA;
                border-radius: 6px;
            }
            """
        )

        self.retry_button = QPushButton("다시 시도")
        self.retry_button.setCursor(Qt.PointingHandCursor)
        self.retry_button.setFixedSize(118, 42)
        self.retry_button.setStyleSheet(
            """
            QPushButton {
                background-color: #3C6FEA;
                color: #FFFFFF;
                border: none;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }
            QPushButton:hover { background-color: #2F5FD0; }
            """
        )
        self.retry_button.clicked.connect(self.stack.app.retry_user_registration)
        self.retry_button.hide()

        self.list_button = QPushButton("사용자 목록")
        self.list_button.setCursor(Qt.PointingHandCursor)
        self.list_button.setFixedSize(118, 42)
        self.list_button.setStyleSheet(
            """
            QPushButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }
            QPushButton:hover {
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }
            """
        )
        self.list_button.clicked.connect(lambda: self.stack.app.show_user_list(show_add_card=True))
        self.list_button.hide()

        button_layout = QHBoxLayout()
        button_layout.setSpacing(12)
        button_layout.addStretch(1)
        button_layout.addWidget(self.list_button)
        button_layout.addWidget(self.retry_button)
        button_layout.addStretch(1)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(48, 34, 48, 34)
        card_layout.setSpacing(0)
        card_layout.addWidget(self.status_icon, alignment=Qt.AlignCenter)
        card_layout.addSpacing(16)
        card_layout.addWidget(self.status_label)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.detail_label)
        card_layout.addSpacing(24)
        card_layout.addWidget(self.progress_bar)
        card_layout.addSpacing(22)
        card_layout.addLayout(button_layout)
        card.setLayout(card_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(92, 44, 92, 44)
        layout.addStretch(1)
        layout.addWidget(title_label)
        layout.addSpacing(8)
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(24)
        layout.addWidget(card)
        layout.addStretch(1)
        self.setLayout(layout)

    def prepare(self, record):
        name = str((record or {}).get("name", (record or {}).get("nickname", ""))).strip()
        self.subtitle_label.setText(f"{name} 사용자의 자동 인식 정보를 준비합니다")
        self.set_collecting(0)

    def set_collecting(self, percent=None):
        self.status_icon.setText("1")
        self.status_icon.setStyleSheet(
            "background-color: #EEF4FF; color: #3C6FEA; border-radius: 24px; "
            "font-size: 21px; font-weight: 600;"
        )
        self.status_label.setText("체압 데이터를 등록하고 있습니다…")
        self.detail_label.setText("바른 운전 자세로 앉아 잠시 움직이지 마세요.")
        self.retry_button.hide()
        self.list_button.hide()
        if percent is None:
            self.progress_bar.setRange(0, 0)
        else:
            self.progress_bar.setRange(0, 100)
            self.progress_bar.setValue(max(0, min(100, int(percent))))

    def set_training(self):
        self.status_icon.setText("2")
        self.status_label.setText("사용자 인식 모델을 업데이트하고 있습니다…")
        self.detail_label.setText("새 체압 데이터를 반영해 SVM을 다시 학습합니다.")
        self.progress_bar.setRange(0, 0)
        self.retry_button.hide()
        self.list_button.hide()

    def set_success(self):
        self.status_icon.setText("✓")
        self.status_icon.setStyleSheet(
            "background-color: #EEF9F1; color: #2E9B56; border-radius: 24px; "
            "font-size: 22px; font-weight: 600;"
        )
        self.status_label.setText("등록이 완료되었습니다")
        self.detail_label.setText("새 사용자 인식 모델이 적용되었습니다.")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.retry_button.hide()
        self.list_button.hide()

    def set_error(self, message):
        self.status_icon.setText("!")
        self.status_icon.setStyleSheet(
            "background-color: #FFF3E8; color: #E28632; border-radius: 24px; "
            "font-size: 22px; font-weight: 600;"
        )
        self.status_label.setText("자동 사용자 인식 등록에 실패했습니다")
        self.detail_label.setText(str(message))
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.list_button.show()
        self.retry_button.show()


class SeatSettingConfirmWindow(QWidget):
    """시트 환경 적용 후 사용자가 적절한지 확인하는 화면."""

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.record = None
        self.mode = "new"
        self.start_after_confirm = True
        self.init_ui()

    def init_ui(self):
        self.setObjectName("SeatSettingConfirmWindow")
        self.setStyleSheet(
            """
            QWidget#SeatSettingConfirmWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QLabel, QPushButton {
                background-color: transparent;
                border: none;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        title_label = QLabel("시트 환경 확인")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            """
            font-size: 30px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        self.subtitle_label = QLabel("시트가 설정값으로 이동했습니다")
        self.subtitle_label.setAlignment(Qt.AlignCenter)
        self.subtitle_label.setStyleSheet(
            """
            font-size: 14px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        card = QFrame()
        card.setObjectName("SeatConfirmCard")
        card.setStyleSheet(
            """
            QFrame#SeatConfirmCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 28px;
            }
            """
        )
        card.setGraphicsEffect(self.make_shadow(blur=26, y_offset=9, alpha=26))

        self.status_icon = QLabel("✓")
        self.status_icon.setAlignment(Qt.AlignCenter)
        self.status_icon.setFixedSize(46, 46)
        self.status_icon.setStyleSheet(
            """
            background-color: #EEF4FF;
            color: #3C6FEA;
            border-radius: 23px;
            font-size: 23px;
            font-weight: 600;
            """
        )

        self.user_label = QLabel("-")
        self.user_label.setAlignment(Qt.AlignCenter)
        self.user_label.setStyleSheet(
            """
            font-size: 20px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        self.id_label = QLabel("사용자 번호 -")
        self.id_label.setAlignment(Qt.AlignCenter)
        self.id_label.setStyleSheet(
            """
            font-size: 13px;
            font-weight: 500;
            color: #8A8F9E;
            """
        )

        forward_card, self.forward_value_label = self.create_value_card("전후 위치", "-")
        backrest_card, self.backrest_value_label = self.create_value_card("등받이 각도", "-")

        values_layout = QHBoxLayout()
        values_layout.setSpacing(16)
        values_layout.addWidget(forward_card)
        values_layout.addWidget(backrest_card)

        self.instruction_label = QLabel("실제 위치가 적절하면 확인을 눌러주세요")
        self.instruction_label.setAlignment(Qt.AlignCenter)
        self.instruction_label.setWordWrap(True)
        self.instruction_label.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        self.edit_button = QPushButton("수정")
        self.edit_button.setObjectName("ConfirmEditButton")
        self.edit_button.setCursor(Qt.PointingHandCursor)
        self.edit_button.setFixedSize(118, 42)
        self.edit_button.setStyleSheet(self.secondary_button_style("ConfirmEditButton"))
        self.edit_button.clicked.connect(self.go_edit)

        self.confirm_button = QPushButton("확인")
        self.confirm_button.setObjectName("ConfirmSeatButton")
        self.confirm_button.setCursor(Qt.PointingHandCursor)
        self.confirm_button.setFixedSize(118, 42)
        self.confirm_button.setStyleSheet(
            """
            QPushButton#ConfirmSeatButton {
                background-color: #3C6FEA;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }
            QPushButton#ConfirmSeatButton:hover {
                background-color: #2F5FD0;
            }
            """
        )
        self.confirm_button.clicked.connect(self.confirm)

        button_layout = QHBoxLayout()
        button_layout.setSpacing(16)
        button_layout.addStretch(1)
        button_layout.addWidget(self.edit_button)
        button_layout.addWidget(self.confirm_button)
        button_layout.addStretch(1)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(38, 28, 38, 30)
        card_layout.setSpacing(0)
        card_layout.addWidget(self.status_icon, alignment=Qt.AlignCenter)
        card_layout.addSpacing(12)
        card_layout.addWidget(self.user_label)
        card_layout.addSpacing(3)
        card_layout.addWidget(self.id_label)
        card_layout.addSpacing(22)
        card_layout.addLayout(values_layout)
        card_layout.addSpacing(18)
        card_layout.addWidget(self.instruction_label)
        card_layout.addSpacing(18)
        card_layout.addLayout(button_layout)
        card.setLayout(card_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(86, 42, 86, 42)
        layout.addStretch(1)
        layout.addWidget(title_label)
        layout.addSpacing(8)
        layout.addWidget(self.subtitle_label)
        layout.addSpacing(24)
        layout.addWidget(card)
        layout.addStretch(1)
        self.setLayout(layout)

    def make_shadow(self, blur=22, y_offset=8, alpha=22):
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(blur)
        shadow.setXOffset(0)
        shadow.setYOffset(y_offset)
        shadow.setColor(QColor(0, 0, 0, alpha))
        return shadow

    def create_value_card(self, title, value):
        card = QFrame()
        card.setObjectName("SeatValueCard")
        card.setMinimumHeight(92)
        card.setStyleSheet(
            """
            QFrame#SeatValueCard {
                background-color: #F8FAFF;
                border: 1px solid #E7ECF8;
                border-radius: 18px;
            }
            """
        )

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            """
            font-size: 14px;
            font-weight: 500;
            color: #6E6E73;
            """
        )

        value_label = QLabel(value)
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet(
            """
            font-size: 25px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        layout.addWidget(title_label)
        layout.addWidget(value_label)
        card.setLayout(layout)

        return card, value_label

    def secondary_button_style(self, object_name):
        return f"""
            QPushButton#{object_name} {{
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }}
            QPushButton#{object_name}:hover {{
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }}
        """

    def prepare(self, record, start_after_confirm=True, mode="new", hardware_event=None):
        self.record = normalize_profile_record(record)
        self.start_after_confirm = start_after_confirm
        self.mode = mode
        self.hardware_event = hardware_event

        if self.record is None:
            return

        name = self.record.get("name", "")
        user_id = self.record.get("user_id", "")
        seat_position = self.record.get("seat_position", self.record.get("seat_forward", ""))
        backrest_angle = self.record.get("backrest_angle", "")

        self.user_label.setText(name)
        display_number = get_user_display_number(user_id)
        self.id_label.setText(f"사용자 번호 {display_number}")
        self.forward_value_label.setText(str(seat_position))
        self.backrest_value_label.setText(f"{backrest_angle}°")

        if mode == "select":
            self.subtitle_label.setText("선택한 사용자 시트 위치를 적용했습니다")
            self.instruction_label.setText("시트 환경이 맞으면 확인을 눌러 주행을 시작하세요")
            event_to_send = hardware_event or "USER_SELECTED"
        elif mode == "edit":
            self.subtitle_label.setText("수정된 시트 환경을 저장했습니다")
            self.instruction_label.setText("다시 사용자를 선택하면 시트가 적용됩니다")
            event_to_send = hardware_event
        else:
            self.subtitle_label.setText("등록한 시트 위치가 적용되었습니다")
            self.instruction_label.setText("실제 위치가 적절하면 확인을 눌러주세요")
            event_to_send = hardware_event or "NEW_USER_REGISTERED"

        # mode="edit"에서는 이 화면을 거의 사용하지 않지만, 안전하게 처리한다.
        # 하드웨어 이벤트가 지정된 경우에만 actuator 쪽으로 명령을 남긴다.
        if event_to_send:
            send_user_id_to_hardware(user_id, name, event=event_to_send)

    def go_edit(self):
        if self.record is None:
            return

        # 확인 화면에서 수정으로 들어가도 수정 후 바로 주행하지 않는다.
        # 값만 저장하고 사용자 목록으로 돌아가 다시 선택하도록 한다.
        self.stack.app.open_seat_edit(
            self.record.get("name", ""),
            start_after_confirm=False,
            return_to_confirm=False
        )

    def confirm(self):
        if self.record is None:
            return

        self.stack.app.confirm_seat_setting(
            self.record,
            start_after_confirm=self.start_after_confirm
        )


class SeatSettingEditWindow(QWidget):
    """기존 사용자의 전후 위치/등받이 각도를 수정하는 화면."""

    def __init__(self, stack):
        super().__init__()
        self.stack = stack
        self.record = None
        self.start_after_confirm = True
        self.return_to_confirm_on_back = False
        self.init_ui()

    def init_ui(self):
        self.setObjectName("SeatSettingEditWindow")
        self.setStyleSheet(
            """
            QWidget#SeatSettingEditWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            QLabel, QLineEdit, QPushButton {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        title_label = QLabel("시트 환경 수정")
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            """
            font-size: 30px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        subtitle_label = QLabel("전후 위치와 등받이 각도를 수정하세요")
        subtitle_label.setAlignment(Qt.AlignCenter)
        subtitle_label.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 400;
            color: #6E6E73;
            """
        )

        card = QFrame()
        card.setObjectName("SeatEditCard")
        card.setStyleSheet(
            """
            QFrame#SeatEditCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 26px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(26)
        shadow.setXOffset(0)
        shadow.setYOffset(9)
        shadow.setColor(QColor(0, 0, 0, 30))
        card.setGraphicsEffect(shadow)

        self.user_label = QLabel("사용자: -")
        self.user_label.setStyleSheet("font-size: 16px; font-weight: 500; color: #1D1D1F;")

        self.id_label = QLabel("사용자 번호: -")
        self.id_label.setStyleSheet("font-size: 15px; font-weight: 500; color: #6E6E73;")

        seat_forward_label = QLabel("전후 위치")
        seat_forward_label.setStyleSheet("font-size: 14px; font-weight: 500; color: #6E6E73;")

        self.seat_forward_input = QLineEdit()
        self.seat_forward_input.setPlaceholderText(f"예: 0  ({int(SEAT_POSITION_MIN_MM)}~{int(SEAT_POSITION_MAX_MM)})")
        self.seat_forward_input.setFixedHeight(42)
        self.seat_forward_input.setValidator(QDoubleValidator(SEAT_POSITION_MIN_MM, SEAT_POSITION_MAX_MM, 1, self))
        self.seat_forward_input.setInputMethodHints(Qt.ImhFormattedNumbersOnly)
        self.seat_forward_input.setStyleSheet(self.input_style())

        backrest_label = QLabel("등받이 각도")
        backrest_label.setStyleSheet("font-size: 14px; font-weight: 500; color: #6E6E73;")

        self.backrest_angle_input = QLineEdit()
        self.backrest_angle_input.setPlaceholderText("예: 105  (90~130)")
        self.backrest_angle_input.setFixedHeight(42)
        self.backrest_angle_input.setValidator(QDoubleValidator(BACKREST_ANGLE_MIN_DEG, BACKREST_ANGLE_MAX_DEG, 1, self))
        self.backrest_angle_input.setInputMethodHints(Qt.ImhFormattedNumbersOnly)
        self.backrest_angle_input.setStyleSheet(self.input_style())

        seat_input_layout = QHBoxLayout()
        seat_input_layout.setSpacing(14)

        forward_layout = QVBoxLayout()
        forward_layout.setSpacing(6)
        forward_layout.addWidget(seat_forward_label)
        forward_layout.addWidget(self.seat_forward_input)

        backrest_layout = QVBoxLayout()
        backrest_layout.setSpacing(6)
        backrest_layout.addWidget(backrest_label)
        backrest_layout.addWidget(self.backrest_angle_input)

        seat_input_layout.addLayout(forward_layout)
        seat_input_layout.addLayout(backrest_layout)

        self.back_button = QPushButton("이전")
        self.back_button.setObjectName("SeatEditBackButton")
        self.back_button.setCursor(Qt.PointingHandCursor)
        self.back_button.setFixedSize(110, 42)
        self.back_button.setStyleSheet(self.secondary_button_style("SeatEditBackButton"))
        self.back_button.clicked.connect(self.go_back)

        self.save_button = QPushButton("수정")
        self.save_button.setObjectName("SeatEditSaveButton")
        self.save_button.setCursor(Qt.PointingHandCursor)
        self.save_button.setFixedSize(110, 42)
        self.save_button.setStyleSheet(
            """
            QPushButton#SeatEditSaveButton {
                background-color: #3C6FEA;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }
            QPushButton#SeatEditSaveButton:hover {
                background-color: #2F5FD0;
            }
            """
        )
        self.save_button.clicked.connect(self.submit_edit)

        button_layout = QHBoxLayout()
        button_layout.addStretch(1)
        button_layout.addWidget(self.back_button)
        button_layout.addSpacing(12)
        button_layout.addWidget(self.save_button)
        button_layout.addStretch(1)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(42, 34, 42, 34)
        card_layout.setSpacing(10)
        card_layout.addWidget(self.user_label)
        card_layout.addWidget(self.id_label)
        card_layout.addSpacing(12)
        card_layout.addLayout(seat_input_layout)
        card_layout.addSpacing(18)
        card_layout.addLayout(button_layout)
        card.setLayout(card_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(90, 50, 90, 55)
        layout.addStretch(1)
        layout.addWidget(title_label)
        layout.addSpacing(6)
        layout.addWidget(subtitle_label)
        layout.addSpacing(28)
        layout.addWidget(card)
        layout.addStretch(1)
        self.setLayout(layout)

    def input_style(self):
        return """
            QLineEdit {
                background-color: #F8FAFF;
                color: #1D1D1F;
                border: 1px solid #E5EBF7;
                border-radius: 13px;
                padding-left: 14px;
                padding-right: 14px;
                font-size: 15px;
                font-weight: 400;
            }
            QLineEdit:focus {
                border: 1px solid #B7CEFF;
                background-color: #FFFFFF;
            }
        """

    def secondary_button_style(self, object_name):
        return f"""
            QPushButton#{object_name} {{
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }}
            QPushButton#{object_name}:hover {{
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }}
        """

    def prepare(self, record, start_after_confirm=True, return_to_confirm_on_back=False):
        self.record = normalize_profile_record(record)
        self.start_after_confirm = start_after_confirm
        self.return_to_confirm_on_back = return_to_confirm_on_back

        if self.record is None:
            return

        self.user_label.setText(f"사용자: {self.record.get('name', '')}")
        display_number = get_user_display_number(self.record.get("user_id", ""))
        self.id_label.setText(f"사용자 번호: {display_number}")
        self.seat_forward_input.setText(self.record.get("seat_position", self.record.get("seat_forward", "")))
        self.backrest_angle_input.setText(self.record.get("backrest_angle", ""))
        self.clearFocus()

    def submit_edit(self):
        if self.record is None:
            return

        seat_forward = normalize_number_text(self.seat_forward_input.text())
        backrest_angle = normalize_number_text(self.backrest_angle_input.text())

        if seat_forward == "":
            QMessageBox.warning(self, "입력 오류", "전후 위치를 숫자로 입력해주세요.")
            self.seat_forward_input.setFocus()
            return

        if backrest_angle == "":
            QMessageBox.warning(self, "입력 오류", "등받이 각도를 숫자로 입력해주세요.")
            self.backrest_angle_input.setFocus()
            return

        if not (SEAT_POSITION_MIN_MM <= float(seat_forward) <= SEAT_POSITION_MAX_MM):
            QMessageBox.warning(self, "입력 오류", f"전후 위치는 {int(SEAT_POSITION_MIN_MM)}부터 {int(SEAT_POSITION_MAX_MM)} 사이로 입력해주세요.")
            self.seat_forward_input.setFocus()
            return

        if not (BACKREST_ANGLE_MIN_DEG <= float(backrest_angle) <= BACKREST_ANGLE_MAX_DEG):
            QMessageBox.warning(self, "입력 오류", "등받이 각도는 90부터 130 사이로 입력해주세요.")
            self.backrest_angle_input.setFocus()
            return

        self.stack.app.update_existing_user_seat(
            self.record.get("user_id", ""),
            seat_forward,
            backrest_angle,
            start_after_confirm=self.start_after_confirm
        )

    def go_back(self):
        if self.record is not None and self.return_to_confirm_on_back:
            self.stack.app.open_seat_setting_confirm(
                self.record,
                start_after_confirm=self.start_after_confirm,
                mode="edit"
            )
        else:
            self.stack.app.show_user_list()


class OptimizedPressureMapWidget(QWidget):
    """
    SFS로 선택된 16개 센서의 실제 12x12 좌표와 보정 센서값을 이용해
    좌석의 상대 압력 분포를 부드럽게 시각화한다.

    정확하게 표현되는 항목
    - selected_sensor_positions.csv의 센서 위치
    - corrected_sensor 16개 값의 상대적인 크기
    - 센서값으로 계산한 압력 중심

    추정해서 표현되는 항목
    - 센서 사이의 연속적인 색 영역
    - 좌석 쿠션의 외곽 형태

    방향
    - 위쪽: 좌석 앞쪽(발을 뻗는 방향)
    - 아래쪽: 좌석 뒤쪽(등받이 방향)
    - 왼쪽: 운전자 기준 왼쪽
    """

    GRID_SIZE = 12
    NOISE_FLOOR = 8.0
    INITIAL_DISPLAY_SCALE = 520.0
    MIN_DISPLAY_SCALE = 180.0
    MAX_DISPLAY_SCALE = 900.0

    def __init__(self, sensor_positions=None):
        super().__init__()

        self.sensor_positions = list(
            sensor_positions or load_selected_sensor_positions()
        )
        self.sensor_values = [0.0] * len(self.sensor_positions)
        self.smoothed_sensor_values = [0.0] * len(self.sensor_positions)
        self.has_smoothed_values = False
        self.has_real_values = False
        self.mock_phase = 0.0

        # 프레임마다 최댓값 기준이 크게 바뀌어 색이 출렁이는 문제를 막기 위한
        # 완만한 적응형 표시 스케일이다. 실제 센서값은 수정하지 않는다.
        self.display_scale = self.INITIAL_DISPLAY_SCALE

        # 실제 센서값은 그대로 두고 화면 표시만 완만하게 따라가도록 한다.
        # 좌우로 체중을 옮길 때 한쪽이 서서히 진해지고 반대쪽이 옅어지는 모습을
        # 관찰하기 위한 EMA 계수다. 값이 클수록 반응이 빠르다.
        self.VALUE_SMOOTHING_ALPHA = 0.72

        self.setMinimumHeight(140)
        self.setStyleSheet("background-color: transparent; border: none;")

    @staticmethod
    def _clamp(value, minimum=0.0, maximum=1.0):
        return max(minimum, min(maximum, value))

    @staticmethod
    def _mix_color(color_a, color_b, ratio):
        ratio = max(0.0, min(1.0, float(ratio)))
        return QColor(
            int(round(color_a.red() + (color_b.red() - color_a.red()) * ratio)),
            int(round(color_a.green() + (color_b.green() - color_a.green()) * ratio)),
            int(round(color_a.blue() + (color_b.blue() - color_a.blue()) * ratio)),
        )

    def _pressure_color(self, intensity):
        """밝은 하늘색에서 짙은 인디고로 이어지는 연속 색상."""

        intensity = self._clamp(intensity)
        stops = [
            (0.00, QColor("#F2F7FF")),
            (0.20, QColor("#E0ECFF")),
            (0.42, QColor("#BED4FF")),
            (0.64, QColor("#83A9F5")),
            (0.82, QColor("#4F7CDD")),
            (1.00, QColor("#2F55B5")),
        ]

        for index in range(1, len(stops)):
            left_position, left_color = stops[index - 1]
            right_position, right_color = stops[index]

            if intensity <= right_position:
                local_ratio = (
                    (intensity - left_position)
                    / max(0.0001, right_position - left_position)
                )
                return self._mix_color(left_color, right_color, local_ratio)

        return stops[-1][1]

    def _update_display_scale(self, values):
        """색상 기준을 빠르게 올리고 천천히 내리면서 화면 깜빡임을 줄인다."""

        positive_values = sorted(
            [max(0.0, float(value) - self.NOISE_FLOOR) for value in values],
            reverse=True,
        )

        if not positive_values:
            return

        strongest = positive_values[: min(3, len(positive_values))]
        robust_peak = sum(strongest) / max(1, len(strongest))
        target_scale = self._clamp(
            robust_peak * 1.12,
            self.MIN_DISPLAY_SCALE,
            self.MAX_DISPLAY_SCALE,
        )

        # 강한 압력이 새로 들어오면 빠르게 반영하고,
        # 압력이 줄어들 때는 천천히 내려 안정적으로 보이게 한다.
        follow_rate = 0.55 if target_scale > self.display_scale else 0.16
        self.display_scale += (target_scale - self.display_scale) * follow_rate

    def _normalize_values(self):
        values = [max(0.0, float(value)) for value in self.sensor_values]

        if not values:
            return []

        if self.has_real_values:
            self._update_display_scale(values)
        else:
            # mock 화면도 실제 화면과 비슷한 밝기로 유지한다.
            self.display_scale = 560.0

        denominator = max(1.0, self.display_scale - self.NOISE_FLOOR)
        normalized = []

        for value in values:
            adjusted = max(0.0, value - self.NOISE_FLOOR)
            ratio = self._clamp(adjusted / denominator)

            # 약한 압력은 더 옅게, 강한 압력은 더 선명하게 표시해
            # 좌우 하중 차이가 눈에 잘 보이도록 한다.
            # 원본 센서값이나 SVM 입력값에는 영향을 주지 않는다.
            normalized.append(ratio ** 1.28)

        return normalized

    def _generate_mock_values(self):
        """센서 미연결 환경에서도 좌우 둔부 압력처럼 보이는 시연용 값."""

        self.mock_phase += 0.20
        values = []

        left_center = (6.4, 3.7)
        right_center = (6.4, 8.2)

        # 실제 센서가 연결되지 않은 시연 환경에서는 하중 중심이
        # 좌우로 천천히 이동하는 모습을 분명하게 확인할 수 있게 한다.
        balance_wave = 0.23 * math.sin(self.mock_phase * 0.42)
        left_strength = 0.80 + balance_wave
        right_strength = 0.80 - balance_wave

        for grid_row, grid_column in self.sensor_positions:
            left_distance = (
                ((grid_row - left_center[0]) / 1.65) ** 2
                + ((grid_column - left_center[1]) / 1.75) ** 2
            )
            right_distance = (
                ((grid_row - right_center[0]) / 1.65) ** 2
                + ((grid_column - right_center[1]) / 1.75) ** 2
            )

            pressure = max(
                left_strength * math.exp(-left_distance),
                right_strength * math.exp(-right_distance),
            )
            pressure += random.uniform(-0.012, 0.012)
            values.append(max(0.0, pressure) * 610.0)

        return values

    def set_sensor_values(self, sensor_values=None):
        try:
            values = [float(value) for value in list(sensor_values)]
        except (TypeError, ValueError):
            values = []

        if (
            len(values) == len(self.sensor_positions)
            and all(math.isfinite(value) for value in values)
        ):
            raw_values = [max(0.0, value) for value in values]

            if not self.has_smoothed_values:
                self.smoothed_sensor_values = list(raw_values)
                self.has_smoothed_values = True
            else:
                alpha = self.VALUE_SMOOTHING_ALPHA
                self.smoothed_sensor_values = [
                    previous + (current - previous) * alpha
                    for previous, current in zip(
                        self.smoothed_sensor_values,
                        raw_values,
                    )
                ]

            self.sensor_values = list(self.smoothed_sensor_values)
            self.has_real_values = True
        else:
            mock_values = self._generate_mock_values()

            if not self.has_smoothed_values:
                self.smoothed_sensor_values = list(mock_values)
                self.has_smoothed_values = True
            else:
                alpha = 0.18
                self.smoothed_sensor_values = [
                    previous + (current - previous) * alpha
                    for previous, current in zip(
                        self.smoothed_sensor_values,
                        mock_values,
                    )
                ]

            self.sensor_values = list(self.smoothed_sensor_values)
            self.has_real_values = False

        self.update()

    def _make_outer_seat_path(self, seat_rect):
        """
        과한 사다리꼴 대신 실제 자동차 방석처럼 보이는
        거의 직사각형의 부드러운 쿠션 외곽선.
        """

        left = seat_rect.left()
        right = seat_rect.right()
        top = seat_rect.top()
        bottom = seat_rect.bottom()
        width = seat_rect.width()
        height = seat_rect.height()

        front_inset = width * 0.018
        front_radius = min(width, height) * 0.105
        rear_radius = min(width, height) * 0.125
        side_curve = width * 0.018

        path = QPainterPath()
        path.moveTo(left + front_inset + front_radius, top)
        path.lineTo(right - front_inset - front_radius, top)
        path.quadTo(
            right - front_inset,
            top,
            right - front_inset,
            top + front_radius,
        )
        path.cubicTo(
            right - front_inset + side_curve,
            top + height * 0.34,
            right + side_curve,
            top + height * 0.67,
            right,
            bottom - rear_radius,
        )
        path.quadTo(right, bottom, right - rear_radius, bottom)
        path.lineTo(left + rear_radius, bottom)
        path.quadTo(left, bottom, left, bottom - rear_radius)
        path.cubicTo(
            left - side_curve,
            top + height * 0.67,
            left + front_inset - side_curve,
            top + height * 0.34,
            left + front_inset,
            top + front_radius,
        )
        path.quadTo(
            left + front_inset,
            top,
            left + front_inset + front_radius,
            top,
        )
        path.closeSubpath()
        return path

    def _make_inner_panel_path(self, seat_rect):
        """압력 분포가 그려지는 중앙 쿠션 패널."""

        panel_rect = QRectF(
            seat_rect.left() + seat_rect.width() * 0.065,
            seat_rect.top() + seat_rect.height() * 0.045,
            seat_rect.width() * 0.87,
            seat_rect.height() * 0.91,
        )

        radius = min(panel_rect.width(), panel_rect.height()) * 0.105
        path = QPainterPath()
        path.addRoundedRect(panel_rect, radius, radius)
        return path, panel_rect

    def _grid_to_screen(self, row, column, panel_rect):
        # 실제 12x12 센서 좌표를 중앙 쿠션 패널에 그대로 매핑한다.
        inset_ratio = 0.045
        usable_ratio = 1.0 - inset_ratio * 2.0
        x_ratio = inset_ratio + (float(column) / 11.0) * usable_ratio
        y_ratio = inset_ratio + (float(row) / 11.0) * usable_ratio
        x = panel_rect.left() + x_ratio * panel_rect.width()
        y = panel_rect.top() + y_ratio * panel_rect.height()
        return QPointF(x, y)

    def _calculate_local_intensity(self, grid_row, grid_column, normalized_values):
        """
        가까운 센서만 사용하는 국소 Gaussian 보간.
        멀리 떨어진 두 센서가 중앙 압력과 긴 띠로 연결되는 것을 방지한다.
        """

        sigma = 0.80
        influence_radius = 2.05
        weighted_sum = 0.0
        weight_sum = 0.0

        for (sensor_row, sensor_column), value in zip(
            self.sensor_positions,
            normalized_values,
        ):
            row_difference = grid_row - sensor_row
            column_difference = grid_column - sensor_column
            distance_squared = (
                row_difference * row_difference
                + column_difference * column_difference
            )

            if distance_squared > influence_radius * influence_radius:
                continue

            weight = math.exp(-distance_squared / (2.0 * sigma * sigma))
            weighted_sum += value * weight
            weight_sum += weight

        if weight_sum <= 0.0001:
            return 0.0

        local_average = weighted_sum / weight_sum
        coverage = 1.0 - math.exp(-weight_sum * 1.28)
        intensity = local_average * coverage

        if intensity < 0.022:
            return 0.0

        return self._clamp(intensity)

    def _build_pressure_image(self, panel_rect, normalized_values):
        """작은 투명 이미지에 압력장을 만든 뒤 부드럽게 확대한다."""

        image_width = max(52, min(84, int(panel_rect.width() / 2.8)))
        image_height = max(48, min(80, int(panel_rect.height() / 2.8)))
        image = QImage(image_width, image_height, QImage.Format_ARGB32)
        image.fill(QColor(0, 0, 0, 0))

        inset_ratio = 0.045
        usable_ratio = 1.0 - inset_ratio * 2.0

        for y in range(image_height):
            screen_ratio_y = (y + 0.5) / image_height
            grid_row = (screen_ratio_y - inset_ratio) / usable_ratio * 11.0

            for x in range(image_width):
                screen_ratio_x = (x + 0.5) / image_width
                grid_column = (screen_ratio_x - inset_ratio) / usable_ratio * 11.0
                intensity = self._calculate_local_intensity(
                    grid_row,
                    grid_column,
                    normalized_values,
                )

                if intensity <= 0.0:
                    continue

                color = self._pressure_color(intensity)
                # 약한 영역은 거의 투명하게, 강한 영역은 선명하게 보여
                # 좌우 하중 차이가 더 분명하게 드러나도록 한다.
                color.setAlpha(int(round(235 * (intensity ** 1.18))))
                image.setPixelColor(x, y, color)

        return image

    def _draw_side_bolsters(self, painter, seat_rect):
        """좌석임을 알아보기 쉬운 매우 옅은 양쪽 볼스터 표현."""

        width = seat_rect.width()
        height = seat_rect.height()

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(226, 234, 247, 28))

        left_path = QPainterPath()
        left_path.moveTo(seat_rect.left() + width * 0.072, seat_rect.top() + height * 0.08)
        left_path.cubicTo(
            seat_rect.left() + width * 0.012,
            seat_rect.top() + height * 0.30,
            seat_rect.left() + width * 0.012,
            seat_rect.top() + height * 0.72,
            seat_rect.left() + width * 0.095,
            seat_rect.bottom() - height * 0.08,
        )
        left_path.cubicTo(
            seat_rect.left() + width * 0.13,
            seat_rect.top() + height * 0.67,
            seat_rect.left() + width * 0.13,
            seat_rect.top() + height * 0.29,
            seat_rect.left() + width * 0.072,
            seat_rect.top() + height * 0.08,
        )
        left_path.closeSubpath()
        painter.drawPath(left_path)

        right_path = QPainterPath()
        right_path.moveTo(seat_rect.right() - width * 0.072, seat_rect.top() + height * 0.08)
        right_path.cubicTo(
            seat_rect.right() - width * 0.012,
            seat_rect.top() + height * 0.30,
            seat_rect.right() - width * 0.012,
            seat_rect.top() + height * 0.72,
            seat_rect.right() - width * 0.095,
            seat_rect.bottom() - height * 0.08,
        )
        right_path.cubicTo(
            seat_rect.right() - width * 0.13,
            seat_rect.top() + height * 0.67,
            seat_rect.right() - width * 0.13,
            seat_rect.top() + height * 0.29,
            seat_rect.right() - width * 0.072,
            seat_rect.top() + height * 0.08,
        )
        right_path.closeSubpath()
        painter.drawPath(right_path)

    def _draw_sensor_markers(self, painter, panel_rect, normalized_values):
        """
        기존의 큰 흰색 원 대신 작은 둥근 사각 점으로 센서 위치만 조용히 표시한다.
        압력이 강한 센서일수록 조금 더 또렷해진다.
        """

        base_size = max(2.0, min(3.3, panel_rect.height() * 0.018))

        for (sensor_row, sensor_column), normalized_value in zip(
            self.sensor_positions,
            normalized_values,
        ):
            point = self._grid_to_screen(sensor_row, sensor_column, panel_rect)
            marker_size = base_size + normalized_value * 0.9
            alpha = int(round(52 + normalized_value * 148))

            marker_color = QColor(255, 255, 255, alpha)
            border_color = QColor(72, 105, 172, int(round(35 + normalized_value * 90)))

            marker_rect = QRectF(
                point.x() - marker_size / 2.0,
                point.y() - marker_size / 2.0,
                marker_size,
                marker_size,
            )

            painter.setPen(QPen(border_color, 0.75))
            painter.setBrush(marker_color)
            painter.drawRoundedRect(
                marker_rect,
                marker_size * 0.32,
                marker_size * 0.32,
            )

    def _draw_pressure_center(self, painter, panel_rect, normalized_values):
        """압력 중심을 눈에 거슬리지 않는 작은 반투명 점으로 표시한다."""

        pressure_weights = [max(0.0, value - 0.05) for value in normalized_values]
        total_weight = sum(pressure_weights)

        if total_weight <= 0.08:
            return

        center_row = sum(
            position[0] * weight
            for position, weight in zip(self.sensor_positions, pressure_weights)
        ) / total_weight
        center_column = sum(
            position[1] * weight
            for position, weight in zip(self.sensor_positions, pressure_weights)
        ) / total_weight
        point = self._grid_to_screen(center_row, center_column, panel_rect)

        radius = max(1.5, min(2.2, panel_rect.height() * 0.012))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(58, 91, 165, 88))
        painter.drawEllipse(point, radius, radius)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        width = max(1, self.width())
        height = max(1, self.height())

        horizontal_margin = 14.0
        vertical_margin = 5.0
        available_width = max(20.0, width - horizontal_margin * 2)
        available_height = max(20.0, height - vertical_margin * 2)

        # 대시보드 카드 안에서 안정적으로 보이는 자동차 좌석 방석 비율.
        seat_aspect_ratio = 1.26
        seat_width = min(available_width, available_height * seat_aspect_ratio)
        seat_height = seat_width / seat_aspect_ratio

        if seat_height > available_height:
            seat_height = available_height
            seat_width = seat_height * seat_aspect_ratio

        seat_rect = QRectF(
            (width - seat_width) / 2.0,
            (height - seat_height) / 2.0,
            seat_width,
            seat_height,
        )

        outer_path = self._make_outer_seat_path(seat_rect)
        panel_path, panel_rect = self._make_inner_panel_path(seat_rect)

        # 아주 약한 바닥 그림자
        shadow_path = self._make_outer_seat_path(
            QRectF(
                seat_rect.left(),
                seat_rect.top() + 2.0,
                seat_rect.width(),
                seat_rect.height(),
            )
        )
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(80, 105, 150, 8))
        painter.drawPath(shadow_path)

        # 좌석 외곽과 내부 패널
        painter.setPen(QPen(QColor(209, 221, 238, 82), 0.65))
        painter.setBrush(QColor("#FBFCFE"))
        painter.drawPath(outer_path)

        self._draw_side_bolsters(painter, seat_rect)

        painter.setPen(QPen(QColor(214, 224, 239, 48), 0.55))
        painter.setBrush(QColor(255, 255, 255, 58))
        painter.drawPath(panel_path)

        normalized_values = self._normalize_values()
        pressure_image = self._build_pressure_image(panel_rect, normalized_values)

        painter.save()
        painter.setClipPath(panel_path)
        painter.drawImage(panel_rect, pressure_image)
        painter.restore()

        # 압력 위에 센서 위치와 중심점을 작고 절제된 형태로 표시한다.
        self._draw_sensor_markers(painter, panel_rect, normalized_values)
        self._draw_pressure_center(painter, panel_rect, normalized_values)

        # 마지막에 외곽을 한 번 더 그려 가장자리를 정돈한다.
        painter.setPen(QPen(QColor(204, 218, 237, 74), 0.65))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(outer_path)


class BackCurvatureWidget(QWidget):
    """
    초음파센서 4개(S1, S2, S3, S5)로 추정한 등 표면 곡선을 표시하는 위젯.

    - 회색 점선: 기준 자세 거리값
    - 진한 선: 현재 등 곡선
    - 우측 수치: 기준 자세 대비 등 구부러짐 정도
    """

    SENSOR_ORDER = ("s1", "s2", "s3", "s5")
    SENSOR_HEIGHTS = {
        "s1": 310.0,
        "s2": 250.0,
        "s3": 190.0,
        "s5": 70.0,
    }

    def __init__(self):
        super().__init__()
        self.payload = None
        self.setMinimumHeight(230)
        self.setStyleSheet("background-color: transparent; border: none;")

    def set_feedback(self, payload):
        self.payload = payload if isinstance(payload, dict) else None
        self.update()

    def _safe_float(self, value, default=0.0):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default

        if not math.isfinite(number):
            return default

        return number

    def _height_to_y(self, height_mm, rect):
        top_height = 310.0
        bottom_height = 70.0
        ratio = (top_height - float(height_mm)) / max(1.0, top_height - bottom_height)
        return rect.top() + ratio * rect.height()

    def _distance_to_x(self, distance_mm, rect, min_distance, max_distance):
        span = max(1.0, max_distance - min_distance)
        ratio = (float(distance_mm) - min_distance) / span
        ratio = max(0.0, min(1.0, ratio))
        return rect.left() + ratio * rect.width()

    def _build_current_points(self):
        payload = self.payload or {}
        curve_points = payload.get("curve_points", [])

        if isinstance(curve_points, list) and len(curve_points) >= 2:
            points = []

            for point in curve_points:
                if not isinstance(point, dict):
                    continue

                height = point.get("height_from_seat_mm")
                distance = point.get("distance_mm")

                if height is None or distance is None:
                    continue

                points.append((
                    self._safe_float(height),
                    self._safe_float(distance),
                ))

            if len(points) >= 2:
                return points

        distances = payload.get("distances_mm", {})
        if isinstance(distances, dict):
            points = []

            for key in self.SENSOR_ORDER:
                if key not in distances:
                    continue

                points.append((
                    self.SENSOR_HEIGHTS[key],
                    self._safe_float(distances.get(key)),
                ))

            if len(points) >= 2:
                return points

        return []

    def _build_baseline_points(self):
        payload = self.payload or {}
        baseline_distances = payload.get("baseline_distances_mm", {})

        if not isinstance(baseline_distances, dict):
            return []

        points = []

        for key in self.SENSOR_ORDER:
            if key not in baseline_distances:
                continue

            points.append((
                self.SENSOR_HEIGHTS[key],
                self._safe_float(baseline_distances.get(key)),
            ))

        return points

    def _draw_polyline(self, painter, points, graph_rect, min_distance, max_distance):
        if len(points) < 2:
            return

        path = QPainterPath()
        first_height, first_distance = points[0]
        path.moveTo(
            self._distance_to_x(first_distance, graph_rect, min_distance, max_distance),
            self._height_to_y(first_height, graph_rect),
        )

        for height, distance in points[1:]:
            path.lineTo(
                self._distance_to_x(distance, graph_rect, min_distance, max_distance),
                self._height_to_y(height, graph_rect),
            )

        painter.drawPath(path)

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        width = self.width()
        height = self.height()

        if width <= 0 or height <= 0:
            return

        payload = self.payload

        if not isinstance(payload, dict):
            painter.setPen(QPen(QColor("#8A94A6"), 1))
            font = painter.font()
            font.setPointSize(13)
            font.setWeight(QFont.Medium)
            painter.setFont(font)
            painter.drawText(self.rect(), Qt.AlignCenter, "초음파 자세 데이터를 기다리는 중입니다")
            return

        stale = bool(payload.get("_stale", False))
        warning = bool(payload.get("warning", False))
        state = str(payload.get("state", "")).upper()
        message = str(payload.get("message", "")).strip()

        if stale:
            status_text = "등 센서 대기"
            status_color = QColor("#8A94A6")
            line_color = QColor("#8A94A6")
        elif state == "WAITING_FOR_START":
            status_text = "주행 시작 대기"
            status_color = QColor("#3C6FEA")
            line_color = QColor("#94A3B8")
        elif state == "CALIBRATING":
            status_text = "등 기준 자세 측정 중"
            status_color = QColor("#3C6FEA")
            line_color = QColor("#94A3B8")
        elif state in ("CALIBRATION_ERROR", "MEASUREMENT_ERROR", "SIGNAL_LOST"):
            status_text = "등 센서 측정 확인"
            status_color = QColor("#D97706")
            line_color = QColor("#D97706")
        elif warning or state == "WARNING":
            status_text = "등 굽음 감지"
            status_color = QColor("#D97706")
            line_color = QColor("#D97706")
        else:
            status_text = "바른 등 자세"
            status_color = QColor("#3C6FEA")
            line_color = QColor("#3C6FEA")

        if message and not stale:
            status_detail = message
        else:
            status_detail = "등 초음파센서 연결을 확인하세요" if stale else ""

        if stale or state in (
            "WAITING_FOR_START",
            "CALIBRATING",
            "CALIBRATION_ERROR",
            "MEASUREMENT_ERROR",
            "SIGNAL_LOST",
        ):
            bend_percent = 0
        else:
            bend_percent = calculate_back_bend_percent(payload)

        margin = 6
        graph_rect = QRectF(margin + 2, 18, width * 0.54, height - 32)
        info_left = graph_rect.right() + 18
        info_rect = QRectF(info_left, 18, width - info_left - 8, height - 32)

        # 그래프 배경
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F7F9FD"))
        painter.drawRoundedRect(graph_rect, 18, 18)

        # 센서 높이 보조선
        painter.setPen(QPen(QColor("#E2E8F0"), 1))
        for key in self.SENSOR_ORDER:
            y = self._height_to_y(self.SENSOR_HEIGHTS[key], graph_rect)
            painter.drawLine(
                QPointF(graph_rect.left() + 10, y),
                QPointF(graph_rect.right() - 10, y),
            )

        current_points = self._build_current_points()
        baseline_points = self._build_baseline_points()
        all_distances = [distance for _, distance in current_points + baseline_points]

        if len(all_distances) == 0:
            min_distance = 70.0
            max_distance = 150.0
        else:
            min_distance = min(all_distances)
            max_distance = max(all_distances)
            padding = max(12.0, (max_distance - min_distance) * 0.25)
            min_distance -= padding
            max_distance += padding

        # 기준 자세 곡선
        if len(baseline_points) >= 2:
            baseline_pen = QPen(QColor("#94A3B8"), 2)
            baseline_pen.setStyle(Qt.DashLine)
            painter.setPen(baseline_pen)
            self._draw_polyline(painter, baseline_points, graph_rect, min_distance, max_distance)

        # 현재 자세 곡선
        if len(current_points) >= 2:
            painter.setPen(QPen(line_color, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            self._draw_polyline(painter, current_points, graph_rect, min_distance, max_distance)

            painter.setPen(Qt.NoPen)
            painter.setBrush(line_color)

            for height_mm, distance_mm in current_points:
                x = self._distance_to_x(distance_mm, graph_rect, min_distance, max_distance)
                y = self._height_to_y(height_mm, graph_rect)
                painter.drawEllipse(QPointF(x, y), 4.4, 4.4)

        # 센서 라벨
        label_font = painter.font()
        label_font.setPointSize(8)
        label_font.setWeight(QFont.Medium)
        painter.setFont(label_font)
        painter.setPen(QColor("#94A3B8"))

        for key in self.SENSOR_ORDER:
            y = self._height_to_y(self.SENSOR_HEIGHTS[key], graph_rect)
            painter.drawText(
                QRectF(graph_rect.left() + 8, y - 9, 34, 18),
                Qt.AlignLeft | Qt.AlignVCenter,
                key.upper(),
            )

        # 우측 정보 영역
        title_font = painter.font()
        title_font.setPointSize(10)
        title_font.setWeight(QFont.Medium)
        painter.setFont(title_font)
        painter.setPen(QColor("#6E6E73"))
        painter.drawText(info_rect, Qt.AlignLeft | Qt.AlignTop, "등 구부러짐 정도")

        percent_font = painter.font()
        percent_font.setPointSize(31)
        percent_font.setWeight(QFont.DemiBold)
        painter.setFont(percent_font)
        painter.setPen(QColor("#1D1D1F") if not stale else QColor("#8A94A6"))
        painter.drawText(
            QRectF(info_rect.left(), info_rect.top() + 26, info_rect.width(), 46),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"{bend_percent}%",
        )

        # 진행바
        bar_rect = QRectF(info_rect.left(), info_rect.top() + 88, info_rect.width(), 12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#EEF2FA"))
        painter.drawRoundedRect(bar_rect, 6, 6)

        fill_width = bar_rect.width() * max(0.0, min(100.0, bend_percent)) / 100.0
        if fill_width > 0:
            painter.setBrush(status_color)
            painter.drawRoundedRect(
                QRectF(bar_rect.left(), bar_rect.top(), fill_width, bar_rect.height()),
                6,
                6,
            )

        status_font = painter.font()
        status_font.setPointSize(13)
        status_font.setWeight(QFont.DemiBold)
        painter.setFont(status_font)
        painter.setPen(status_color)
        painter.drawText(
            QRectF(info_rect.left(), info_rect.top() + 116, info_rect.width(), 24),
            Qt.AlignLeft | Qt.AlignVCenter,
            status_text,
        )

        detail_font = painter.font()
        detail_font.setPointSize(9)
        detail_font.setWeight(QFont.Normal)
        painter.setFont(detail_font)
        painter.setPen(QColor("#8A94A6"))
        painter.drawText(
            QRectF(info_rect.left(), info_rect.top() + 142, info_rect.width(), 42),
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            status_detail or "기준 자세와 현재 등 곡선을 비교합니다",
        )

        # 범례
        legend_y = graph_rect.bottom() + 6
        legend_font = painter.font()
        legend_font.setPointSize(8)
        painter.setFont(legend_font)

        painter.setPen(QPen(QColor("#94A3B8"), 2, Qt.DashLine))
        painter.drawLine(QPointF(graph_rect.left() + 16, legend_y), QPointF(graph_rect.left() + 36, legend_y))
        painter.setPen(QColor("#94A3B8"))
        painter.drawText(QRectF(graph_rect.left() + 42, legend_y - 8, 64, 16), Qt.AlignLeft | Qt.AlignVCenter, "기준")

        painter.setPen(QPen(line_color, 3))
        painter.drawLine(QPointF(graph_rect.left() + 100, legend_y), QPointF(graph_rect.left() + 120, legend_y))
        painter.setPen(line_color)
        painter.drawText(QRectF(graph_rect.left() + 126, legend_y - 8, 64, 16), Qt.AlignLeft | Qt.AlignVCenter, "현재")





class NeckPostureWidget(QWidget):
    """
    목/헤드 초음파센서 2개(HEAD, C7)로 추정한 목 전방 이동을 표시하는 위젯.

    - 회색 점선: 기준 자세
    - 진한 선: 현재 후두부-C7 위치
    - 우측 수치: 기준 대비 목 전방 이동 정도
    """

    def __init__(self):
        super().__init__()
        self.payload = None
        self.setMinimumHeight(230)
        self.setStyleSheet("background-color: transparent; border: none;")

    def set_feedback(self, payload):
        self.payload = payload if isinstance(payload, dict) else None
        self.update()

    def _safe_float(self, value, default=0.0):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default

        if not math.isfinite(number):
            return default

        return number

    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        width = max(1, self.width())
        height = max(1, self.height())

        payload = self.payload
        stale = True

        if isinstance(payload, dict):
            stale = bool(payload.get("_stale", False))
        else:
            payload = {}

        warning = bool(payload.get("warning", False))
        state = str(payload.get("state", "")).upper()
        message = str(payload.get("message", "")).strip()

        if stale or state in (
            "WAITING_FOR_START",
            "CALIBRATING",
            "CALIBRATION_ERROR",
            "SIGNAL_LOST",
        ):
            angle_drop = 0.0
            neck_percent = 0
            drowsy_problem = False
        else:
            angle_drop = get_neck_angle_drop(payload)
            neck_percent = calculate_neck_forward_percent(payload)
            drowsy_problem = is_neck_drowsy_problem(payload)

        if stale:
            status_text = "목 센서 대기"
            status_color = QColor("#8A94A6")
            line_color = QColor("#8A94A6")
        elif state == "WAITING_FOR_START":
            status_text = "주행 시작 대기"
            status_color = QColor("#3C6FEA")
            line_color = QColor("#94A3B8")
        elif state == "CALIBRATING":
            status_text = "목 기준 자세 측정 중"
            status_color = QColor("#3C6FEA")
            line_color = QColor("#94A3B8")
        elif state == "CALIBRATION_ERROR":
            status_text = "목 센서 측정 확인"
            status_color = QColor("#D97706")
            line_color = QColor("#D97706")
        elif state == "SIGNAL_LOST":
            status_text = "목 센서 신호 확인"
            status_color = QColor("#D97706")
            line_color = QColor("#D97706")
        elif drowsy_problem:
            status_text = "졸음 의심"
            status_color = QColor("#D92D20")
            line_color = QColor("#D92D20")
        elif warning or state == "WARNING":
            status_text = "목 전방 이동"
            status_color = QColor("#D97706")
            line_color = QColor("#D97706")
        elif state in ("PENDING", "RECOVERING"):
            status_text = "목 자세 확인 중"
            status_color = QColor("#E99B19")
            line_color = QColor("#E99B19")
        else:
            status_text = "바른 목 자세"
            status_color = QColor("#3C6FEA")
            line_color = QColor("#3C6FEA")

        if message and not stale:
            status_detail = message
        else:
            status_detail = "목 초음파센서 연결을 확인하세요" if stale else ""

        margin = 6
        graph_rect = QRectF(margin + 2, 18, width * 0.46, height - 32)
        info_left = graph_rect.right() + 16
        info_rect = QRectF(info_left, 18, width - info_left - 8, height - 32)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#F7F9FD"))
        painter.drawRoundedRect(graph_rect, 18, 18)

        head_y = graph_rect.top() + graph_rect.height() * 0.28
        c7_y = graph_rect.top() + graph_rect.height() * 0.74
        sensor_x = graph_rect.left() + 26
        baseline_x = graph_rect.left() + graph_rect.width() * 0.58

        # 센서 고정판
        painter.setPen(QPen(QColor("#94A3B8"), 4, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(sensor_x, head_y - 42), QPointF(sensor_x, c7_y + 42))

        # 센서 본체
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#64748B"))
        for y in (head_y, c7_y):
            painter.drawRoundedRect(QRectF(sensor_x - 10, y - 10, 20, 20), 5, 5)

        # 기준 자세
        baseline_pen = QPen(QColor("#94A3B8"), 2)
        baseline_pen.setStyle(Qt.DashLine)
        painter.setPen(baseline_pen)
        painter.drawLine(QPointF(baseline_x, head_y), QPointF(baseline_x, c7_y))

        head_x = baseline_x
        c7_x = baseline_x

        baseline = payload.get("baseline", {}) if isinstance(payload.get("baseline", {}), dict) else {}
        corrected = payload.get("corrected_mm", {}) if isinstance(payload.get("corrected_mm", {}), dict) else {}

        common_reference = self._safe_float(baseline.get("common_reference_mm"), 0.0)
        head_corrected = self._safe_float(corrected.get("head"), common_reference)
        c7_corrected = self._safe_float(corrected.get("c7"), common_reference)

        if not stale and common_reference > 0.0:
            pixels_per_mm = min(2.0, max(0.8, graph_rect.width() / 95.0))
            head_x = baseline_x + (head_corrected - common_reference) * pixels_per_mm
            c7_x = baseline_x + (c7_corrected - common_reference) * pixels_per_mm

        min_x = sensor_x + 28
        max_x = graph_rect.right() - 12
        head_x = max(min_x, min(max_x, head_x))
        c7_x = max(min_x, min(max_x, c7_x))

        # 센서-대상 거리 보조선
        painter.setPen(QPen(QColor("#CBD5E1"), 1.5, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(sensor_x + 10, head_y), QPointF(head_x, head_y))
        painter.drawLine(QPointF(sensor_x + 10, c7_y), QPointF(c7_x, c7_y))

        # 현재 목 라인
        painter.setPen(QPen(line_color, 4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawLine(QPointF(c7_x, c7_y), QPointF(head_x, head_y))

        painter.setPen(Qt.NoPen)
        painter.setBrush(line_color)
        for label, x, y in (("HEAD", head_x, head_y), ("C7", c7_x, c7_y)):
            painter.drawEllipse(QPointF(x, y), 6, 6)

        label_font = painter.font()
        label_font.setPointSize(8)
        label_font.setWeight(QFont.Medium)
        painter.setFont(label_font)
        painter.setPen(QColor("#64748B"))
        painter.drawText(QRectF(graph_rect.left() + 8, head_y - 25, 64, 18), Qt.AlignLeft | Qt.AlignVCenter, "HEAD")
        painter.drawText(QRectF(graph_rect.left() + 8, c7_y + 8, 64, 18), Qt.AlignLeft | Qt.AlignVCenter, "C7")

        # 우측 정보 영역
        title_font = painter.font()
        title_font.setPointSize(10)
        title_font.setWeight(QFont.Medium)
        painter.setFont(title_font)
        painter.setPen(QColor("#6E6E73"))
        painter.drawText(info_rect, Qt.AlignLeft | Qt.AlignTop, "목 전방 이동 정도")

        percent_font = painter.font()
        percent_font.setPointSize(31)
        percent_font.setWeight(QFont.DemiBold)
        painter.setFont(percent_font)
        painter.setPen(QColor("#1D1D1F") if not stale else QColor("#8A94A6"))
        painter.drawText(
            QRectF(info_rect.left(), info_rect.top() + 26, info_rect.width(), 46),
            Qt.AlignLeft | Qt.AlignVCenter,
            f"{neck_percent}%",
        )

        angle_font = painter.font()
        angle_font.setPointSize(10)
        angle_font.setWeight(QFont.Medium)
        painter.setFont(angle_font)
        painter.setPen(QColor("#6E6E73"))
        angle_text = "전방 변화 -" if stale else f"전방 변화 {angle_drop:+.1f}°"
        painter.drawText(
            QRectF(info_rect.left(), info_rect.top() + 72, info_rect.width(), 20),
            Qt.AlignLeft | Qt.AlignVCenter,
            angle_text,
        )

        # 진행바
        bar_rect = QRectF(info_rect.left(), info_rect.top() + 100, info_rect.width(), 12)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#EEF2FA"))
        painter.drawRoundedRect(bar_rect, 6, 6)

        fill_width = bar_rect.width() * max(0.0, min(100.0, neck_percent)) / 100.0
        if fill_width > 0:
            painter.setBrush(status_color)
            painter.drawRoundedRect(
                QRectF(bar_rect.left(), bar_rect.top(), fill_width, bar_rect.height()),
                6,
                6,
            )

        status_font = painter.font()
        status_font.setPointSize(13)
        status_font.setWeight(QFont.DemiBold)
        painter.setFont(status_font)
        painter.setPen(status_color)
        painter.drawText(
            QRectF(info_rect.left(), info_rect.top() + 126, info_rect.width(), 24),
            Qt.AlignLeft | Qt.AlignVCenter,
            status_text,
        )

        detail_font = painter.font()
        detail_font.setPointSize(9)
        detail_font.setWeight(QFont.Normal)
        painter.setFont(detail_font)
        painter.setPen(QColor("#8A94A6"))
        painter.drawText(
            QRectF(info_rect.left(), info_rect.top() + 152, info_rect.width(), 44),
            Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
            status_detail or "후두부와 C7 위치 변화로 목 전방 이동을 확인합니다",
        )


class DashboardWindow(QWidget):
    def __init__(self, stack):
        super().__init__()

        self.stack = stack
        self.last_mock_score = None

        # 센서 문제가 일정 시간 이상 유지될 때만 경고 화면을 띄우기 위한 상태값.
        self.pressure_warning_type = None
        self.pressure_warning_started_at = None
        self.pressure_warning_ready_type = None
        self.back_bend_warning_started_at = None
        self.back_bend_warning_ready = False
        self.back_warning_recovery_started_at = None
        self.neck_warning_started_at = None
        self.neck_warning_ready = False
        self.neck_warning_recovery_started_at = None
        self.drowsy_warning_started_at = None
        self.drowsy_warning_ready = False
        self.drowsy_warning_recovery_started_at = None
        self.last_warning_popup_at = 0.0
        self.last_back_warning_popup_at = 0.0
        self.back_warning_popup_latched = False
        self.last_neck_warning_popup_at = 0.0
        self.neck_warning_popup_latched = False
        self.last_drowsy_popup_at = 0.0
        self.drowsy_warning_popup_latched = False

        self.init_ui()

    def init_ui(self):
        self.setObjectName("DashboardWindow")
        self.setStyleSheet(
            """
            QWidget#DashboardWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QLabel {
                background-color: transparent;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QPushButton {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        self.user_label = QLabel("사용자: -")
        self.user_label.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 500;
            color: #6E6E73;
            """
        )

        self.end_button = QPushButton("운전 종료")
        self.end_button.setObjectName("DashboardEndButton")
        self.end_button.setCursor(Qt.PointingHandCursor)
        self.end_button.setFixedSize(94, 34)
        self.end_button.setStyleSheet(
            """
            QPushButton#DashboardEndButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 12px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton#DashboardEndButton:hover {
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }
            """
        )
        self.end_button.clicked.connect(self.go_report)

        header_layout = QHBoxLayout()
        header_layout.addWidget(self.user_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.end_button)

        score_card = QFrame()
        score_card.setObjectName("DashboardCard")
        score_card.setStyleSheet(
            """
            QFrame#DashboardCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 22px;
            }
            """
        )

        score_shadow = QGraphicsDropShadowEffect()
        score_shadow.setBlurRadius(22)
        score_shadow.setXOffset(0)
        score_shadow.setYOffset(8)
        score_shadow.setColor(QColor(0, 0, 0, 25))
        score_card.setGraphicsEffect(score_shadow)

        back_curve_title = QLabel("등 자세 모니터링")
        back_curve_title.setAlignment(Qt.AlignCenter)
        back_curve_title.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 500;
            color: #1D1D1F;
            """
        )

        self.back_curve_widget = BackCurvatureWidget()

        # 점수 그래프 기록을 위해 내부적으로는 score/state label 값을 계속 갱신한다.
        # 다만 대시보드 왼쪽 위 카드에는 점수 대신 초음파 기반 등 구부러짐 정도를 표시한다.
        self.score_label = QLabel("-")
        self.score_label.hide()
        self.state_label = QLabel("대기 중")
        self.state_label.hide()

        score_layout = QVBoxLayout()
        score_layout.setContentsMargins(16, 18, 16, 14)
        score_layout.setSpacing(8)
        score_layout.addWidget(back_curve_title)
        score_layout.addWidget(self.back_curve_widget, 1)

        score_card.setLayout(score_layout)

        heatmap_card = QFrame()
        heatmap_card.setObjectName("DashboardCard")
        heatmap_card.setStyleSheet(
            """
            QFrame#DashboardCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 22px;
            }
            """
        )

        heatmap_shadow = QGraphicsDropShadowEffect()
        heatmap_shadow.setBlurRadius(22)
        heatmap_shadow.setXOffset(0)
        heatmap_shadow.setYOffset(8)
        heatmap_shadow.setColor(QColor(0, 0, 0, 25))
        heatmap_card.setGraphicsEffect(heatmap_shadow)

        heatmap_title = QLabel("좌석 압력 분포")
        heatmap_title.setAlignment(Qt.AlignCenter)
        heatmap_title.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 500;
            color: #1D1D1F;
            """
        )

        self.pressure_map_widget = OptimizedPressureMapWidget(
            load_selected_sensor_positions()
        )

        heatmap_layout = QVBoxLayout()
        heatmap_layout.setContentsMargins(16, 18, 16, 14)
        heatmap_layout.setSpacing(8)
        heatmap_layout.addWidget(heatmap_title)
        heatmap_layout.addWidget(self.pressure_map_widget, 1)

        heatmap_card.setLayout(heatmap_layout)

        neck_card = QFrame()
        neck_card.setObjectName("DashboardCard")
        neck_card.setStyleSheet(
            """
            QFrame#DashboardCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 22px;
            }
            """
        )

        neck_shadow = QGraphicsDropShadowEffect()
        neck_shadow.setBlurRadius(22)
        neck_shadow.setXOffset(0)
        neck_shadow.setYOffset(8)
        neck_shadow.setColor(QColor(0, 0, 0, 25))
        neck_card.setGraphicsEffect(neck_shadow)

        neck_title = QLabel("목 자세 모니터링")
        neck_title.setAlignment(Qt.AlignCenter)
        neck_title.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 500;
            color: #1D1D1F;
            """
        )

        self.neck_posture_widget = NeckPostureWidget()

        neck_layout = QVBoxLayout()
        neck_layout.setContentsMargins(16, 18, 16, 14)
        neck_layout.setSpacing(8)
        neck_layout.addWidget(neck_title)
        neck_layout.addWidget(self.neck_posture_widget, 1)

        neck_card.setLayout(neck_layout)

        top_content_layout = QHBoxLayout()
        top_content_layout.setSpacing(16)
        top_content_layout.addWidget(score_card, 1)
        top_content_layout.addWidget(neck_card, 1)
        top_content_layout.addWidget(heatmap_card, 1)

        graph_card = QFrame()
        graph_card.setObjectName("GraphCard")
        graph_card.setStyleSheet(
            """
            QFrame#GraphCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 22px;
            }
            """
        )

        graph_shadow = QGraphicsDropShadowEffect()
        graph_shadow.setBlurRadius(22)
        graph_shadow.setXOffset(0)
        graph_shadow.setYOffset(8)
        graph_shadow.setColor(QColor(0, 0, 0, 22))
        graph_card.setGraphicsEffect(graph_shadow)

        graph_title_label = QLabel("실시간 자세 점수 그래프")
        graph_title_label.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 500;
            color: #1D1D1F;
            """
        )

        self.realtime_score_badge = QLabel("실시간 점수 -")
        self.realtime_score_badge.setAlignment(Qt.AlignCenter)
        self.realtime_score_badge.setFixedHeight(32)
        self.realtime_score_badge.setMinimumWidth(118)
        self.set_realtime_score_badge(None)

        graph_header_layout = QHBoxLayout()
        graph_header_layout.setSpacing(10)
        graph_header_layout.addWidget(graph_title_label)
        graph_header_layout.addStretch(1)
        graph_header_layout.addWidget(self.realtime_score_badge)

        self.graph_widget = ScoreGraphWidget(
            mode="dashboard",
            max_points=30,
            empty_text="주행 분석을 시작하면 점수 그래프가 표시됩니다."
        )
        self.graph_widget.setMinimumHeight(165)

        graph_layout = QVBoxLayout()
        graph_layout.setContentsMargins(20, 16, 20, 18)
        graph_layout.setSpacing(8)
        graph_layout.addLayout(graph_header_layout)
        graph_layout.addWidget(self.graph_widget, 1)

        graph_card.setLayout(graph_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(34, 26, 34, 28)
        layout.setSpacing(18)

        layout.addLayout(header_layout)
        layout.addLayout(top_content_layout, 2)
        layout.addWidget(graph_card, 2)

        self.setLayout(layout)

    def showEvent(self, event):
        current_user = self.stack.app.current_user

        if current_user is None:
            self.user_label.setText("사용자: -")
        else:
            self.user_label.setText(f"사용자: {current_user}")

        super().showEvent(event)

    def set_realtime_score_badge(self, score):
        """그래프 카드 오른쪽 위에 표시되는 실시간 점수 배지를 갱신한다."""

        if not hasattr(self, "realtime_score_badge"):
            return

        try:
            score_value = int(round(float(score)))
        except (TypeError, ValueError):
            self.realtime_score_badge.setText("실시간 점수 -")
            background = "#F3F6FB"
            color = "#6E6E73"
            border = "#E7ECF8"
        else:
            self.realtime_score_badge.setText(f"실시간 점수 {score_value}점")

            if score_value < SCORE_WARNING_THRESHOLD:
                background = "#FFF3D9"
                color = "#C47A00"
                border = "#FFD38A"
            elif score_value < 85:
                background = "#F4F7FF"
                color = "#3C6FEA"
                border = "#D6E3FF"
            else:
                background = "#EEF8F2"
                color = "#1C8C4A"
                border = "#CDEED8"

        self.realtime_score_badge.setStyleSheet(
            f"""
            QLabel {{
                background-color: {background};
                color: {color};
                border: 1px solid {border};
                border-radius: 13px;
                padding-left: 12px;
                padding-right: 12px;
                font-size: 13px;
                font-weight: 600;
            }}
            """
        )

    def reset_warning_hold_state(self, reset_popup_time=False):
        """주차/종료/새 주행 시작 시 센서 경고 유지시간 계산을 초기화한다."""

        self.pressure_warning_type = None
        self.pressure_warning_started_at = None
        self.pressure_warning_ready_type = None
        self.back_bend_warning_started_at = None
        self.back_bend_warning_ready = False
        self.back_warning_recovery_started_at = None
        self.neck_warning_started_at = None
        self.neck_warning_ready = False
        self.neck_warning_recovery_started_at = None
        self.drowsy_warning_started_at = None
        self.drowsy_warning_ready = False
        self.drowsy_warning_recovery_started_at = None
        self.back_warning_popup_latched = False
        self.neck_warning_popup_latched = False
        self.drowsy_warning_popup_latched = False

        if reset_popup_time:
            self.last_warning_popup_at = 0.0
            self.last_back_warning_popup_at = 0.0
            self.last_neck_warning_popup_at = 0.0
            self.last_drowsy_popup_at = 0.0

    def update_pressure_warning_hold(self, pressure_warning_type):
        """
        좌우 하중 쏠림이 5초 이상 같은 방향으로 유지될 때만
        경고 후보를 ready 상태로 만든다.
        """

        now = time.monotonic()

        if pressure_warning_type is None:
            self.pressure_warning_type = None
            self.pressure_warning_started_at = None
            self.pressure_warning_ready_type = None
            return

        if self.pressure_warning_type != pressure_warning_type:
            self.pressure_warning_type = pressure_warning_type
            self.pressure_warning_started_at = now
            self.pressure_warning_ready_type = None
            return

        if self.pressure_warning_started_at is None:
            self.pressure_warning_started_at = now
            self.pressure_warning_ready_type = None
            return

        if now - self.pressure_warning_started_at >= PRESSURE_LOAD_SHIFT_ALERT_HOLD_SEC:
            self.pressure_warning_ready_type = pressure_warning_type

    def update_back_bend_warning_hold(self, bend_percent):
        """
        등 구부러짐 100%가 8초 이상 유지될 때만 경고 후보가 된다.
        순간적으로 임계값 아래로 내려갔다고 새 경고를 허용하지 않고,
        65% 이하의 정상권이 5초 유지돼야 이전 경고 에피소드를 해제한다.
        """

        now = time.monotonic()
        try:
            percent = max(0.0, min(100.0, float(bend_percent)))
        except (TypeError, ValueError):
            percent = 0.0
        back_bend_problem = percent >= 100.0

        if not back_bend_problem:
            self.back_bend_warning_started_at = None
            self.back_bend_warning_ready = False

            if percent <= BACK_WARNING_RECOVERY_PERCENT:
                if self.back_warning_recovery_started_at is None:
                    self.back_warning_recovery_started_at = now
                elif now - self.back_warning_recovery_started_at >= BACK_WARNING_RECOVERY_HOLD_SEC:
                    self.back_warning_popup_latched = False
            else:
                self.back_warning_recovery_started_at = None
            return

        self.back_warning_recovery_started_at = None

        if self.back_bend_warning_started_at is None:
            self.back_bend_warning_started_at = now
            self.back_bend_warning_ready = False
            return

        if now - self.back_bend_warning_started_at >= ULTRASONIC_BACK_BEND_ALERT_HOLD_SEC:
            self.back_bend_warning_ready = True

    def update_neck_warning_hold(self, neck_percent, angle_drop_deg):
        """
        일반 목 경고는 100%가 8초 유지되어야 하고, 졸음 의심은 21도 이상
        큰 변화가 2초 유지되어야 한다. 고개 돌림처럼 잠깐 튀는 값은 무시하며,
        충분한 정상 상태가 5초 유지된 뒤에만 다음 팝업을 허용한다.
        """

        now = time.monotonic()
        try:
            percent = max(0.0, min(100.0, float(neck_percent)))
        except (TypeError, ValueError):
            percent = 0.0
        try:
            angle_drop = float(angle_drop_deg)
        except (TypeError, ValueError):
            angle_drop = 0.0

        neck_forward_problem = percent >= 100.0
        drowsy_problem = angle_drop >= NECK_DROWSY_ANGLE_DROP_THRESHOLD_DEG

        if not neck_forward_problem:
            self.neck_warning_started_at = None
            self.neck_warning_ready = False

            if percent <= NECK_WARNING_RECOVERY_PERCENT:
                if self.neck_warning_recovery_started_at is None:
                    self.neck_warning_recovery_started_at = now
                elif now - self.neck_warning_recovery_started_at >= NECK_WARNING_RECOVERY_HOLD_SEC:
                    self.neck_warning_popup_latched = False
            else:
                self.neck_warning_recovery_started_at = None
        elif self.neck_warning_started_at is None:
            self.neck_warning_recovery_started_at = None
            self.neck_warning_started_at = now
            self.neck_warning_ready = False
        elif now - self.neck_warning_started_at >= NECK_FORWARD_ALERT_HOLD_SEC:
            self.neck_warning_ready = True

        if not drowsy_problem:
            self.drowsy_warning_started_at = None
            self.drowsy_warning_ready = False

            if angle_drop <= NECK_DROWSY_RECOVERY_ANGLE_DEG:
                if self.drowsy_warning_recovery_started_at is None:
                    self.drowsy_warning_recovery_started_at = now
                elif now - self.drowsy_warning_recovery_started_at >= NECK_DROWSY_RECOVERY_HOLD_SEC:
                    self.drowsy_warning_popup_latched = False
            else:
                self.drowsy_warning_recovery_started_at = None
        elif self.drowsy_warning_started_at is None:
            self.drowsy_warning_recovery_started_at = None
            self.drowsy_warning_started_at = now
            self.drowsy_warning_ready = False
        elif now - self.drowsy_warning_started_at >= NECK_DROWSY_ALERT_HOLD_SEC:
            self.drowsy_warning_ready = True

    def compose_sensor_warning_message(self):
        """현재 ready 상태인 센서 문제를 조합해 경고 제목과 문구를 만든다."""

        pressure_type = self.pressure_warning_ready_type
        back_ready = self.back_bend_warning_ready
        neck_ready = self.neck_warning_ready
        drowsy_ready = self.drowsy_warning_ready

        if drowsy_ready:
            return (
                "졸음 운전 의심",
                "목이 크게 앞으로 떨어진 상태가 감지되었습니다.\n"
                "즉시 자세를 바로잡고, 필요하면 안전한 곳에 정차해 휴식하세요."
            )

        if pressure_type is not None and back_ready and neck_ready:
            return (
                "복합 자세 경고",
                "하중 쏠림, 등 구부러짐, 목 전방 이동이 함께 감지되었습니다.\n"
                "몸을 중앙에 맞추고 허리와 목을 바로 세워주세요."
            )

        if pressure_type is not None and back_ready:
            return (
                "복합 자세 경고",
                "하중 쏠림과 등 구부러짐이 함께 감지되었습니다.\n"
                "몸을 중앙에 맞추고 허리를 펴주세요."
            )

        if pressure_type is not None and neck_ready:
            return (
                "복합 자세 경고",
                "하중 쏠림과 목 전방 이동이 함께 감지되었습니다.\n"
                "몸을 중앙에 맞추고 턱을 가볍게 당겨주세요."
            )

        if back_ready and neck_ready:
            return (
                "상체 자세 경고",
                "등 구부러짐과 목 전방 이동이 함께 감지되었습니다.\n"
                "허리를 펴고 머리를 뒤로 가볍게 당겨주세요."
            )

        if pressure_type == "left":
            return (
                "좌측 하중 경고",
                "왼쪽으로 하중이 집중되었습니다.\n"
                "몸을 오른쪽으로 살짝 이동해 중앙에 맞춰주세요."
            )

        if pressure_type == "right":
            return (
                "우측 하중 경고",
                "오른쪽으로 하중이 집중되었습니다.\n"
                "몸을 왼쪽으로 살짝 이동해 중앙에 맞춰주세요."
            )

        if back_ready:
            return (
                "등 자세 경고",
                "등 구부러짐이 지속적으로 감지되었습니다.\n"
                "허리를 펴고 등받이에 바르게 기대주세요."
            )

        if neck_ready:
            return (
                "목 자세 경고",
                "목이 앞으로 나온 자세가 지속적으로 감지되었습니다.\n"
                "턱을 가볍게 당기고 후두부를 뒤로 이동해주세요."
            )

        return None, None

    def maybe_show_sensor_warning(self):
        """
        센서 문제가 설정된 유지시간 이상 계속되면 경고 화면을 띄운다.
        등/목/졸음 경고는 같은 문제 구간에서 한 번만 표시하고, 충분히 정상으로
        회복된 뒤에도 각각의 긴 쿨다운을 만족해야 다시 표시한다.
        """

        if self.stack.app.drive_state != DRIVE:
            return

        if self.stack.currentWidget() == self.stack.warning_window:
            return

        title, message = self.compose_sensor_warning_message()

        if title is None or message is None:
            return

        now = time.monotonic()
        drowsy_warning = bool(self.drowsy_warning_ready)

        back_warning = bool(self.back_bend_warning_ready) and not drowsy_warning
        neck_warning = bool(self.neck_warning_ready) and not drowsy_warning and not back_warning

        if drowsy_warning:
            if self.drowsy_warning_popup_latched:
                return
            if now - self.last_drowsy_popup_at < NECK_DROWSY_POPUP_COOLDOWN_SEC:
                return
            self.last_drowsy_popup_at = now
            self.drowsy_warning_popup_latched = True
            self.last_warning_popup_at = now
        elif back_warning:
            # 같은 등 구부러짐이 계속되는 동안에는 한 번만 표시한다.
            # 충분히 회복했다 다시 나빠지더라도 최소 120초 간격을 보장한다.
            if self.back_warning_popup_latched:
                return
            if now - self.last_back_warning_popup_at < BACK_WARNING_POPUP_COOLDOWN_SEC:
                return
            self.last_back_warning_popup_at = now
            self.back_warning_popup_latched = True
            self.last_warning_popup_at = now
        elif neck_warning:
            if self.neck_warning_popup_latched:
                return
            if now - self.last_neck_warning_popup_at < NECK_WARNING_POPUP_COOLDOWN_SEC:
                return
            self.last_neck_warning_popup_at = now
            self.neck_warning_popup_latched = True
            self.last_warning_popup_at = now
        else:
            if now - self.last_warning_popup_at < WARNING_POPUP_COOLDOWN_SEC:
                return
            self.last_warning_popup_at = now

        self.stack.app.session.add_warning()
        active_scores = self.stack.app.session.get_active_scores()
        active_warning_indices = self.stack.app.session.get_active_warning_indices()
        self.graph_widget.set_scores(active_scores, active_warning_indices)

        self.stack.warning_window.set_warning(title, message)
        self.stack.setCurrentWidget(self.stack.warning_window)

    def start_analysis(self, user_name):
        self.user_label.setText(f"사용자: {user_name}")
        self.reset_warning_hold_state(reset_popup_time=True)
        self.set_realtime_score_badge(None)

        # 같은 사용자로 재개하면 이전 점수 흐름을 이어서 보여주고,
        # 다른 사용자로 바뀌면 해당 사용자의 새 구간 데이터로 그래프를 갱신한다.
        active_scores = self.stack.app.session.get_active_scores()
        active_warning_indices = self.stack.app.session.get_active_warning_indices()
        self.graph_widget.set_scores(active_scores, active_warning_indices)

        if len(active_scores) > 0:
            self.last_mock_score = active_scores[-1]
        else:
            self.last_mock_score = 96

        if not hasattr(self, "timer"):
            self.timer = QTimer(self)
            self.timer.setInterval(DASHBOARD_ANALYSIS_INTERVAL_MS)
            self.timer.timeout.connect(self.update_mock_data)

        if not hasattr(self, "heatmap_timer"):
            self.heatmap_timer = QTimer(self)
            self.heatmap_timer.setInterval(PRESSURE_HEATMAP_UPDATE_INTERVAL_MS)
            self.heatmap_timer.timeout.connect(self.update_realtime_heatmap)

        if not hasattr(self, "back_curve_timer"):
            self.back_curve_timer = QTimer(self)
            self.back_curve_timer.setInterval(ULTRASONIC_BACK_CURVE_UPDATE_INTERVAL_MS)
            self.back_curve_timer.timeout.connect(self.update_back_curvature)

        if not hasattr(self, "neck_posture_timer"):
            self.neck_posture_timer = QTimer(self)
            self.neck_posture_timer.setInterval(NECK_POSTURE_UPDATE_INTERVAL_MS)
            self.neck_posture_timer.timeout.connect(self.update_neck_posture)

        self.timer.start()
        self.heatmap_timer.start()
        self.back_curve_timer.start()
        self.neck_posture_timer.start()

        # 시작 직후 빈 화면처럼 보이지 않도록 한 번씩 즉시 갱신한다.
        self.update_realtime_heatmap()
        self.update_back_curvature()
        self.update_neck_posture()
        self.update_mock_data()

    def pause_analysis(self):
        self.reset_warning_hold_state(reset_popup_time=False)

        if hasattr(self, "timer"):
            self.timer.stop()

        if hasattr(self, "heatmap_timer"):
            self.heatmap_timer.stop()

        if hasattr(self, "back_curve_timer"):
            self.back_curve_timer.stop()

        if hasattr(self, "neck_posture_timer"):
            self.neck_posture_timer.stop()

    def update_back_curvature(self):
        """
        초음파 모니터가 갱신하는 posture_feedback.json을 읽어
        왼쪽 위 등 자세 모니터링 카드를 갱신한다.
        """

        payload = load_ultrasonic_posture_feedback()
        self.back_curve_widget.set_feedback(payload)

        bend_percent = 0

        if isinstance(payload, dict) and not bool(payload.get("_stale", False)):
            bend_percent = calculate_back_bend_percent(payload)

        self.update_back_bend_warning_hold(bend_percent)
        self.maybe_show_sensor_warning()

    def update_neck_posture(self):
        """
        목/헤드 초음파 모니터가 갱신하는 neck_posture_feedback.json을 읽어
        상단 목 자세 모니터링 카드를 갱신한다.
        """

        payload = load_neck_posture_feedback()
        self.neck_posture_widget.set_feedback(payload)

        neck_percent = 0
        angle_drop = 0.0

        if isinstance(payload, dict) and not bool(payload.get("_stale", False)):
            neck_percent = calculate_neck_forward_percent(payload)
            angle_drop = get_neck_angle_drop(payload)

        self.update_neck_warning_hold(neck_percent, angle_drop)
        self.maybe_show_sensor_warning()

    def update_realtime_heatmap(self):
        """
        히트맵만 빠르게 갱신한다.
        자세 SVM/사용자 SVM은 실행하지 않고 최신 corrected_sensor 값만 가져온다.
        """

        sensor_values = get_latest_pressure_sensor_values()

        if sensor_values is not None:
            self.update_heatmap(sensor_values)

    def update_mock_data(self):
        prediction = get_pressure_prediction_once()

        sensor_values = None
        pressure_warning_type = None

        # SVM 판정이 무효여도 실제 압력 16채널 자체는 히트맵에 표시한다.
        if isinstance(prediction, dict):
            sensor_values = _cache_pressure_sensor_values(prediction)

        if prediction is not None and prediction.get("is_valid", True):
            posture = prediction.get("posture", "")
            # 실시간 좌우 압력 불균형은 상태 문구와 연속 점수에 함께 반영한다.
            try:
                balance_index = float(prediction.get("balance_index", 0.0))
            except (TypeError, ValueError):
                balance_index = 0.0

            balance_index = max(0.0, min(100.0, balance_index))
            balance = str(prediction.get("balance", "Unknown"))

            score = calculate_integrated_posture_score(
                prediction,
                back_payload=load_ultrasonic_posture_feedback(),
                neck_payload=load_neck_posture_feedback(),
                previous_score=self.last_mock_score,
            )

            if balance == "Left" and balance_index >= PRESSURE_LOAD_SHIFT_BALANCE_THRESHOLD:
                state = "좌측 하중 집중"
                pressure_warning_type = "left"
            elif balance == "Right" and balance_index >= PRESSURE_LOAD_SHIFT_BALANCE_THRESHOLD:
                state = "우측 하중 집중"
                pressure_warning_type = "right"
            else:
                state = posture_to_korean_state(posture, score)
                pressure_warning_type = None

            self.last_mock_score = score

        elif isinstance(prediction, dict):
            # 센서 16채널은 들어왔지만 edge 조건 등으로 SVM 판정만 보류된 상태다.
            # 히트맵은 계속 표시하고 그래프에는 마지막 정상 점수를 유지한다.
            score = self.last_mock_score if self.last_mock_score is not None else 75
            warning_code = str(prediction.get("warning", "")).strip().lower()
            if warning_code == "edge_sensor":
                state = "좌석 중앙에 앉아주세요"
            else:
                state = "체압 자세 판정 확인 중"

        else:
            if USE_REAL_PRESSURE_SENSOR:
                # 실제 장비 모드에서 랜덤값을 실측값처럼 표시하지 않는다.
                self.score_label.setText("-")
                self.state_label.setText("체압센서 연결 중")
                self.set_realtime_score_badge(None)
                self.update_pressure_warning_hold(None)
                return

            # 센서 없는 UI 데모 모드에서만 mock 점수를 사용한다.
            if self.last_mock_score is None:
                self.last_mock_score = random.randint(78, 88)
            delta = random.randint(-5, 5)
            score = max(62, min(97, self.last_mock_score + delta))
            self.last_mock_score = score
            state = get_score_state(score)

        self.score_label.setText(f"{score}점")
        self.state_label.setText(state)
        self.set_realtime_score_badge(score)

        self.update_pressure_warning_hold(pressure_warning_type)
        self.maybe_show_sensor_warning()

        # 1초 단위 자세 판단 결과에도 센서값이 있으면 히트맵을 한 번 더 동기화한다.
        # 실제 빠른 반응은 update_realtime_heatmap()의 150ms 타이머가 담당한다.
        if sensor_values is not None:
            self.update_heatmap(sensor_values)

        active_scores = self.stack.app.session.get_active_scores()
        previous_score = active_scores[-1] if len(active_scores) > 0 else None

        score_index = self.stack.app.session.add_score(score)

        # 점수가 기준 점수 아래로 처음 떨어지는 순간을 경고 발생 시점으로 기록한다.
        # 계속 낮은 상태가 이어질 때 매초 경고가 쌓이지 않도록 이전 점수와 비교한다.
        is_warning = score < SCORE_WARNING_THRESHOLD and (previous_score is None or previous_score >= SCORE_WARNING_THRESHOLD)

        if is_warning and score_index is not None:
            self.stack.app.session.add_warning(score_index)

        self.graph_widget.add_score(score, is_warning=is_warning, warning_time=score_index)

    def update_heatmap(self, sensor_values=None):
        """
        corrected_sensor 16개 값을 SFS 실제 좌표에 배치해 압력 분포를 갱신한다.
        센서가 준비되지 않은 환경에서는 같은 좌표를 사용한 자연스러운 mock 분포를 표시한다.
        """

        self.pressure_map_widget.set_sensor_values(sensor_values)

    def go_report(self):
        self.stack.app.enter_report_state()


class WarningWindow(QWidget):
    def __init__(self, stack):
        super().__init__()

        self.stack = stack

        self.init_ui()

    def init_ui(self):
        self.setObjectName("WarningWindow")
        self.setStyleSheet(
            """
            QWidget#WarningWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QLabel {
                background-color: transparent;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QPushButton {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        warning_card = QFrame()
        warning_card.setObjectName("WarningCard")
        warning_card.setStyleSheet(
            """
            QFrame#WarningCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 28px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(30)
        shadow.setXOffset(0)
        shadow.setYOffset(10)
        shadow.setColor(QColor(0, 0, 0, 35))
        warning_card.setGraphicsEffect(shadow)

        self.icon_label = QLabel("!")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedSize(64, 64)
        self.set_warning_icon_style("normal")

        self.title_label = QLabel("자세 경고")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(
            """
            font-size: 28px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        self.message_label = QLabel("좌측 하중이 집중되었습니다.\n몸을 중앙으로 맞춰주세요.")
        self.message_label.setAlignment(Qt.AlignCenter)
        self.message_label.setStyleSheet(
            """
            font-size: 18px;
            font-weight: 400;
            color: #4A4A4A;
            line-height: 150%;
            """
        )

        self.confirm_button = QPushButton("확인")
        self.confirm_button.setCursor(Qt.PointingHandCursor)
        self.confirm_button.setFixedSize(110, 42)
        self.confirm_button.setStyleSheet(
            """
            QPushButton {
                background-color: #3C6FEA;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 16px;
                font-weight: 500;
            }

            QPushButton:hover {
                background-color: #2F5FD0;
            }
            """
        )
        self.confirm_button.clicked.connect(self.go_dashboard)

        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(50, 42, 50, 42)
        card_layout.setSpacing(18)
        card_layout.addWidget(self.icon_label, alignment=Qt.AlignCenter)
        card_layout.addWidget(self.title_label)
        card_layout.addWidget(self.message_label)
        card_layout.addSpacing(8)
        card_layout.addWidget(self.confirm_button, alignment=Qt.AlignCenter)

        warning_card.setLayout(card_layout)

        layout = QVBoxLayout()
        layout.setContentsMargins(90, 70, 90, 70)
        layout.addStretch(1)
        layout.addWidget(warning_card)
        layout.addStretch(1)

        self.setLayout(layout)

    def set_warning_icon_style(self, mode="normal"):
        if mode == "drowsy":
            background = "#FEE4E2"
            color = "#D92D20"
        else:
            background = "#FFF1D6"
            color = "#D88900"

        self.icon_label.setStyleSheet(
            f"""
            background-color: {background};
            color: {color};
            border-radius: 32px;
            font-size: 34px;
            font-weight: 600;
            """
        )

    def set_warning(self, title, message):
        self.title_label.setText(title)
        self.message_label.setText(message)

        if "졸음" in str(title):
            self.set_warning_icon_style("drowsy")
        else:
            self.set_warning_icon_style("normal")

    def go_dashboard(self):
        self.stack.setCurrentWidget(self.stack.app.dashboard_window)


class ReportWindow(QWidget):
    def __init__(self, stack):
        super().__init__()

        self.stack = stack
        self.report_pages = []
        self.current_report_index = 0

        self.init_ui()

    def init_ui(self):
        self.setObjectName("ReportWindow")
        self.setStyleSheet(
            """
            QWidget#ReportWindow {
                background-color: #FAFAFC;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QLabel {
                background-color: transparent;
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }

            QPushButton {
                font-family: 'Noto Sans CJK KR', 'Noto Sans KR', 'NanumGothic', 'DejaVu Sans';
            }
            """
        )

        self.title_label = QLabel("주행 리포트")
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet(
            """
            font-size: 28px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        self.exit_button = QPushButton("종료")
        self.exit_button.setObjectName("ReportExitButton")
        self.exit_button.setCursor(Qt.PointingHandCursor)
        self.exit_button.setFixedSize(58, 30)
        self.exit_button.setStyleSheet(
            """
            QPushButton#ReportExitButton {
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 11px;
                font-size: 13px;
                font-weight: 500;
            }

            QPushButton#ReportExitButton:hover {
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }
            """
        )
        self.exit_button.clicked.connect(QApplication.quit)

        left_space = QWidget()
        left_space.setFixedSize(58, 30)
        left_space.setStyleSheet("background-color: transparent; border: none;")

        header_layout = QHBoxLayout()
        header_layout.addWidget(left_space)
        header_layout.addStretch(1)
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        header_layout.addWidget(self.exit_button)

        self.driver_label = QLabel("운전자 리포트")
        self.driver_label.setAlignment(Qt.AlignCenter)
        self.driver_label.setStyleSheet(
            """
            font-size: 16px;
            font-weight: 500;
            color: #6E6E73;
            """
        )

        avg_card = self.create_metric_card("평균 점수", "-")
        self.avg_score_label = avg_card.findChild(QLabel, "MetricValue")

        min_card = self.create_metric_card("최저 점수", "-")
        self.min_score_label = min_card.findChild(QLabel, "MetricValue")

        metric_layout = QHBoxLayout()
        metric_layout.setSpacing(20)
        metric_layout.addWidget(avg_card)
        metric_layout.addWidget(min_card)

        graph_card = QFrame()
        graph_card.setObjectName("ReportGraphCard")
        graph_card.setStyleSheet(
            """
            QFrame#ReportGraphCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 22px;
            }
            """
        )

        graph_shadow = QGraphicsDropShadowEffect()
        graph_shadow.setBlurRadius(22)
        graph_shadow.setXOffset(0)
        graph_shadow.setYOffset(8)
        graph_shadow.setColor(QColor(0, 0, 0, 22))
        graph_card.setGraphicsEffect(graph_shadow)

        self.report_graph_widget = ScoreGraphWidget(
            mode="report",
            max_points=None,
            empty_text="저장된 점수 데이터가 없습니다."
        )
        self.report_graph_widget.setMinimumHeight(205)

        graph_layout = QVBoxLayout()
        graph_layout.setContentsMargins(18, 18, 18, 18)
        graph_layout.addWidget(self.report_graph_widget, 1)

        graph_card.setLayout(graph_layout)

        self.home_button = QPushButton("홈으로")
        self.home_button.setObjectName("ReportHomeButton")
        self.home_button.setCursor(Qt.PointingHandCursor)
        self.home_button.setFixedSize(130, 42)
        self.home_button.setStyleSheet(
            """
            QPushButton#ReportHomeButton {
                background-color: #3C6FEA;
                color: white;
                border: none;
                border-radius: 15px;
                font-size: 16px;
                font-weight: 500;
            }

            QPushButton#ReportHomeButton:hover {
                background-color: #2F5FD0;
            }
            """
        )
        self.home_button.clicked.connect(self.go_home)

        self.prev_report_button = QPushButton("이전 리포트")
        self.prev_report_button.setObjectName("ReportPrevButton")
        self.prev_report_button.setCursor(Qt.PointingHandCursor)
        self.prev_report_button.setFixedSize(120, 42)
        self.prev_report_button.setStyleSheet(self.secondary_button_style("ReportPrevButton"))
        self.prev_report_button.clicked.connect(self.show_previous_report)

        self.next_report_button = QPushButton("다음 리포트")
        self.next_report_button.setObjectName("ReportNextButton")
        self.next_report_button.setCursor(Qt.PointingHandCursor)
        self.next_report_button.setFixedSize(120, 42)
        self.next_report_button.setStyleSheet(self.secondary_button_style("ReportNextButton"))
        self.next_report_button.clicked.connect(self.show_next_report)

        self.page_label = QLabel("1 / 1")
        self.page_label.setAlignment(Qt.AlignCenter)
        self.page_label.setFixedWidth(56)
        self.page_label.setStyleSheet(
            """
            font-size: 14px;
            font-weight: 500;
            color: #8A8F9E;
            """
        )

        bottom_layout = QHBoxLayout()
        bottom_layout.addStretch(1)
        bottom_layout.addWidget(self.home_button)
        bottom_layout.addSpacing(18)
        bottom_layout.addWidget(self.prev_report_button)
        bottom_layout.addWidget(self.page_label)
        bottom_layout.addWidget(self.next_report_button)
        bottom_layout.addStretch(1)

        layout = QVBoxLayout()
        layout.setContentsMargins(34, 26, 34, 28)
        layout.setSpacing(14)

        layout.addLayout(header_layout)
        layout.addWidget(self.driver_label)
        layout.addLayout(metric_layout)
        layout.addWidget(graph_card, 1)
        layout.addLayout(bottom_layout)

        self.setLayout(layout)

        self.update_navigation_buttons()

    def secondary_button_style(self, object_name):
        return f"""
            QPushButton#{object_name} {{
                background-color: #FAFCFF;
                color: #7B8DBA;
                border: 1px solid #EEF2FA;
                border-radius: 15px;
                font-size: 15px;
                font-weight: 500;
            }}

            QPushButton#{object_name}:hover {{
                background-color: #F3F7FF;
                color: #3C6FEA;
                border: 1px solid #D6E3FF;
            }}
        """

    def create_metric_card(self, title, value):
        card = QFrame()
        card.setObjectName("MetricCard")
        card.setStyleSheet(
            """
            QFrame#MetricCard {
                background-color: #FFFFFF;
                border: none;
                border-radius: 22px;
            }
            """
        )

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(22)
        shadow.setXOffset(0)
        shadow.setYOffset(8)
        shadow.setColor(QColor(0, 0, 0, 22))
        card.setGraphicsEffect(shadow)

        title_label = QLabel(title)
        title_label.setAlignment(Qt.AlignCenter)
        title_label.setStyleSheet(
            """
            font-size: 15px;
            font-weight: 500;
            color: #6E6E73;
            """
        )

        value_label = QLabel(value)
        value_label.setObjectName("MetricValue")
        value_label.setAlignment(Qt.AlignCenter)
        value_label.setStyleSheet(
            """
            font-size: 34px;
            font-weight: 600;
            color: #1D1D1F;
            """
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(20, 16, 20, 16)
        layout.addWidget(title_label)
        layout.addSpacing(6)
        layout.addWidget(value_label)

        card.setLayout(layout)

        return card

    def set_report_data_from_session(self, summaries):
        self.report_pages = self.build_driver_reports(summaries)
        self.current_report_index = 0
        self.render_current_report()

    def build_driver_reports(self, summaries):
        """
        E 키가 눌린 시점의 세션 데이터를 운전자 이름 기준으로 묶는다.
        운전자가 1명이면 1개 리포트, 2명 이상이면 운전자 수만큼 리포트 페이지가 만들어진다.
        """

        driver_reports = []
        driver_index_map = {}

        for summary in summaries:
            user = summary["user"]

            if user not in driver_index_map:
                driver_index_map[user] = len(driver_reports)
                driver_reports.append(
                    {
                        "user": user,
                        "scores": [],
                        "warning_indices": [],
                        "segment_count": 0,
                        "start_time": summary["start_time"],
                        "end_time": summary["end_time"]
                    }
                )

            report = driver_reports[driver_index_map[user]]
            offset = len(report["scores"])
            report["scores"].extend(summary["scores"])

            for warning_index in summary.get("warning_indices", []):
                report["warning_indices"].append(offset + warning_index)

            report["segment_count"] += 1
            report["end_time"] = summary["end_time"]

        for report in driver_reports:
            scores = report["scores"]

            if len(scores) == 0:
                report["avg_score"] = "-"
                report["min_score"] = "-"
            else:
                report["avg_score"] = round(sum(scores) / len(scores))
                report["min_score"] = min(scores)

        return driver_reports

    def render_current_report(self):
        if len(self.report_pages) == 0:
            self.driver_label.setText("저장된 주행 데이터 없음")
            self.avg_score_label.setText("-")
            self.min_score_label.setText("-")
            self.report_graph_widget.reset_scores()
            self.update_navigation_buttons()
            return

        report = self.report_pages[self.current_report_index]
        total_pages = len(self.report_pages)
        page_number = self.current_report_index + 1

        score_count = len(report["scores"])

        if total_pages == 1:
            self.driver_label.setText(f"{report['user']} 주행 결과 · 전체 운전시간 {score_count}초")
        else:
            self.driver_label.setText(
                f"{report['user']} 주행 결과  ·  {page_number}/{total_pages}  ·  전체 운전시간 {score_count}초"
            )

        avg_score = report["avg_score"]
        min_score = report["min_score"]

        self.avg_score_label.setText(f"{avg_score}점" if avg_score != "-" else "-")
        self.min_score_label.setText(f"{min_score}점" if min_score != "-" else "-")
        self.report_graph_widget.set_scores(
            report["scores"],
            report.get("warning_indices", [])
        )

        self.update_navigation_buttons()

    def create_graph_placeholder_text(self, report):
        scores = report["scores"]
        count = len(scores)

        if count == 0:
            return f"{report['user']}의 저장된 점수 데이터가 없습니다."

        # 너무 많은 점수를 전부 표시하면 지저분해져서 앞뒤 일부만 보여준다.
        if count <= 16:
            score_text = " → ".join(str(score) for score in scores)
        else:
            front_scores = " → ".join(str(score) for score in scores[:8])
            back_scores = " → ".join(str(score) for score in scores[-8:])
            score_text = f"{front_scores} → ... → {back_scores}"

        return (
            f"{report['user']} 점수 그래프 영역\n\n"
            f"측정 데이터: {count}개\n"
            f"주행 구간: {report['segment_count']}개\n\n"
            f"점수 흐름\n{score_text}"
        )

    def update_navigation_buttons(self):
        total_pages = len(self.report_pages)
        has_multiple_reports = total_pages >= 2

        self.prev_report_button.setVisible(has_multiple_reports)
        self.next_report_button.setVisible(has_multiple_reports)
        self.page_label.setVisible(has_multiple_reports)

        if not has_multiple_reports:
            return

        self.page_label.setText(f"{self.current_report_index + 1} / {total_pages}")
        self.prev_report_button.setEnabled(self.current_report_index > 0)
        self.next_report_button.setEnabled(self.current_report_index < total_pages - 1)

    def show_previous_report(self):
        if self.current_report_index > 0:
            self.current_report_index -= 1
            self.render_current_report()

    def show_next_report(self):
        if self.current_report_index < len(self.report_pages) - 1:
            self.current_report_index += 1
            self.render_current_report()

    def go_home(self):
        self.stack.app.reset_to_user_select()


# =========================================================
# Touch Screen On-Screen Keyboard
# =========================================================
class TouchKeyButton(QPushButton):
    """터치스크린에서 Touch 이벤트를 직접 처리하는 키보드 버튼."""

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self._touch_pressed = False

        # Raspberry Pi Touch Display에서 터치가 마우스 클릭으로 변환되지 않는
        # 환경에서도 키보드 버튼이 직접 TouchBegin/TouchEnd를 받도록 한다.
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)

    def event(self, event):
        event_type = event.type()

        if event_type == QEvent.TouchBegin:
            self._touch_pressed = True
            self.setDown(True)
            event.accept()
            return True

        if event_type == QEvent.TouchUpdate:
            event.accept()
            return True

        if event_type == QEvent.TouchEnd:
            should_click = self._touch_pressed
            self._touch_pressed = False
            self.setDown(False)
            event.accept()

            # 키보드는 포커스를 받지 않으므로 입력창 포커스를 유지한 채 즉시 입력한다.
            if should_click:
                self.click()

            return True

        if event_type == QEvent.TouchCancel:
            self._touch_pressed = False
            self.setDown(False)
            event.accept()
            return True

        return super().event(event)


class TouchKeyboard(QWidget):
    """
    라즈베리파이 7인치 터치스크린용 화면 키보드.
    이전 버전처럼 화면 위에 겹쳐 띄우지 않고, MainWindow 하단 레이아웃 공간에 붙는다.
    그래서 입력창/등록 버튼을 가리지 않는다.
    """

    CHO_LIST = [
        "ㄱ", "ㄲ", "ㄴ", "ㄷ", "ㄸ", "ㄹ", "ㅁ", "ㅂ", "ㅃ", "ㅅ",
        "ㅆ", "ㅇ", "ㅈ", "ㅉ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
    ]

    JUNG_LIST = [
        "ㅏ", "ㅐ", "ㅑ", "ㅒ", "ㅓ", "ㅔ", "ㅕ", "ㅖ", "ㅗ", "ㅘ", "ㅙ",
        "ㅚ", "ㅛ", "ㅜ", "ㅝ", "ㅞ", "ㅟ", "ㅠ", "ㅡ", "ㅢ", "ㅣ",
    ]

    JONG_LIST = [
        "", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ",
        "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ",
        "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ",
    ]

    VOWEL_COMBINE = {
        ("ㅗ", "ㅏ"): "ㅘ",
        ("ㅗ", "ㅐ"): "ㅙ",
        ("ㅗ", "ㅣ"): "ㅚ",
        ("ㅜ", "ㅓ"): "ㅝ",
        ("ㅜ", "ㅔ"): "ㅞ",
        ("ㅜ", "ㅣ"): "ㅟ",
        ("ㅡ", "ㅣ"): "ㅢ",
    }

    FINAL_COMBINE = {
        ("ㄱ", "ㅅ"): "ㄳ",
        ("ㄴ", "ㅈ"): "ㄵ",
        ("ㄴ", "ㅎ"): "ㄶ",
        ("ㄹ", "ㄱ"): "ㄺ",
        ("ㄹ", "ㅁ"): "ㄻ",
        ("ㄹ", "ㅂ"): "ㄼ",
        ("ㄹ", "ㅅ"): "ㄽ",
        ("ㄹ", "ㅌ"): "ㄾ",
        ("ㄹ", "ㅍ"): "ㄿ",
        ("ㄹ", "ㅎ"): "ㅀ",
        ("ㅂ", "ㅅ"): "ㅄ",
    }

    FINAL_SPLIT = {
        "ㄳ": ("ㄱ", "ㅅ"),
        "ㄵ": ("ㄴ", "ㅈ"),
        "ㄶ": ("ㄴ", "ㅎ"),
        "ㄺ": ("ㄹ", "ㄱ"),
        "ㄻ": ("ㄹ", "ㅁ"),
        "ㄼ": ("ㄹ", "ㅂ"),
        "ㄽ": ("ㄹ", "ㅅ"),
        "ㄾ": ("ㄹ", "ㅌ"),
        "ㄿ": ("ㄹ", "ㅍ"),
        "ㅀ": ("ㄹ", "ㅎ"),
        "ㅄ": ("ㅂ", "ㅅ"),
    }

    def __init__(self, parent=None):
        super().__init__(parent)

        self.target_input = None
        self.current_mode = "text"
        self.shift_enabled = False

        self.cho_index = {value: index for index, value in enumerate(self.CHO_LIST)}
        self.jung_index = {value: index for index, value in enumerate(self.JUNG_LIST)}
        self.jong_index = {value: index for index, value in enumerate(self.JONG_LIST)}

        self.setObjectName("TouchKeyboard")
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_AcceptTouchEvents, True)
        self.setFixedHeight(148)
        self.setStyleSheet(
            """
            QWidget#TouchKeyboard {
                background-color: #F6F8FC;
                border-top: 1px solid #E5EBF7;
            }
            QPushButton {
                background-color: #FFFFFF;
                color: #1D1D1F;
                border: 1px solid #E5EBF7;
                border-radius: 9px;
                font-size: 14px;
                font-weight: 500;
                min-height: 29px;
            }
            QPushButton:pressed {
                background-color: #DCE8FF;
                border: 1px solid #B7CEFF;
            }
            QPushButton#FunctionKey {
                background-color: #EEF4FF;
                color: #3C6FEA;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#DoneKey {
                background-color: #3C6FEA;
                color: white;
                border: none;
                font-size: 13px;
                font-weight: 600;
            }
            """
        )

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(10, 6, 10, 7)
        self.main_layout.setSpacing(4)
        self.setLayout(self.main_layout)
        self.rebuild_keyboard()

    def set_target_input(self, line_edit, mode="text"):
        self.target_input = line_edit
        self.current_mode = mode
        self.shift_enabled = False
        self.setFixedHeight(104 if mode == "number" else 148)
        self.rebuild_keyboard()
        self.show()
        line_edit.setFocus()

    def hide_keyboard(self):
        self.hide()
        if self.target_input is not None:
            self.target_input.clearFocus()
        self.target_input = None

    def rebuild_keyboard(self):
        self.clear_layout(self.main_layout)

        if self.current_mode == "number":
            # 숫자 입력은 2줄로 줄여서 전후 위치/등받이 입력 화면을 최대한 가리지 않는다.
            rows = [
                ["1", "2", "3", "4", "5", "⌫"],
                ["6", "7", "8", "9", "0", "-", ".", "완료"],
            ]
        else:
            if self.shift_enabled:
                rows = [
                    ["ㅃ", "ㅉ", "ㄸ", "ㄲ", "ㅆ", "ㅛ", "ㅕ", "ㅑ", "ㅒ", "ㅖ"],
                    ["ㅁ", "ㄴ", "ㅇ", "ㄹ", "ㅎ", "ㅗ", "ㅓ", "ㅏ", "ㅣ"],
                    ["⇧", "ㅋ", "ㅌ", "ㅊ", "ㅍ", "ㅠ", "ㅜ", "ㅡ", "⌫"],
                    ["공백", "완료"],
                ]
            else:
                rows = [
                    ["ㅂ", "ㅈ", "ㄷ", "ㄱ", "ㅅ", "ㅛ", "ㅕ", "ㅑ", "ㅐ", "ㅔ"],
                    ["ㅁ", "ㄴ", "ㅇ", "ㄹ", "ㅎ", "ㅗ", "ㅓ", "ㅏ", "ㅣ"],
                    ["⇧", "ㅋ", "ㅌ", "ㅊ", "ㅍ", "ㅠ", "ㅜ", "ㅡ", "⌫"],
                    ["공백", "완료"],
                ]

        for row in rows:
            row_layout = QHBoxLayout()
            row_layout.setSpacing(4)
            row_layout.addStretch(1)

            for key in row:
                button = self.create_key_button(key)

                if self.current_mode == "number":
                    if key == "완료":
                        button.setFixedWidth(94)
                    elif key == "⌫":
                        button.setFixedWidth(58)
                    else:
                        button.setFixedWidth(48)
                else:
                    if key == "공백":
                        button.setFixedWidth(250)
                    elif key == "완료":
                        button.setFixedWidth(104)
                    elif key in ["⌫", "⇧"]:
                        button.setFixedWidth(54)
                    else:
                        button.setFixedWidth(42)

                row_layout.addWidget(button)

            row_layout.addStretch(1)
            self.main_layout.addLayout(row_layout)

    def clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            child_layout = item.layout()

            if widget is not None:
                widget.deleteLater()
            elif child_layout is not None:
                self.clear_layout(child_layout)

    def create_key_button(self, key):
        button = TouchKeyButton(key, self)
        button.setCursor(Qt.PointingHandCursor)
        button.setFocusPolicy(Qt.NoFocus)

        # 마우스 클릭과 실제 터치를 둘 다 지원한다.
        button.setAttribute(Qt.WA_AcceptTouchEvents, True)

        if key in ["⌫", "⇧", "공백"]:
            button.setObjectName("FunctionKey")
        elif key == "완료":
            button.setObjectName("DoneKey")

        button.clicked.connect(lambda checked=False, value=key: self.handle_key(value))
        return button

    def handle_key(self, key):
        if self.target_input is None:
            return

        if key == "완료":
            self.hide_keyboard()
            return

        if key == "⌫":
            self.target_input.backspace()
            self.target_input.setFocus()
            return

        if key == "⇧":
            self.shift_enabled = not self.shift_enabled
            self.rebuild_keyboard()
            self.target_input.setFocus()
            return

        if key == "공백":
            self.target_input.insert(" ")
            self.target_input.setFocus()
            return

        if self.current_mode == "number":
            self.target_input.insert(key)
        else:
            self.insert_hangul_key(key)

        self.target_input.setFocus()

    def insert_hangul_key(self, key):
        line_edit = self.target_input
        text = line_edit.text()
        cursor_pos = line_edit.cursorPosition()
        prefix = text[:cursor_pos]
        suffix = text[cursor_pos:]

        if key in self.cho_index:
            new_prefix = self.apply_consonant(prefix, key)
        elif key in self.jung_index:
            new_prefix = self.apply_vowel(prefix, key)
        else:
            new_prefix = prefix + key

        line_edit.setText(new_prefix + suffix)
        line_edit.setCursorPosition(len(new_prefix))

    def is_hangul_syllable(self, char):
        if not char:
            return False
        return 0xAC00 <= ord(char) <= 0xD7A3

    def decompose_syllable(self, char):
        code = ord(char) - 0xAC00
        cho = code // 588
        jung = (code % 588) // 28
        jong = code % 28
        return cho, jung, jong

    def compose_syllable(self, cho, jung, jong=0):
        return chr(0xAC00 + (cho * 21 + jung) * 28 + jong)

    def apply_consonant(self, prefix, consonant):
        if not prefix:
            return consonant

        last_char = prefix[-1]

        if self.is_hangul_syllable(last_char):
            cho, jung, jong = self.decompose_syllable(last_char)

            if jong == 0 and consonant in self.jong_index and self.jong_index[consonant] != 0:
                return prefix[:-1] + self.compose_syllable(cho, jung, self.jong_index[consonant])

            if jong != 0:
                current_final = self.JONG_LIST[jong]
                combined_final = self.FINAL_COMBINE.get((current_final, consonant))

                if combined_final is not None:
                    return prefix[:-1] + self.compose_syllable(cho, jung, self.jong_index[combined_final])

        return prefix + consonant

    def apply_vowel(self, prefix, vowel):
        if not prefix:
            return vowel

        last_char = prefix[-1]

        if last_char in self.cho_index:
            return prefix[:-1] + self.compose_syllable(self.cho_index[last_char], self.jung_index[vowel], 0)

        if self.is_hangul_syllable(last_char):
            cho, jung, jong = self.decompose_syllable(last_char)

            if jong == 0:
                current_vowel = self.JUNG_LIST[jung]
                combined_vowel = self.VOWEL_COMBINE.get((current_vowel, vowel))

                if combined_vowel is not None:
                    return prefix[:-1] + self.compose_syllable(cho, self.jung_index[combined_vowel], 0)

                return prefix + vowel

            current_final = self.JONG_LIST[jong]

            if current_final in self.FINAL_SPLIT:
                first_final, second_initial = self.FINAL_SPLIT[current_final]
                previous = self.compose_syllable(cho, jung, self.jong_index[first_final])

                if second_initial in self.cho_index:
                    next_char = self.compose_syllable(self.cho_index[second_initial], self.jung_index[vowel], 0)
                    return prefix[:-1] + previous + next_char

            if current_final in self.cho_index:
                previous = self.compose_syllable(cho, jung, 0)
                next_char = self.compose_syllable(self.cho_index[current_final], self.jung_index[vowel], 0)
                return prefix[:-1] + previous + next_char

        return prefix + vowel


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("Seat ID Project")
        self.resize(TOUCH_DISPLAY_WIDTH, TOUCH_DISPLAY_HEIGHT)
        self.setMinimumSize(800, 480)

        self.drive_state = IDLE
        self.current_user = None
        self.current_user_id = None
        self.session = DriveSession()

        # S 버튼 입력 후 체압 안정화 측정 화면이 진행 중인지 표시한다.
        self.identification_measurement_running = False
        self.identification_measurement_token = None
        self.identification_attempt = 0
        self.identification_attempt_started_at = 0.0
        self.identification_pressure_start_sample_id = None
        self.identification_ready_pressure_prediction = None
        self.identification_pressure_samples = []
        self.identification_last_collected_sample_id = None
        self.identification_retry_scheduled = False
        self.sensor_readiness_timer = QTimer(self)
        self.sensor_readiness_timer.setInterval(SENSOR_READINESS_POLL_INTERVAL_MS)
        self.sensor_readiness_timer.timeout.connect(self.check_identification_sensor_readiness)

        # 신규 사용자 체압 등록 → SVM 재학습 파이프라인 상태
        self.registration_process = None
        self.registration_stage = None
        self.registration_pipeline_running = False
        self.pending_registration_record = None
        self.pending_start_after_register = True
        self.registration_before_sample_count = 0
        self.registration_before_database_mtime_ns = None
        self.registration_process_output = ""
        self.registration_old_model_mtimes = {}

        # 이전 앱 실행의 START 측정 신호가 남아 있어 초음파가 즉시 보정되는 일을 막는다.
        clear_sensor_measurement_trigger()

        self.init_ui()

        # 앱 전체에서 P/S/E 키 입력을 감지한다.
        # 나중에 Arduino Leonardo가 HID 키보드처럼 S/P/E를 보내도 이 함수에서 처리된다.
        QApplication.instance().installEventFilter(self)

        # Raspberry Pi/Leonardo HID 환경에서 KeyPress 이벤트가 특정 자식 위젯에
        # 잡혀 eventFilter까지 안정적으로 전달되지 않는 경우를 대비한 보조 단축키.
        # MainWindow 및 모든 자식 위젯에서 S/P/E를 받을 수 있다.
        self.setup_drive_shortcuts()
        print("[INPUT] S/P/E 전역 단축키 활성화 완료")

    def setup_drive_shortcuts(self):
        """S/P/E 물리 키와 Leonardo HID 입력을 안정적으로 처리한다."""
        self.start_shortcut = QShortcut(QKeySequence("S"), self)
        self.park_shortcut = QShortcut(QKeySequence("P"), self)
        self.end_shortcut = QShortcut(QKeySequence("E"), self)

        for shortcut in (
            self.start_shortcut,
            self.park_shortcut,
            self.end_shortcut,
        ):
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.setAutoRepeat(False)

        self.start_shortcut.activated.connect(
            lambda: self.handle_drive_shortcut(Qt.Key_S)
        )
        self.park_shortcut.activated.connect(
            lambda: self.handle_drive_shortcut(Qt.Key_P)
        )
        self.end_shortcut.activated.connect(
            lambda: self.handle_drive_shortcut(Qt.Key_E)
        )

    def handle_drive_shortcut(self, key):
        """
        QShortcut 경로.
        텍스트/숫자 입력창을 실제로 편집 중일 때는 S/P/E를 문자로 입력할 수 있게
        단축키 화면 전환을 막고, 그 외 화면에서는 주행 버튼 명령으로 처리한다.
        """
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) and focused.isVisible():
            return

        if self.registration_pipeline_running and key in (Qt.Key_S, Qt.Key_P, Qt.Key_E):
            return

        if self.identification_measurement_running and key in (Qt.Key_S, Qt.Key_P, Qt.Key_E):
            print("체압 측정 중 입력 무시")
            return

        if key == Qt.Key_S:
            self.enter_user_select_state()
        elif key == Qt.Key_P:
            self.enter_park_safe_state()
        elif key == Qt.Key_E:
            self.enter_report_state()

    def init_ui(self):
        self.stack = QStackedWidget()
        self.stack.app = self

        self.stack.setStyleSheet(
            """
            QStackedWidget {
                background-color: #FAFAFC;
                border: none;
            }
            """
        )

        self.home_window = HomeWindow(self.stack)
        self.pressure_measure_window = PressureIdentificationMeasureWindow(self.stack)
        self.identification_window = IdentificationConfirmWindow(self.stack)
        self.add_user_window = AddUserWindow(self.stack)
        self.registration_progress_window = UserRegistrationProgressWindow(self.stack)
        self.seat_confirm_window = SeatSettingConfirmWindow(self.stack)
        self.seat_edit_window = SeatSettingEditWindow(self.stack)
        self.dashboard_window = DashboardWindow(self.stack)
        self.report_window = ReportWindow(self.stack)
        self.warning_window = WarningWindow(self.stack)
        self.screen_off_window = ScreenOffWindow(self.stack)

        self.stack.warning_window = self.warning_window

        self.stack.addWidget(self.home_window)             # 사용자 목록 / 안전모드
        self.stack.addWidget(self.pressure_measure_window) # 사용자 식별 전 체압 측정 안내
        self.stack.addWidget(self.identification_window)   # 자동 사용자 확인
        self.stack.addWidget(self.add_user_window)         # 신규 사용자 등록
        self.stack.addWidget(self.registration_progress_window)  # 체압 등록 / SVM 재학습
        self.stack.addWidget(self.seat_confirm_window)     # 시트 환경 확인
        self.stack.addWidget(self.seat_edit_window)        # 시트 환경 수정
        self.stack.addWidget(self.dashboard_window)        # 대시보드
        self.stack.addWidget(self.report_window)           # 리포트
        self.stack.addWidget(self.warning_window)          # 경고 화면
        self.stack.addWidget(self.screen_off_window)       # 화면 꺼짐

        # 터치스크린 입력용 화면 키보드.
        # 화면 위에 겹치지 않도록 QVBoxLayout의 하단 영역에 실제 위젯으로 붙인다.
        self.touch_keyboard = TouchKeyboard(self)
        self.touch_keyboard.hide()

        # 화면이 바뀌면 이전 입력창에 붙어 있던 터치 키보드는 항상 닫는다.
        # 예: 신규 등록 화면에서 키보드를 띄운 뒤 등록/이전/화면 전환을 해도
        # 다른 화면에 키보드가 남아있지 않게 한다.
        self.stack.currentChanged.connect(self.hide_touch_keyboard)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.touch_keyboard, 0)
        self.setLayout(layout)

        # 처음 앱 실행 시에는 화면이 꺼진 것처럼 검은 화면만 보여준다.
        self.home_window.update_mode_view(self.drive_state, self.current_user)
        self.turn_display_off()
        self.stack.setCurrentWidget(self.screen_off_window)

    def hide_touch_keyboard(self):
        """입력이 끝났거나 화면이 바뀔 때 하단 터치 키보드를 닫는다."""
        if hasattr(self, "touch_keyboard") and self.touch_keyboard is not None:
            self.touch_keyboard.hide_keyboard()

    def is_keyboard_child(self, obj):
        """클릭한 위젯이 터치 키보드 내부 위젯인지 확인한다."""
        if not hasattr(self, "touch_keyboard") or self.touch_keyboard is None:
            return False

        widget = obj
        while widget is not None:
            if widget is self.touch_keyboard:
                return True
            if not hasattr(widget, "parent"):
                break
            widget = widget.parent()

        return False

    def is_keyboard_target(self, obj):
        """클릭한 위젯이 현재 키보드가 입력 중인 QLineEdit인지 확인한다."""
        if not hasattr(self, "touch_keyboard") or self.touch_keyboard is None:
            return False

        return obj is self.touch_keyboard.target_input

    def eventFilter(self, obj, event):
        # 라즈베리파이 터치는 Touch 이벤트 뒤에 MouseButtonPress를 합성할 수 있다.
        # 그 합성 이벤트의 obj가 키 버튼이 아닌 상위 위젯으로 전달되는 경우가 있어,
        # 전역 마우스 이벤트로 키보드를 자동 종료하면 첫 키를 누르는 즉시 닫힌다.
        # 완료 키와 화면 전환 함수가 명시적으로 닫도록 하고 여기서는 유지한다.

        if event.type() == QEvent.FocusIn and isinstance(obj, QLineEdit):
            # 터치스크린에서 입력창을 누르거나 유효성 검사 후 입력창으로 돌아오면
            # 필요한 순간에만 하단 키보드를 띄운다.
            validator = obj.validator()
            if isinstance(validator, (QDoubleValidator, QIntValidator)):
                keyboard_mode = "number"
            else:
                keyboard_mode = "text"

            if hasattr(self, "touch_keyboard"):
                self.touch_keyboard.set_target_input(obj, keyboard_mode)
            return False

        if event.type() == QEvent.KeyPress:
            if self.registration_pipeline_running and event.key() in (Qt.Key_S, Qt.Key_P, Qt.Key_E):
                return True

            if self.identification_measurement_running and event.key() in (Qt.Key_S, Qt.Key_P, Qt.Key_E):
                print("체압 측정 중 입력 무시")
                return True

            # 이름 입력창에서는 S/P/E도 문자 입력으로 취급해야 하므로 화면 전환하지 않음
            if isinstance(obj, QLineEdit):
                return False

            # 키를 꾹 누를 때 반복 입력되는 것 방지
            if event.isAutoRepeat():
                return True

            # QApplication eventFilter가 KeyPress를 먼저 소비하므로,
            # 여기서 직접 S/P/E 명령을 실행해야 한다.
            # 이전 버전은 QShortcut이 활성화되어 있으면 아무 함수도 호출하지 않은 채
            # return True 해버려 S/P/E가 전부 먹히는 문제가 있었다.
            if event.key() == Qt.Key_S:
                print("[KEY] START(S) 입력 감지")
                self.handle_drive_shortcut(Qt.Key_S)
                return True

            elif event.key() == Qt.Key_P:
                print("[KEY] PARK(P) 입력 감지")
                self.handle_drive_shortcut(Qt.Key_P)
                return True

            elif event.key() == Qt.Key_E:
                print("[KEY] END(E) 입력 감지")
                self.handle_drive_shortcut(Qt.Key_E)
                return True

        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        # 키보드는 레이아웃에 들어가 있으므로 별도 setGeometry를 하지 않는다.
        super().resizeEvent(event)

    def set_display_power(self, power_on):
        """
        라즈베리파이에서 실제 디스플레이 출력을 켜고/끄는 자리.
        개발 중에는 USE_REAL_DISPLAY_POWER=False로 두면 UI 검은 화면만 전환된다.
        라즈베리파이에서 테스트할 때 True로 바꾸고, 사용하는 디스플레이 방식에 맞게 명령을 조정한다.
        """

        if not USE_REAL_DISPLAY_POWER:
            return

        value = "1" if power_on else "0"

        try:
            subprocess.run(
                ["vcgencmd", "display_power", value],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=2
            )
        except Exception as error:
            print(f"디스플레이 전원 명령 실행 실패: {error}")

    def turn_display_on(self):
        self.set_display_power(True)

    def turn_display_off(self):
        self.set_display_power(False)

    def enter_user_select_state(self):
        self.hide_touch_keyboard()

        """
        S 키 입력.
        - 최초 대기/리포트 상태: 자동 사용자 식별 흐름 시작
        - 주차 대기 상태: 화면을 다시 켜고 체압 기반 자동 사용자 식별 재시작
        """

        self.turn_display_on()

        if self.drive_state == REPORT:
            self.session = DriveSession()
            self.current_user = None
            self.current_user_id = None

        if self.drive_state in [IDLE, REPORT]:
            self.drive_state = USER_SELECT
            self.start_identification_flow()
            print("상태 변경: USER_SELECT / 자동 사용자 식별 시작")
            return

        if self.drive_state == PARK_SAFE:
            # 주차 중에는 화면을 비워두고, 다시 S 버튼을 눌렀을 때
            # 새로 앉은 사람의 체압을 다시 측정해 자동 식별 흐름을 시작한다.
            self.drive_state = USER_SELECT
            self.start_identification_flow()
            print("상태 변경: PARK_SAFE -> USER_SELECT / 자동 사용자 식별 재시작")
            return

        if self.drive_state == DRIVE:
            print("이미 DRIVE 상태입니다.")
            return

    def start_identification_flow(self):
        self.hide_touch_keyboard()

        """
        S 버튼 입력 후 사용자 식별을 시작한다.

        기존처럼 바로 SVM 예측을 수행하지 않고,
        먼저 체압 측정 안내 화면을 보여 주어 사용자가 바른 자세로 안정되게 앉을 시간을 확보한다.
        이후 finish_identification_measurement()에서 실제 사용자 예측을 수행한다.
        """

        if self.identification_measurement_running:
            print("체압 측정이 이미 진행 중입니다.")
            return

        self.home_window.reload_profiles()
        self.home_window.update_mode_view(self.drive_state, self.current_user)

        self.identification_measurement_running = True
        self.identification_attempt = 0
        self.identification_ready_pressure_prediction = None
        self.identification_pressure_samples = []
        self.identification_last_collected_sample_id = None
        self.identification_retry_scheduled = False

        # 압력 수집은 GUI 메인 스레드를 막지 않는 백그라운드 서비스가 담당한다.
        ensure_pressure_background_service()
        self.stack.setCurrentWidget(self.pressure_measure_window)
        self.start_identification_sensor_attempt()

    def start_identification_sensor_attempt(self):
        """새 token으로 체압·등·목 측정 한 회차를 시작한다."""

        if not self.identification_measurement_running:
            return

        self.identification_retry_scheduled = False
        self.identification_attempt += 1
        self.identification_attempt_started_at = time.monotonic()

        current_pressure = get_pressure_prediction_once()
        self.identification_pressure_start_sample_id = (
            current_pressure.get("sample_id") if isinstance(current_pressure, dict) else None
        )
        self.identification_ready_pressure_prediction = None
        self.identification_pressure_samples = []
        self.identification_last_collected_sample_id = None

        self.identification_measurement_token = send_sensor_measurement_trigger()
        self.pressure_measure_window.start_measurement(
            PRESSURE_IDENTIFICATION_MEASUREMENT_MS,
            self.identification_attempt,
        )
        self.sensor_readiness_timer.start()
        print(
            "체압 · 등 · 목 동시 측정 시작 / "
            f"시도={self.identification_attempt}, token={self.identification_measurement_token}"
        )

    def collect_identification_pressure_sample(self, prediction):
        """같은 캐시를 중복 집계하지 않고 새 체압 사용자 예측만 모은다."""

        if not isinstance(prediction, dict) or not bool(prediction.get("is_valid", True)):
            return

        user_id = str(prediction.get("user_id", "")).strip()
        if not user_id:
            return

        confidence = confidence_to_ratio(
            prediction.get("user_confidence", prediction.get("confidence", 0.0))
        )
        if confidence <= 0.0:
            return

        sample_id = prediction.get("sample_id")
        if sample_id is None:
            values = prediction.get("corrected_sensor", [])
            try:
                sample_id = tuple(round(float(value), 2) for value in values)
            except (TypeError, ValueError):
                sample_id = None

        if sample_id == self.identification_last_collected_sample_id:
            return

        self.identification_last_collected_sample_id = sample_id
        self.identification_pressure_samples.append(dict(prediction))
        self.identification_pressure_samples = self.identification_pressure_samples[
            -PRESSURE_IDENTIFICATION_MAX_USER_SAMPLES:
        ]

    def check_identification_sensor_readiness(self):
        """현재 START 회차에서 세 센서가 모두 성공했을 때만 다음 화면으로 이동한다."""

        if not self.identification_measurement_running or self.identification_retry_scheduled:
            return

        pressure_prediction = get_pressure_prediction_once()
        self.collect_identification_pressure_sample(pressure_prediction)
        readiness = evaluate_startup_sensor_readiness(
            self.identification_measurement_token,
            self.identification_pressure_start_sample_id,
            pressure_prediction,
            load_ultrasonic_posture_feedback(),
            load_neck_posture_feedback(),
        )
        self.pressure_measure_window.show_sensor_status(readiness, self.identification_attempt)

        collected_count = len(self.identification_pressure_samples)
        if readiness["all_ready"] and collected_count < PRESSURE_IDENTIFICATION_MIN_USER_SAMPLES:
            readiness["pressure"]["ready"] = False
            readiness["pressure"]["phase"] = "measuring"
            readiness["pressure"]["label"] = (
                f"사용자 판별 데이터 수집 {collected_count}/"
                f"{PRESSURE_IDENTIFICATION_MIN_USER_SAMPLES}"
            )
            readiness["all_ready"] = False
            self.pressure_measure_window.show_sensor_status(readiness, self.identification_attempt)

        if readiness["all_ready"]:
            self.identification_ready_pressure_prediction = (
                aggregate_pressure_identification_samples(
                    self.identification_pressure_samples,
                    fallback_prediction=pressure_prediction,
                )
            )
            self.sensor_readiness_timer.stop()
            QTimer.singleShot(0, self.finish_identification_measurement)
            return

        elapsed_ms = int(
            max(0.0, time.monotonic() - self.identification_attempt_started_at) * 1000
        )
        phases = [readiness[key]["phase"] for key in ("pressure", "back", "neck")]
        has_error = "error" in phases
        still_calibrating = "measuring" in phases
        timed_out = elapsed_ms >= PRESSURE_IDENTIFICATION_MEASUREMENT_MS
        minimum_measurement_finished = elapsed_ms >= (
            SENSOR_CALIBRATION_SETTLE_MS + SENSOR_CALIBRATION_MEASURE_MS
        )

        # 한 센서가 오류를 냈더라도 다른 초음파가 보정 중이면 그 작업이 끝날 때까지 기다린다.
        # 체압의 순간적인 edge 판정을 곧바로 실패로 보지 않도록 최소 측정 시간도 보장한다.
        if (
            has_error
            and minimum_measurement_finished
            and not still_calibrating
        ) or timed_out:
            failed_labels = [
                readiness[key]["label"]
                for key in ("pressure", "back", "neck")
                if not readiness[key]["ready"]
            ]
            reason = " / ".join(failed_labels) or "센서 측정 결과를 받지 못했습니다"
            self.schedule_identification_retry(reason)

    def schedule_identification_retry(self, reason):
        if not self.identification_measurement_running or self.identification_retry_scheduled:
            return
        self.identification_retry_scheduled = True
        self.sensor_readiness_timer.stop()
        self.pressure_measure_window.show_retry(reason, self.identification_attempt + 1)
        print(f"센서 측정 재시도 예약: {reason}")
        QTimer.singleShot(SENSOR_RETRY_DELAY_MS, self.start_identification_sensor_attempt)

    def cancel_identification_measurement(self):
        self.identification_measurement_running = False
        self.identification_retry_scheduled = False
        self.identification_measurement_token = None
        self.identification_ready_pressure_prediction = None
        self.identification_pressure_samples = []
        self.identification_last_collected_sample_id = None
        self.sensor_readiness_timer.stop()
        self.pressure_measure_window.stop_measurement()

    def finish_identification_measurement(self):
        """
        체압 측정 안내 시간이 끝난 뒤 실제 사용자 식별 결과를 확인 화면으로 넘긴다.
        """

        if not self.identification_measurement_running:
            return

        pressure_prediction = self.identification_ready_pressure_prediction
        self.cancel_identification_measurement()

        if isinstance(pressure_prediction, dict):
            print(
                "[USER-ID] "
                f"등록목록 후보={pressure_prediction.get('user_id', '')}, "
                f"전역 SVM 1위={pressure_prediction.get('user_global_best_id', '')}, "
                f"후보 신뢰도={pressure_prediction.get('user_confidence', 0)}, "
                f"원본 확률={pressure_prediction.get('user_raw_confidence', 0)}, "
                f"표본={pressure_prediction.get('identification_sample_count', 0)}, "
                f"합의율={pressure_prediction.get('identification_consensus', 0)}, "
                f"범위={pressure_prediction.get('user_match_scope', '')}"
            )

        self.home_window.reload_profiles()
        self.home_window.update_mode_view(self.drive_state, self.current_user)

        result = identify_user_from_pressure_csv(
            self.home_window.profiles,
            prediction=pressure_prediction,
        )

        if result.get("is_new_user") and len(self.home_window.profiles) == 0:
            # 등록된 사용자가 아예 없으면 측정 안내 후 신규 등록 화면으로 보낸다.
            self.open_new_user_registration(start_after_register=True)
            return

        if result.get("is_new_user") and len(self.home_window.profiles) >= MAX_USER_PROFILES:
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            self.show_user_list(show_add_card=False)
            return

        self.identification_window.start_identification(result)
        self.stack.setCurrentWidget(self.identification_window)
        print("체압 측정 완료 / 사용자 확인 화면 표시")

    def confirm_identified_user(self, user_name):
        """5초 타이머가 끝났을 때 예측 사용자를 확정한다."""

        self.select_user(user_name)

    def show_user_list_from_identification(self):
        """
        자동 사용자 식별 화면에서 '사용자 목록 보기'를 눌렀을 때 호출된다.

        여기서 사용자를 직접 선택하더라도 바로 대시보드로 가지 않고,
        select_user()를 통해
        하드웨어 명령 전송 → 시트 환경 확인 화면 → 확인 → 대시보드
        순서를 반드시 거치게 한다.
        """

        if self.drive_state == IDLE:
            self.drive_state = USER_SELECT

        self.show_user_list(show_add_card=False)

    def show_user_list(self, show_add_card=False):
        """예측 사용자가 틀렸을 때 기존 사용자 목록으로 이동한다."""
        self.hide_touch_keyboard()
        self.cancel_identification_measurement()

        self.drive_state = USER_SELECT if self.drive_state != PARK_SAFE else PARK_SAFE
        self.home_window.reload_profiles()
        self.home_window.show_add_card = bool(show_add_card) and len(self.home_window.profiles) < MAX_USER_PROFILES
        self.home_window.update_mode_view(self.drive_state, self.current_user)
        self.stack.setCurrentWidget(self.home_window)

    def open_new_user_registration(self, start_after_register=True):
        """신규 사용자 등록 화면을 연다."""
        self.hide_touch_keyboard()

        if self.drive_state == IDLE:
            self.drive_state = USER_SELECT

        if len(load_user_profile_records()) >= MAX_USER_PROFILES:
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            self.show_user_list(show_add_card=False)
            return

        self.add_user_window.prepare(start_after_register=start_after_register)
        self.stack.setCurrentWidget(self.add_user_window)

    def register_new_user(self, record, start_after_register=True):
        """
        신규 사용자 저장.
        - user_id 자동 생성값 저장
        - user_profile.csv에 사용자 추가
        - 체압 데이터 처리부에 user_id 연동 요청
        - 체압 등록과 사용자 모델 재학습 실행
        - 등록 완료 후 사용자 목록으로 복귀
        """

        if not isinstance(record, dict):
            return

        user_name = clean_user_name(record.get("name", ""))
        seat_forward = normalize_number_text(record.get("seat_forward", ""))
        backrest_angle = normalize_number_text(record.get("backrest_angle", ""))

        if seat_forward != "" and backrest_angle != "":
            seat_env = make_seat_env(seat_forward, backrest_angle)
        else:
            seat_env = str(record.get("seat_env", "")).strip() or make_default_seat_env()

        if user_name == "":
            QMessageBox.warning(self, "입력 오류", "사용자 이름을 입력해주세요.")
            return

        records = load_user_profile_records()

        if len(records) >= MAX_USER_PROFILES:
            QMessageBox.information(
                self,
                "사용자 추가 불가",
                get_user_limit_message()
            )
            self.home_window.reload_profiles()
            self.home_window.update_mode_view(self.drive_state, self.current_user)
            self.show_user_list(show_add_card=False)
            return

        if is_duplicate_profile(user_name, records):
            QMessageBox.warning(
                self,
                "중복 사용자",
                f"'{user_name}' 사용자는 이미 등록되어 있습니다.\n다른 이름을 입력해주세요."
            )
            return

        user_id = str(record.get("user_id", "")).strip()
        if user_id == "" or find_user_record_by_id(user_id, records) is not None:
            user_id = generate_next_user_id(records)

        saved_record = {
            "user_id": user_id,
            "name": user_name,
            "nickname": user_name,
            "seat_position": seat_forward,
            "seat_forward": seat_forward,
            "backrest_angle": backrest_angle,
            "seat_env": seat_env,
            "created_at": record.get("created_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        }

        records.append(saved_record)
        save_user_profile_records(records)
        self.home_window.reload_profiles()
        self.home_window.update_mode_view(self.drive_state, self.current_user)

        # 등록 요청 이력을 남긴 뒤 체압 수집 → SVM 재학습을 순서대로 실행한다.
        send_new_user_to_pressure_processor(saved_record)
        self.start_user_registration_pipeline(
            saved_record,
            start_after_register=start_after_register,
        )

    def _count_pressure_samples_for_user(self, user_id):
        if not os.path.exists(PRESSURE_DATABASE_FILE):
            return 0

        target_id = str(user_id).strip()
        count = 0
        try:
            with open(PRESSURE_DATABASE_FILE, "r", encoding="utf-8-sig", newline="") as file:
                reader = csv.DictReader(file)
                for row in reader:
                    row_id = str(row.get("user_id", "")).strip()
                    try:
                        row_id = str(int(float(row_id)))
                    except (TypeError, ValueError):
                        pass
                    if row_id == target_id:
                        count += 1
        except OSError:
            return 0
        return count

    def _close_pressure_prediction_service(self):
        global _pressure_prediction_error_printed
        try:
            module = importlib.import_module("real_time_prediction_rasp")
            if hasattr(module, "close_service"):
                module.close_service()
        except Exception as error:
            print(f"체압 예측 서비스 종료 경고: {error}")
        importlib.invalidate_caches()
        _pressure_prediction_error_printed = False

    def _append_registration_log(self, text):
        if not text:
            return
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            with open(REGISTRATION_PIPELINE_LOG, "a", encoding="utf-8") as file:
                file.write(text)
                if not text.endswith("\n"):
                    file.write("\n")
        except OSError as error:
            print(f"등록 로그 저장 실패: {error}")

    def _start_registration_process(self, stage, script_path, arguments):
        if not os.path.exists(script_path):
            self._registration_failed(f"필요한 파일이 없습니다: {os.path.basename(script_path)}")
            return

        process = QProcess(self)
        process.setWorkingDirectory(APP_DIR)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_registration_process_output)
        process.finished.connect(self._registration_process_finished)
        process.errorOccurred.connect(self._registration_process_error)

        self.registration_stage = stage
        self.registration_process = process
        self.registration_process_output = ""
        process.start(sys.executable, ["-u", script_path] + list(arguments))

        if not process.waitForStarted(3000):
            self._registration_failed(f"{os.path.basename(script_path)} 실행을 시작하지 못했습니다.")

    def start_user_registration_pipeline(self, record, start_after_register=True):
        if self.registration_pipeline_running:
            return

        normalized_record = normalize_profile_record(record)
        if normalized_record is None:
            QMessageBox.warning(self, "등록 오류", "신규 사용자 정보를 불러올 수 없습니다.")
            return

        self.pending_registration_record = normalized_record
        self.pending_start_after_register = bool(start_after_register)
        self.registration_pipeline_running = True

        self.hide_touch_keyboard()
        self.registration_progress_window.prepare(normalized_record)
        self.stack.setCurrentWidget(self.registration_progress_window)

        user_id = normalized_record.get("user_id", "")
        user_name = normalized_record.get("name", normalized_record.get("nickname", ""))
        self.registration_before_sample_count = self._count_pressure_samples_for_user(user_id)
        try:
            self.registration_before_database_mtime_ns = os.stat(
                PRESSURE_DATABASE_FILE
            ).st_mtime_ns
        except OSError:
            self.registration_before_database_mtime_ns = None

        # 현재 실행 중인 예측 서비스가 압력 센서 포트와 모델 파일을 점유하지 않도록 닫는다.
        self._close_pressure_prediction_service()

        if not RUN_PRESSURE_REGISTRATION_ON_NEW_USER:
            self._start_user_model_training()
            return

        self.registration_progress_window.set_collecting(0)
        self._start_registration_process(
            "pressure",
            PRESSURE_REGISTRATION_SCRIPT,
            [
                "--user-id", str(user_id),
                "--nickname", str(user_name),
                "--port", str(PRESSURE_SENSOR_PORT),
            ],
        )

    def retry_user_registration(self):
        if self.registration_pipeline_running or self.pending_registration_record is None:
            return
        self.start_user_registration_pipeline(
            self.pending_registration_record,
            start_after_register=self.pending_start_after_register,
        )

    def _read_registration_process_output(self):
        process = self.registration_process
        if process is None:
            return

        data = bytes(process.readAllStandardOutput()).decode("utf-8", errors="ignore")
        if not data:
            return

        print(data, end="")
        self._append_registration_log(data)
        self.registration_process_output += data

        if self.registration_stage == "pressure":
            matches = re.findall(r"(\d{1,3})%", data)
            if matches:
                self.registration_progress_window.set_collecting(int(matches[-1]))

    def _registration_process_error(self, process_error):
        if not self.registration_pipeline_running:
            return
        self._registration_failed(f"프로세스 실행 오류가 발생했습니다. 코드: {int(process_error)}")

    def _registration_process_finished(self, exit_code, exit_status):
        self._read_registration_process_output()
        stage = self.registration_stage
        self.registration_process = None

        stage_name = "체압 데이터 등록" if stage == "pressure" else "사용자 인식 모델 업데이트"

        if exit_status != QProcess.NormalExit or exit_code != 0:
            self._registration_failed(
                f"{stage_name} 과정이 정상적으로 완료되지 않았습니다. 종료 코드: {exit_code}"
            )
            return

        # pressure_database.py는 내부 예외를 출력한 뒤 종료 코드 0으로 끝날 수 있으므로
        # 출력에 명시적인 오류가 있으면 성공으로 처리하지 않는다.
        if re.search(r"(?m)^\s*\[ERROR\]", self.registration_process_output):
            error_lines = [
                line.strip()
                for line in self.registration_process_output.splitlines()
                if line.strip().startswith("[ERROR]")
            ]
            detail = error_lines[-1] if error_lines else "외부 처리 과정에서 오류가 발생했습니다."
            self._registration_failed(f"{stage_name} 실패: {detail}")
            return

        if stage == "pressure":
            record = self.pending_registration_record or {}
            user_id = record.get("user_id", "")
            after_count = self._count_pressure_samples_for_user(user_id)
            try:
                after_database_mtime_ns = os.stat(
                    PRESSURE_DATABASE_FILE
                ).st_mtime_ns
            except OSError:
                after_database_mtime_ns = None

            if after_count <= 0:
                self._registration_failed(
                    "체압 데이터가 pressure_database.csv에 저장되지 않았습니다."
                )
                return

            before_mtime = self.registration_before_database_mtime_ns
            if (
                before_mtime is not None
                and after_database_mtime_ns is not None
                and after_database_mtime_ns <= before_mtime
            ):
                self._registration_failed(
                    "체압 측정 후 pressure_database.csv가 갱신되지 않았습니다."
                )
                return

            self._start_user_model_training()
            return

        if stage == "training":
            if not self._model_files_were_updated():
                self._registration_failed("재학습 후 user_model.pkl 또는 user_scaler.pkl이 갱신되지 않았습니다.")
                return

            registered_user_id = (self.pending_registration_record or {}).get("user_id", "")
            if not user_model_contains_user_id(USER_MODEL_FILE, registered_user_id):
                self._registration_failed(
                    "갱신된 user_model.pkl의 classes_에 방금 등록한 사용자 ID가 없습니다. "
                    "svm_model.pkl이 아니라 사용자용 train_user_model.py와 "
                    "pressure_database.csv를 확인해주세요."
                )
                return

            self._close_pressure_prediction_service()
            self.registration_progress_window.set_success()
            self.registration_pipeline_running = False
            QTimer.singleShot(1200, self._finish_user_registration_success)

    def _start_user_model_training(self):
        self.registration_progress_window.set_training()
        self.registration_old_model_mtimes = {}
        for path in (USER_MODEL_FILE, USER_SCALER_FILE):
            try:
                self.registration_old_model_mtimes[path] = os.stat(path).st_mtime_ns
            except OSError:
                self.registration_old_model_mtimes[path] = None

        self._start_registration_process(
            "training",
            TRAIN_USER_MODEL_SCRIPT,
            [],
        )

    def _model_files_were_updated(self):
        for path in (USER_MODEL_FILE, USER_SCALER_FILE):
            if not os.path.exists(path):
                return False
            old_mtime = self.registration_old_model_mtimes.get(path)
            if old_mtime is not None:
                try:
                    if os.stat(path).st_mtime_ns <= old_mtime:
                        return False
                except OSError:
                    return False
        return True

    def _registration_failed(self, message):
        process = self.registration_process
        # kill()로 finished 신호가 다시 들어와 중복 처리되지 않도록 상태부터 비운다.
        self.registration_process = None
        self.registration_stage = None
        self.registration_pipeline_running = False
        if process is not None and process.state() != QProcess.NotRunning:
            process.blockSignals(True)
            process.kill()
            process.waitForFinished(1000)
            process.deleteLater()
        self._close_pressure_prediction_service()
        print(f"신규 사용자 자동 인식 등록 실패: {message}")
        self._append_registration_log(f"[ERROR] {message}")
        self.registration_progress_window.set_error(message)
        self.stack.setCurrentWidget(self.registration_progress_window)

    def _finish_user_registration_success(self):
        record = self.pending_registration_record

        self.registration_stage = None
        self.registration_pipeline_running = False

        # 신규 사용자 등록이 끝나도 바로 액추에이터를 구동하거나
        # 대시보드로 넘어가지 않는다.
        # 등록은 user_profile.csv / pressure_database.csv / user_model.pkl 갱신까지만 담당하고,
        # 실제 시트 적용과 주행 시작은 사용자 목록에서 다시 해당 사용자를 선택했을 때 수행한다.
        if record is not None:
            print(
                "신규 사용자 등록 완료 / 사용자 목록으로 복귀: "
                f"user_id={record.get('user_id', '')}, "
                f"name={record.get('name', record.get('nickname', ''))}"
            )

        self.home_window.reload_profiles()
        self.drive_state = USER_SELECT
        self.home_window.update_mode_view(self.drive_state, self.current_user)
        self.show_user_list(show_add_card=True)

    def open_seat_setting_confirm(self, record, start_after_confirm=True, mode="new", hardware_event=None):
        self.hide_touch_keyboard()

        normalized_record = normalize_profile_record(record)

        if normalized_record is None:
            QMessageBox.warning(self, "사용자 오류", "사용자 정보를 불러올 수 없습니다.")
            self.show_user_list()
            return

        self.seat_confirm_window.prepare(
            normalized_record,
            start_after_confirm=start_after_confirm,
            mode=mode,
            hardware_event=hardware_event,
        )
        self.stack.setCurrentWidget(self.seat_confirm_window)

    def confirm_seat_setting(self, record, start_after_confirm=True):
        normalized_record = normalize_profile_record(record)

        if normalized_record is None:
            self.show_user_list()
            return

        if start_after_confirm:
            # 시트 확인 화면에 들어올 때 이미 하드웨어 명령을 보냈으므로
            # 확인 버튼에서는 주행 세션과 대시보드만 시작한다.
            self.start_drive_for_record(normalized_record, send_hardware=False)
        else:
            self.show_user_list(show_add_card=True)

    def open_seat_edit(self, user_name, start_after_confirm=True, return_to_confirm=False):
        self.hide_touch_keyboard()

        if self.drive_state == IDLE:
            QMessageBox.information(
                self,
                "시스템 대기 중",
                "S 버튼을 눌러 시스템을 시작한 뒤 시트 환경을 수정할 수 있습니다."
            )
            return

        if self.drive_state == DRIVE:
            QMessageBox.information(
                self,
                "수정 불가",
                "주행 분석 중에는 시트 환경을 수정할 수 없습니다.\nP 버튼을 눌러 안전모드로 전환한 뒤 수정해주세요."
            )
            return

        record = find_user_record_by_name(user_name)

        if record is None:
            QMessageBox.warning(self, "사용자 없음", "사용자 파일에서 해당 사용자를 찾을 수 없습니다.")
            self.show_user_list()
            return

        self.seat_edit_window.prepare(
            record,
            start_after_confirm=start_after_confirm,
            return_to_confirm_on_back=return_to_confirm
        )
        self.stack.setCurrentWidget(self.seat_edit_window)

    def update_existing_user_seat(self, user_id, seat_position, backrest_angle, start_after_confirm=True):
        updated_record = update_user_seat_profile_record(user_id, seat_position, backrest_angle)

        if updated_record is None:
            QMessageBox.warning(self, "수정 실패", "사용자 시트 환경을 수정하지 못했습니다.")
            self.show_user_list()
            return

        self.home_window.reload_profiles()
        self.home_window.update_mode_view(self.drive_state, self.current_user)

        # 현재 주행 세션의 사용자와 같은 경우, 이후 로그에 반영될 시트 환경도 갱신한다.
        if self.current_user_id == updated_record.get("user_id", "") and self.session.active_segment is not None:
            self.session.active_segment["seat_env"] = updated_record.get("seat_env", "")

        # 시트 환경 수정은 값만 저장한다.
        # 여기서 액추에이터를 구동하거나 대시보드로 들어가지 않고,
        # 다시 사용자 목록으로 돌아가 사용자를 선택하도록 한다.
        QMessageBox.information(self, "수정 완료", "시트 환경이 저장되었습니다.\n사용자를 다시 선택하면 시트가 적용됩니다.")
        self.show_user_list(show_add_card=True)
        print(f"시트 환경 수정 완료: user_id={updated_record.get('user_id', '')}, name={updated_record.get('name', '')}")

    def get_user_hardware_event(self, record):
        """현재 사용자 상태를 기준으로 하드웨어 이벤트 이름을 결정한다."""

        normalized_record = normalize_profile_record(record)
        if normalized_record is None:
            return "USER_SELECTED"

        next_user_id = str(normalized_record.get("user_id", "")).strip()

        if self.current_user is None:
            return "USER_SELECTED"

        if str(self.current_user_id).strip() == next_user_id:
            return "USER_RESUMED"

        return "USER_CHANGED"

    def start_drive_for_record(self, record, hardware_event=None, send_hardware=True):
        """
        시트 환경 확인이 끝난 뒤 실제 주행 세션과 대시보드를 시작한다.
        send_hardware=False이면 확인 화면 진입 시 이미 액추에이터 명령을 보낸 것으로 본다.
        """

        normalized_record = normalize_profile_record(record)

        if normalized_record is None:
            self.show_user_list()
            return

        previous_user = self.current_user
        previous_user_id = self.current_user_id

        self.current_user = normalized_record["name"]
        self.current_user_id = normalized_record["user_id"]

        self.session.start_or_resume_user(self.current_user)

        if hardware_event is None:
            hardware_event = self.get_user_hardware_event(normalized_record)

        if previous_user is None:
            print(f"사용자 선택: {self.current_user} / {self.current_user_id}")
        elif str(previous_user_id).strip() == str(self.current_user_id).strip():
            print(f"동일 사용자 유지: {self.current_user} / {self.current_user_id}")
        else:
            print(f"사용자 변경: {previous_user} → {self.current_user}")

        if send_hardware:
            send_user_id_to_hardware(self.current_user_id, self.current_user, event=hardware_event)

        self.drive_state = DRIVE

        self.dashboard_window.start_analysis(self.current_user)
        self.stack.setCurrentWidget(self.dashboard_window)

        print("상태 변경: DRIVE")

    def select_user(self, user_name):
        self.hide_touch_keyboard()

        """
        사용자 프로필 클릭, 자동 식별 확정, 사용자 목록 보기 후 선택 시 실행.
        어떤 경로에서 사용자를 선택하더라도 바로 DRIVE로 진입하지 않고,
        먼저 액추에이터 적용 명령을 보낸 뒤 시트 환경 확인 화면을 거친다.
        """

        if self.drive_state == IDLE:
            QMessageBox.information(
                self,
                "시스템 대기 중",
                "S 버튼을 눌러 시스템을 시작한 뒤 사용자를 선택하세요."
            )
            return

        if self.drive_state not in [USER_SELECT, PARK_SAFE]:
            return

        record = find_user_record_by_name(user_name)

        if record is None:
            QMessageBox.warning(
                self,
                "사용자 없음",
                "사용자 파일에서 해당 사용자를 찾을 수 없습니다."
            )
            self.show_user_list()
            return

        hardware_event = self.get_user_hardware_event(record)

        self.open_seat_setting_confirm(
            record,
            start_after_confirm=True,
            mode="select",
            hardware_event=hardware_event,
        )

        print(f"사용자 선택 대기: {record.get('name', '')} / {record.get('user_id', '')}")

    def enter_park_safe_state(self):
        self.hide_touch_keyboard()
        self.cancel_identification_measurement()

        """
        P 키 입력.
        주행 분석 일시정지 → 하드웨어 기준 위치 복귀 명령 전송 → 주차 대기 화면으로 전환.
        이후 다시 S 버튼을 누르면 새로 앉은 사람의 체압을 측정해 자동 사용자 식별을 시작한다.
        """

        if self.drive_state != DRIVE:
            print("P 입력 무시: DRIVE 상태가 아닙니다.")
            return

        self.drive_state = PARK_SAFE

        self.dashboard_window.pause_analysis()
        self.session.pause()

        # 팀원 hardware_bridge.py와 연동되는 부분.
        # PARK_SAFE 이벤트가 hardware_command.csv에 기록되면
        # 브릿지가 Arduino의 기준 위치 복귀 명령을 보내 시트/등받이를 복귀시키고,
        # 마지막 적용 사용자 상태를 비운다.
        send_hardware_event(
            event="PARK_SAFE",
            user_id=self.current_user_id or "",
            user_name=self.current_user or "",
        )

        # 주차 상태에서는 최초 시작 전과 같은 검은 대기 화면만 표시한다.
        # 세션은 종료하지 않으므로 E 버튼을 누르면 리포트가 생성되고,
        # S 버튼을 누르면 사용자 목록이 아니라 자동 식별 흐름을 다시 시작한다.
        self.home_window.update_mode_view(self.drive_state, self.current_user)
        self.turn_display_off()
        self.stack.setCurrentWidget(self.screen_off_window)

        print("상태 변경: PARK_SAFE / 기준 위치 복귀 명령 전송 / 주차 대기 화면")

    def enter_report_state(self):
        self.hide_touch_keyboard()
        self.cancel_identification_measurement()

        """
        E 키 입력.
        전체 운전 세션 종료 → 리포트 생성.
        """

        if self.drive_state not in [DRIVE, PARK_SAFE]:
            print("E 입력 무시: 종료할 주행 세션이 없습니다.")
            return

        send_hardware_event(
            event="SESSION_END",
            user_id=self.current_user_id or "",
            user_name=self.current_user or "",
        )

        self.drive_state = REPORT

        self.dashboard_window.pause_analysis()
        self.session.finish()

        log_path = self.session.save_csv_log()
        if log_path is not None:
            print(f"주행 로그 저장 완료: {log_path}")
        else:
            print("저장할 주행 로그가 없습니다.")

        summaries = self.session.get_summaries()
        self.report_window.set_report_data_from_session(summaries)

        self.turn_display_on()
        self.stack.setCurrentWidget(self.report_window)

        print("상태 변경: REPORT")

    def reset_to_user_select(self):
        """
        리포트 화면에서 홈으로 버튼을 눌렀을 때.
        새 운전 세션을 시작할 준비 상태로 돌아감.
        """

        self.drive_state = USER_SELECT
        self.current_user = None
        self.current_user_id = None
        self.session = DriveSession()

        self.turn_display_on()
        self.home_window.update_mode_view(self.drive_state, self.current_user)
        self.dashboard_window.graph_widget.reset_scores()
        self.dashboard_window.score_label.setText("-")
        self.dashboard_window.state_label.setText("대기 중")
        self.stack.setCurrentIndex(0)

        print("새 세션 준비")

    def closeEvent(self, event):
        process = self.registration_process
        if process is not None and process.state() != QProcess.NotRunning:
            process.blockSignals(True)
            process.kill()
            process.waitForFinished(1000)

        self._close_pressure_prediction_service()
        super().closeEvent(event)

    def enter_screen_off_state(self):
        """
        필요하면 나중에 일정 시간 미사용 후 화면 꺼짐 상태로 보낼 때 사용할 함수.
        """

        if self.drive_state == DRIVE:
            return

        self.drive_state = IDLE
        self.current_user = None
        self.current_user_id = None
        self.session = DriveSession()
        self.home_window.update_mode_view(self.drive_state, self.current_user)
        self.turn_display_off()
        self.stack.setCurrentWidget(self.screen_off_window)
        print("상태 변경: IDLE / 화면 꺼짐")


if __name__ == "__main__":
    # 일부 Raspberry Pi/Wayland 환경에서는 Touch 이벤트가 QPushButton의
    # MouseButtonPress로 자동 변환되지 않을 수 있다.
    # 터치 전용 버튼 처리와 함께 mouse synthesis fallback도 명시적으로 켠다.
    try:
        QApplication.setAttribute(Qt.AA_SynthesizeMouseForUnhandledTouchEvents, True)
    except Exception:
        pass

    app = QApplication(sys.argv)

    window = MainWindow()

    if USE_TOUCH_DISPLAY_FULLSCREEN:
        window.showFullScreen()
    else:
        window.show()

    sys.exit(app.exec_())
