#!/usr/bin/env python3
"""HC-SR04 2개로 후두부-C7 목 자세 대체각을 실시간 감시한다

Arduino 입력 형식
  {"t_ms":1234,"head_mm":205.4,"c7_mm":187.2}

실행 흐름
  1. 바른 자세에서 버튼 또는 Enter를 누른다
  2. 2초 준비 후 5초간 기준 자세를 측정한다
  3. 두 센서의 기준값이 같아지도록 센서별 오프셋을 자동 계산한다
  4. 범위 검사, 지속성 스파이크 제거, 중앙값, EMA 필터를 차례로 적용한다
  5. 기준보다 대체각이 7도 이상 나빠진 자세가 7초 지속되면 피드백한다

중요
  후두부와 C7을 뒤에서 측정하므로 이 값은 귀의 이주와 C7을 사진에서 표시해
  계산하는 임상적 CVA 절대값이 아니다
  초기 자세를 90도로 맞춘 뒤 기준 대비 목의 전방 이동을 각도로 나타내는
  후두부-C7 자세 변화용 CVA 대체각이다
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import statistics
import sys
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Protocol, Sequence, Tuple


# ---------------------------------------------------------------------------
# 개럿이 설치 환경에 맞춰 조절할 값
# ---------------------------------------------------------------------------

DEFAULT_BAUDRATE = 115200

# 여러 Arduino가 동시에 연결되는 프로젝트 환경에서는 포트 자동 선택이 위험할 수 있다.
# 라즈베리파이에서는 되도록 SEAT_ID_NECK_PORT=/dev/ttyUSB1 처럼 명시해서 실행한다.
DEFAULT_NECK_PORT = os.environ.get("SEAT_ID_NECK_PORT", "").strip()

# 반드시 두 센서 송수신부 중심 사이의 실제 세로 간격으로 바꿔준다
DEFAULT_VERTICAL_GAP_MM = 200.0

# 허리 코드와 같은 기준 측정 흐름
CALIBRATION_SETTLE_SECONDS = 2.0
CALIBRATION_SECONDS = 5.0
# 실제 허브 환경에서 순간 null과 필터 거부가 있어도 한 번의 START로
# 보정을 마칠 수 있게 최소 개수를 현실적인 수준으로 두고 최대 수집 시간을 연장한다.
MIN_CALIBRATION_SAMPLES = 12
CALIBRATION_MAX_SECONDS = 10.0

# 초기 실험값이며 의학적으로 검증된 진단 기준이 아니다
DEFAULT_ANGLE_DROP_THRESHOLD_DEG = 7.0
# 실제 의자에서는 초음파 센서가 머리 앞쪽을 향해 있어, 앞으로 숙일수록
# HEAD 거리가 감소하고 계산 각도는 증가한다. 기존 수식의 방향을 반전한다.
NECK_FORWARD_DIRECTION_SIGN = -1.0
DEFAULT_POSTURE_HOLD_SECONDS = 7.0
DEFAULT_RECOVERY_HOLD_SECONDS = 3.0
DEFAULT_RECOVERY_MARGIN_DEG = 1.5

# 측정 및 필터 설정
MIN_DISTANCE_MM = 20.0
MAX_DISTANCE_MM = 500.0
MEDIAN_WINDOW = 5
HISTORY_WINDOW = 7
EMA_ALPHA = 0.35
MIN_SPIKE_GATE_MM = 18.0
MAD_GATE_MULTIPLIER = 6.0
REAL_STEP_CONFIRM_SAMPLES = 4
REAL_STEP_CLUSTER_MM = 12.0
# 전체 5~10초 구간에 한 번이라도 큰 반사가 섞였다고 보정을 전부 버리지 않는다.
# 수집값 가운데 연속된 가장 안정적인 구간을 찾아 기준값으로 사용한다.
BASELINE_STABLE_WINDOW_SAMPLES = 12
# HC-SR04 두 채널의 설치 오차와 머리카락/옷 반사를 감안한 실험용 허용치다.
# 35 mm를 넘으면 가장 안정적인 구간조차 흔들린 것이므로 다시 측정한다.
MAX_BASELINE_RELATIVE_SPAN_MM = 35.0

# 한 프레임에서 HEAD 또는 C7 한쪽만 null이어도 직전의 신선한 값을 짧게 재사용한다.
# 55 ms 발사 간격 기준 약 3프레임 정도를 허용해 순간 null로 인한 깜빡임을 줄인다.
PARTIAL_PAIR_STALE_SECONDS = 0.60
SERIAL_RECONNECT_COOLDOWN_SECONDS = 0.60

# 신호 없음 표시는 너무 민감하게 깜빡이지 않도록 1.5초로 둔다.
SIGNAL_STALE_SECONDS = 1.5

GUI_UPDATE_MS = 20
FEEDBACK_WRITE_INTERVAL_SECONDS = 0.20
STATUS_HEARTBEAT_SECONDS = 0.50


def valid_distance(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and MIN_DISTANCE_MM <= number <= MAX_DISTANCE_MM


def percentile(values: Sequence[float], fraction: float) -> float:
    ordered = sorted(float(value) for value in values)
    if not ordered:
        raise ValueError("빈 값의 백분위수는 계산할 수 없습니다")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def cva_surrogate_angle_deg(
    corrected_head_mm: float,
    corrected_c7_mm: float,
    vertical_gap_mm: float,
) -> float:
    """C7에서 후두부로 향하는 선과 수평선 사이의 대체각을 반환한다

    이 함수는 두 센서 거리로 기하학적 각도만 계산한다.
    실제 설치 방향에 따른 전방/후방 부호는 forward_angle_change_deg()에서 적용한다.
    """
    if vertical_gap_mm <= 0.0:
        raise ValueError("센서 세로 간격은 0보다 커야 합니다")
    horizontal_gap_mm = float(corrected_head_mm) - float(corrected_c7_mm)
    return math.degrees(math.atan2(float(vertical_gap_mm), horizontal_gap_mm))


def forward_angle_change_deg(baseline_angle_deg: float, current_angle_deg: float) -> float:
    """실제 설치 방향을 반영한 목 전방 변화량. 앞으로 숙이면 양수다."""

    return NECK_FORWARD_DIRECTION_SIGN * (
        float(baseline_angle_deg) - float(current_angle_deg)
    )


@dataclass(frozen=True)
class Baseline:
    raw_head_mm: float
    raw_c7_mm: float
    common_reference_mm: float
    head_offset_mm: float
    c7_offset_mm: float
    baseline_angle_deg: float
    relative_p90_p10_span_mm: float
    sample_count: int

    def correct(self, head_mm: float, c7_mm: float) -> Tuple[float, float]:
        return (
            float(head_mm) - self.head_offset_mm,
            float(c7_mm) - self.c7_offset_mm,
        )


@dataclass(frozen=True)
class Analysis:
    state: str
    message: str
    warning: bool
    corrected_head_mm: float
    corrected_c7_mm: float
    horizontal_gap_mm: float
    current_angle_deg: float
    angle_drop_deg: float
    bad_duration_seconds: float


class SampleSource(Protocol):
    label: str

    def read_latest(self) -> Optional[Tuple[float, float]]:
        ...

    def clear(self) -> None:
        ...

    def baseline_saved(self) -> None:
        ...

    def close(self) -> None:
        ...


def choose_serial_port() -> str:
    try:
        from serial.tools import list_ports  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "pyserial이 필요합니다  터미널에서 python -m pip install pyserial 을 실행해주세요"
        ) from exc

    ports = list(list_ports.comports())
    if not ports:
        raise RuntimeError(
            "연결된 시리얼 장치를 찾지 못했습니다  USB 연결과 Arduino 업로드를 확인해주세요"
        )

    keywords = (
        "arduino",
        "ch340",
        "wch",
        "cp210",
        "usb serial",
        "usb-serial",
        "ttyacm",
        "ttyusb",
    )

    def score(port: object) -> Tuple[int, str]:
        device = str(getattr(port, "device", ""))
        description = str(getattr(port, "description", ""))
        manufacturer = str(getattr(port, "manufacturer", ""))
        searchable = f"{device} {description} {manufacturer}".lower()
        points = sum(4 for keyword in keywords if keyword in searchable)
        if getattr(port, "vid", None) is not None:
            points += 2
        return points, device

    selected = max(ports, key=score)
    selected_device = str(selected.device)
    candidates = ", ".join(str(port.device) for port in ports)
    print(f"시리얼 자동 선택={selected_device}  검색된 포트={candidates}")
    return selected_device


class ArduinoSerialSource:
    """목 초음파 JSON을 안전하게 읽고 USB 순간 끊김과 부분 프레임을 복구한다."""

    def __init__(self, port: str, baudrate: int) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:
            raise RuntimeError("pyserial이 필요합니다  터미널에서 python -m pip install pyserial 을 실행해주세요") from exc
        port = str(port or "").strip()
        if port == "":
            raise RuntimeError("목 초음파 Arduino 포트가 지정되지 않았습니다. SEAT_ID_NECK_PORT 또는 --port를 지정해주세요.")
        self._serial_module = serial
        self.port = choose_serial_port() if port.lower() == "auto" else port
        self.baudrate = int(baudrate)
        self.serial = None
        self.label = f"{self.port} · {self.baudrate} bps"
        self.receive_buffer = bytearray()
        self.latest_head_mm: Optional[float] = None
        self.latest_c7_mm: Optional[float] = None
        self.latest_head_at = 0.0
        self.latest_c7_at = 0.0
        self.last_reconnect_attempt = 0.0
        self._open()

    def _open(self) -> None:
        kwargs = {"port": self.port, "baudrate": self.baudrate, "timeout": 0.0, "write_timeout": 0.2}
        try:
            self.serial = self._serial_module.Serial(exclusive=True, **kwargs)
        except TypeError:
            self.serial = self._serial_module.Serial(**kwargs)
        time.sleep(1.0)
        self.receive_buffer.clear()
        print(f"목 초음파 시리얼 연결: {self.port}")

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
            print(f"목 초음파 시리얼 재연결 완료: {self.port}")
            return True
        except Exception as exc:
            print(f"목 초음파 시리얼 재연결 대기: {exc}", file=sys.stderr)
            return False

    def clear(self) -> None:
        self.receive_buffer.clear()
        self.latest_head_mm = None
        self.latest_c7_mm = None
        self.latest_head_at = 0.0
        self.latest_c7_at = 0.0
        try:
            if self.serial is None:
                return
            waiting = int(getattr(self.serial, "in_waiting", 0))
            if waiting > 0:
                self.serial.read(waiting)
        except Exception as exc:
            print(f"목 초음파 버퍼 정리 중 USB 오류: {exc}", file=sys.stderr)
            self._reconnect()

    def _update_cached_value(self, key: str, value: object, now: float) -> None:
        if not valid_distance(value):
            return
        if key == "head_mm":
            self.latest_head_mm = float(value)
            self.latest_head_at = now
        elif key == "c7_mm":
            self.latest_c7_mm = float(value)
            self.latest_c7_at = now

    def _cached_pair_if_fresh(self, now: float) -> Optional[Tuple[float, float]]:
        if self.latest_head_mm is None or self.latest_c7_mm is None:
            return None
        if now - self.latest_head_at > PARTIAL_PAIR_STALE_SECONDS:
            return None
        if now - self.latest_c7_at > PARTIAL_PAIR_STALE_SECONDS:
            return None
        return self.latest_head_mm, self.latest_c7_mm

    def read_latest(self) -> Optional[Tuple[float, float]]:
        try:
            if self.serial is None:
                if not self._reconnect():
                    return None
            waiting = int(getattr(self.serial, "in_waiting", 0))
            if waiting > 0:
                self.receive_buffer.extend(self.serial.read(waiting))
        except Exception as exc:
            print(f"목 초음파 읽기 오류, 재연결 시도: {exc}", file=sys.stderr)
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
            try:
                payload = json.loads(raw_line.decode("utf-8", errors="ignore"))
            except (UnicodeError, json.JSONDecodeError, TypeError):
                continue
            if not isinstance(payload, dict):
                continue
            self._update_cached_value("head_mm", payload.get("head_mm"), now)
            self._update_cached_value("c7_mm", payload.get("c7_mm"), now)
        return self._cached_pair_if_fresh(now)

    def baseline_saved(self) -> None:
        return None

    def close(self) -> None:
        try:
            if self.serial is not None:
                self.serial.close()
        except Exception:
            pass


class DemoSource:
    """센서 없이 오프셋, 스파이크 필터, 거북목 경고와 회복을 확인한다"""

    def __init__(self) -> None:
        self.label = "센서 없는 데모 모드"
        self.random = random.Random(20260807)
        self.next_sample_at = time.monotonic()
        self.monitoring_started_at: Optional[float] = None
        self.frame = 0

    def clear(self) -> None:
        self.next_sample_at = time.monotonic()

    def baseline_saved(self) -> None:
        self.monitoring_started_at = time.monotonic()

    def close(self) -> None:
        return None

    def read_latest(self) -> Optional[Tuple[float, float]]:
        now = time.monotonic()
        if now < self.next_sample_at:
            return None
        self.next_sample_at = now + 0.070
        self.frame += 1

        head_forward_mm = 0.0
        if self.monitoring_started_at is not None:
            elapsed = now - self.monitoring_started_at
            if 2.0 <= elapsed < 4.0:
                head_forward_mm = 30.0 * (elapsed - 2.0) / 2.0
            elif 4.0 <= elapsed < 9.0:
                head_forward_mm = 30.0
            elif 9.0 <= elapsed < 11.0:
                head_forward_mm = 30.0 * (11.0 - elapsed) / 2.0

        # 실제 설치처럼 앞으로 숙이면 HEAD 센서와 머리 사이 거리가 감소한다.
        head = 225.0 - head_forward_mm + self.random.uniform(-1.2, 1.2)
        c7 = 185.0 + self.random.uniform(-1.0, 1.0)

        # 실제 자세 변화와 달리 한 번만 나타나는 큰 값은 필터가 제거해야 한다
        if self.frame % 47 == 0:
            head += 85.0
        if self.frame % 73 == 0:
            c7 -= 70.0
        return head, c7


class RobustPairFilter:
    """지속성 스파이크 판별 뒤 중앙값과 EMA를 적용하는 2채널 필터"""

    def __init__(self) -> None:
        self.histories: List[Deque[float]] = [
            deque(maxlen=HISTORY_WINDOW),
            deque(maxlen=HISTORY_WINDOW),
        ]
        self.step_candidates: List[Deque[float]] = [
            deque(maxlen=REAL_STEP_CONFIRM_SAMPLES),
            deque(maxlen=REAL_STEP_CONFIRM_SAMPLES),
        ]
        self.ema_values: List[Optional[float]] = [None, None]
        self.rejected_count = 0

    def clear(self, keep_rejected_count: bool = True) -> None:
        for values in self.histories:
            values.clear()
        for values in self.step_candidates:
            values.clear()
        self.ema_values = [None, None]
        if not keep_rejected_count:
            self.rejected_count = 0

    def _filter_channel(self, index: int, value: float) -> float:
        history = self.histories[index]
        candidates = self.step_candidates[index]
        accepted = float(value)

        if len(history) >= 3:
            center = float(statistics.median(history))
            mad = float(
                statistics.median(abs(sample - center) for sample in history)
            )
            robust_sigma = 1.4826 * mad
            gate = max(MIN_SPIKE_GATE_MM, MAD_GATE_MULTIPLIER * robust_sigma)

            if abs(value - center) > gate:
                if candidates and abs(value - statistics.median(candidates)) > REAL_STEP_CLUSTER_MM:
                    candidates.clear()
                candidates.append(float(value))

                # 비슷한 큰 변화가 연속되면 순간 튐이 아니라 실제 빠른 자세 이동으로 인정한다
                if (
                    len(candidates) >= REAL_STEP_CONFIRM_SAMPLES
                    and max(candidates) - min(candidates) <= REAL_STEP_CLUSTER_MM
                ):
                    accepted = float(statistics.median(candidates))
                    history.clear()
                    history.append(accepted)
                    candidates.clear()
                else:
                    self.rejected_count += 1
                    accepted = center
            else:
                candidates.clear()
                history.append(accepted)
        else:
            candidates.clear()
            history.append(accepted)

        median_value = float(
            statistics.median(list(history)[-MEDIAN_WINDOW:])
        )
        previous_ema = self.ema_values[index]
        ema = (
            median_value
            if previous_ema is None
            else EMA_ALPHA * median_value + (1.0 - EMA_ALPHA) * previous_ema
        )
        self.ema_values[index] = ema
        return ema

    def update(self, pair: Sequence[float]) -> Tuple[float, float]:
        if len(pair) != 2 or not all(valid_distance(value) for value in pair):
            raise ValueError("후두부와 C7의 유효한 거리값 2개가 필요합니다")
        return (
            self._filter_channel(0, float(pair[0])),
            self._filter_channel(1, float(pair[1])),
        )


def _baseline_window_metrics(
    samples: Sequence[Tuple[float, float]],
) -> Tuple[float, float, float, float]:
    """연속 보정 구간의 흔들림과 안정도 점수를 계산한다."""

    head_values = [pair[0] for pair in samples]
    c7_values = [pair[1] for pair in samples]
    relative_values = [head - c7 for head, c7 in samples]

    head_span = percentile(head_values, 0.90) - percentile(head_values, 0.10)
    c7_span = percentile(c7_values, 0.90) - percentile(c7_values, 0.10)
    relative_span = percentile(relative_values, 0.90) - percentile(relative_values, 0.10)

    # 상대 위치가 가장 중요하다. 두 센서가 함께 앞뒤로 조금 움직이는 현상은
    # 상대 위치보다 낮은 가중치로 반영해 지나치게 민감한 보정 실패를 막는다.
    stability_score = relative_span + 0.20 * (head_span + c7_span)
    return stability_score, relative_span, head_span, c7_span


def select_stable_baseline_samples(
    samples: Sequence[Tuple[float, float]],
) -> Tuple[List[Tuple[float, float]], int, float]:
    """수집값에서 가장 안정적인 연속 구간을 선택한다.

    측정을 시작하거나 끝낼 때 생긴 움직임과 초음파 단발성 반사를 보정값에서
    제외한다. 시간 순서를 무시한 임의 샘플 선택은 하지 않는다.
    """

    if len(samples) < MIN_CALIBRATION_SAMPLES:
        raise RuntimeError(
            f"유효 측정값이 {len(samples)}개뿐입니다  최소 {MIN_CALIBRATION_SAMPLES}개가 필요합니다"
        )

    window_size = min(
        len(samples),
        max(MIN_CALIBRATION_SAMPLES, BASELINE_STABLE_WINDOW_SAMPLES),
    )
    best_start = 0
    best_samples = list(samples[:window_size])
    best_score, best_relative_span, _, _ = _baseline_window_metrics(best_samples)

    for start in range(1, len(samples) - window_size + 1):
        candidate = list(samples[start : start + window_size])
        score, relative_span, _, _ = _baseline_window_metrics(candidate)
        if score < best_score:
            best_start = start
            best_samples = candidate
            best_score = score
            best_relative_span = relative_span

    return best_samples, best_start, best_relative_span


def build_baseline(samples: Sequence[Tuple[float, float]]) -> Baseline:
    if len(samples) < MIN_CALIBRATION_SAMPLES:
        raise RuntimeError(
            f"유효 측정값이 {len(samples)}개뿐입니다  최소 {MIN_CALIBRATION_SAMPLES}개가 필요합니다"
        )

    stable_samples, stable_start, relative_span = select_stable_baseline_samples(samples)
    if relative_span > MAX_BASELINE_RELATIVE_SPAN_MM:
        raise RuntimeError(
            "기준 측정 중 안정적인 목 위치를 찾지 못했습니다  "
            f"가장 안정적인 {len(stable_samples)}개 구간의 변화폭={relative_span:.1f} mm  "
            "두 센서가 후두부와 C7을 정면으로 보도록 각도를 확인한 뒤 다시 측정해주세요"
        )

    if len(samples) > len(stable_samples):
        print(
            "목 기준값 안정 구간 자동 선택  "
            f"전체={len(samples)}개  선택={stable_start + 1}~"
            f"{stable_start + len(stable_samples)}번  변화폭={relative_span:.1f} mm"
        )

    head_values = [pair[0] for pair in stable_samples]
    c7_values = [pair[1] for pair in stable_samples]

    raw_head = float(statistics.median(head_values))
    raw_c7 = float(statistics.median(c7_values))
    common_reference = (raw_head + raw_c7) / 2.0

    # corrected = raw - offset
    # 따라서 기준 자세에서는 HEAD와 C7 모두 common_reference가 된다
    head_offset = raw_head - common_reference
    c7_offset = raw_c7 - common_reference
    corrected_head = raw_head - head_offset
    corrected_c7 = raw_c7 - c7_offset
    baseline_angle = cva_surrogate_angle_deg(
        corrected_head,
        corrected_c7,
        DEFAULT_VERTICAL_GAP_MM,
    )

    return Baseline(
        raw_head_mm=raw_head,
        raw_c7_mm=raw_c7,
        common_reference_mm=common_reference,
        head_offset_mm=head_offset,
        c7_offset_mm=c7_offset,
        baseline_angle_deg=baseline_angle,
        relative_p90_p10_span_mm=relative_span,
        sample_count=len(stable_samples),
    )


class PostureTimer:
    def __init__(
        self,
        angle_threshold_deg: float,
        hold_seconds: float,
        recovery_margin_deg: float,
        recovery_hold_seconds: float,
    ) -> None:
        self.angle_threshold_deg = angle_threshold_deg
        self.hold_seconds = hold_seconds
        self.recovery_margin_deg = recovery_margin_deg
        self.recovery_hold_seconds = recovery_hold_seconds
        self.warning = False
        self.bad_since: Optional[float] = None
        self.good_since: Optional[float] = None
        self.recovered_until = 0.0

    def reset(self) -> None:
        self.warning = False
        self.bad_since = None
        self.good_since = None
        self.recovered_until = 0.0

    def update(self, angle_drop_deg: float, now: float) -> Tuple[str, bool, float]:
        bad = angle_drop_deg >= self.angle_threshold_deg
        release_threshold = max(
            0.0,
            self.angle_threshold_deg - self.recovery_margin_deg,
        )

        if not self.warning:
            self.good_since = None
            if bad:
                if self.bad_since is None:
                    self.bad_since = now
                bad_duration = now - self.bad_since
                if bad_duration >= self.hold_seconds:
                    self.warning = True
                    return "WARNING", True, bad_duration
                return "PENDING", False, bad_duration

            self.bad_since = None
            if now < self.recovered_until:
                return "RECOVERED", False, 0.0
            return "NORMAL", False, 0.0

        # 경고 중에는 기준보다 충분히 회복된 상태가 이어져야 해제한다
        self.bad_since = None
        if angle_drop_deg <= release_threshold:
            if self.good_since is None:
                self.good_since = now
            recovered_for = now - self.good_since
            if recovered_for >= self.recovery_hold_seconds:
                self.warning = False
                self.good_since = None
                self.recovered_until = now + 2.5
                return "RECOVERED", False, 0.0
            return "RECOVERING", True, recovered_for

        self.good_since = None
        return "WARNING", True, self.hold_seconds


def state_message(state: str) -> str:
    return {
        "NORMAL": "현재 목 자세가 기준 범위 안에 있어요",
        "PENDING": "거북목 자세가 계속되는지 확인하고 있어요",
        "WARNING": "턱을 가볍게 당기고 후두부를 뒤로 이동해주세요",
        "RECOVERING": "바른 자세가 유지되는지 확인하고 있어요",
        "RECOVERED": "목 자세 교정이 완료됐어요",
    }.get(state, "목 자세를 측정하고 있어요")


def write_feedback(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def make_calibration_feedback_callback(
    output_path: Path,
    token_provider: Optional[Callable[[], str]] = None,
) -> Callable[[str, float], None]:
    """보정 중 JSON timestamp를 갱신해 PyQt 카드가 대기 상태로 돌아가지 않게 한다."""

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
                "message": f"목 기준 자세 {phase_text}",
                "warning": False,
                "signal_ok": True,
                "clinical_cva": False,
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

def build_feedback_payload(
    baseline: Baseline,
    raw_pair: Optional[Tuple[float, float]],
    filtered_pair: Tuple[float, float],
    analysis: Analysis,
    angle_threshold_deg: float,
    posture_hold_seconds: float,
    rejected_spike_count: int,
    vertical_gap_mm: float,
) -> Dict[str, object]:
    """GUI 모드와 no-window 모드가 같은 JSON 구조를 쓰도록 payload를 만든다."""

    return {
        "timestamp": time.time(),
        "state": analysis.state,
        "message": analysis.message,
        "warning": analysis.warning,
        "signal_ok": True,
        "raw_mm": {
            "head": None if raw_pair is None else round(raw_pair[0], 2),
            "c7": None if raw_pair is None else round(raw_pair[1], 2),
        },
        "filtered_raw_mm": {
            "head": round(filtered_pair[0], 2),
            "c7": round(filtered_pair[1], 2),
        },
        "corrected_mm": {
            "head": round(analysis.corrected_head_mm, 2),
            "c7": round(analysis.corrected_c7_mm, 2),
        },
        "offsets_mm": {
            "head": round(baseline.head_offset_mm, 2),
            "c7": round(baseline.c7_offset_mm, 2),
        },
        "baseline": asdict(baseline),
        "vertical_gap_mm": vertical_gap_mm,
        "cva_surrogate_angle_deg": round(analysis.current_angle_deg, 2),
        "angle_drop_deg": round(analysis.angle_drop_deg, 2),
        "angle_drop_threshold_deg": angle_threshold_deg,
        "bad_duration_seconds": round(analysis.bad_duration_seconds, 2),
        "posture_hold_seconds": posture_hold_seconds,
        "rejected_spike_count": rejected_spike_count,
        "clinical_cva": False,
    }


def collect_baseline_for_headless(
    source: SampleSource,
    pair_filter: RobustPairFilter,
    vertical_gap_mm: float,
    progress_callback: Optional[Callable[[str, float], None]] = None,
) -> Baseline:
    """no-window 모드에서 기준 자세를 측정한다."""

    print(
        f"바른 목 자세를 잡아주세요  {CALIBRATION_SETTLE_SECONDS:.1f}초 뒤에 "
        f"{CALIBRATION_SECONDS:.1f}초 동안 기준값을 측정합니다"
    )

    source.clear()
    pair_filter.clear(keep_rejected_count=False)

    settle_deadline = time.monotonic() + CALIBRATION_SETTLE_SECONDS
    while time.monotonic() < settle_deadline:
        remaining = max(0.0, settle_deadline - time.monotonic())
        if progress_callback is not None:
            progress_callback("settle", remaining)
        source.read_latest()
        time.sleep(0.005)

    print("기준 측정을 시작합니다  머리와 목을 움직이지 마세요")
    source.clear()
    pair_filter.clear(keep_rejected_count=False)

    samples: List[Tuple[float, float]] = []
    measurement_started_at = time.monotonic()
    minimum_deadline = measurement_started_at + CALIBRATION_SECONDS
    hard_deadline = measurement_started_at + CALIBRATION_MAX_SECONDS

    while time.monotonic() < hard_deadline:
        now = time.monotonic()
        if progress_callback is not None:
            progress_callback("measure", max(0.0, minimum_deadline - now))
        pair = source.read_latest()
        if pair is None:
            time.sleep(0.005)
            continue

        try:
            filtered = pair_filter.update(pair)
        except ValueError:
            continue

        samples.append(filtered)

        if now >= minimum_deadline and len(samples) >= MIN_CALIBRATION_SAMPLES:
            break

    baseline = build_baseline(samples)

    corrected_head, corrected_c7 = baseline.correct(
        baseline.raw_head_mm,
        baseline.raw_c7_mm,
    )

    # 실제 설치 간격으로 기준각을 다시 계산한다.
    baseline = Baseline(
        raw_head_mm=baseline.raw_head_mm,
        raw_c7_mm=baseline.raw_c7_mm,
        common_reference_mm=baseline.common_reference_mm,
        head_offset_mm=baseline.head_offset_mm,
        c7_offset_mm=baseline.c7_offset_mm,
        baseline_angle_deg=cva_surrogate_angle_deg(
            corrected_head,
            corrected_c7,
            vertical_gap_mm,
        ),
        relative_p90_p10_span_mm=baseline.relative_p90_p10_span_mm,
        sample_count=baseline.sample_count,
    )

    pair_filter.clear(keep_rejected_count=False)
    source.clear()
    source.baseline_saved()

    print(
        "기준 자세 저장 완료  "
        f"HEAD 원본={baseline.raw_head_mm:.1f} mm  "
        f"C7 원본={baseline.raw_c7_mm:.1f} mm  "
        f"기준각={baseline.baseline_angle_deg:.1f}°  "
        f"샘플={baseline.sample_count}개"
    )

    return baseline


def run_headless_monitor(
    source: SampleSource,
    vertical_gap_mm: float,
    angle_threshold_deg: float,
    posture_hold_seconds: float,
    recovery_margin_deg: float,
    recovery_hold_seconds: float,
    output_path: Path,
    auto_calibrate: bool,
    trigger_path: Optional[Path] = None,
) -> None:
    """
    Tkinter 창 없이 neck_posture_feedback.json만 갱신한다.
    메인 PyQt UI에 붙일 때는 이 모드를 사용한다.
    """

    trigger_watcher: Optional[MeasurementTriggerWatcher] = None
    if trigger_path is not None:
        trigger_watcher = MeasurementTriggerWatcher(trigger_path)
        write_feedback(
            output_path,
            {
                "timestamp": time.time(),
                "state": "WAITING_FOR_START",
                "message": "주행 시작 버튼을 기다리고 있습니다",
                "warning": False,
                "clinical_cva": False,
                "measurement_token": "",
            },
        )
        trigger_watcher.wait_for_next("목 초음파")
    elif not auto_calibrate:
        input("바른 목 자세로 앉은 뒤 Enter를 누르세요 ")

    pair_filter = RobustPairFilter()
    calibration_feedback = make_calibration_feedback_callback(
        output_path,
        lambda: trigger_watcher.last_token if trigger_watcher is not None else "",
    )

    while True:
        try:
            write_feedback(
                output_path,
                {
                    "timestamp": time.time(),
                    "state": "CALIBRATING",
                    "message": "목 기준 자세를 측정하고 있습니다",
                    "warning": False,
                    "clinical_cva": False,
                    "measurement_token": (
                        trigger_watcher.last_token if trigger_watcher is not None else ""
                    ),
                },
            )
            baseline = collect_baseline_for_headless(
                source,
                pair_filter,
                vertical_gap_mm,
                progress_callback=calibration_feedback,
            )
            break
        except RuntimeError as exc:
            print(f"기준 자세 저장 실패: {exc}", file=sys.stderr)
            write_feedback(
                output_path,
                {
                    "timestamp": time.time(),
                    "state": "CALIBRATION_ERROR",
                    "message": str(exc),
                    "warning": False,
                    "clinical_cva": False,
                    "measurement_token": (
                        trigger_watcher.last_token if trigger_watcher is not None else ""
                    ),
                },
            )
            if trigger_watcher is not None:
                trigger_watcher.wait_for_next("목 초음파")
                continue
            if auto_calibrate:
                raise
            input("다시 바른 자세로 앉은 뒤 Enter를 누르세요 ")

    timer = PostureTimer(
        angle_threshold_deg,
        posture_hold_seconds,
        recovery_margin_deg,
        recovery_hold_seconds,
    )

    last_feedback_write_at = 0.0
    last_print_at = 0.0
    latest_raw: Optional[Tuple[float, float]] = None
    last_valid_pair_at = time.monotonic()
    last_signal_status_write_at = 0.0

    print(
        "목 자세 no-window 감시를 시작합니다  "
        f"출력={output_path}  경고 기준={angle_threshold_deg:.1f}° 전방 변화, "
        f"{posture_hold_seconds:.1f}초 유지"
    )

    while True:
        now = time.monotonic()

        if trigger_watcher is not None and trigger_watcher.consume_new_trigger():
            print("목 초음파: 새 START(S) 신호 수신 / 기준 자세 다시 측정")
            while True:
                try:
                    write_feedback(
                        output_path,
                        {
                            "timestamp": time.time(),
                            "state": "CALIBRATING",
                            "message": "목 기준 자세를 다시 측정하고 있습니다",
                            "warning": False,
                            "clinical_cva": False,
                            "measurement_token": trigger_watcher.last_token or "",
                        },
                    )
                    baseline = collect_baseline_for_headless(
                        source,
                        pair_filter,
                        vertical_gap_mm,
                        progress_callback=calibration_feedback,
                    )
                    timer = PostureTimer(
                        angle_threshold_deg,
                        posture_hold_seconds,
                        recovery_margin_deg,
                        recovery_hold_seconds,
                    )
                    latest_raw = None
                    print("목 초음파: 새 기준 자세 적용 완료")
                    break
                except RuntimeError as exc:
                    print(f"목 기준 자세 재측정 실패: {exc}", file=sys.stderr)
                    write_feedback(
                        output_path,
                        {
                            "timestamp": time.time(),
                            "state": "CALIBRATION_ERROR",
                            "message": str(exc),
                            "warning": False,
                            "signal_ok": False,
                            "clinical_cva": False,
                            "measurement_token": trigger_watcher.last_token or "",
                        },
                    )
                    trigger_watcher.wait_for_next("목 초음파")
            continue

        pair = source.read_latest()

        if pair is None:
            if (
                now - last_valid_pair_at >= SIGNAL_STALE_SECONDS
                and now - last_signal_status_write_at >= STATUS_HEARTBEAT_SECONDS
            ):
                write_feedback(
                    output_path,
                    {
                        "timestamp": time.time(),
                        "state": "SIGNAL_LOST",
                        "message": "목 초음파 신호를 기다리고 있습니다",
                        "warning": False,
                        "signal_ok": False,
                        "clinical_cva": False,
                        "measurement_token": (
                            trigger_watcher.last_token if trigger_watcher is not None else ""
                        ),
                    },
                )
                last_signal_status_write_at = now
            time.sleep(0.005)
            continue

        last_valid_pair_at = now
        latest_raw = pair

        try:
            filtered = pair_filter.update(pair)
        except ValueError:
            time.sleep(0.005)
            continue

        corrected_head, corrected_c7 = baseline.correct(*filtered)
        angle = cva_surrogate_angle_deg(corrected_head, corrected_c7, vertical_gap_mm)
        angle_drop = forward_angle_change_deg(baseline.baseline_angle_deg, angle)
        state, warning, bad_duration = timer.update(angle_drop, now)

        analysis = Analysis(
            state=state,
            message=state_message(state),
            warning=warning,
            corrected_head_mm=corrected_head,
            corrected_c7_mm=corrected_c7,
            horizontal_gap_mm=corrected_head - corrected_c7,
            current_angle_deg=angle,
            angle_drop_deg=angle_drop,
            bad_duration_seconds=bad_duration,
        )

        if now - last_feedback_write_at >= FEEDBACK_WRITE_INTERVAL_SECONDS:
            payload = build_feedback_payload(
                baseline=baseline,
                raw_pair=latest_raw,
                filtered_pair=filtered,
                analysis=analysis,
                angle_threshold_deg=angle_threshold_deg,
                posture_hold_seconds=posture_hold_seconds,
                rejected_spike_count=pair_filter.rejected_count,
                vertical_gap_mm=vertical_gap_mm,
            )
            payload["measurement_token"] = (
                trigger_watcher.last_token if trigger_watcher is not None else ""
            )
            write_feedback(output_path, payload)
            last_feedback_write_at = now

        if now - last_print_at >= 1.0 or warning:
            print(
                f"{analysis.state}  "
                f"각도={analysis.current_angle_deg:.1f}°  "
                f"전방변화={analysis.angle_drop_deg:+.1f}°  "
                f"지속={analysis.bad_duration_seconds:.1f}s"
            )
            last_print_at = now



class NeckDashboard:
    COLORS = {
        "bg": "#F4F7FB",
        "card": "#FFFFFF",
        "border": "#DCE4EF",
        "text": "#182230",
        "muted": "#6B778C",
        "blue": "#2878E8",
        "blue_soft": "#EAF3FF",
        "green": "#20A464",
        "green_soft": "#E8F7F0",
        "amber": "#E99B19",
        "amber_soft": "#FFF5DF",
        "red": "#E34B4B",
        "red_soft": "#FDECEC",
        "sensor": "#45566C",
        "line": "#AAB7C8",
    }

    def __init__(
        self,
        source: SampleSource,
        vertical_gap_mm: float,
        angle_threshold_deg: float,
        posture_hold_seconds: float,
        recovery_margin_deg: float,
        recovery_hold_seconds: float,
        output_path: Path,
        width: int,
        height: int,
        fullscreen: bool,
        auto_calibrate: bool,
    ) -> None:
        try:
            import tkinter as tk
        except ImportError as exc:
            raise RuntimeError("Tkinter가 없어 실시간 화면을 열 수 없습니다") from exc

        self.tk = tk
        self.source = source
        self.vertical_gap_mm = vertical_gap_mm
        self.angle_threshold_deg = angle_threshold_deg
        self.posture_hold_seconds = posture_hold_seconds
        self.output_path = output_path

        self.filter = RobustPairFilter()
        self.timer = PostureTimer(
            angle_threshold_deg,
            posture_hold_seconds,
            recovery_margin_deg,
            recovery_hold_seconds,
        )

        self.root = tk.Tk()
        self.root.title("목 자세 CVA 대체각 모니터")
        self.root.geometry(f"{max(1100, width)}x{max(700, height)}")
        self.root.configure(bg=self.COLORS["bg"])
        self.root.attributes("-fullscreen", fullscreen)

        self.canvas = tk.Canvas(
            self.root,
            bg=self.COLORS["bg"],
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True)

        self.calibration_button = tk.Button(
            self.root,
            text="기준 자세 측정 시작",
            command=self.start_calibration,
            bg=self.COLORS["blue"],
            fg="white",
            activebackground="#1F67C7",
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=26,
            pady=11,
            font=("Malgun Gothic", 11, "bold"),
            cursor="hand2",
        )
        self.calibration_button.place(relx=0.5, rely=1.0, y=-22, anchor="s")

        self.mode = "WAITING"
        self.error_message = ""
        self.phase_ends_at = 0.0
        self.calibration_samples: List[Tuple[float, float]] = []
        self.baseline: Optional[Baseline] = None
        self.latest_raw: Optional[Tuple[float, float]] = None
        self.latest_filtered: Optional[Tuple[float, float]] = None
        self.latest_analysis: Optional[Analysis] = None
        self.last_data_at = 0.0
        self.last_feedback_write_at = 0.0
        self.closed = False

        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.root.bind("<Return>", lambda _event: self.start_calibration())
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Escape>", lambda _event: self.close())

        self.root.after(GUI_UPDATE_MS, self._tick)
        if auto_calibrate:
            self.root.after(700, self.start_calibration)

    def toggle_fullscreen(self, _event: object = None) -> None:
        current = bool(self.root.attributes("-fullscreen"))
        self.root.attributes("-fullscreen", not current)

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            self.source.close()
        finally:
            self.root.destroy()

    def start_calibration(self) -> None:
        if self.closed or self.mode in ("SETTLING", "CALIBRATING"):
            return
        self.mode = "SETTLING"
        self.error_message = ""
        self.baseline = None
        self.latest_analysis = None
        self.calibration_samples.clear()
        self.filter.clear(keep_rejected_count=False)
        self.timer.reset()
        self.source.clear()
        self.phase_ends_at = time.monotonic() + CALIBRATION_SETTLE_SECONDS
        self.calibration_button.configure(text="기준 자세 측정 중", state="disabled")

    def _start_measurement_phase(self, now: float) -> None:
        self.mode = "CALIBRATING"
        self.phase_ends_at = now + CALIBRATION_SECONDS
        self.calibration_samples.clear()
        self.filter.clear()
        self.source.clear()

    def _finish_calibration(self) -> None:
        try:
            baseline = build_baseline(self.calibration_samples)
            # 실제 설치 간격으로 기준각을 다시 계산한다
            corrected_head, corrected_c7 = baseline.correct(
                baseline.raw_head_mm,
                baseline.raw_c7_mm,
            )
            baseline = Baseline(
                raw_head_mm=baseline.raw_head_mm,
                raw_c7_mm=baseline.raw_c7_mm,
                common_reference_mm=baseline.common_reference_mm,
                head_offset_mm=baseline.head_offset_mm,
                c7_offset_mm=baseline.c7_offset_mm,
                baseline_angle_deg=cva_surrogate_angle_deg(
                    corrected_head,
                    corrected_c7,
                    self.vertical_gap_mm,
                ),
                relative_p90_p10_span_mm=baseline.relative_p90_p10_span_mm,
                sample_count=baseline.sample_count,
            )
        except RuntimeError as exc:
            self.mode = "CALIBRATION_ERROR"
            self.error_message = str(exc)
            self.calibration_button.configure(
                text="기준 자세 다시 측정",
                state="normal",
            )
            return

        self.baseline = baseline
        self.mode = "NORMAL"
        self.error_message = ""
        self.timer.reset()
        self.filter.clear()
        self.source.clear()
        self.source.baseline_saved()
        self.calibration_button.configure(text="기준 자세 다시 측정", state="normal")
        print(
            "기준 자세 저장 완료  "
            f"HEAD 원본={baseline.raw_head_mm:.1f} mm  "
            f"C7 원본={baseline.raw_c7_mm:.1f} mm  "
            f"공통 보정값={baseline.common_reference_mm:.1f} mm  "
            f"HEAD 오프셋={baseline.head_offset_mm:+.1f} mm  "
            f"C7 오프셋={baseline.c7_offset_mm:+.1f} mm"
        )

    def _analyse(self, filtered: Tuple[float, float], now: float) -> Analysis:
        if self.baseline is None:
            raise RuntimeError("기준 자세를 먼저 저장해야 합니다")

        corrected_head, corrected_c7 = self.baseline.correct(*filtered)
        angle = cva_surrogate_angle_deg(
            corrected_head,
            corrected_c7,
            self.vertical_gap_mm,
        )
        angle_drop = forward_angle_change_deg(self.baseline.baseline_angle_deg, angle)
        state, warning, bad_duration = self.timer.update(angle_drop, now)
        self.mode = state

        return Analysis(
            state=state,
            message=state_message(state),
            warning=warning,
            corrected_head_mm=corrected_head,
            corrected_c7_mm=corrected_c7,
            horizontal_gap_mm=corrected_head - corrected_c7,
            current_angle_deg=angle,
            angle_drop_deg=angle_drop,
            bad_duration_seconds=bad_duration,
        )

    def _save_feedback_if_due(self, now: float) -> None:
        if (
            self.baseline is None
            or self.latest_filtered is None
            or self.latest_analysis is None
            or now - self.last_feedback_write_at < FEEDBACK_WRITE_INTERVAL_SECONDS
        ):
            return

        payload = build_feedback_payload(
            baseline=self.baseline,
            raw_pair=self.latest_raw,
            filtered_pair=self.latest_filtered,
            analysis=self.latest_analysis,
            angle_threshold_deg=self.angle_threshold_deg,
            posture_hold_seconds=self.posture_hold_seconds,
            rejected_spike_count=self.filter.rejected_count,
            vertical_gap_mm=self.vertical_gap_mm,
        )
        try:
            write_feedback(self.output_path, payload)
            self.last_feedback_write_at = now
        except OSError as exc:
            print(f"피드백 파일 저장 실패: {exc}", file=sys.stderr)

    def _tick(self) -> None:
        if self.closed:
            return

        now = time.monotonic()

        if self.mode == "SETTLING" and now >= self.phase_ends_at:
            self._start_measurement_phase(now)
        elif self.mode == "CALIBRATING" and now >= self.phase_ends_at:
            self._finish_calibration()

        pair = self.source.read_latest()
        if pair is not None:
            self.latest_raw = pair
            self.last_data_at = now
            try:
                filtered = self.filter.update(pair)
            except ValueError:
                filtered = None

            if filtered is not None:
                self.latest_filtered = filtered
                if self.mode == "CALIBRATING":
                    self.calibration_samples.append(filtered)
                elif self.baseline is not None and self.mode not in (
                    "SETTLING",
                    "CALIBRATING",
                    "CALIBRATION_ERROR",
                ):
                    self.latest_analysis = self._analyse(filtered, now)
                    self._save_feedback_if_due(now)

        self._draw(now)
        self.root.after(GUI_UPDATE_MS, self._tick)

    def _status_content(self, now: float) -> Tuple[str, str, str, str]:
        signal_lost = (
            self.last_data_at > 0.0
            and now - self.last_data_at > SIGNAL_STALE_SECONDS
        )
        if signal_lost:
            return (
                "센서 신호 확인",
                "유효한 두 센서값이 들어오지 않고 있어요",
                self.COLORS["amber"],
                self.COLORS["amber_soft"],
            )
        if self.mode == "WAITING":
            return (
                "측정 준비",
                "바른 자세로 앉은 뒤 기준 자세 측정을 시작해주세요",
                self.COLORS["blue"],
                self.COLORS["blue_soft"],
            )
        if self.mode == "SETTLING":
            remaining = max(0.0, self.phase_ends_at - now)
            return (
                "자세 준비 중",
                f"바른 자세를 유지해주세요  {remaining:.1f}초 뒤 측정",
                self.COLORS["amber"],
                self.COLORS["amber_soft"],
            )
        if self.mode == "CALIBRATING":
            remaining = max(0.0, self.phase_ends_at - now)
            return (
                "기준 자세 측정 중",
                f"움직이지 말고 유지해주세요  남은 시간 {remaining:.1f}초",
                self.COLORS["amber"],
                self.COLORS["amber_soft"],
            )
        if self.mode == "CALIBRATION_ERROR":
            return (
                "기준 저장 실패",
                self.error_message,
                self.COLORS["red"],
                self.COLORS["red_soft"],
            )
        if self.latest_analysis is None:
            return (
                "측정 시작",
                "필터가 첫 측정값을 준비하고 있어요",
                self.COLORS["blue"],
                self.COLORS["blue_soft"],
            )

        analysis = self.latest_analysis
        if analysis.state == "WARNING":
            color, soft = self.COLORS["red"], self.COLORS["red_soft"]
            title = "거북목 자세 교정 필요"
        elif analysis.state in ("PENDING", "RECOVERING"):
            color, soft = self.COLORS["amber"], self.COLORS["amber_soft"]
            title = "자세 변화 확인 중" if analysis.state == "PENDING" else "회복 확인 중"
        elif analysis.state == "RECOVERED":
            color, soft = self.COLORS["green"], self.COLORS["green_soft"]
            title = "목 자세 교정 완료"
        else:
            color, soft = self.COLORS["blue"], self.COLORS["blue_soft"]
            title = "바른 목 자세"
        return title, analysis.message, color, soft

    def _draw_card(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        fill: Optional[str] = None,
        outline: Optional[str] = None,
    ) -> None:
        self.canvas.create_rectangle(
            x1,
            y1,
            x2,
            y2,
            fill=fill or self.COLORS["card"],
            outline=outline or self.COLORS["border"],
            width=1,
        )

    def _draw_posture_diagram(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: str,
    ) -> None:
        canvas = self.canvas
        self._draw_card(x1, y1, x2, y2)
        canvas.create_text(
            x1 + 24,
            y1 + 28,
            anchor="w",
            text="후두부-C7 위치 변화",
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 14, "bold"),
        )
        canvas.create_text(
            x1 + 24,
            y1 + 52,
            anchor="w",
            text="점선은 기준 자세 · 실선은 현재 자세",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )

        plot_left = x1 + 70
        plot_right = x2 - 50
        head_y = y1 + 145
        c7_y = y2 - 105
        sensor_x = plot_left
        baseline_x = x1 + (x2 - x1) * 0.58

        # 센서 고정판과 센서 본체
        canvas.create_line(
            sensor_x - 22,
            head_y - 55,
            sensor_x - 22,
            c7_y + 55,
            fill=self.COLORS["sensor"],
            width=6,
        )
        for label, y in (("HEAD", head_y), ("C7", c7_y)):
            canvas.create_rectangle(
                sensor_x - 16,
                y - 13,
                sensor_x + 14,
                y + 13,
                fill=self.COLORS["sensor"],
                outline="",
            )
            canvas.create_text(
                sensor_x - 26,
                y,
                anchor="e",
                text=label,
                fill=self.COLORS["text"],
                font=("Malgun Gothic", 9, "bold"),
            )

        canvas.create_line(
            baseline_x,
            head_y,
            baseline_x,
            c7_y,
            fill=self.COLORS["line"],
            width=3,
            dash=(7, 5),
        )

        head_x = baseline_x
        c7_x = baseline_x
        if self.baseline is not None and self.latest_analysis is not None:
            pixels_per_mm = min(3.2, (plot_right - baseline_x) / 75.0)
            head_x = baseline_x + (
                self.latest_analysis.corrected_head_mm
                - self.baseline.common_reference_mm
            ) * pixels_per_mm
            c7_x = baseline_x + (
                self.latest_analysis.corrected_c7_mm
                - self.baseline.common_reference_mm
            ) * pixels_per_mm
            head_x = max(sensor_x + 55, min(plot_right, head_x))
            c7_x = max(sensor_x + 55, min(plot_right, c7_x))

        canvas.create_line(
            sensor_x + 14,
            head_y,
            head_x,
            head_y,
            fill="#B8C6D8",
            width=2,
        )
        canvas.create_line(
            sensor_x + 14,
            c7_y,
            c7_x,
            c7_y,
            fill="#B8C6D8",
            width=2,
        )
        canvas.create_line(
            c7_x,
            c7_y,
            head_x,
            head_y,
            fill=color,
            width=5,
        )

        for label, x, y in (("후두부", head_x, head_y), ("C7", c7_x, c7_y)):
            canvas.create_oval(
                x - 10,
                y - 10,
                x + 10,
                y + 10,
                fill=color,
                outline="white",
                width=2,
            )
            canvas.create_text(
                x + 16,
                y - 15,
                anchor="w",
                text=label,
                fill=self.COLORS["text"],
                font=("Malgun Gothic", 10, "bold"),
            )

        if self.latest_analysis is not None:
            canvas.create_text(
                (head_x + c7_x) / 2 + 18,
                (head_y + c7_y) / 2,
                anchor="w",
                text=f"{self.latest_analysis.current_angle_deg:.1f}°",
                fill=color,
                font=("Malgun Gothic", 18, "bold"),
            )

        canvas.create_text(
            x1 + 24,
            y2 - 28,
            anchor="w",
            text=(
                f"센서 중심 세로 간격 {self.vertical_gap_mm:.0f} mm  ·  "
                "거리 증가 방향 = 몸 앞쪽"
            ),
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )

    def _draw_metric(
        self,
        x: float,
        y: float,
        label: str,
        value: str,
        color: Optional[str] = None,
    ) -> None:
        self.canvas.create_text(
            x,
            y,
            anchor="w",
            text=label,
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )
        self.canvas.create_text(
            x,
            y + 23,
            anchor="w",
            text=value,
            fill=color or self.COLORS["text"],
            font=("Malgun Gothic", 15, "bold"),
        )

    def _draw(self, now: float) -> None:
        if self.closed:
            return

        canvas = self.canvas
        canvas.delete("all")
        width = max(canvas.winfo_width(), 1100)
        height = max(canvas.winfo_height(), 700)

        title, detail, status_color, status_soft = self._status_content(now)

        canvas.create_text(
            24,
            30,
            anchor="w",
            text="실시간 목 자세 CVA 대체각",
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 20, "bold"),
        )
        canvas.create_text(
            24,
            57,
            anchor="w",
            text=f"{self.source.label}  ·  기준 보정은 Enter 또는 아래 버튼",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 10),
        )
        canvas.create_text(
            width - 24,
            43,
            anchor="e",
            text="Enter 재측정  ·  F11 전체화면  ·  Esc 종료",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )

        margin = 24
        gap = 18
        right_width = max(350, width * 0.31)
        left_x = margin
        left_y = 82
        left_right = width - margin - right_width - gap
        bottom = height - 82
        right_x = left_right + gap

        self._draw_posture_diagram(
            left_x,
            left_y,
            left_right,
            bottom,
            status_color,
        )

        status_height = 122
        self._draw_card(
            right_x,
            left_y,
            width - margin,
            left_y + status_height,
            fill=status_soft,
            outline=status_soft,
        )
        canvas.create_text(
            right_x + 22,
            left_y + 31,
            anchor="w",
            text=title,
            fill=status_color,
            font=("Malgun Gothic", 16, "bold"),
        )
        canvas.create_text(
            right_x + 22,
            left_y + 70,
            width=right_width - 44,
            anchor="nw",
            text=detail,
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 10),
        )

        angle_top = left_y + status_height + gap
        angle_bottom = angle_top + 158
        self._draw_card(right_x, angle_top, width - margin, angle_bottom)
        canvas.create_text(
            right_x + 22,
            angle_top + 25,
            anchor="w",
            text="각도 판별",
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 12, "bold"),
        )

        if self.latest_analysis is None:
            current_angle = "—"
            angle_drop = "—"
            duration = "—"
        else:
            current_angle = f"{self.latest_analysis.current_angle_deg:.1f}°"
            angle_drop = f"{self.latest_analysis.angle_drop_deg:+.1f}°"
            if self.latest_analysis.state == "PENDING":
                duration = (
                    f"{self.latest_analysis.bad_duration_seconds:.1f} / "
                    f"{self.posture_hold_seconds:.1f}초"
                )
            elif self.latest_analysis.warning:
                duration = f"{self.posture_hold_seconds:.1f}초 이상"
            else:
                duration = "정상"

        metric_y = angle_top + 55
        third = (right_width - 44) / 3
        self._draw_metric(right_x + 22, metric_y, "현재 대체각", current_angle, status_color)
        self._draw_metric(right_x + 22 + third, metric_y, "기준 대비 감소", angle_drop)
        self._draw_metric(right_x + 22 + third * 2, metric_y, "지속시간", duration)
        canvas.create_text(
            right_x + 22,
            angle_bottom - 20,
            anchor="w",
            text=(
                f"경고 기준  감소 {self.angle_threshold_deg:.1f}° 이상이 "
                f"{self.posture_hold_seconds:.1f}초 지속"
            ),
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )

        sensor_top = angle_bottom + gap
        sensor_bottom = bottom
        self._draw_card(right_x, sensor_top, width - margin, sensor_bottom)
        canvas.create_text(
            right_x + 22,
            sensor_top + 25,
            anchor="w",
            text="센서값과 자동 오프셋",
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 12, "bold"),
        )

        if self.latest_analysis is not None:
            head_corrected = f"{self.latest_analysis.corrected_head_mm:.1f} mm"
            c7_corrected = f"{self.latest_analysis.corrected_c7_mm:.1f} mm"
        elif self.latest_filtered is not None:
            head_corrected = f"원본 {self.latest_filtered[0]:.1f} mm"
            c7_corrected = f"원본 {self.latest_filtered[1]:.1f} mm"
        else:
            head_corrected = c7_corrected = "—"

        row_y = sensor_top + 56
        half = (right_width - 44) / 2
        self._draw_metric(right_x + 22, row_y, "후두부 보정 거리", head_corrected)
        self._draw_metric(right_x + 22 + half, row_y, "C7 보정 거리", c7_corrected)

        if self.baseline is None:
            offsets_text = "기준 측정 후 자동 계산"
            baseline_text = "기준 측정 전"
        else:
            offsets_text = (
                f"HEAD {self.baseline.head_offset_mm:+.1f}  ·  "
                f"C7 {self.baseline.c7_offset_mm:+.1f} mm"
            )
            baseline_text = (
                f"두 센서 기준값 → {self.baseline.common_reference_mm:.1f} mm로 일치"
            )

        canvas.create_text(
            right_x + 22,
            row_y + 70,
            anchor="w",
            text=f"적용 오프셋  {offsets_text}",
            fill=self.COLORS["text"],
            font=("Malgun Gothic", 10, "bold"),
        )
        canvas.create_text(
            right_x + 22,
            row_y + 96,
            anchor="w",
            text=baseline_text,
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )
        canvas.create_text(
            right_x + 22,
            min(sensor_bottom - 20, row_y + 127),
            anchor="w",
            text=f"필터가 제거한 순간 튐  {self.filter.rejected_count}회",
            fill=self.COLORS["muted"],
            font=("Malgun Gothic", 9),
        )

        # 실제 버튼의 색과 문구도 현재 상태에 맞춘다
        if self.mode in ("SETTLING", "CALIBRATING"):
            self.calibration_button.configure(bg=self.COLORS["amber"])
        else:
            self.calibration_button.configure(bg=self.COLORS["blue"])

    def run(self) -> None:
        self.root.mainloop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="후두부와 C7 초음파센서 2개로 목 자세 대체각을 실시간 표시합니다"
    )
    parser.add_argument(
        "--port",
        default=DEFAULT_NECK_PORT,
        help=(
            "목 초음파 Arduino 시리얼 포트. "
            "여러 Arduino가 연결되므로 /dev/ttyUSB1처럼 직접 지정 권장. "
            "환경변수 SEAT_ID_NECK_PORT도 사용 가능. auto는 직접 지정했을 때만 자동 선택"
        ),
    )
    parser.add_argument("--baudrate", type=int, default=DEFAULT_BAUDRATE)
    parser.add_argument(
        "--vertical-gap-mm",
        type=float,
        default=DEFAULT_VERTICAL_GAP_MM,
        help="후두부 센서와 C7 센서 중심의 실제 세로 간격 mm",
    )
    parser.add_argument(
        "--angle-threshold",
        type=float,
        default=DEFAULT_ANGLE_DROP_THRESHOLD_DEG,
        help="기준 대체각 대비 감소 임계값 degree",
    )
    parser.add_argument(
        "--posture-hold",
        type=float,
        default=DEFAULT_POSTURE_HOLD_SECONDS,
        help="나쁜 자세가 경고로 확정되기 전 유지시간 s",
    )
    parser.add_argument(
        "--recovery-hold",
        type=float,
        default=DEFAULT_RECOVERY_HOLD_SECONDS,
        help="정상 복귀가 확정되기 전 유지시간 s",
    )
    parser.add_argument(
        "--recovery-margin",
        type=float,
        default=DEFAULT_RECOVERY_MARGIN_DEG,
        help="경고 해제 히스테리시스 degree",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("neck_posture_feedback.json"),
        help="다른 프로그램이 읽을 수 있는 실시간 상태 JSON 파일",
    )
    parser.add_argument("--demo", action="store_true", help="Arduino 없이 전체 화면 시험")
    parser.add_argument(
        "--no-window",
        action="store_true",
        help="Tkinter 창 없이 JSON 파일만 갱신한다. 메인 PyQt UI 연동용",
    )
    parser.add_argument(
        "--auto-calibrate",
        action="store_true",
        help="화면이 열린 뒤 버튼 입력 없이 기준 측정 시작",
    )
    parser.add_argument(
        "--wait-for-trigger",
        type=Path,
        default=None,
        help="app.py의 START(S) 측정 신호 JSON이 갱신될 때까지 기준 측정을 시작하지 않음",
    )
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--window-width", type=int, default=1280)
    parser.add_argument("--window-height", type=int, default=760)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if args.vertical_gap_mm <= 0.0:
        print("--vertical-gap-mm는 0보다 커야 합니다", file=sys.stderr)
        return 2
    if args.angle_threshold <= 0.0:
        print("--angle-threshold는 0보다 커야 합니다", file=sys.stderr)
        return 2
    if args.posture_hold < 0.0 or args.recovery_hold < 0.0:
        print("유지시간은 0 이상이어야 합니다", file=sys.stderr)
        return 2
    if args.recovery_margin < 0.0:
        print("--recovery-margin은 0 이상이어야 합니다", file=sys.stderr)
        return 2

    if not args.demo and str(args.port or "").strip() == "":
        print(
            "목 초음파 Arduino 포트를 지정해야 합니다.\n"
            "예: SEAT_ID_NECK_PORT=/dev/ttyUSB1 python3 neck_cva_monitor_2ch.py --no-window --auto-calibrate\n"
            "또는: python3 neck_cva_monitor_2ch.py --port /dev/ttyUSB1 --no-window --auto-calibrate",
            file=sys.stderr,
        )
        return 2

    source: SampleSource
    if args.demo:
        source = DemoSource()
        print("센서 없는 데모 모드로 실행합니다")
    else:
        try:
            source = ArduinoSerialSource(args.port, args.baudrate)
        except Exception as exc:
            print(f"시리얼 연결 실패: {exc}", file=sys.stderr)
            print("Arduino 시리얼 모니터를 닫았는지도 확인해주세요", file=sys.stderr)
            return 1

    if args.no_window:
        try:
            run_headless_monitor(
                source=source,
                vertical_gap_mm=args.vertical_gap_mm,
                angle_threshold_deg=args.angle_threshold,
                posture_hold_seconds=args.posture_hold,
                recovery_margin_deg=args.recovery_margin,
                recovery_hold_seconds=args.recovery_hold,
                output_path=args.output,
                auto_calibrate=args.auto_calibrate,
                trigger_path=args.wait_for_trigger,
            )
        except KeyboardInterrupt:
            print("\n목 자세 모니터를 종료합니다")
        except Exception as exc:
            print(f"목 자세 no-window 실행 실패: {exc}", file=sys.stderr)
            source.close()
            return 1
        finally:
            source.close()
        return 0

    try:
        dashboard = NeckDashboard(
            source=source,
            vertical_gap_mm=args.vertical_gap_mm,
            angle_threshold_deg=args.angle_threshold,
            posture_hold_seconds=args.posture_hold,
            recovery_margin_deg=args.recovery_margin,
            recovery_hold_seconds=args.recovery_hold,
            output_path=args.output,
            width=args.window_width,
            height=args.window_height,
            fullscreen=args.fullscreen,
            auto_calibrate=args.auto_calibrate,
        )
    except Exception as exc:
        source.close()
        print(f"실시간 화면 시작 실패: {exc}", file=sys.stderr)
        return 1

    try:
        dashboard.run()
    except KeyboardInterrupt:
        dashboard.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
