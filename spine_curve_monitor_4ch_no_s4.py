#!/usr/bin/env python3
"""HC-SR04 4개(S4 제외)로 등 중앙선의 2차 곡선을 추정하고 실시간으로 표시한다

Arduino 입력 형식
  {"t_ms":1234,"s1":95.2,"s2":111.8,"s3":126.4,"s4":null,"s5":91.9}
  S4는 값이 있거나 null이어도 읽지 않는다

사용 센서 좌표
  실제 설치 높이는 위에서부터 S1, S2 S3, S4, S5 순서다
  S1, S2, S3, S5만 사용하고 S3를 원점으로 사용
  y = [120, 60, 0, -120] mm

추정식
  z = b*y^2 + d*y + e

주의
  이 프로그램이 추정하는 것은 실제 척추뼈의 3차원 곡면이나 임상적 전만각이 아니라
  초음파센서가 본 등 표면 중앙선의 세로 방향 2차 곡선이다
"""

from __future__ import annotations

import argparse
import json
import math
import random
import select
import statistics
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Protocol, Sequence


SENSOR_KEYS = ("s1", "s2", "s3", "s5")
IGNORED_SENSOR_KEYS = ("s4",)
# 개럿이의 실제 배선은 S1이 최상단, S5가 최하단이다
SENSOR_HEIGHTS_FROM_SEAT_MM = (310.0, 250.0, 190.0, 70.0)
ALL_SENSOR_HEIGHTS_FROM_SEAT_MM = {
    "s1": 310.0,
    "s2": 250.0,
    "s3": 190.0,
    "s4": 130.0,
    "s5": 70.0,
}
Y_MM = (120.0, 60.0, 0.0, -120.0)
Y_ORIGIN_HEIGHT_FROM_SEAT_MM = 190.0
Y_SCALE_MM = 60.0

DEFAULT_BAUDRATE = 115200
# 실시간 감시에서는 5개 중앙값으로 옷 주름·몸의 짧은 움직임 반사를 줄인다.
# 아두이노가 약 0.325초마다 한 묶음을 보낼 때 5개 창은 약 0.65초,
# 3개 창은 약 0.325초의 필터 지연을 만든다
MEDIAN_WINDOW = 5
CALIBRATION_SETTLE_SECONDS = 2.0
CALIBRATION_SECONDS = 5.0
# 실제 의자에서는 한 묶음 출력이 약 0.3초이고 일부 채널이 순간 null일 수 있다.
# 4개 이상이면 중앙값 기준선을 만들 수 있으며, 부족할 때는 아래 최대 시간까지
# 자동으로 더 수집한다.
MIN_CALIBRATION_SAMPLES = 4
CALIBRATION_MAX_SECONDS = 10.0
CALIBRATION_FILTER_WINDOW = 5
# 전체 수집 구간에 자세를 잡는 순간의 움직임이 섞여도, 연속된 안정 구간을
# 찾아 기준으로 사용한다. 약 0.3초/묶음 환경에서 6개는 약 1.8초 분량이다.
BASELINE_STABLE_WINDOW_SAMPLES = 6
MAX_CALIBRATION_SPAN_MM = 30.0
CALIBRATION_SPIKE_THRESHOLD_MM = 45.0
MAX_CALIBRATION_CORRECTION_RATIO = 0.30
MAX_FIT_RMSE_MM = 15.0

# 초기 실험용 값이며 의학적으로 검증된 임계값이 아니다
# 0.0006 mm^-1은 중심에서 120 mm 떨어진 곳에서 약 8.6 mm의 곡률 변화에 해당한다
DEFAULT_B_LOSS_THRESHOLD = 0.0006
# 왼쪽 위 등 자세 카드와 posture_feedback.json의 warning 상태가 너무 예민하게 바뀌지 않도록
# 등 구부러짐이 8초 이상 유지될 때만 WARNING으로 전환하고,
# 정상 복귀도 4초 확인해 상태가 빠르게 왕복하지 않게 한다.
DEFAULT_ALERT_HOLD_SECONDS = 8.0
DEFAULT_RECOVERY_HOLD_SECONDS = 4.0
DASHBOARD_MAX_FPS = 30.0
IDLE_POLL_SECONDS = 0.003
PARTIAL_FRAME_STALE_SECONDS = 1.20
SERIAL_RECONNECT_COOLDOWN_SECONDS = 0.60
SIGNAL_STALE_SECONDS = 2.0
STATUS_HEARTBEAT_SECONDS = 0.5

# 화면 표시용 값이며 센서 설치 환경에 맞춰 조절할 수 있다
ZONE_MIN_ERROR_MM = 3.0
ZONE_RELATIVE_CUTOFF = 0.65
ZONE_RECOVERY_LIGHT_SECONDS = 3.0
ZONE_RECOVERY_CONFIRM_SECONDS = 0.8
GLOBAL_SHIFT_NOTICE_MM = 12.0

ZONE_LABELS = {
    "s1": "상부 등",
    "s2": "중상부 등",
    "s3": "등 중앙",
    "s5": "허리 부근",
}


def valid_distance(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and 20.0 <= number <= 500.0


@dataclass(frozen=True)
class QuadraticFit:
    b_mm_inv: float
    d: float
    e_mm: float
    rmse_mm: float
    hollow_height_from_seat_mm: Optional[float]

    def distance_at_relative_y(self, y_mm: float) -> float:
        return self.b_mm_inv * y_mm * y_mm + self.d * y_mm + self.e_mm


def solve_3x3(
    matrix: Sequence[Sequence[float]], vector: Sequence[float]
) -> List[float]:
    """부분 피벗 가우스 소거법으로 3x3 연립방정식을 푼다"""
    augmented = [
        [float(value) for value in row] + [float(rhs)]
        for row, rhs in zip(matrix, vector)
    ]
    if len(augmented) != 3 or any(len(row) != 4 for row in augmented):
        raise ValueError("3x3 연립방정식이 필요합니다")

    for column in range(3):
        pivot_row = max(
            range(column, 3),
            key=lambda row_index: abs(augmented[row_index][column]),
        )
        if abs(augmented[pivot_row][column]) < 1.0e-12:
            raise ValueError("2차 곡선을 계산할 수 없는 센서 좌표입니다")
        augmented[column], augmented[pivot_row] = (
            augmented[pivot_row],
            augmented[column],
        )

        pivot = augmented[column][column]
        augmented[column] = [value / pivot for value in augmented[column]]

        for row_index in range(3):
            if row_index == column:
                continue
            factor = augmented[row_index][column]
            augmented[row_index] = [
                current - factor * pivot_value
                for current, pivot_value in zip(
                    augmented[row_index], augmented[column]
                )
            ]

    return [augmented[row_index][3] for row_index in range(3)]


def fit_quadratic(distances_mm: Sequence[float]) -> QuadraticFit:
    """S1, S2, S3, S5의 비등간격 4점으로 최소제곱 2차 곡선을 구한다"""
    if len(distances_mm) != len(SENSOR_KEYS) or not all(
        valid_distance(value) for value in distances_mm
    ):
        raise ValueError("S1, S2, S3, S5의 유효한 거리값 4개가 필요합니다")

    distances = [float(value) for value in distances_mm]

    # 수치 안정성을 위해 y를 60 mm 단위의 x로 바꿔
    # z = a*x^2 + c*x + e를 구한 뒤 mm 단위 계수 b, d로 되돌린다
    x_values = [y_mm / Y_SCALE_MM for y_mm in Y_MM]
    sum_x = sum(x_values)
    sum_x2 = sum(x * x for x in x_values)
    sum_x3 = sum(x * x * x for x in x_values)
    sum_x4 = sum(x * x * x * x for x in x_values)

    normal_matrix = (
        (sum_x4, sum_x3, sum_x2),
        (sum_x3, sum_x2, sum_x),
        (sum_x2, sum_x, float(len(x_values))),
    )
    normal_vector = (
        sum(distance * x * x for x, distance in zip(x_values, distances)),
        sum(distance * x for x, distance in zip(x_values, distances)),
        sum(distances),
    )
    a_scaled, c_scaled, e = solve_3x3(normal_matrix, normal_vector)
    b = a_scaled / (Y_SCALE_MM * Y_SCALE_MM)
    d = c_scaled / Y_SCALE_MM

    predicted = [b * y * y + d * y + e for y in Y_MM]
    rmse = math.sqrt(
        statistics.fmean(
            (actual - estimate) ** 2
            for actual, estimate in zip(distances, predicted)
        )
    )

    hollow_height: Optional[float] = None
    if abs(b) >= 1.0e-8:
        vertex_relative_y = -d / (2.0 * b)
        if Y_MM[0] <= vertex_relative_y <= Y_MM[-1]:
            hollow_height = Y_ORIGIN_HEIGHT_FROM_SEAT_MM + vertex_relative_y

    return QuadraticFit(b, d, e, rmse, hollow_height)


def curve_points(fit: QuadraticFit, step_mm: int = 10) -> List[Dict[str, float]]:
    """디스플레이가 곡선을 그릴 수 있도록 70~310 mm 구간의 점을 만든다"""
    points: List[Dict[str, float]] = []
    for relative_y in range(-120, 121, step_mm):
        points.append(
            {
                "height_from_seat_mm": Y_ORIGIN_HEIGHT_FROM_SEAT_MM + relative_y,
                "distance_mm": round(fit.distance_at_relative_y(float(relative_y)), 2),
            }
        )
    return points


class SampleSource(Protocol):
    def read_sample(self) -> Optional[List[float]]:
        ...

    def clear(self) -> None:
        ...


class ArduinoSerialSource:
    """등 초음파 JSON을 안전하게 읽고 부분 null 프레임과 USB 순간 끊김을 복구한다."""

    def __init__(self, port: str, baudrate: int) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyserial이 필요합니다: pip install pyserial") from exc
        self._serial_module = serial
        self.port = str(port)
        self.baudrate = int(baudrate)
        self.serial = None
        self.receive_buffer = bytearray()
        self.last_reconnect_attempt = 0.0
        self.latest_values: Dict[str, Optional[float]] = {key: None for key in SENSOR_KEYS}
        self.latest_at: Dict[str, float] = {key: 0.0 for key in SENSOR_KEYS}
        self._open()

    def _open(self) -> None:
        kwargs = {"port": self.port, "baudrate": self.baudrate, "timeout": 0.0, "write_timeout": 0.2}
        try:
            self.serial = self._serial_module.Serial(exclusive=True, **kwargs)
        except TypeError:
            self.serial = self._serial_module.Serial(**kwargs)
        time.sleep(1.0)
        self.receive_buffer.clear()
        print(f"등 초음파 시리얼 연결: {self.port}")

    def _reconnect(self) -> bool:
        now = time.monotonic()
        if now - self.last_reconnect_attempt < SERIAL_RECONNECT_COOLDOWN_SECONDS:
            return False
        self.last_reconnect_attempt = now
        try:
            if self.serial is not None:
                self.serial.close()
        except Exception:
            pass
        try:
            time.sleep(0.25)
            self._open()
            print(f"등 초음파 시리얼 재연결 완료: {self.port}")
            return True
        except Exception as exc:
            print(f"등 초음파 시리얼 재연결 대기: {exc}", file=sys.stderr)
            return False

    def clear(self) -> None:
        self.receive_buffer.clear()
        self.latest_values = {key: None for key in SENSOR_KEYS}
        self.latest_at = {key: 0.0 for key in SENSOR_KEYS}
        try:
            if self.serial is None:
                return
            waiting = int(getattr(self.serial, "in_waiting", 0))
            if waiting > 0:
                self.serial.read(waiting)
        except Exception as exc:
            print(f"등 초음파 버퍼 정리 중 USB 오류: {exc}", file=sys.stderr)
            self._reconnect()

    def _update_cache(self, payload: object, now: float) -> None:
        if not isinstance(payload, dict):
            return
        for key in SENSOR_KEYS:
            value = payload.get(key)
            if valid_distance(value):
                self.latest_values[key] = float(value)
                self.latest_at[key] = now

    def _cached_sample(self, now: float) -> Optional[List[float]]:
        values: List[float] = []
        for key in SENSOR_KEYS:
            value = self.latest_values.get(key)
            at = self.latest_at.get(key, 0.0)
            if value is None or now - at > PARTIAL_FRAME_STALE_SECONDS:
                return None
            values.append(float(value))
        return values

    def read_sample(self) -> Optional[List[float]]:
        try:
            if self.serial is None:
                if not self._reconnect():
                    return None
            waiting = int(getattr(self.serial, "in_waiting", 0))
            if waiting > 0:
                self.receive_buffer.extend(self.serial.read(waiting))
        except Exception as exc:
            print(f"등 초음파 읽기 오류, 재연결 시도: {exc}", file=sys.stderr)
            self._reconnect()
            return None
        if len(self.receive_buffer) > 16384:
            del self.receive_buffer[:-8192]
        newline_index = self.receive_buffer.rfind(b"\n")
        if newline_index < 0:
            return None
        completed = bytes(self.receive_buffer[:newline_index])
        del self.receive_buffer[: newline_index + 1]
        now = time.monotonic()
        for raw_line in completed.splitlines()[-12:]:
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            self._update_cache(payload, now)
        return self._cached_sample(now)

    def close(self) -> None:
        try:
            if self.serial is not None:
                self.serial.close()
        except Exception:
            pass


class DemoSource:
    """센서 없이 기준 자세 -> 구부정 자세 -> 회복을 시험한다"""

    def __init__(self) -> None:
        self.started_at = time.monotonic()
        self.random = random.Random(42)

    def clear(self) -> None:
        return None

    def read_sample(self) -> Optional[List[float]]:
        time.sleep(0.10)
        elapsed = time.monotonic() - self.started_at

        bad_posture_start = CALIBRATION_SETTLE_SECONDS + CALIBRATION_SECONDS + 1.0
        # 기본 경고 유지시간이 5초이므로 demo에서도 WARNING 전환을 볼 수 있게 7초간 유지한다.
        bad_posture_end = bad_posture_start + 7.0
        if elapsed < bad_posture_start or elapsed >= bad_posture_end:
            base = [95.0, 114.0, 127.0, 93.0]
        else:
            base = [96.0, 102.0, 106.0, 94.0]

        return [value + self.random.uniform(-1.0, 1.0) for value in base]


class MedianFilterBank:
    def __init__(self, window: int) -> None:
        self.buffers: List[Deque[float]] = [deque(maxlen=window) for _ in SENSOR_KEYS]

    def clear(self) -> None:
        for buffer in self.buffers:
            buffer.clear()

    def update(self, distances_mm: Sequence[float]) -> List[float]:
        for buffer, value in zip(self.buffers, distances_mm):
            buffer.append(float(value))
        return [statistics.median(buffer) for buffer in self.buffers]


def centered_median_filter(values: Sequence[float], window: int) -> List[float]:
    """앞뒤 샘플의 중앙값으로 순간적인 초음파 튐을 제거한다"""
    if window < 1 or window % 2 == 0:
        raise ValueError("중앙값 필터 크기는 1 이상의 홀수여야 합니다")

    radius = window // 2
    filtered: List[float] = []
    for index in range(len(values)):
        start = max(0, index - radius)
        stop = min(len(values), index + radius + 1)
        filtered.append(float(statistics.median(values[start:stop])))
    return filtered


def filter_calibration_samples(samples: Sequence[Sequence[float]]) -> List[List[float]]:
    """센서별 시계열에 중앙값 필터를 적용한 뒤 다시 샘플 행으로 묶는다"""
    columns = list(zip(*samples))
    filtered_columns = [
        centered_median_filter(column, CALIBRATION_FILTER_WINDOW) for column in columns
    ]
    return [list(row) for row in zip(*filtered_columns)]


def calibration_percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("백분위수를 계산할 값이 없습니다")
    position = max(0.0, min(1.0, float(fraction))) * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def select_stable_calibration_samples(
    samples: Sequence[Sequence[float]],
) -> tuple[List[List[float]], int, List[float]]:
    """수집값 중 센서 네 개가 함께 가장 안정적인 연속 구간을 고른다."""

    if len(samples) < MIN_CALIBRATION_SAMPLES:
        raise ValueError("안정 구간을 고를 기준 측정값이 부족합니다")

    window_size = min(
        len(samples),
        max(MIN_CALIBRATION_SAMPLES, BASELINE_STABLE_WINDOW_SAMPLES),
    )
    best_rows: Optional[List[List[float]]] = None
    best_start = 0
    best_spans: Optional[List[float]] = None
    best_score: Optional[float] = None

    for start in range(0, len(samples) - window_size + 1):
        rows = [list(map(float, row)) for row in samples[start : start + window_size]]
        columns = list(zip(*rows))
        spans = [
            calibration_percentile(column, 0.90)
            - calibration_percentile(column, 0.10)
            for column in columns
        ]
        # 한 센서의 큰 움직임도 놓치지 않으면서 전체 흔들림이 작은 구간을 우선한다.
        score = max(spans) * 2.0 + sum(spans)
        if best_score is None or score < best_score:
            best_rows = rows
            best_start = start
            best_spans = spans
            best_score = score

    if best_rows is None or best_spans is None:
        raise ValueError("안정된 기준 측정 구간을 찾지 못했습니다")
    return best_rows, best_start, best_spans


def replace_marked_values(values: Sequence[float], marked: Sequence[bool]) -> List[float]:
    """표시된 이상값을 가장 가까운 앞뒤 정상값의 선형 보간값으로 바꾼다"""
    if len(values) != len(marked):
        raise ValueError("값과 이상값 표시의 길이가 다릅니다")

    good_indices = [index for index, is_marked in enumerate(marked) if not is_marked]
    if not good_indices:
        raise ValueError("보정에 사용할 정상 측정값이 없습니다")

    corrected = [float(value) for value in values]
    for index, is_marked in enumerate(marked):
        if not is_marked:
            continue

        left = next((candidate for candidate in reversed(good_indices) if candidate < index), None)
        right = next((candidate for candidate in good_indices if candidate > index), None)

        if left is None:
            corrected[index] = float(values[right])  # type: ignore[index]
        elif right is None:
            corrected[index] = float(values[left])
        else:
            position = (index - left) / (right - left)
            corrected[index] = float(values[left]) + position * (
                float(values[right]) - float(values[left])
            )

    return corrected


def correct_calibration_spikes(
    samples: Sequence[Sequence[float]],
) -> tuple[List[List[float]], List[int]]:
    """센서별 중앙값에서 크게 벗어난 짧은 튐을 찾아 앞뒤 정상값으로 보정한다"""
    columns = list(zip(*samples))
    corrected_columns: List[List[float]] = []
    correction_counts: List[int] = []

    for sensor_index, column in enumerate(columns):
        center = float(statistics.median(column))
        marked = [
            abs(float(value) - center) > CALIBRATION_SPIKE_THRESHOLD_MM
            for value in column
        ]
        correction_count = sum(marked)
        correction_ratio = correction_count / len(column)

        if correction_ratio > MAX_CALIBRATION_CORRECTION_RATIO:
            raise RuntimeError(
                f"{SENSOR_KEYS[sensor_index].upper()} 이상값이 너무 많아 자동 보정할 수 없습니다  "
                f"{correction_count}/{len(column)}개  센서 각도와 옷 주름을 확인해주세요"
            )

        corrected_columns.append(replace_marked_values(column, marked))
        correction_counts.append(correction_count)

    corrected_samples = [list(row) for row in zip(*corrected_columns)]
    return corrected_samples, correction_counts


@dataclass
class Baseline:
    distances_mm: List[float]
    fit: QuadraticFit


def fitted_shape_errors_mm(
    fit: QuadraticFit, baseline_fit: QuadraticFit
) -> Dict[str, float]:
    """전체 앞뒤 이동과 기울기를 뺀 뒤 부위별 곡선 모양 차이만 계산한다"""
    changes = [
        fit.distance_at_relative_y(y_mm)
        - baseline_fit.distance_at_relative_y(y_mm)
        for y_mm in Y_MM
    ]
    mean_y = statistics.fmean(Y_MM)
    mean_change = statistics.fmean(changes)
    denominator = sum((y_mm - mean_y) ** 2 for y_mm in Y_MM)
    slope = (
        sum(
            (y_mm - mean_y) * (change - mean_change)
            for y_mm, change in zip(Y_MM, changes)
        )
        / denominator
    )
    residuals = [
        change - (mean_change + slope * (y_mm - mean_y))
        for y_mm, change in zip(Y_MM, changes)
    ]
    return {key: value for key, value in zip(SENSOR_KEYS, residuals)}


def problem_zone_flags(
    shape_errors: Dict[str, float], warning: bool
) -> Dict[str, bool]:
    """경고 중 곡선 모양 차이가 큰 부위만 빨간 표시 대상으로 고른다"""
    if not warning or not shape_errors:
        return {key: False for key in SENSOR_KEYS}

    largest = max(abs(value) for value in shape_errors.values())
    cutoff = max(ZONE_MIN_ERROR_MM, largest * ZONE_RELATIVE_CUTOFF)
    flags = {key: abs(shape_errors[key]) >= cutoff for key in SENSOR_KEYS}
    if not any(flags.values()):
        largest_key = max(SENSOR_KEYS, key=lambda key: abs(shape_errors[key]))
        flags[largest_key] = True
    return flags


def movement_guidance(error_mm: float) -> str:
    """센서 가상평면을 기준으로 해당 부위가 움직일 방향을 알려준다"""
    if error_mm > 0.0:
        return "등받이 쪽으로"
    return "앞쪽으로"


class ZoneLightTracker:
    """문제는 빨간색, 해결된 부위는 3초간 초록색으로 유지한다"""

    def __init__(self) -> None:
        self.red = {key: False for key in SENSOR_KEYS}
        self.good_since: Dict[str, Optional[float]] = {
            key: None for key in SENSOR_KEYS
        }
        self.green_until = {key: 0.0 for key in SENSOR_KEYS}

    def reset(self) -> None:
        for key in SENSOR_KEYS:
            self.red[key] = False
            self.good_since[key] = None
            self.green_until[key] = 0.0

    def update(
        self, problem_flags: Dict[str, bool], now: float, overall_warning: bool
    ) -> Dict[str, str]:
        states: Dict[str, str] = {}
        for key in SENSOR_KEYS:
            if problem_flags.get(key, False):
                self.red[key] = True
                self.good_since[key] = None
                self.green_until[key] = 0.0
            elif self.red[key]:
                # 전체 경고가 해제됐다면 이미 회복 유지시간을 통과한 상태다
                if not overall_warning:
                    self.red[key] = False
                    self.good_since[key] = None
                    self.green_until[key] = now + ZONE_RECOVERY_LIGHT_SECONDS
                elif self.good_since[key] is None:
                    self.good_since[key] = now
                elif now - self.good_since[key] >= ZONE_RECOVERY_CONFIRM_SECONDS:
                    self.red[key] = False
                    self.good_since[key] = None
                    self.green_until[key] = now + ZONE_RECOVERY_LIGHT_SECONDS
            else:
                self.good_since[key] = None

            if self.red[key]:
                states[key] = "red"
            elif now < self.green_until[key]:
                states[key] = "green"
            else:
                states[key] = "off"
        return states


def calibrate(
    source: SampleSource,
    filters: MedianFilterBank,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> Baseline:
    print(
        f"바른 자세를 잡아주세요  {CALIBRATION_SETTLE_SECONDS:.1f}초 뒤에 "
        f"{CALIBRATION_SECONDS:.1f}초 동안 기준값을 측정할게요"
    )
    source.clear()
    filters.clear()

    settle_deadline = time.monotonic() + CALIBRATION_SETTLE_SECONDS
    while time.monotonic() < settle_deadline:
        remaining = max(0.0, settle_deadline - time.monotonic())
        if progress_callback is not None:
            progress_callback("settle", remaining)
        if source.read_sample() is None:
            time.sleep(0.005)

    source.clear()
    print("기준 측정을 시작합니다  그대로 유지해주세요")

    samples: List[List[float]] = []
    measurement_started_at = time.monotonic()
    minimum_deadline = measurement_started_at + CALIBRATION_SECONDS
    hard_deadline = measurement_started_at + CALIBRATION_MAX_SECONDS

    while time.monotonic() < hard_deadline:
        now = time.monotonic()
        remaining = max(0.0, minimum_deadline - now)
        if progress_callback is not None:
            progress_callback("measure", remaining)
        sample = source.read_sample()
        if sample is not None:
            samples.append(sample)
        else:
            time.sleep(0.005)

        # 기본 5초는 유지하되 출력 주기가 느린 환경에서는 최소 샘플이
        # 모일 때까지 최대 10초까지만 자동 연장한다.
        if now >= minimum_deadline and len(samples) >= MIN_CALIBRATION_SAMPLES:
            break

    if len(samples) < MIN_CALIBRATION_SAMPLES:
        raise RuntimeError(
            f"기준 측정값이 부족합니다  {len(samples)}개 수신, 최소 {MIN_CALIBRATION_SAMPLES}개 필요"
        )

    # 전체 5~10초 중 자세를 잡거나 풀 때의 움직임 하나로 보정 전체를 버리지 않는다.
    # 네 채널이 함께 가장 안정적이었던 연속 구간을 고른 뒤에만 튐 보정과
    # 중앙값 필터를 적용한다. 선택된 구간 자체가 흔들리면 기존처럼 실패시킨다.
    full_raw_spans = [max(column) - min(column) for column in zip(*samples)]
    stable_samples, stable_start, stable_robust_spans = select_stable_calibration_samples(samples)
    raw_spans = [max(column) - min(column) for column in zip(*stable_samples)]
    corrected_samples, correction_counts = correct_calibration_spikes(stable_samples)
    filtered_samples = filter_calibration_samples(corrected_samples)
    spans = [max(column) - min(column) for column in zip(*filtered_samples)]
    if any(span > MAX_CALIBRATION_SPAN_MM for span in spans):
        rounded = [round(span, 1) for span in spans]
        raw_rounded = [round(span, 1) for span in raw_spans]
        raise RuntimeError(
            "기준 측정 중 움직임이 너무 컸습니다  "
            f"사용 센서={list(SENSOR_KEYS)}  필터링 후 센서별 변화폭={rounded} mm  "
            f"선택 구간 원본 변화폭={raw_rounded} mm  "
            f"전체 수집 변화폭={[round(span, 1) for span in full_raw_spans]} mm"
        )

    print(
        "등 기준 안정 구간 선택 완료  "
        f"전체={len(samples)}개, 선택={stable_start + 1}~"
        f"{stable_start + len(stable_samples)}번째  "
        f"강건 변화폭={[round(span, 1) for span in stable_robust_spans]} mm"
    )

    if any(correction_counts):
        print(
            "튀는 값 자동 보정 완료  "
            f"사용 센서={list(SENSOR_KEYS)}  센서별 보정 개수={correction_counts}  "
            f"원본 변화폭={[round(span, 1) for span in raw_spans]} mm  "
            f"보정·필터링 후={[round(span, 1) for span in spans]} mm"
        )
    elif any(raw > filtered + 1.0 for raw, filtered in zip(raw_spans, spans)):
        print(
            "작은 흔들림 필터링 완료  "
            f"원본 변화폭={[round(span, 1) for span in raw_spans]} mm  "
            f"필터링 후={[round(span, 1) for span in spans]} mm"
        )

    baseline_distances = [statistics.median(column) for column in zip(*filtered_samples)]
    fit = fit_quadratic(baseline_distances)

    if fit.rmse_mm > MAX_FIT_RMSE_MM:
        raise RuntimeError(
            f"기준 곡선 오차가 너무 큽니다  RMSE={fit.rmse_mm:.1f} mm, 센서 정렬과 옷 주름을 확인해주세요"
        )

    filters.clear()
    print(
        "기준 자세 저장 완료  "
        f"b0={fit.b_mm_inv:+.6f} mm^-1, "
        f"곡선 RMSE={fit.rmse_mm:.1f} mm"
    )
    return Baseline(baseline_distances, fit)


class WarningTimer:
    def __init__(self, alert_hold: float, recovery_hold: float) -> None:
        self.alert_hold = alert_hold
        self.recovery_hold = recovery_hold
        self.warning = False
        self.bad_since: Optional[float] = None
        self.good_since: Optional[float] = None

    def reset(self) -> None:
        self.warning = False
        self.bad_since = None
        self.good_since = None

    def update(self, bad_posture: bool, now: float) -> bool:
        if bad_posture:
            self.good_since = None
            if self.warning:
                return True
            if self.bad_since is None:
                self.bad_since = now
            elif now - self.bad_since >= self.alert_hold:
                self.warning = True
        else:
            self.bad_since = None
            if not self.warning:
                self.good_since = None
                return False
            if self.good_since is None:
                self.good_since = now
            elif now - self.good_since >= self.recovery_hold:
                self.warning = False
                self.good_since = None
        return self.warning


def stdin_enter_pressed() -> bool:
    if not sys.stdin.isatty():
        return False
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0.0)
    except (OSError, ValueError):
        return False
    if ready:
        sys.stdin.readline()
        return True
    return False


def write_feedback(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def make_calibration_feedback_callback(
    output_path: Path,
    token_provider: Optional[Callable[[], str]] = None,
) -> Callable[[str, float], None]:
    """no-window 보정 중에도 UI가 stale 상태가 되지 않도록 heartbeat를 쓴다."""

    last_write_at = [0.0]

    def callback(phase: str, remaining: float) -> None:
        now = time.monotonic()
        if now - last_write_at[0] < STATUS_HEARTBEAT_SECONDS:
            return
        last_write_at[0] = now
        phase_text = "자세 안정화 중" if phase == "settle" else "기준값 수집 중"
        measurement_token = token_provider() if token_provider is not None else ""
        write_feedback(
            output_path,
            {
                "timestamp": time.time(),
                "state": "CALIBRATING",
                "warning": False,
                "signal_ok": True,
                "message": f"등 기준 자세 {phase_text}",
                "calibration_phase": phase,
                "remaining_seconds": round(max(0.0, float(remaining)), 1),
                "measurement_token": str(measurement_token or ""),
            },
        )

    return callback


class MeasurementTriggerWatcher:
    """app.py가 쓰는 START 측정 JSON을 감시해 새 token이 생겼을 때만 보정을 시작한다."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.started_wall_time = time.time()
        self.last_token: Optional[str] = None

        payload = self._read_payload()
        if payload is not None:
            token = str(payload.get("token", "")).strip()
            try:
                timestamp = float(payload.get("timestamp", 0.0))
            except (TypeError, ValueError):
                timestamp = 0.0

            # 프로세스 실행 이전에 남아 있던 오래된 START 신호는 소비한 것으로 간주한다.
            if token and timestamp < self.started_wall_time - 0.5:
                self.last_token = token

    def _read_payload(self) -> Optional[Dict[str, object]]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        return payload if isinstance(payload, dict) else None

    def consume_new_trigger(self) -> bool:
        payload = self._read_payload()
        if payload is None:
            return False

        token = str(payload.get("token", "")).strip()
        if not token or token == self.last_token:
            return False

        self.last_token = token
        return True

    def wait_for_next(self, label: str) -> None:
        print(f"{label}: START(S) 측정 신호 대기 중")
        while True:
            if self.consume_new_trigger():
                print(f"{label}: START(S) 신호 수신 / 기준 자세 측정 시작")
                return
            time.sleep(0.05)


def build_payload(
    distances_mm: Sequence[float],
    fit: QuadraticFit,
    baseline: Baseline,
    curvature_loss: float,
    threshold: float,
    warning: bool,
) -> Dict[str, object]:
    delta_b = fit.b_mm_inv - baseline.fit.b_mm_inv
    mean_gap_change = statistics.fmean(distances_mm) - statistics.fmean(baseline.distances_mm)
    shape_errors = fitted_shape_errors_mm(fit, baseline.fit)
    distance_changes = {
        key: current - reference
        for key, current, reference in zip(
            SENSOR_KEYS, distances_mm, baseline.distances_mm
        )
    }

    current_upper_change = statistics.fmean(
        distances_mm[i] - baseline.distances_mm[i] for i in (0, 1)
    )
    current_lower_change = statistics.fmean(
        distances_mm[i] - baseline.distances_mm[i] for i in (2, 3)
    )
    upper_lower_tilt_change = current_upper_change - current_lower_change

    return {
        "timestamp": time.time(),
        "state": "WARNING" if warning else "NORMAL",
        "warning": warning,
        "signal_ok": True,
        "message": "허리를 펴십시오" if warning else "바른 자세입니다",
        "active_sensors": list(SENSOR_KEYS),
        "ignored_sensors": list(IGNORED_SENSOR_KEYS),
        "distances_mm": {
            key: round(value, 2) for key, value in zip(SENSOR_KEYS, distances_mm)
        },
        "baseline_distances_mm": {
            key: round(value, 2)
            for key, value in zip(SENSOR_KEYS, baseline.distances_mm)
        },
        "distance_changes_mm": {
            key: round(value, 2) for key, value in distance_changes.items()
        },
        "shape_errors_mm": {
            key: round(value, 2) for key, value in shape_errors.items()
        },
        "sensor_heights_from_seat_mm": {
            key: ALL_SENSOR_HEIGHTS_FROM_SEAT_MM[key]
            for key in ("s1", "s2", "s3", "s4", "s5")
        },
        "fit": asdict(fit),
        "baseline_b_mm_inv": baseline.fit.b_mm_inv,
        "delta_b_mm_inv": delta_b,
        "curvature_loss_mm_inv": curvature_loss,
        "b_loss_threshold_mm_inv": threshold,
        "mean_gap_change_mm": mean_gap_change,
        "upper_lower_tilt_change_mm": upper_lower_tilt_change,
        "curve_points": curve_points(fit),
    }


class RealtimeDashboard:
    """추가 설치 없이 Tkinter로 실시간 가상평면과 등 곡선을 표시한다"""

    COLORS = {
        "background": "#F3F6FA",
        "card": "#FFFFFF",
        "border": "#DCE4EE",
        "text": "#152033",
        "muted": "#64748B",
        "plane": "#0F766E",
        "baseline": "#475569",
        "blue": "#2563EB",
        "blue_soft": "#DBEAFE",
        "red": "#DC2626",
        "red_soft": "#FEE2E2",
        "green": "#16A34A",
        "green_soft": "#DCFCE7",
        "amber": "#D97706",
        "amber_soft": "#FEF3C7",
        "off": "#CBD5E1",
        "off_soft": "#F1F5F9",
    }

    def __init__(
        self,
        width: int = 1280,
        height: int = 760,
        fullscreen: bool = False,
        alert_hold: float = DEFAULT_ALERT_HOLD_SECONDS,
    ) -> None:
        try:
            import tkinter as tk
        except ImportError as exc:
            raise RuntimeError("Tkinter가 없어 실시간 화면을 열 수 없습니다") from exc

        self.tk = tk
        self.root = tk.Tk()
        self.root.title("실시간 척추 자세 가상평면")
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(1100, 700)
        self.fullscreen = bool(fullscreen)
        self.alert_hold = float(alert_hold)
        self.root.attributes("-fullscreen", self.fullscreen)
        self.root.configure(bg=self.COLORS["background"])

        self.canvas = tk.Canvas(
            self.root,
            bg=self.COLORS["background"],
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.calibration_button = tk.Button(
            self.root,
            text="기준 자세 측정 시작",
            command=self._request_calibration,
            font=("Malgun Gothic", 11, "bold"),
            bg=self.COLORS["blue"],
            fg="#FFFFFF",
            activebackground="#1D4ED8",
            activeforeground="#FFFFFF",
            relief="flat",
            cursor="hand2",
        )
        self.calibration_button.place(
            relx=1.0, x=-24, y=19, anchor="ne", width=210, height=40
        )

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Return>", lambda _event: self._request_calibration())
        self.root.bind("<Escape>", lambda _event: self.close())
        self.root.bind("<F11>", lambda _event: self.toggle_fullscreen())
        self.canvas.bind("<Configure>", lambda _event: self._mark_dirty())

        self.closed = False
        self.calibration_requested = False
        self.mode = "WAITING"
        self.calibration_stage = ""
        self.calibration_remaining = 0.0
        self.error_message = ""
        self.baseline: Optional[Baseline] = None
        self.current_distances: Optional[List[float]] = None
        self.current_fit: Optional[QuadraticFit] = None
        self.curvature_loss = 0.0
        self.threshold = DEFAULT_B_LOSS_THRESHOLD
        self.warning = False
        self.bad_posture = False
        self.shape_errors = {key: 0.0 for key in SENSOR_KEYS}
        self.zone_states = {key: "off" for key in SENSOR_KEYS}
        self.zone_tracker = ZoneLightTracker()
        self.overall_green_until = 0.0
        self.previous_warning = False
        self.last_draw_at = 0.0
        self.dirty = True
        self._draw()
        self.pump(force_draw=True)

    def _mark_dirty(self) -> None:
        self.dirty = True

    def _request_calibration(self) -> None:
        if self.closed or self.mode == "CALIBRATION":
            return
        self.calibration_requested = True
        self.mode = "QUEUED"
        self.error_message = ""
        self.dirty = True

    def consume_calibration_request(self) -> bool:
        requested = self.calibration_requested
        self.calibration_requested = False
        return requested

    def wait_for_calibration_start(self) -> bool:
        if self.mode != "CALIBRATION_ERROR":
            self.mode = "WAITING"
        self.dirty = True
        while not self.closed:
            if self.consume_calibration_request() or stdin_enter_pressed():
                return True
            self.pump()
            time.sleep(0.015)
        return False

    def toggle_fullscreen(self) -> None:
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        self.dirty = True

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.root.destroy()
        except self.tk.TclError:
            pass

    def pump(self, force_draw: bool = False) -> bool:
        if self.closed:
            return False
        try:
            self.root.update_idletasks()
            self.root.update()
        except self.tk.TclError:
            self.closed = True
            return False

        now = time.monotonic()
        if force_draw or self.dirty or now - self.last_draw_at >= 1.0 / DASHBOARD_MAX_FPS:
            self._draw()
            self.last_draw_at = now
            self.dirty = False
        return not self.closed

    def show_calibration(self, stage: str, remaining: float) -> None:
        if self.closed:
            return
        self.mode = "CALIBRATION"
        self.calibration_stage = stage
        self.calibration_remaining = remaining
        self.calibration_button.configure(state="disabled", text="기준값 측정 중")
        self.dirty = True
        self.pump()

    def show_calibration_error(self, message: str) -> None:
        if self.closed:
            return
        self.mode = "CALIBRATION_ERROR"
        self.error_message = message
        self.calibration_button.configure(state="normal", text="기준 자세 다시 측정")
        self.dirty = True

    def set_baseline(self, baseline: Baseline, threshold: float) -> None:
        if self.closed:
            return
        self.baseline = baseline
        self.threshold = threshold
        self.current_distances = list(baseline.distances_mm)
        self.current_fit = baseline.fit
        self.curvature_loss = 0.0
        self.warning = False
        self.bad_posture = False
        self.previous_warning = False
        self.overall_green_until = 0.0
        self.shape_errors = {key: 0.0 for key in SENSOR_KEYS}
        self.zone_tracker.reset()
        self.zone_states = {key: "off" for key in SENSOR_KEYS}
        self.mode = "NORMAL"
        self.error_message = ""
        self.calibration_button.configure(state="normal", text="기준 자세 다시 측정")
        self.dirty = True

    def update_posture(
        self,
        distances_mm: Sequence[float],
        fit: QuadraticFit,
        baseline: Baseline,
        curvature_loss: float,
        threshold: float,
        bad_posture: bool,
        warning: bool,
        now: float,
    ) -> None:
        self.baseline = baseline
        self.current_distances = [float(value) for value in distances_mm]
        self.current_fit = fit
        self.curvature_loss = curvature_loss
        self.threshold = threshold
        self.bad_posture = bad_posture
        self.warning = warning
        self.shape_errors = fitted_shape_errors_mm(fit, baseline.fit)
        flags = problem_zone_flags(self.shape_errors, warning)
        self.zone_states = self.zone_tracker.update(flags, now, warning)

        if self.previous_warning and not warning:
            self.overall_green_until = now + ZONE_RECOVERY_LIGHT_SECONDS
        self.previous_warning = warning

        if warning:
            self.mode = "WARNING"
        elif now < self.overall_green_until:
            self.mode = "RECOVERED"
        elif bad_posture:
            self.mode = "PENDING"
        else:
            self.mode = "NORMAL"
        self.error_message = ""
        self.dirty = True

    def show_measurement_error(self, rmse_mm: float) -> None:
        self.mode = "MEASUREMENT_ERROR"
        self.error_message = f"곡선 오차 {rmse_mm:.1f} mm  센서 반사를 확인해주세요"
        self.dirty = True

    def _status_content(self) -> tuple[str, str, str, str]:
        if self.mode == "WAITING":
            return (
                "측정 준비",
                "바른 자세로 앉은 뒤 측정을 시작해주세요",
                self.COLORS["blue"],
                self.COLORS["blue_soft"],
            )
        if self.mode == "QUEUED":
            return (
                "측정 준비",
                "기준 자세 측정을 곧 시작합니다",
                self.COLORS["blue"],
                self.COLORS["blue_soft"],
            )
        if self.mode == "CALIBRATION":
            if self.calibration_stage == "settle":
                detail = f"바른 자세를 유지해주세요  {self.calibration_remaining:.1f}초 뒤 측정"
            else:
                detail = f"움직이지 말고 유지해주세요  남은 시간 {self.calibration_remaining:.1f}초"
            return (
                "기준 자세 측정 중",
                detail,
                self.COLORS["amber"],
                self.COLORS["amber_soft"],
            )
        if self.mode == "WARNING":
            return (
                "자세 교정 필요",
                "빨간 부위와 화살표를 따라 자세를 조절해주세요",
                self.COLORS["red"],
                self.COLORS["red_soft"],
            )
        if self.mode == "RECOVERED":
            return (
                "교정 완료",
                "해결된 부위를 3초 동안 초록색으로 표시합니다",
                self.COLORS["green"],
                self.COLORS["green_soft"],
            )
        if self.mode == "PENDING":
            return (
                "자세 변화 확인 중",
                "잠깐의 움직임인지 확인하고 있어요",
                self.COLORS["amber"],
                self.COLORS["amber_soft"],
            )
        if self.mode in ("MEASUREMENT_ERROR", "CALIBRATION_ERROR"):
            title = "측정 보류" if self.mode == "MEASUREMENT_ERROR" else "기준 저장 실패"
            return (
                title,
                self.error_message,
                self.COLORS["amber"],
                self.COLORS["amber_soft"],
            )
        return (
            "바른 자세",
            "현재 자세를 편안하게 유지해주세요",
            self.COLORS["blue"],
            self.COLORS["blue_soft"],
        )

    def _current_curve_color(self) -> str:
        if self.mode == "WARNING":
            return self.COLORS["red"]
        if self.mode == "RECOVERED":
            return self.COLORS["green"]
        if self.mode in ("PENDING", "MEASUREMENT_ERROR"):
            return self.COLORS["amber"]
        return self.COLORS["blue"]

    def _instruction_lines(self) -> List[str]:
        if self.mode == "WARNING":
            flagged = [key for key in SENSOR_KEYS if self.zone_states[key] == "red"]
            flagged.sort(key=lambda key: abs(self.shape_errors[key]), reverse=True)
            lines: List[str] = []
            for key in flagged[:2]:
                error = self.shape_errors[key]
                lines.append(
                    f"{ZONE_LABELS[key]}을 {movement_guidance(error)}  "
                    f"약 {abs(error):.1f} mm"
                )
            return lines or ["허리를 세우고 기준 곡선에 맞춰주세요"]

        green_zones = [key for key in SENSOR_KEYS if self.zone_states[key] == "green"]
        if self.mode == "RECOVERED" or green_zones:
            if green_zones:
                names = " · ".join(ZONE_LABELS[key] for key in green_zones)
                return [f"{names} 교정 완료", "초록 표시가 3초 뒤 자동으로 꺼집니다"]
            return ["자세 교정이 완료됐어요", "현재 자세를 유지해주세요"]

        if self.mode == "PENDING":
            return [
                "연속된 측정값을 빠르게 확인하고 있어요",
                "자세 이상이 확인되면 바로 빨간색으로 바뀝니다",
            ]

        if self.mode in ("MEASUREMENT_ERROR", "CALIBRATION_ERROR"):
            return ["센서 앞의 옷 주름과 각도를 확인해주세요", "값이 안정되면 다시 측정됩니다"]

        if self.baseline is not None and self.current_distances is not None:
            mean_shift = statistics.fmean(
                current - reference
                for current, reference in zip(
                    self.current_distances, self.baseline.distances_mm
                )
            )
            if mean_shift >= GLOBAL_SHIFT_NOTICE_MM:
                return ["등 곡선은 정상 범위예요", "몸 전체가 기준보다 앞쪽에 있어요"]
            if mean_shift <= -GLOBAL_SHIFT_NOTICE_MM:
                return ["등 곡선은 정상 범위예요", "몸 전체가 기준보다 등받이에 가까워요"]
        return ["현재 자세가 기준 곡선 안에 있어요", "그대로 편안하게 유지해주세요"]

    def _draw_card(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=self.COLORS["card"],
            outline=self.COLORS["border"],
            width=1,
        )

    def _draw(self) -> None:
        if self.closed:
            return
        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1100)
        height = max(canvas.winfo_height(), 700)

        canvas.create_text(
            24,
            30,
            anchor="w",
            text="실시간 척추 자세 가상평면",
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 20, "bold"),
        )
        canvas.create_text(
            24,
            56,
            anchor="w",
            text="S1 최상단 · S5 최하단 · S4 제외",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 10),
        )

        margin = 24
        gap = 18
        right_width = max(340, width * 0.30)
        left_x = margin
        left_y = 82
        left_right = width - margin - right_width - gap
        bottom = height - 24
        right_x = left_right + gap
        right_right = width - margin

        self._draw_card(left_x, left_y, left_right, bottom)
        canvas.create_text(
            left_x + 22,
            left_y + 26,
            anchor="w",
            text="측면에서 본 등 표면",
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 14, "bold"),
        )
        canvas.create_text(
            left_x + 22,
            left_y + 51,
            anchor="w",
            text="회색 점선은 기준 자세  색 선은 현재 자세",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 10),
        )

        plot_top = left_y + 94
        plot_bottom = bottom - 58
        plane_x = left_x + 130
        plot_right = left_right - 46
        min_height = 50.0
        max_height = 330.0

        all_distances: List[float] = []
        if self.baseline is not None:
            all_distances.extend(self.baseline.distances_mm)
        if self.current_distances is not None:
            all_distances.extend(self.current_distances)
        max_distance = max([180.0] + all_distances) + 35.0
        distance_scale = max(0.5, (plot_right - plane_x) / max_distance)

        def map_y(height_mm: float) -> float:
            ratio = (height_mm - min_height) / (max_height - min_height)
            return plot_bottom - ratio * (plot_bottom - plot_top)

        def map_x(distance_mm: float) -> float:
            return plane_x + max(0.0, distance_mm) * distance_scale

        canvas.create_line(
            plane_x,
            plot_top - 10,
            plane_x,
            plot_bottom + 10,
            fill=self.COLORS["plane"],
            width=3,
            dash=(8, 5),
        )
        canvas.create_text(
            plane_x,
            plot_top - 23,
            text="초음파 센서 가상평면",
            fill=self.COLORS["plane"],
            font=("Malgun Gothic", 10, "bold"),
        )

        if self.baseline is not None:
            baseline_points: List[float] = []
            for relative_y in range(-120, 121, 4):
                baseline_points.extend(
                    [
                        map_x(self.baseline.fit.distance_at_relative_y(relative_y)),
                        map_y(Y_ORIGIN_HEIGHT_FROM_SEAT_MM + relative_y),
                    ]
                )
            canvas.create_line(
                *baseline_points,
                fill=self.COLORS["baseline"],
                width=3,
                dash=(7, 5),
                smooth=True,
            )

        current_color = self._current_curve_color()
        if self.current_fit is not None:
            current_points: List[float] = []
            for relative_y in range(-120, 121, 4):
                current_points.extend(
                    [
                        map_x(self.current_fit.distance_at_relative_y(relative_y)),
                        map_y(Y_ORIGIN_HEIGHT_FROM_SEAT_MM + relative_y),
                    ]
                )
            canvas.create_line(
                *current_points,
                fill=current_color,
                width=5,
                smooth=True,
            )

        distance_by_key = (
            dict(zip(SENSOR_KEYS, self.current_distances))
            if self.current_distances is not None
            else {}
        )
        for key in ("s1", "s2", "s3", "s4", "s5"):
            sensor_y = map_y(ALL_SENSOR_HEIGHTS_FROM_SEAT_MM[key])
            if key == "s4":
                canvas.create_oval(
                    plane_x - 8,
                    sensor_y - 8,
                    plane_x + 8,
                    sensor_y + 8,
                    fill="#FFFFFF",
                    outline=self.COLORS["off"],
                    width=2,
                )
                canvas.create_line(
                    plane_x - 5,
                    sensor_y - 5,
                    plane_x + 5,
                    sensor_y + 5,
                    fill=self.COLORS["off"],
                    width=2,
                )
                canvas.create_line(
                    plane_x + 5,
                    sensor_y - 5,
                    plane_x - 5,
                    sensor_y + 5,
                    fill=self.COLORS["off"],
                    width=2,
                )
                canvas.create_text(
                    plane_x - 14,
                    sensor_y,
                    anchor="e",
                    text="S4  제외",
                    fill=self.COLORS["muted"],
                    font=("Malgun Gothic", 10),
                )
                continue

            state = self.zone_states.get(key, "off")
            state_color = {
                "red": self.COLORS["red"],
                "green": self.COLORS["green"],
                "off": self.COLORS["off"],
            }[state]
            soft_color = {
                "red": self.COLORS["red_soft"],
                "green": self.COLORS["green_soft"],
                "off": self.COLORS["off_soft"],
            }[state]

            canvas.create_text(
                plane_x - 14,
                sensor_y,
                anchor="e",
                text=f"{key.upper()}  {ZONE_LABELS[key]}",
                fill=self.COLORS["text"] if state != "off" else self.COLORS["muted"],
                font=("Malgun Gothic", 10, "bold" if state != "off" else "normal"),
            )
            canvas.create_oval(
                plane_x - 7,
                sensor_y - 7,
                plane_x + 7,
                sensor_y + 7,
                fill=self.COLORS["plane"],
                outline="#FFFFFF",
                width=2,
            )

            if key not in distance_by_key:
                continue
            current_x = map_x(distance_by_key[key])
            ray_color = state_color if state != "off" else "#A8B4C5"
            canvas.create_line(
                plane_x + 8,
                sensor_y,
                current_x,
                sensor_y,
                fill=ray_color,
                width=2,
                dash=(4, 4),
            )

            if state != "off":
                canvas.create_oval(
                    current_x - 15,
                    sensor_y - 15,
                    current_x + 15,
                    sensor_y + 15,
                    fill=soft_color,
                    outline="",
                )
            canvas.create_oval(
                current_x - 7,
                sensor_y - 7,
                current_x + 7,
                sensor_y + 7,
                fill=state_color if state != "off" else "#FFFFFF",
                outline=state_color if state != "off" else current_color,
                width=3,
            )

            if state == "red":
                error = self.shape_errors[key]
                target_x = current_x - error * distance_scale
                canvas.create_line(
                    current_x,
                    sensor_y - 17,
                    target_x,
                    sensor_y - 17,
                    fill=self.COLORS["red"],
                    width=3,
                    arrow="last",
                    arrowshape=(10, 12, 5),
                )
                canvas.create_text(
                    current_x + 12,
                    sensor_y + 17,
                    anchor="w",
                    text=f"{movement_guidance(error)}  {abs(error):.1f} mm",
                    fill=self.COLORS["red"],
                    font=("Malgun Gothic", 9, "bold"),
                )
            elif state == "green":
                canvas.create_text(
                    current_x + 12,
                    sensor_y + 16,
                    anchor="w",
                    text="교정 완료",
                    fill=self.COLORS["green"],
                    font=("Malgun Gothic", 9, "bold"),
                )
            else:
                canvas.create_text(
                    current_x + 10,
                    sensor_y + 14,
                    anchor="w",
                    text=f"{distance_by_key[key]:.0f} mm",
                    fill=self.COLORS["muted"],
                    font=("Malgun Gothic", 8),
                )

        canvas.create_text(
            left_x + 22,
            bottom - 28,
            anchor="w",
            text="센서면에서 등까지의 거리와 기준 곡선을 실시간 비교",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )

        status_title, status_detail, status_color, status_soft = self._status_content()
        status_bottom = left_y + 150
        self._draw_card(right_x, left_y, right_right, status_bottom)
        canvas.create_rectangle(
            right_x,
            left_y,
            right_x + 8,
            status_bottom,
            fill=status_color,
            outline=status_color,
        )
        canvas.create_oval(
            right_x + 24,
            left_y + 25,
            right_x + 50,
            left_y + 51,
            fill=status_soft,
            outline="",
        )
        canvas.create_oval(
            right_x + 32,
            left_y + 33,
            right_x + 42,
            left_y + 43,
            fill=status_color,
            outline="",
        )
        canvas.create_text(
            right_x + 62,
            left_y + 37,
            anchor="w",
            text=status_title,
            fill=status_color,
            font=("Malgun Gothic", 16, "bold"),
        )
        canvas.create_text(
            right_x + 24,
            left_y + 79,
            anchor="nw",
            width=max(270, right_right - right_x - 48),
            text=status_detail,
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 11),
        )

        instruction_top = status_bottom + 14
        instruction_bottom = instruction_top + 142
        self._draw_card(right_x, instruction_top, right_right, instruction_bottom)
        canvas.create_text(
            right_x + 20,
            instruction_top + 23,
            anchor="w",
            text="지금 할 동작",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 10, "bold"),
        )
        for line_index, line in enumerate(self._instruction_lines()):
            canvas.create_text(
                right_x + 20,
                instruction_top + 56 + line_index * 34,
                anchor="w",
                width=max(270, right_right - right_x - 40),
                text=line,
                fill=self.COLORS["red"] if self.mode == "WARNING" else self.COLORS["text"],
                font=("Malgun Gothic", 11, "bold" if line_index == 0 else "normal"),
            )

        metrics_top = instruction_bottom + 14
        metrics_bottom = min(metrics_top + 216, bottom - 116)
        self._draw_card(right_x, metrics_top, right_right, metrics_bottom)
        canvas.create_text(
            right_x + 20,
            metrics_top + 23,
            anchor="w",
            text="실시간 수치",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 10, "bold"),
        )
        if self.current_fit is not None and self.baseline is not None:
            values = (
                f"현재 b   {self.current_fit.b_mm_inv:+.6f} mm⁻¹\n"
                f"기준 b₀  {self.baseline.fit.b_mm_inv:+.6f} mm⁻¹\n"
                f"곡률손실  {self.curvature_loss:+.6f} mm⁻¹\n"
                f"곡선 RMSE  {self.current_fit.rmse_mm:.1f} mm"
            )
            canvas.create_text(
                right_x + 20,
                metrics_top + 53,
                anchor="nw",
                text=values,
                fill=self.COLORS["text"],
                font=("Consolas", 10),
            )
            gauge_y = metrics_bottom - 34
            gauge_x1 = right_x + 20
            gauge_x2 = right_right - 20
            canvas.create_rectangle(
                gauge_x1,
                gauge_y,
                gauge_x2,
                gauge_y + 10,
                fill=self.COLORS["off_soft"],
                outline="",
            )
            ratio = max(0.0, min(1.0, self.curvature_loss / max(self.threshold, 1.0e-12)))
            canvas.create_rectangle(
                gauge_x1,
                gauge_y,
                gauge_x1 + (gauge_x2 - gauge_x1) * ratio,
                gauge_y + 10,
                fill=status_color,
                outline="",
            )
            canvas.create_text(
                gauge_x1,
                gauge_y - 8,
                anchor="sw",
                text=f"경고 기준  {self.threshold:.6f} mm⁻¹",
                fill=self.COLORS["muted"],
                font=("Malgun Gothic", 8),
            )
        else:
            canvas.create_text(
                right_x + 20,
                metrics_top + 60,
                anchor="nw",
                text="기준 자세 측정 후\n실시간 수치가 표시됩니다",
                fill=self.COLORS["muted"],
                font=("Malgun Gothic", 11),
            )

        legend_top = metrics_bottom + 14
        legend_bottom = bottom
        if legend_top < legend_bottom - 20:
            self._draw_card(right_x, legend_top, right_right, legend_bottom)
            legend_items = (
                (self.COLORS["red"], "교정이 필요한 부위"),
                (self.COLORS["green"], "방금 해결된 부위  3초 표시"),
                (self.COLORS["off"], "정상 또는 점등 꺼짐"),
            )
            for index, (color, label) in enumerate(legend_items):
                item_y = legend_top + 27 + index * 25
                canvas.create_oval(
                    right_x + 20,
                    item_y - 6,
                    right_x + 32,
                    item_y + 6,
                    fill=color,
                    outline="",
                )
                canvas.create_text(
                    right_x + 42,
                    item_y,
                    anchor="w",
                    text=label,
                    fill=self.COLORS["text"],
                    font=("Malgun Gothic", 9),
                )

        canvas.create_text(
            width - 246,
            66,
            anchor="e",
            text="Enter 재측정  ·  F11 전체화면  ·  Esc 종료",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )


def monitor(
    source: SampleSource,
    baseline: Baseline,
    filters: MedianFilterBank,
    output_path: Path,
    b_threshold: float,
    alert_hold: float,
    recovery_hold: float,
    demo_duration: Optional[float] = None,
    dashboard: Optional[RealtimeDashboard] = None,
    trigger_watcher: Optional[MeasurementTriggerWatcher] = None,
) -> None:
    timer = WarningTimer(alert_hold, recovery_hold)
    baseline_sign = 1.0 if baseline.fit.b_mm_inv >= 0.0 else -1.0
    last_print_at = 0.0
    previous_warning = False
    started_at = time.monotonic()
    last_valid_sample_at = time.monotonic()
    last_signal_status_write_at = 0.0

    print("자세 감시를 시작합니다  S4는 제외됨  다시 보정하려면 Enter를 누르세요")

    while True:
        now = time.monotonic()
        if dashboard is not None:
            if not dashboard.pump():
                print("실시간 화면을 종료합니다")
                return
        if demo_duration is not None and now - started_at >= demo_duration:
            print("데모를 종료합니다")
            return

        dashboard_recalibration = (
            dashboard.consume_calibration_request() if dashboard is not None else False
        )
        start_triggered = (
            trigger_watcher.consume_new_trigger() if trigger_watcher is not None else False
        )
        if stdin_enter_pressed() or dashboard_recalibration or start_triggered:
            progress_callback = (
                dashboard.show_calibration
                if dashboard is not None
                else make_calibration_feedback_callback(
                    output_path,
                    lambda: trigger_watcher.last_token if trigger_watcher is not None else "",
                )
            )
            while True:
                try:
                    baseline = calibrate(source, filters, progress_callback)
                    break
                except RuntimeError as exc:
                    print(f"기준 자세 저장 실패: {exc}", file=sys.stderr)
                    write_feedback(
                        output_path,
                        {
                            "timestamp": time.time(),
                            "state": "CALIBRATION_ERROR",
                            "warning": False,
                            "signal_ok": False,
                            "message": str(exc),
                            "measurement_token": (
                                trigger_watcher.last_token
                                if trigger_watcher is not None
                                else ""
                            ),
                        },
                    )
                    if trigger_watcher is not None:
                        trigger_watcher.wait_for_next("등 초음파")
                        continue
                    if dashboard is not None:
                        dashboard.show_calibration_error(str(exc))
                    baseline = None
                    break
            if baseline is None:
                continue
            baseline_sign = 1.0 if baseline.fit.b_mm_inv >= 0.0 else -1.0
            timer.reset()
            previous_warning = False
            if dashboard is not None:
                dashboard.set_baseline(baseline, b_threshold)
            continue

        raw = source.read_sample()
        if raw is None:
            if (
                now - last_valid_sample_at >= SIGNAL_STALE_SECONDS
                and now - last_signal_status_write_at >= STATUS_HEARTBEAT_SECONDS
            ):
                write_feedback(
                    output_path,
                    {
                        "timestamp": time.time(),
                        "state": "SIGNAL_LOST",
                        "warning": False,
                        "signal_ok": False,
                        "message": "등 초음파 신호를 기다리고 있습니다",
                        "measurement_token": (
                            trigger_watcher.last_token if trigger_watcher is not None else ""
                        ),
                    },
                )
                last_signal_status_write_at = now
            time.sleep(IDLE_POLL_SECONDS)
            continue

        last_valid_sample_at = now

        filtered = filters.update(raw)
        fit = fit_quadratic(filtered)

        if fit.rmse_mm > MAX_FIT_RMSE_MM:
            payload: Dict[str, object] = {
                "timestamp": time.time(),
                "state": "MEASUREMENT_ERROR",
                "warning": False,
                "message": "센서 측정값을 확인하세요",
                "fit_rmse_mm": fit.rmse_mm,
                "measurement_token": (
                    trigger_watcher.last_token if trigger_watcher is not None else ""
                ),
            }
            write_feedback(output_path, payload)
            if dashboard is not None:
                dashboard.show_measurement_error(fit.rmse_mm)
            if now - last_print_at >= 0.8:
                print(f"측정 보류  곡선 RMSE={fit.rmse_mm:.1f} mm")
                last_print_at = now
            continue

        # 기준 곡률과 같은 방향의 성분이 줄어들수록 양수가 된다
        # 곡선이 평평해지거나 반대 방향으로 뒤집히면 curvature_loss가 증가한다
        curvature_loss = abs(baseline.fit.b_mm_inv) - baseline_sign * fit.b_mm_inv
        bad_posture = curvature_loss >= b_threshold
        warning = timer.update(bad_posture, now)

        payload = build_payload(
            filtered,
            fit,
            baseline,
            curvature_loss,
            b_threshold,
            warning,
        )
        payload["measurement_token"] = (
            trigger_watcher.last_token if trigger_watcher is not None else ""
        )
        write_feedback(output_path, payload)
        if dashboard is not None:
            dashboard.update_posture(
                distances_mm=filtered,
                fit=fit,
                baseline=baseline,
                curvature_loss=curvature_loss,
                threshold=b_threshold,
                bad_posture=bad_posture,
                warning=warning,
                now=now,
            )

        if warning != previous_warning or now - last_print_at >= 0.8:
            print(
                f"{payload['message']}  "
                f"b={fit.b_mm_inv:+.6f}, "
                f"b0={baseline.fit.b_mm_inv:+.6f}, "
                f"곡률손실={curvature_loss:+.6f} mm^-1"
            )
            last_print_at = now
            previous_warning = warning


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="S4를 제외한 초음파센서 4개로 등 표면 곡률을 감시합니다"
    )
    parser.add_argument("--port", default="/dev/ttyACM0", help="Arduino 시리얼 포트")
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("posture_feedback.json"),
        help="디스플레이 프로그램이 읽을 상태 JSON 파일",
    )
    parser.add_argument(
        "--b-threshold",
        type=float,
        default=DEFAULT_B_LOSS_THRESHOLD,
        help="기준 자세 대비 곡률 손실 임계값, 단위 mm^-1",
    )
    parser.add_argument("--alert-hold", type=float, default=DEFAULT_ALERT_HOLD_SECONDS)
    parser.add_argument("--recovery-hold", type=float, default=DEFAULT_RECOVERY_HOLD_SECONDS)
    parser.add_argument(
        "--median-window",
        type=int,
        default=MEDIAN_WINDOW,
        help="실시간 중앙값 필터 크기, 1 이상의 홀수이며 작을수록 빠르게 반응",
    )
    parser.add_argument("--auto-calibrate", action="store_true", help="Enter 없이 바로 기준 측정")
    parser.add_argument(
        "--wait-for-trigger",
        type=Path,
        default=None,
        help="app.py의 START(S) 측정 신호 JSON이 갱신될 때까지 기준 측정을 시작하지 않음",
    )
    parser.add_argument("--demo", action="store_true", help="Arduino 없이 동작을 시험")
    parser.add_argument("--demo-duration", type=float, default=7.5)
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="실시간 창 없이 기존 터미널 출력만 사용",
    )
    parser.add_argument("--fullscreen", action="store_true", help="실시간 창을 전체화면으로 시작")
    parser.add_argument("--window-width", type=int, default=1280)
    parser.add_argument("--window-height", type=int, default=760)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.b_threshold <= 0.0:
        print("--b-threshold는 0보다 커야 합니다", file=sys.stderr)
        return 2
    if args.alert_hold < 0.0 or args.recovery_hold < 0.0:
        print("--alert-hold와 --recovery-hold는 0 이상이어야 합니다", file=sys.stderr)
        return 2
    if args.median_window < 1 or args.median_window % 2 == 0:
        print("--median-window는 1 이상의 홀수여야 합니다", file=sys.stderr)
        return 2

    source: SampleSource
    if args.demo:
        source = DemoSource()
        args.auto_calibrate = True
    else:
        try:
            source = ArduinoSerialSource(args.port, args.baudrate)
        except Exception as exc:
            print(f"시리얼 연결 실패: {exc}", file=sys.stderr)
            return 1

    filters = MedianFilterBank(args.median_window)

    dashboard: Optional[RealtimeDashboard] = None
    if not args.no_window:
        try:
            dashboard = RealtimeDashboard(
                width=max(1100, args.window_width),
                height=max(700, args.window_height),
                fullscreen=args.fullscreen,
                alert_hold=args.alert_hold,
            )
        except Exception as exc:
            print(
                f"실시간 화면 시작 실패: {exc}\n"
                "터미널만 사용하려면 --no-window 옵션을 추가해주세요",
                file=sys.stderr,
            )
            return 1

    trigger_watcher: Optional[MeasurementTriggerWatcher] = None
    if args.wait_for_trigger is not None:
        trigger_watcher = MeasurementTriggerWatcher(args.wait_for_trigger)
        write_feedback(
            args.output,
            {
                "timestamp": time.time(),
                "state": "WAITING_FOR_START",
                "warning": False,
                "message": "주행 시작 버튼을 기다리고 있습니다",
                "measurement_token": "",
            },
        )
        trigger_watcher.wait_for_next("등 초음파")
    elif not args.auto_calibrate:
        if dashboard is not None:
            if not dashboard.wait_for_calibration_start():
                return 0
        else:
            input("바른 자세로 앉은 뒤 Enter를 누르세요 ")

    while True:
        progress_callback = (
            dashboard.show_calibration
            if dashboard is not None
            else make_calibration_feedback_callback(
                args.output,
                lambda: trigger_watcher.last_token if trigger_watcher is not None else "",
            )
        )
        try:
            write_feedback(
                args.output,
                {
                    "timestamp": time.time(),
                    "state": "CALIBRATING",
                    "warning": False,
                    "message": "등 기준 자세를 측정하고 있습니다",
                    "measurement_token": (
                        trigger_watcher.last_token if trigger_watcher is not None else ""
                    ),
                },
            )
            baseline = calibrate(source, filters, progress_callback)
            if dashboard is not None and dashboard.closed:
                return 0
            break
        except RuntimeError as exc:
            print(f"기준 자세 저장 실패: {exc}", file=sys.stderr)
            write_feedback(
                args.output,
                {
                    "timestamp": time.time(),
                    "state": "CALIBRATION_ERROR",
                    "warning": False,
                    "message": str(exc),
                    "measurement_token": (
                        trigger_watcher.last_token if trigger_watcher is not None else ""
                    ),
                },
            )
            if trigger_watcher is not None:
                trigger_watcher.wait_for_next("등 초음파")
                continue
            if dashboard is None:
                return 1
            dashboard.show_calibration_error(str(exc))
            if not dashboard.wait_for_calibration_start():
                return 0

    if dashboard is not None:
        dashboard.set_baseline(baseline, args.b_threshold)

    try:
        monitor(
            source=source,
            baseline=baseline,
            filters=filters,
            output_path=args.output,
            b_threshold=args.b_threshold,
            alert_hold=args.alert_hold,
            recovery_hold=args.recovery_hold,
            demo_duration=args.demo_duration if args.demo else None,
            dashboard=dashboard,
            trigger_watcher=trigger_watcher,
        )
    except KeyboardInterrupt:
        print("\n종료합니다")
    finally:
        if dashboard is not None:
            dashboard.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
