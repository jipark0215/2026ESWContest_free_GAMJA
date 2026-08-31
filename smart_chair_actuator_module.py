from __future__ import annotations

from pathlib import Path
import math
import time
import os
from typing import Callable

import pandas as pd
import serial
from serial import SerialException


# =========================================================
# 1. 최종 파일 구조
# =========================================================
#
# user_profile.csv
#   user_id,nickname,seat_position,backrest_angle
#   - UI/사용자 설정 담당 코드가 작성·수정
#
# pressure_database.csv
#   user_id,sensor1,...,sensor16
#   - 체압 측정/SVM 담당 코드가 작성·사용
#   - 이 코드는 직접 읽거나 수정하지 않음
#
# actuator_profile.csv
#   user_id,seat_time,backrest_time
#   - 이 코드가 생성·갱신
#   - Arduino 전송 시 이 파일만 조회
#
# 세 파일은 user_id로 연결된다.
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

USER_PROFILE_CSV_PATH = BASE_DIR / "user_profile.csv"
ACTUATOR_PROFILE_CSV_PATH = BASE_DIR / "actuator_profile.csv"

# pressure_database.csv는 다른 담당 코드가 사용한다.
# 이 모듈은 SVM/UI가 확정해서 넘긴 user_id만 입력받는다.


# =========================================================
# 2. Arduino 시리얼 통신 설정
# =========================================================

# Windows 예시: "COM5"
# Raspberry Pi 예시: "/dev/ttyACM0" 또는 "/dev/ttyUSB0"
ACTUATOR_PORT = os.environ.get("SEAT_ID_ACTUATOR_PORT", "/dev/ttyUSB0")

BAUDRATE = 115200
SERIAL_TIMEOUT_SEC = 0.2

# 액추에이터는 부하와 전원 상태에 따라 명목 속도보다 느려질 수 있다.
# 그러나 이동 로그만으로 완료를 추정하면 실제로는 멈췄는데도 성공으로
# 기록될 수 있다. 반드시 Arduino의 명시적인 DONE을 받아야 완료로 인정한다.
ACTUATOR_DONE_TIMEOUT_MIN_SEC = 30.0
ACTUATOR_DONE_TIMEOUT_SCALE = 2.0
ACTUATOR_DONE_TIMEOUT_GRACE_SEC = 10.0
# 제공된 smart_chair_arduino_2.ino는 RESET을 정식 지원한다.
# APPLY,0,0은 사용자 적용 시퀀스이므로 기준 복귀 명령으로 대체하지 않는다.
ACTUATOR_RESET_COMMAND_MODE = os.environ.get(
    "SEAT_ID_ACTUATOR_RESET_COMMAND", "RESET"
).strip().upper()
# 명령 전송 후 아무 바이트도 오지 않으면 긴 동작 완료 시간을 모두 기다리지 않고
# 포트를 재연결해 한 번 재시도한다.
ACTUATOR_INITIAL_REPLY_TIMEOUT_SEC = 4.0
ACTUATOR_EXPECTED_FIRMWARE = "SEAT_ID_ACTUATOR_R7"
ACTUATOR_VERIFY_FIRMWARE = os.environ.get(
    "SEAT_ID_VERIFY_ACTUATOR_FIRMWARE", "1"
).strip().lower() not in {"0", "false", "no", "off"}

ACTUATOR_COMPLETION_REPLIES = {
    "DONE",
    "OK",
    "COMPLETE",
    "COMPLETED",
    "APPLY_DONE",
    "RESET_DONE",
}


class ActuatorNoResponseError(TimeoutError):
    """명령 전송 후 Arduino가 어떤 응답도 보내지 않았을 때 발생한다."""


def _safe_reset_input_buffer(connection: serial.Serial) -> None:
    """USB 허브의 일시적인 flush 오류가 제어 프로세스를 죽이지 않게 한다."""

    try:
        connection.reset_input_buffer()
    except (SerialException, OSError) as exc:
        print(f"[WARN] 액추에이터 입력 버퍼 초기화 생략: {exc}")


# =========================================================
# 3. 하드웨어·기어 사양
#
# 나중에 실제 스펙이 바뀌면 우선 이 구역의 값만 수정한다.
# 변환 함수와 CSV 처리 코드는 그대로 사용할 수 있다.
# =========================================================

# ---------- 시트 위치 조절용 리니어 액추에이터 ----------

# 첨부한 제품 사양: DC 12 V, 속도 15 mm/s, 추력 64 N, 스트로크 100 mm
SEAT_STROKE_MM = 100.0
SEAT_RATED_FORCE_N = 64.0
SEAT_EXTEND_SPEED_MM_S = 15.0
SEAT_RETRACT_SPEED_MM_S = 15.0

# 100 mm 스트로크의 중앙인 50 mm 확장 상태를
# seat_position = 0 mm인 물리적 기준 위치로 정의한다.
SEAT_REFERENCE_EXTENSION_MM = 50.0

# 등받이 90~130도 범위와 함께 사용할 때의 시트 안전 범위.
# 기준점 대비 -20~+20 mm만 허용한다.
SEAT_END_MARGIN_MM = 5.0
SEAT_SAFE_MIN_POSITION_MM = -20.0
SEAT_SAFE_MAX_POSITION_MM = 20.0


# ---------- 등받이 각도 조절용 리니어 액추에이터 ----------

# 첨부한 제품 사양: DC 12 V, 속도 15 mm/s, 추력 64 N, 스트로크 50 mm
BACKREST_STROKE_MM = 50.0
BACKREST_RATED_FORCE_N = 64.0
BACKREST_EXTEND_SPEED_MM_S = 15.0
BACKREST_RETRACT_SPEED_MM_S = 15.0

# 50 mm 스트로크의 중앙인 25 mm 확장 상태를
# 등받이 기준 각도에서의 물리적 기준 위치로 정의한다.
BACKREST_REFERENCE_EXTENSION_MM = 25.0
BACKREST_END_MARGIN_MM = 0.5


# ---------- 랙·피니언 ----------

PINION_DIAMETER_MM = 25.0
RACK_LENGTH_MM = 60.0

# 등받이 기준 각도
BACKREST_REFERENCE_ANGLE_DEG = 110.0

# 구조물에서 사용하기로 한 등받이 각도 범위.
# 중앙 스트로크를 사용하므로 필요할 경우 나중에 90도 미만도 설정할 수 있지만,
# 실제 구조물 간섭을 확인하기 전에는 기존 90~130도 범위를 유지한다.
BACKREST_SAFE_MIN_ANGLE_DEG = 90.0
BACKREST_SAFE_MAX_ANGLE_DEG = 130.0

# +1: 등받이 각도가 커질수록 액추에이터 확장
# -1: 등받이 각도가 커질수록 액추에이터 수축
BACKREST_DIRECTION_SIGN = -1.0


# =========================================================
# 4. 거리 → 구동시간 공통 변환
# =========================================================

def distance_to_signed_time_s(
    distance_mm: float,
    extend_speed_mm_s: float,
    retract_speed_mm_s: float,
) -> float:
    """
    이동거리(mm)를 부호가 있는 구동시간(s)으로 변환한다.

    반환값이 양수이면 확장 방향,
    음수이면 수축 방향이다.
    """

    if extend_speed_mm_s <= 0 or retract_speed_mm_s <= 0:
        raise ValueError("액추에이터 속도는 0보다 커야 합니다.")

    if distance_mm >= 0:
        return distance_mm / extend_speed_mm_s

    return distance_mm / retract_speed_mm_s


# =========================================================
# 5. 시트 위치 → seat_time
# =========================================================

def seat_position_to_time_s(
    seat_position_mm: float,
) -> float:
    """
    user_profile.csv의 seat_position 값을
    기준 위치로부터의 시트 목표시간으로 변환한다.
    """

    seat_position_mm = float(seat_position_mm)

    if not (
        SEAT_SAFE_MIN_POSITION_MM
        <= seat_position_mm
        <= SEAT_SAFE_MAX_POSITION_MM
    ):
        raise ValueError(
            f"시트 위치 {seat_position_mm} mm가 안전 범위 "
            f"{SEAT_SAFE_MIN_POSITION_MM}~"
            f"{SEAT_SAFE_MAX_POSITION_MM} mm를 벗어났습니다."
        )

    target_extension_mm = (
        SEAT_REFERENCE_EXTENSION_MM
        + seat_position_mm
    )

    if not 0.0 <= target_extension_mm <= SEAT_STROKE_MM:
        raise ValueError(
            "계산된 시트 액추에이터 확장 길이가 "
            "실제 스트로크 범위를 벗어났습니다."
        )

    return distance_to_signed_time_s(
        distance_mm=seat_position_mm,
        extend_speed_mm_s=SEAT_EXTEND_SPEED_MM_S,
        retract_speed_mm_s=SEAT_RETRACT_SPEED_MM_S,
    )


# =========================================================
# 6. 등받이 각도 → 랙 이동거리 → backrest_time
# =========================================================

def backrest_angle_to_rack_distance_mm(
    backrest_angle_deg: float,
) -> float:
    """
    등받이 목표 각도를 랙의 직선 이동거리(mm)로 변환한다.

    랙 이동거리
    = π × 피니언 지름 × 기준각과의 차이 / 360
    """

    backrest_angle_deg = float(backrest_angle_deg)

    if not (
        BACKREST_SAFE_MIN_ANGLE_DEG
        <= backrest_angle_deg
        <= BACKREST_SAFE_MAX_ANGLE_DEG
    ):
        raise ValueError(
            f"등받이 각도 {backrest_angle_deg}°가 안전 범위 "
            f"{BACKREST_SAFE_MIN_ANGLE_DEG}~"
            f"{BACKREST_SAFE_MAX_ANGLE_DEG}°를 벗어났습니다."
        )

    angle_difference_deg = (
        backrest_angle_deg
        - BACKREST_REFERENCE_ANGLE_DEG
    )

    rack_distance_mm = (
        math.pi
        * PINION_DIAMETER_MM
        * angle_difference_deg
        / 360.0
    )

    return BACKREST_DIRECTION_SIGN * rack_distance_mm


def backrest_angle_to_time_s(
    backrest_angle_deg: float,
) -> float:
    """
    등받이 각도를 랙 이동거리로 바꾸고,
    그 거리를 액추에이터 구동시간으로 변환한다.
    """

    rack_distance_mm = backrest_angle_to_rack_distance_mm(
        backrest_angle_deg
    )

    target_extension_mm = (
        BACKREST_REFERENCE_EXTENSION_MM
        + rack_distance_mm
    )

    available_travel_mm = min(
        BACKREST_STROKE_MM,
        RACK_LENGTH_MM,
    )

    minimum_extension_mm = BACKREST_END_MARGIN_MM
    maximum_extension_mm = available_travel_mm - BACKREST_END_MARGIN_MM

    if not minimum_extension_mm <= target_extension_mm <= maximum_extension_mm:
        raise ValueError(
            "계산된 등받이 액추에이터 확장 길이가 안전 범위를 벗어났습니다. "
            f"계산값={target_extension_mm:.3f} mm, "
            f"허용값={minimum_extension_mm:.3f}~{maximum_extension_mm:.3f} mm"
        )

    return distance_to_signed_time_s(
        distance_mm=rack_distance_mm,
        extend_speed_mm_s=BACKREST_EXTEND_SPEED_MM_S,
        retract_speed_mm_s=BACKREST_RETRACT_SPEED_MM_S,
    )


def validate_combined_target(
    seat_position_mm: float,
    backrest_angle_deg: float,
) -> None:
    """
    시트 이동 보상과 등받이 각도 조절을 모두 반영한
    등받이 액추에이터의 최종 확장 길이를 검사한다.

    시트가 앞으로 이동하면 등받이 액추에이터는 같은 거리만큼 수축하고,
    시트가 뒤로 이동하면 같은 거리만큼 확장한다.
    """

    seat_position_mm = float(seat_position_mm)
    rack_distance_mm = backrest_angle_to_rack_distance_mm(
        backrest_angle_deg
    )

    final_backrest_extension_mm = (
        BACKREST_REFERENCE_EXTENSION_MM
        - seat_position_mm
        + rack_distance_mm
    )

    minimum_extension_mm = BACKREST_END_MARGIN_MM
    maximum_extension_mm = (
        min(BACKREST_STROKE_MM, RACK_LENGTH_MM)
        - BACKREST_END_MARGIN_MM
    )

    if not (
        minimum_extension_mm
        <= final_backrest_extension_mm
        <= maximum_extension_mm
    ):
        raise ValueError(
            "시트 위치와 등받이 각도의 조합이 등받이 액추에이터 "
            "안전 범위를 벗어났습니다. "
            f"계산값={final_backrest_extension_mm:.3f} mm, "
            f"허용값={minimum_extension_mm:.3f}~"
            f"{maximum_extension_mm:.3f} mm"
        )


# =========================================================
# 7. CSV 공통 처리
# =========================================================

def _read_csv_and_validate(
    csv_path: Path,
    required_columns: set[str],
) -> pd.DataFrame:
    """
    CSV 존재 여부, 필수 열, user_id 형식과 중복을 검사한다.
    """

    if not csv_path.exists():
        raise FileNotFoundError(
            f"CSV 파일이 없습니다: {csv_path}"
        )

    data = pd.read_csv(csv_path)

    missing_columns = required_columns - set(data.columns)

    if missing_columns:
        raise ValueError(
            f"{csv_path.name}에 필요한 열이 없습니다: "
            + ", ".join(sorted(missing_columns))
        )

    converted_user_ids = pd.to_numeric(
        data["user_id"],
        errors="coerce",
    )

    if converted_user_ids.isna().any():
        raise ValueError(
            f"{csv_path.name}의 user_id에 숫자가 아닌 값이 있습니다."
        )

    data["user_id"] = converted_user_ids.astype(int)

    if data["user_id"].duplicated().any():
        duplicated_ids = data.loc[
            data["user_id"].duplicated(keep=False),
            "user_id",
        ].tolist()

        raise ValueError(
            f"{csv_path.name}에 중복 user_id가 있습니다: "
            f"{duplicated_ids}"
        )

    return data


def _atomic_save_csv(
    data: pd.DataFrame,
    csv_path: Path,
) -> None:
    """
    임시 파일에 먼저 저장한 뒤 원본 파일을 교체한다.
    """

    temporary_path = csv_path.with_suffix(".tmp.csv")

    data.to_csv(
        temporary_path,
        index=False,
        encoding="utf-8-sig",
    )

    temporary_path.replace(csv_path)


# =========================================================
# 8. 사용자 한 명의 최신 설정을 초 데이터로 계산
# =========================================================

def calculate_user_actuator_times(
    user_id: int,
    user_profile_csv_path: Path = USER_PROFILE_CSV_PATH,
) -> tuple[float, float]:
    """
    user_profile.csv에서 해당 user_id의 최신 설정을 읽고
    seat_time, backrest_time을 계산해서 반환한다.

    이 함수는 아직 actuator_profile.csv를 수정하지 않는다.
    """

    user_id = int(user_id)

    profiles = _read_csv_and_validate(
        user_profile_csv_path,
        {
            "user_id",
            "nickname",
            "seat_position",
            "backrest_angle",
        },
    )

    matched = profiles[
        profiles["user_id"] == user_id
    ]

    if matched.empty:
        raise ValueError(
            f"사용자 {user_id}가 "
            f"{user_profile_csv_path.name}에 없습니다."
        )

    profile = matched.iloc[0]

    seat_time_s = seat_position_to_time_s(
        profile["seat_position"]
    )

    backrest_time_s = backrest_angle_to_time_s(
        profile["backrest_angle"]
    )

    validate_combined_target(
        profile["seat_position"],
        profile["backrest_angle"],
    )

    return (
        round(seat_time_s, 6),
        round(backrest_time_s, 6),
    )


# =========================================================
# 9. 모든 사용자의 actuator_profile.csv 생성·전체 동기화
# =========================================================

def sync_all_actuator_profiles(
    user_profile_csv_path: Path = USER_PROFILE_CSV_PATH,
    actuator_profile_csv_path: Path = ACTUATOR_PROFILE_CSV_PATH,
) -> pd.DataFrame:
    """
    user_profile.csv의 모든 사용자 설정을 읽어
    actuator_profile.csv를 전체 생성 또는 갱신한다.

    actuator_profile.csv에는 정확히 다음 열만 저장한다.
        user_id
        seat_time
        backrest_time
    """

    profiles = _read_csv_and_validate(
        user_profile_csv_path,
        {
            "user_id",
            "nickname",
            "seat_position",
            "backrest_angle",
        },
    )

    rows: list[dict[str, float | int]] = []

    for _, profile in profiles.iterrows():
        user_id = int(profile["user_id"])

        seat_time_s = round(
            seat_position_to_time_s(
                profile["seat_position"]
            ),
            6,
        )

        backrest_time_s = round(
            backrest_angle_to_time_s(
                profile["backrest_angle"]
            ),
            6,
        )

        validate_combined_target(
            profile["seat_position"],
            profile["backrest_angle"],
        )

        rows.append(
            {
                "user_id": user_id,
                "seat_time": seat_time_s,
                "backrest_time": backrest_time_s,
            }
        )

    actuator_profiles = pd.DataFrame(
        rows,
        columns=[
            "user_id",
            "seat_time",
            "backrest_time",
        ],
    )

    actuator_profiles = actuator_profiles.sort_values(
        "user_id"
    ).reset_index(drop=True)

    _atomic_save_csv(
        actuator_profiles,
        actuator_profile_csv_path,
    )

    print(
        "\n[SYNC] actuator_profile.csv 전체 동기화 완료"
    )
    print(actuator_profiles.to_string(index=False))

    return actuator_profiles


# =========================================================
# 10. 신규 등록·설정 변경 사용자 한 명만 추가 또는 덮어쓰기
# =========================================================

def update_user_actuator_profile(
    user_id: int,
    user_profile_csv_path: Path = USER_PROFILE_CSV_PATH,
    actuator_profile_csv_path: Path = ACTUATOR_PROFILE_CSV_PATH,
) -> dict[str, float | int]:
    """
    UI 담당 코드가 user_profile.csv에 신규 사용자 또는
    수정된 사용자 설정을 저장한 직후 호출한다.

    같은 user_id가 actuator_profile.csv에 있으면
    기존 seat_time, backrest_time을 새 값으로 덮어쓴다.

    같은 user_id가 없으면 새 행으로 추가한다.
    """

    user_id = int(user_id)

    seat_time_s, backrest_time_s = (
        calculate_user_actuator_times(
            user_id=user_id,
            user_profile_csv_path=user_profile_csv_path,
        )
    )

    new_row = pd.DataFrame(
        [
            {
                "user_id": user_id,
                "seat_time": seat_time_s,
                "backrest_time": backrest_time_s,
            }
        ]
    )

    if actuator_profile_csv_path.exists():
        actuator_profiles = _read_csv_and_validate(
            actuator_profile_csv_path,
            {
                "user_id",
                "seat_time",
                "backrest_time",
            },
        )

        # 기존 같은 user_id 행 제거
        actuator_profiles = actuator_profiles[
            actuator_profiles["user_id"] != user_id
        ]

        # 새 계산값 추가
        actuator_profiles = pd.concat(
            [actuator_profiles, new_row],
            ignore_index=True,
        )

    else:
        actuator_profiles = new_row

    # 위치·각도·닉네임은 저장하지 않고
    # 정확히 세 열만 남긴다.
    actuator_profiles = actuator_profiles[
        [
            "user_id",
            "seat_time",
            "backrest_time",
        ]
    ]

    actuator_profiles = actuator_profiles.sort_values(
        "user_id"
    ).reset_index(drop=True)

    _atomic_save_csv(
        actuator_profiles,
        actuator_profile_csv_path,
    )

    print(
        f"\n[UPDATE] 사용자 {user_id}의 액추에이터 시간값을 "
        "추가 또는 덮어썼습니다."
    )
    print(
        f"seat_time={seat_time_s}초, "
        f"backrest_time={backrest_time_s}초"
    )

    return {
        "user_id": user_id,
        "seat_time": seat_time_s,
        "backrest_time": backrest_time_s,
    }


# =========================================================
# 11. 확정된 user_id의 초 데이터 2개만 조회
# =========================================================

def load_user_actuator_times(
    user_id: int,
    actuator_profile_csv_path: Path = ACTUATOR_PROFILE_CSV_PATH,
) -> tuple[float, float]:
    """
    actuator_profile.csv에서 확정된 user_id를 찾고,
    seat_time과 backrest_time만 반환한다.

    이 단계에서는 user_profile.csv와 pressure_database.csv를
    읽지 않는다.
    """

    user_id = int(user_id)

    actuator_profiles = _read_csv_and_validate(
        actuator_profile_csv_path,
        {
            "user_id",
            "seat_time",
            "backrest_time",
        },
    )

    matched = actuator_profiles[
        actuator_profiles["user_id"] == user_id
    ]

    if matched.empty:
        raise ValueError(
            f"사용자 {user_id}의 시간 데이터가 "
            f"{actuator_profile_csv_path.name}에 없습니다."
        )

    row = matched.iloc[0]

    seat_time_s = float(row["seat_time"])
    backrest_time_s = float(row["backrest_time"])

    if not math.isfinite(seat_time_s):
        raise ValueError("seat_time 값이 올바르지 않습니다.")

    if not math.isfinite(backrest_time_s):
        raise ValueError("backrest_time 값이 올바르지 않습니다.")

    return seat_time_s, backrest_time_s


# =========================================================
# 12. Arduino 시리얼 통신
# =========================================================

def open_actuator_serial() -> serial.Serial:
    """
    액추에이터 제어용 Arduino와 연결한다.
    """

    try:
        connection = serial.Serial(
            port=ACTUATOR_PORT,
            baudrate=BAUDRATE,
            timeout=SERIAL_TIMEOUT_SEC,
        )

    except SerialException as exc:
        raise RuntimeError(
            f"액추에이터 Arduino 연결 실패: "
            f"{ACTUATOR_PORT}"
        ) from exc

    # USB 연결 직후 Arduino가 재시작되는 시간을 기다린다.
    time.sleep(2.0)

    _safe_reset_input_buffer(connection)

    print(
        f"[SERIAL] 액추에이터 Arduino 연결 완료: "
        f"{ACTUATOR_PORT}"
    )

    if ACTUATOR_VERIFY_FIRMWARE:
        try:
            verify_actuator_firmware(connection)
        except Exception:
            try:
                connection.close()
            except Exception:
                pass
            raise

    return connection


def verify_actuator_firmware(connection: serial.Serial) -> None:
    """
    PING 응답으로 실제 보드가 이번 제어 코드와 같은 펌웨어인지 확인한다.

    다른 Arduino나 구버전 펌웨어를 액추에이터 포트로 잡으면 모터 명령을
    보내기 전에 즉시 중단해 잘못된 장치 제어와 가짜 성공 판정을 막는다.
    """

    _safe_reset_input_buffer(connection)
    connection.write(b"PING\n")
    connection.flush()

    deadline = time.monotonic() + 2.5
    received: list[str] = []

    while time.monotonic() < deadline:
        raw = connection.readline()
        if not raw:
            continue

        reply = raw.decode("ascii", errors="ignore").strip()
        if not reply:
            continue

        received.append(reply)
        print(f"[ARDUINO] {reply}")
        if ACTUATOR_EXPECTED_FIRMWARE in reply.upper():
            print(f"[SERIAL] 펌웨어 확인 완료: {ACTUATOR_EXPECTED_FIRMWARE}")
            return

    detail = ", ".join(received) if received else "응답 없음"
    raise RuntimeError(
        "액추에이터 Arduino 펌웨어가 Python 제어 코드와 맞지 않습니다. "
        f"smart_chair_arduino_2.ino({ACTUATOR_EXPECTED_FIRMWARE})를 업로드한 뒤 "
        f"다시 실행하세요. 수신값: {detail}"
    )


def wait_for_done(
    connection: serial.Serial,
    expected_movement_time_s: float,
) -> None:
    """
    Arduino가 동작을 마치고 DONE을 보낼 때까지 기다린다.
    """

    expected_movement_time_s = max(0.0, float(expected_movement_time_s))
    started_at = time.monotonic()
    hard_timeout_s = max(
        ACTUATOR_DONE_TIMEOUT_MIN_SEC,
        expected_movement_time_s * ACTUATOR_DONE_TIMEOUT_SCALE
        + ACTUATOR_DONE_TIMEOUT_GRACE_SEC,
    )
    deadline = started_at + hard_timeout_s
    received_activity = False

    while time.monotonic() < deadline:
        raw = connection.readline()

        if not raw:
            now = time.monotonic()
            if (
                not received_activity
                and now - started_at >= ACTUATOR_INITIAL_REPLY_TIMEOUT_SEC
            ):
                connection.write(b"STOP\n")
                connection.flush()
                raise ActuatorNoResponseError(
                    f"Arduino가 명령 후 {ACTUATOR_INITIAL_REPLY_TIMEOUT_SEC:.1f}초 동안 "
                    "아무 응답도 보내지 않았습니다."
                )
            continue

        reply = raw.decode(
            "ascii",
            errors="ignore",
        ).strip()

        if not reply:
            continue

        received_activity = True
        print(f"[ARDUINO] {reply}")

        normalized_reply = reply.upper().strip()
        if (
            normalized_reply in ACTUATOR_COMPLETION_REPLIES
            or normalized_reply.endswith(" DONE")
        ):
            return

        if normalized_reply.startswith("ERROR"):
            raise RuntimeError(
                f"Arduino 오류: {reply}"
            )

    connection.write(b"STOP\n")
    connection.flush()

    raise TimeoutError(
        f"Arduino 완료 응답을 {hard_timeout_s:.1f}초 동안 받지 못해 "
        "STOP 명령을 전송했습니다."
    )


def send_user_actuator_profile(
    connection: serial.Serial,
    confirmed_user_id: int,
) -> bool:
    """
    SVM 예측 후 UI에서 확정되었거나,
    기존 사용자 목록에서 선택된 user_id를 입력받는다.

    actuator_profile.csv에서 해당 사용자의 초 데이터 2개만
    꺼내 Arduino로 전송한다.

    전송 형식:
        APPLY,시트목표시간ms,등받이목표시간ms

    Arduino는 코드 실행 전에 물리적으로 맞춰 둔
    시트 50 mm, 등받이 25 mm, 등받이 110도 상태를 기준점으로 사용한다.

    모든 APPLY에서 현재 등받이 각도를 110도로 되돌리고,
    시트와 등받이 보상 동작으로 기준 위치에 복귀한 뒤,
    시트 위치 조절과 등받이 각도 조절을 순차적으로 실행한다.
    """

    confirmed_user_id = int(confirmed_user_id)

    seat_time_s, backrest_time_s = (
        load_user_actuator_times(
            confirmed_user_id
        )
    )

    seat_target_ms = int(
        round(seat_time_s * 1000.0)
    )

    backrest_target_ms = int(
        round(backrest_time_s * 1000.0)
    )

    message = (
        f"APPLY,{seat_target_ms},{backrest_target_ms}\n"
    )

    _safe_reset_input_buffer(connection)
    connection.write(message.encode("ascii"))
    connection.flush()

    print(
        f"\n[SEND] 사용자 {confirmed_user_id} 시간값 전송"
    )
    print(
        f"seat_time={seat_time_s:.3f}초 "
        f"({seat_target_ms} ms)"
    )
    print(
        f"backrest_time={backrest_time_s:.3f}초 "
        f"({backrest_target_ms} ms)"
    )

    # 모든 APPLY는 기준점 복귀 후 사용자 목표 이동 순서로 동작한다.
    # 첫 APPLY에서는 현재 상태가 이미 기준점이므로 복귀 이동시간은 0이다.
    seat_max_target_s = max(
        abs(SEAT_SAFE_MIN_POSITION_MM),
        abs(SEAT_SAFE_MAX_POSITION_MM),
    ) / min(SEAT_EXTEND_SPEED_MM_S, SEAT_RETRACT_SPEED_MM_S)

    backrest_min_relative_mm = backrest_angle_to_rack_distance_mm(
        BACKREST_SAFE_MIN_ANGLE_DEG
    )
    backrest_max_relative_mm = backrest_angle_to_rack_distance_mm(
        BACKREST_SAFE_MAX_ANGLE_DEG
    )
    backrest_max_target_s = max(
        abs(backrest_min_relative_mm),
        abs(backrest_max_relative_mm),
    ) / min(BACKREST_EXTEND_SPEED_MM_S, BACKREST_RETRACT_SPEED_MM_S)

    user_change_s = (
        backrest_max_target_s
        + seat_max_target_s
        + seat_max_target_s
        + backrest_max_target_s
    )

    wait_for_done(
        connection,
        user_change_s,
    )

    return True


def reset_to_reference(
    connection: serial.Serial,
) -> None:
    """
    시트와 등받이를 기준 상태로 복귀시킨다.
    """

    _safe_reset_input_buffer(connection)
    if ACTUATOR_RESET_COMMAND_MODE not in {"RESET", "APPLY_ZERO"}:
        raise ValueError(
            "SEAT_ID_ACTUATOR_RESET_COMMAND는 RESET 또는 APPLY_ZERO여야 합니다."
        )

    if ACTUATOR_RESET_COMMAND_MODE == "APPLY_ZERO":
        print(
            "[WARN] 구버전 호환 모드 APPLY_ZERO를 사용합니다. "
            "권장값은 RESET입니다."
        )
        command = b"APPLY,0,0\n"
        command_name = "APPLY,0,0"
    else:
        command = b"RESET\n"
        command_name = "RESET"
    connection.write(command)
    connection.flush()

    print(f"[SEND] 기준 위치 복귀 명령 전송: {command_name}")

    # Arduino가 등받이와 시트를 순차 복귀시키므로 max가 아니라 합계를 쓴다.
    # 이전 코드는 복귀 예상시간을 짧게 계산해 정상 동작 중 STOP이 전송될 수 있었다.
    seat_reset_time_s = SEAT_STROKE_MM / min(
        SEAT_EXTEND_SPEED_MM_S,
        SEAT_RETRACT_SPEED_MM_S,
    )
    backrest_reset_time_s = BACKREST_STROKE_MM / min(
        BACKREST_EXTEND_SPEED_MM_S,
        BACKREST_RETRACT_SPEED_MM_S,
    )
    wait_for_done(
        connection,
        seat_reset_time_s + backrest_reset_time_s,
    )


def stop_actuators(
    connection: serial.Serial,
) -> None:
    """
    Arduino에 긴급 정지 명령을 전송한다.
    """

    connection.write(b"STOP\n")
    connection.flush()

    print("[SEND] 긴급 정지 명령 전송")


def set_physical_reference(
    connection: serial.Serial,
) -> None:
    """
    시험이나 복구 목적으로 현재 물리 위치를 기준점으로 강제 설정한다.
    정상 UI 실행에서는 시작 전에 물리 기준 위치를 맞춰 두므로 사용하지 않는다.

    Arduino 테스트 코드에서는 SET_REFERENCE가 DONE을 보내지 않고
    REFERENCE_SET만 보낼 수 있으므로, DONE을 강제로 기다리지 않는다.
    """

    _safe_reset_input_buffer(connection)
    connection.write(b"SET_REFERENCE\n")
    connection.flush()

    print("[SEND] 기준 위치 설정 명령 전송")

    deadline = time.monotonic() + 2.0
    got_reply = False

    while time.monotonic() < deadline:
        raw = connection.readline()

        if not raw:
            continue

        reply = raw.decode(
            "ascii",
            errors="ignore",
        ).strip()

        if not reply:
            continue

        got_reply = True
        print(f"[ARDUINO] {reply}")

        if reply in {"REFERENCE_SET", "DONE"}:
            return

        if reply.startswith("ERROR"):
            raise RuntimeError(
                f"Arduino 오류: {reply}"
            )

    if not got_reply:
        print("[WARN] SET_REFERENCE 응답이 없었습니다. Arduino 코드에 따라 정상일 수 있습니다.")


# =========================================================
# 13. 체압/SVM/UI 코드가 나중에 호출할 연결용 클래스
# =========================================================

class UserSeatApplier:
    """
    다른 담당 코드가 확정한 user_id를 전달받아
    해당 사용자의 액추에이터 시간값을 적용한다.

    같은 사용자가 연속 인식되었을 때는 명령을 반복하지 않는다.
    시작 전에 맞춰 둔 물리 기준 위치를 Arduino의 기준점으로 사용한다.
    다른 사용자 또는 수정된 설정을 적용할 때는 기준 위치 복귀 후
    새 목표 이동을 자동으로 수행한다.
    """

    def __init__(
        self,
        connection: serial.Serial,
    ) -> None:
        self.connection = connection
        self.last_applied_user_id: int | None = None
        # 시작 시 물리 기준점을 수동으로 맞춘다는 기존 전제를 유지한다.
        self.at_reference = True

    def _reconnect(self) -> None:
        """허브/Arduino가 명령에 무응답이면 같은 설정 포트로 다시 연결한다."""

        try:
            if self.connection is not None and self.connection.is_open:
                self.connection.close()
        except Exception:
            pass
        time.sleep(0.5)
        self.connection = open_actuator_serial()
        print("[RECOVER] 액추에이터 시리얼 재연결 완료")

    def _run_with_no_response_retry(self, label: str, operation: Callable[[serial.Serial], None]) -> None:
        try:
            operation(self.connection)
        except (ActuatorNoResponseError, SerialException) as exc:
            print(f"[RECOVER] {label} 중 통신 무응답: {exc}")
            print("[RECOVER] 포트를 다시 연결하고 명령을 한 번 재시도합니다.")
            self._reconnect()
            operation(self.connection)

    def apply_user(
        self,
        confirmed_user_id: int,
        force: bool = False,
    ) -> bool:
        """
        SVM 결과를 UI에서 '예'로 확정했거나,
        기존 사용자 목록에서 선택했을 때 호출한다.
        """

        confirmed_user_id = int(confirmed_user_id)

        if (
            not force
            and confirmed_user_id
            == self.last_applied_user_id
        ):
            return False

        self._run_with_no_response_retry(
            f"사용자 {confirmed_user_id} 적용",
            lambda connection: send_user_actuator_profile(
                connection=connection,
                confirmed_user_id=confirmed_user_id,
            ),
        )

        self.last_applied_user_id = confirmed_user_id
        seat_time_s, backrest_time_s = load_user_actuator_times(confirmed_user_id)
        self.at_reference = (
            abs(seat_time_s) < 0.0005 and abs(backrest_time_s) < 0.0005
        )
        return True

    def update_profile_and_apply(
        self,
        user_id: int,
    ) -> bool:
        """
        신규 등록 또는 기존 사용자의 설정 수정 직후 호출한다.

        1. user_profile.csv의 최신 위치·각도를 시간으로 변환
        2. actuator_profile.csv에 추가 또는 덮어쓰기
        3. 같은 사용자가 이미 적용된 상태여도 강제로 새 설정 전송
        """

        update_user_actuator_profile(user_id)

        return self.apply_user(
            confirmed_user_id=user_id,
            force=True,
        )

    def reset_to_reference_and_clear_user(self) -> None:
        """
        P 주차 안전모드 또는 운전 종료 시 호출한다.

        Arduino에 RESET을 보내 기준 위치 복귀가 끝날 때까지 기다린 뒤,
        마지막 적용 사용자 ID를 비운다. 따라서 주차 후 같은 사용자가
        다시 확정되어도 사용자 설정을 새로 적용할 수 있다.

        last_applied_user_id가 None이어도 RESET을 전송한다.
        브릿지가 재시작된 경우처럼 Python의 사용자 상태와 Arduino의
        실제 위치가 다를 수 있는 상황에서도 P 입력 시 복귀를 보장하기 위함이다.
        """

        try:
            if self.at_reference and self.last_applied_user_id is None:
                print("[SKIP] 이미 기준 위치이며 적용 사용자도 없어 중복 복귀를 생략합니다.")
                return
            self._run_with_no_response_retry(
                "기준 위치 복귀",
                reset_to_reference,
            )
            self.at_reference = True
        finally:
            # 복귀 응답이 유실되더라도 다음 사용자 명령을 동일 사용자로 오인해
            # 건너뛰지 않도록 Python 쪽 적용 상태는 반드시 초기화한다.
            self.last_applied_user_id = None

    def seat_became_empty(self) -> None:
        """
        기존 호출부와의 호환을 위한 메서드.
        사용자가 일어났을 때도 기준 위치 복귀 후 사용자 상태를 비운다.
        """

        self.reset_to_reference_and_clear_user()


# =========================================================
# 14. 단독 실행
# =========================================================

def main() -> None:
    """
    다른 팀원 코드와 연결하기 전 단독 실행용.

    현재는 user_profile.csv의 사용자 1, 2, 3을 읽어
    actuator_profile.csv를 생성·전체 갱신한다.
    Arduino는 자동으로 움직이지 않는다.
    """

    sync_all_actuator_profiles()

    # Arduino 단독 시험 시 아래 주석을 해제한다.
    #
    # connection = open_actuator_serial()
    #
    # try:
    #     # 시험 전 실제 의자를 기준 상태에 맞춘 뒤 한 번 실행
    #     set_physical_reference(connection)
    #
    #     # 사용자 1의 초 데이터 전송
    #     send_user_actuator_profile(
    #         connection=connection,
    #         confirmed_user_id=1,
    #     )
    #
    #     # 기준 위치로 복귀
    #     reset_to_reference(connection)
    #
    # finally:
    #     if connection.is_open:
    #         connection.close()


if __name__ == "__main__":
    main()
