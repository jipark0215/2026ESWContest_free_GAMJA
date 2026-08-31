from __future__ import annotations

from pathlib import Path
import time

import joblib
import numpy as np
import pandas as pd
import serial
from serial import SerialException
from serial.tools import list_ports

# =========================================================
# Output mode
# True  = 개발용(상세 출력)
# False = 발표용(간단 출력)
# =========================================================
DEBUG_MODE = False

BASE_DIR = Path(__file__).resolve().parent

# =========================================================
# Serial
# Raspberry Pi에서는 COM4가 아니라 /dev/ttyACM0, /dev/ttyUSB0 형태로 잡힌다.
# None으로 두면 자동 탐색한다.
# =========================================================
PORT: str | None = None
BAUDRATE = 115200
NUM_SENSORS = 16
SERIAL_TIMEOUT_SEC = 0.03

ADC_MIN = 0
ADC_MAX = 1023

# Posture Model
MODEL_PATH = BASE_DIR / "svm_model.pkl"
SCALER_PATH = BASE_DIR / "scaler.pkl"

# User Identification Model
USER_MODEL_PATH = BASE_DIR / "user_model.pkl"
USER_SCALER_PATH = BASE_DIR / "user_scaler.pkl"

BASELINE_PATH = BASE_DIR / "selected_baseline.npy"
POSITION_PATH = BASE_DIR / "selected_sensor_positions.csv"

# User profile / pressure DB
USER_PROFILE_PATH = BASE_DIR / "user_profile.csv"
DATABASE_PATH = BASE_DIR / "pressure_database.csv"

EDGE_BOTTOM = 0
EDGE_TOP = 15
EDGE_BOTTOM_THRESHOLD = 30.0   
EDGE_TOP_THRESHOLD = 50.0      
BALANCE_THRESHOLD = 0.10


def check_required_files() -> None:
    required_files = [
        MODEL_PATH,
        SCALER_PATH,
        USER_MODEL_PATH,
        USER_SCALER_PATH,
        BASELINE_PATH,
        POSITION_PATH,
    ]

    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        raise FileNotFoundError("Missing required files:\n- " + "\n- ".join(missing_files))


def normalize_pressure_database_schema() -> None:
    if not DATABASE_PATH.exists():
        return

    database = pd.read_csv(DATABASE_PATH)
    if database.empty:
        return

    renamed = {}
    if "name" in database.columns and "nickname" not in database.columns:
        renamed["name"] = "nickname"

    for i in range(1, NUM_SENSORS + 1):
        old_col = f"sensor{i}"
        new_col = f"sensor_{i}"
        if old_col in database.columns and new_col not in database.columns:
            renamed[old_col] = new_col

    if renamed:
        database = database.rename(columns=renamed)
        database.to_csv(DATABASE_PATH, index=False, encoding="utf-8-sig")


def load_user_database() -> dict[int, str]:
    """
    user_id -> nickname 매핑을 불러온다.
    UI/하드웨어 기준 파일인 user_profile.csv를 우선 사용하고,
    없으면 pressure_database.csv의 nickname/name 컬럼을 fallback으로 사용한다.
    """

    user_dict: dict[int, str] = {}

    if USER_PROFILE_PATH.exists():
        profile = pd.read_csv(USER_PROFILE_PATH)
        if "user_id" in profile.columns:
            name_col = "nickname" if "nickname" in profile.columns else "name" if "name" in profile.columns else None
            if name_col is not None:
                for _, row in profile.iterrows():
                    try:
                        user_id = int(row["user_id"])
                    except (TypeError, ValueError):
                        continue
                    user_dict[user_id] = str(row[name_col])

    if user_dict:
        return user_dict

    if DATABASE_PATH.exists():
        normalize_pressure_database_schema()
        database = pd.read_csv(DATABASE_PATH)
        if "user_id" in database.columns:
            name_col = "nickname" if "nickname" in database.columns else "name" if "name" in database.columns else None
            if name_col is not None:
                for _, row in database.iterrows():
                    try:
                        user_id = int(row["user_id"])
                    except (TypeError, ValueError):
                        continue
                    if user_id not in user_dict:
                        user_dict[user_id] = str(row[name_col])

    return user_dict


def load_resources():
    check_required_files()

    model = joblib.load(MODEL_PATH)
    scaler = joblib.load(SCALER_PATH)

    user_model = joblib.load(USER_MODEL_PATH)
    user_scaler = joblib.load(USER_SCALER_PATH)

    baseline = np.load(BASELINE_PATH)
    baseline = np.asarray(baseline, dtype=np.float32).reshape(-1)

    selected = pd.read_csv(POSITION_PATH)
    if "Sensor Index" not in selected.columns:
        raise ValueError("The CSV file must contain a 'Sensor Index' column.")

    selected_indices = selected["Sensor Index"].to_numpy(dtype=int)

    if baseline.size != NUM_SENSORS:
        raise ValueError(f"Baseline size is {baseline.size}, but {NUM_SENSORS} values are required.")

    if selected_indices.size != NUM_SENSORS:
        raise ValueError(
            f"Selected sensor count is {selected_indices.size}, but {NUM_SENSORS} values are required."
        )

    if hasattr(scaler, "n_features_in_") and scaler.n_features_in_ != NUM_SENSORS:
        raise ValueError(f"Scaler expects {scaler.n_features_in_} features, but this program uses {NUM_SENSORS}.")

    if hasattr(model, "n_features_in_") and model.n_features_in_ != NUM_SENSORS:
        raise ValueError(f"Model expects {model.n_features_in_} features, but this program uses {NUM_SENSORS}.")

    user_dict = load_user_database()

    return model, scaler, user_model, user_scaler, baseline, selected_indices, user_dict


def find_arduino_port() -> str:
    ports = list(list_ports.comports())

    preferred_devices = [
        port.device
        for port in ports
        if port.device.startswith("/dev/ttyACM") or port.device.startswith("/dev/ttyUSB")
    ]

    if preferred_devices:
        return preferred_devices[0]

    # Windows 개발 환경 fallback
    windows_devices = [port.device for port in ports if port.device.upper().startswith("COM")]
    if windows_devices:
        return windows_devices[0]

    detected_devices = [port.device for port in ports]
    raise RuntimeError(
        "Arduino serial port was not found. " f"Detected ports: {detected_devices}"
    )


def open_serial_port(port: str | None = None) -> serial.Serial:
    if port == "auto":
        port = None

    serial_port = port if port is not None else (PORT if PORT is not None else find_arduino_port())

    try:
        connection = serial.Serial(
            port=serial_port,
            baudrate=BAUDRATE,
            timeout=SERIAL_TIMEOUT_SEC,
        )
    except SerialException as exc:
        raise RuntimeError(f"Failed to open {serial_port}: {exc}") from exc

    time.sleep(2)
    connection.reset_input_buffer()

    print(f"Arduino connected: {serial_port}")
    print(f"Baud rate: {BAUDRATE}")

    return connection


def build_balance_indices(selected_indices: np.ndarray) -> tuple[list[int], list[int]]:
    left_sensor_indices: list[int] = []
    right_sensor_indices: list[int] = []

    for array_index, grid_index in enumerate(selected_indices):
        column = int(grid_index) % 12
        if column < 6:
            left_sensor_indices.append(array_index)
        else:
            right_sensor_indices.append(array_index)

    if not left_sensor_indices or not right_sensor_indices:
        raise ValueError("Left or right sensor index list is empty. Check selected_sensor_positions.csv.")

    return left_sensor_indices, right_sensor_indices


def _parse_sensor_line(line: str) -> np.ndarray | None:
    """
    Arduino가 보낸 한 줄을 16개 센서값으로 변환한다.
    형식이 맞지 않으면 None을 반환한다.
    """

    if not line:
        return None

    sensor = np.fromstring(line, sep=",", dtype=np.float32)

    if sensor.size != NUM_SENSORS:
        if DEBUG_MODE:
            print(f"[SKIP] Expected {NUM_SENSORS} values: {line}")
        return None

    if not np.all(np.isfinite(sensor)):
        if DEBUG_MODE:
            print(f"[SKIP] Invalid numeric value: {line}")
        return None

    if np.any(sensor < ADC_MIN) or np.any(sensor > ADC_MAX):
        if DEBUG_MODE:
            print(f"[SKIP] ADC value out of range: {line}")
        return None

    return sensor


def read_sensor(connection: serial.Serial, max_wait_sec: float | None = None) -> np.ndarray:
    """
    압력센서 최신값을 읽는다.

    기존 방식은 readline()으로 처음 만난 유효 줄을 바로 반환했기 때문에,
    UI가 1초에 한 번만 호출되면 시리얼 버퍼에 쌓인 과거 값을 차례대로 읽어
    히트맵이 늦게 따라오는 문제가 생길 수 있었다.

    이 함수는 버퍼에 쌓인 줄을 가능한 한 모두 비우고,
    그중 가장 마지막 유효 센서값만 반환한다.
    """

    start_time = time.monotonic()
    latest_sensor: np.ndarray | None = None

    while True:
        if max_wait_sec is not None and time.monotonic() - start_time > max_wait_sec:
            if latest_sensor is not None:
                return latest_sensor
            raise TimeoutError("Timed out while waiting for a valid pressure sensor line.")

        drained_any = False

        while True:
            raw_line = connection.readline()

            if raw_line:
                drained_any = True
                line = raw_line.decode("ascii", errors="ignore").strip()
                parsed_sensor = _parse_sensor_line(line)

                if parsed_sensor is not None:
                    latest_sensor = parsed_sensor

                # 아직 버퍼에 쌓인 데이터가 있으면 계속 읽어서 과거값을 버리고 최신값으로 갱신한다.
                try:
                    waiting_bytes = int(connection.in_waiting)
                except Exception:
                    waiting_bytes = 0

                if waiting_bytes > 0:
                    continue

            break

        if latest_sensor is not None:
            return latest_sensor

        if not drained_any and max_wait_sec is None:
            continue


def baseline_correction(sensor: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    corrected = sensor.astype(np.float32, copy=False) - baseline
    return np.clip(corrected, 0, None)


def check_edge_sensor(corrected_sensor: np.ndarray) -> bool:
    edge_bottom = corrected_sensor[EDGE_BOTTOM]
    edge_top = corrected_sensor[EDGE_TOP]

    return (
        edge_bottom <= EDGE_BOTTOM_THRESHOLD
        and
        edge_top <= EDGE_TOP_THRESHOLD
    )

def predict_posture(corrected_sensor: np.ndarray, model, scaler):
    svm_input = corrected_sensor.reshape(1, NUM_SENSORS)
    sensor_scaled = scaler.transform(svm_input)
    posture = model.predict(sensor_scaled)[0]

    if hasattr(model, "predict_proba"):
        probabilities = model.predict_proba(sensor_scaled)[0]
        confidence_value = float(np.max(probabilities) * 100.0)
        confidence_label = "Probability"
    else:
        decision = np.asarray(model.decision_function(sensor_scaled))
        confidence_value = float(np.max(decision))
        confidence_label = "Decision score"

    return posture, confidence_value, confidence_label


def predict_user(corrected_sensor: np.ndarray, user_model, user_scaler):
    svm_input = corrected_sensor.reshape(1, NUM_SENSORS)
    sensor_scaled = user_scaler.transform(svm_input)
    probabilities = user_model.predict_proba(sensor_scaled)[0]
    classes = user_model.classes_
    best_index = int(np.argmax(probabilities))
    user_id = classes[best_index]
    confidence = float(probabilities[best_index] * 100.0)
    return int(user_id), confidence


def calculate_balance(corrected_sensor: np.ndarray, left_sensor_indices: list[int], right_sensor_indices: list[int]):
    left_pressure = float(np.sum(corrected_sensor[left_sensor_indices]))
    right_pressure = float(np.sum(corrected_sensor[right_sensor_indices]))
    total_pressure = left_pressure + right_pressure

    if total_pressure <= 0:
        return "Unknown", 0.0, left_pressure, right_pressure

    balance_ratio = (left_pressure - right_pressure) / total_pressure
    balance_index = abs(balance_ratio) * 100.0

    if abs(balance_ratio) < BALANCE_THRESHOLD:
        balance = "Balanced"
    elif balance_ratio > 0:
        balance = "Left"
    else:
        balance = "Right"

    return balance, balance_index, left_pressure, right_pressure


class PressurePredictionService:
    """PyQt UI가 한 번씩 호출할 수 있도록 만든 체압/SVM 예측 서비스."""

    def __init__(self, port: str | None = None):
        (
            self.model,
            self.scaler,
            self.user_model,
            self.user_scaler,
            self.baseline,
            self.selected_indices,
            self.user_dict,
        ) = load_resources()

        self.left_sensor_indices, self.right_sensor_indices = build_balance_indices(self.selected_indices)
        self.connection = open_serial_port(port=port)
        self.sample_id = 1
        self.last_raw_sensor: np.ndarray | None = None
        self.last_corrected_sensor: np.ndarray | None = None

    def read_latest_pressure_sample(self, max_wait_sec: float | None = 0.03) -> dict:
        """
        히트맵 전용 최신 압력 샘플을 반환한다.
        자세 SVM과 사용자 SVM은 실행하지 않아 UI 반응 속도를 빠르게 유지한다.
        """

        raw_sensor = read_sensor(self.connection, max_wait_sec=max_wait_sec)
        corrected_sensor = baseline_correction(raw_sensor, self.baseline)

        self.last_raw_sensor = raw_sensor
        self.last_corrected_sensor = corrected_sensor

        is_valid = check_edge_sensor(corrected_sensor)
        balance, balance_index, left_pressure, right_pressure = calculate_balance(
            corrected_sensor,
            self.left_sensor_indices,
            self.right_sensor_indices,
        )

        return {
            "sample_id": self.sample_id,
            "is_valid": bool(is_valid),
            "raw_sensor": raw_sensor.astype(float).tolist(),
            "corrected_sensor": corrected_sensor.astype(float).tolist(),
            "balance": balance,
            "balance_index": float(balance_index),
            "left_pressure": float(left_pressure),
            "right_pressure": float(right_pressure),
        }

    def predict_once(self, max_wait_sec: float | None = 1.0) -> dict:
        raw_sensor = read_sensor(self.connection, max_wait_sec=max_wait_sec)
        corrected_sensor = baseline_correction(raw_sensor, self.baseline)

        self.last_raw_sensor = raw_sensor
        self.last_corrected_sensor = corrected_sensor

        is_valid = check_edge_sensor(corrected_sensor)

        result = {
            "sample_id": self.sample_id,
            "is_valid": bool(is_valid),
            "raw_sensor": raw_sensor.astype(float).tolist(),
            "corrected_sensor": corrected_sensor.astype(float).tolist(),
        }

        self.sample_id += 1

        if not is_valid:
            result.update(
                {
                    "warning": "edge_sensor",
                    "posture": "edge_warning",
                    "posture_confidence": 0.0,
                    "user_id": "",
                    "user_name": "Unknown",
                    "user_confidence": 0.0,
                    "balance": "Unknown",
                    "balance_index": 0.0,
                }
            )
            return result

        posture, posture_confidence, confidence_label = predict_posture(corrected_sensor, self.model, self.scaler)
        user_id, user_confidence = predict_user(corrected_sensor, self.user_model, self.user_scaler)
        user_name = self.user_dict.get(int(user_id), f"사용자{user_id}")
        balance, balance_index, left_pressure, right_pressure = calculate_balance(
            corrected_sensor,
            self.left_sensor_indices,
            self.right_sensor_indices,
        )

        result.update(
            {
                "posture": str(posture),
                "posture_confidence": float(posture_confidence),
                "posture_confidence_label": confidence_label,
                "user_id": str(int(user_id)),
                "user_name": user_name,
                "user_confidence": float(user_confidence),
                "balance": balance,
                "balance_index": float(balance_index),
                "left_pressure": float(left_pressure),
                "right_pressure": float(right_pressure),
            }
        )
        return result

    def close(self) -> None:
        if getattr(self, "connection", None) is not None and self.connection.is_open:
            self.connection.close()


_service: PressurePredictionService | None = None


def predict_once(max_wait_sec: float | None = 1.0, port: str | None = None) -> dict:
    """UI에서 바로 호출하는 진입점. 시리얼 연결은 한 번 열고 재사용한다."""

    global _service

    if _service is None:
        _service = PressurePredictionService(port=port)

    return _service.predict_once(max_wait_sec=max_wait_sec)


def get_latest_pressure_sample(max_wait_sec: float | None = 0.03, port: str | None = None) -> dict:
    """
    UI 히트맵이 빠르게 호출하는 진입점.
    시리얼 연결은 predict_once()와 같은 전역 서비스를 재사용한다.
    """

    global _service

    if _service is None:
        _service = PressurePredictionService(port=port)

    return _service.read_latest_pressure_sample(max_wait_sec=max_wait_sec)


def get_latest_sensor_values(max_wait_sec: float | None = 0.03, port: str | None = None) -> dict:
    """
    구버전/다른 호출부와의 호환용 alias.
    """

    return get_latest_pressure_sample(max_wait_sec=max_wait_sec, port=port)


def close_service() -> None:
    global _service
    if _service is not None:
        _service.close()
        _service = None


def print_result(result: dict) -> None:
    if not result.get("is_valid", True):
        print("\n" + "=" * 45)
        print("           SENSOR WARNING")
        print("=" * 45)
        print("Please sit correctly.")
        print("Edge sensor is activated.")
        print("=" * 45)
        return

    if DEBUG_MODE:
        print("\n" + "=" * 60)
        print(f"Sample ID        : {result.get('sample_id')}")
        print(f"User             : {result.get('user_name')}")
        print(f"User ID          : {result.get('user_id')}")
        print(f"User Confidence  : {result.get('user_confidence', 0.0):.2f}%")
        print(f"Raw sensor       : {[int(v) for v in result.get('raw_sensor', [])]}")
        print(f"Corrected sensor : {np.round(result.get('corrected_sensor', []), 1).tolist()}")
        print(f"Posture          : {result.get('posture')}")
        print(f"Posture Conf.    : {result.get('posture_confidence', 0.0):.3f}")
        print(f"Balance          : {result.get('balance')}")
        print(f"Balance index    : {result.get('balance_index', 0.0):.2f}%")
        print("=" * 60)
    else:
        print("\n" + "=" * 45)
        print("      Real-Time Prediction")
        print("=" * 45)
        print(f"User            : {result.get('user_name')}")
        print(f"User ID         : {result.get('user_id')}")
        print(f"User Confidence : {result.get('user_confidence', 0.0):.1f}%")
        print("-" * 45)
        print(f"Posture         : {result.get('posture')}")
        print(f"Posture Conf.   : {result.get('posture_confidence', 0.0):.1f}%")
        print(f"Balance         : {result.get('balance')}")
        print(f"Balance Index   : {result.get('balance_index', 0.0):.1f}%")
        print("=" * 45)


def main() -> None:
    print("Real-time prediction started.")
    print("Press Ctrl+C to stop.")

    valid_samples = 0
    invalid_samples = 0

    try:
        while True:
            result = predict_once(max_wait_sec=None)
            if result.get("is_valid", True):
                valid_samples += 1
            else:
                invalid_samples += 1
            print_result(result)
    except KeyboardInterrupt:
        print("\nPrediction stopped.")
    finally:
        close_service()
        print(f"Valid samples   : {valid_samples}")
        print(f"Invalid samples : {invalid_samples}")
        print("Serial port closed.")


if __name__ == "__main__":
    main()