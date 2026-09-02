from __future__ import annotations

from pathlib import Path
import argparse
import time

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
# None으로 두면 find_arduino_port()가 자동 탐색한다.
# =========================================================
PORT: str | None = None
BAUDRATE = 115200
SERIAL_TIMEOUT_SEC = 1.0

# =========================================================
# Sensor
# =========================================================
NUM_SENSORS = 16
NUM_SAMPLES = 100
GROUP_SIZE = 10
NUM_REPRESENTATIVE = NUM_SAMPLES // GROUP_SIZE
ADC_MIN = 0
ADC_MAX = 1023

# =========================================================
# File Path
# =========================================================
BASELINE_PATH = BASE_DIR / "selected_baseline.npy"
DATABASE_PATH = BASE_DIR / "pressure_database.csv"


def check_required_files() -> None:
    required_files = [BASELINE_PATH]
    missing_files = [str(path) for path in required_files if not path.exists()]
    if missing_files:
        raise FileNotFoundError("Missing required files:\n- " + "\n- ".join(missing_files))


def load_resources() -> np.ndarray:
    check_required_files()
    baseline = np.load(BASELINE_PATH)
    baseline = np.asarray(baseline, dtype=np.float32).reshape(-1)

    if baseline.size != NUM_SENSORS:
        raise ValueError(
            f"Baseline size is {baseline.size}, but {NUM_SENSORS} values are required."
        )

    return baseline


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
        "Arduino serial port was not found.\n" f"Detected ports : {detected_devices}"
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

    print(f"Arduino connected : {serial_port}")
    print(f"Baudrate          : {BAUDRATE}")

    return connection


def read_sensor(connection: serial.Serial) -> np.ndarray:
    while True:
        raw_line = connection.readline()
        if not raw_line:
            continue

        line = raw_line.decode("ascii", errors="ignore").strip()
        if not line:
            continue

        sensor = np.fromstring(line, sep=",", dtype=np.float32)

        if sensor.size != NUM_SENSORS:
            print(f"[SKIP] Expected {NUM_SENSORS} values : {line}")
            continue

        if not np.all(np.isfinite(sensor)):
            print(f"[SKIP] Invalid numeric value : {line}")
            continue

        if np.any(sensor < ADC_MIN) or np.any(sensor > ADC_MAX):
            print(f"[SKIP] ADC value out of range : {line}")
            continue

        return sensor


def baseline_correction(sensor: np.ndarray, baseline: np.ndarray) -> np.ndarray:
    corrected = sensor - baseline
    corrected = np.clip(corrected, 0, None)
    return corrected.astype(np.float32)


def collect_pressure_samples(connection: serial.Serial, baseline: np.ndarray) -> np.ndarray:
    samples = []

    print("\nPlease sit in your normal driving posture.")
    print("Remain still during the measurement.")
    print("\nMeasurement will start in...")

    for second in [3, 2, 1]:
        print(f"{second}...")
        time.sleep(1)

    print("\nCollecting pressure data...\n")

    for i in range(NUM_SAMPLES):
        sensor = read_sensor(connection)
        corrected = baseline_correction(sensor, baseline)
        samples.append(corrected)

        percent = int((i + 1) / NUM_SAMPLES * 100)
        if DEBUG_MODE:
            print(f"[{i + 1:3}/{NUM_SAMPLES}] {percent:3d}%")
        else:
            bar_length = 30
            filled = int(bar_length * (i + 1) / NUM_SAMPLES)
            bar = "=" * filled + " " * (bar_length - filled)
            print(f"\r[{bar}] {percent:3d}%", end="", flush=True)

    print("\nMeasurement completed.")

    return np.asarray(samples, dtype=np.float32)


def create_representative_samples(samples: np.ndarray) -> np.ndarray:
    if samples.shape[0] % GROUP_SIZE != 0:
        raise ValueError("NUM_SAMPLES must be divisible by GROUP_SIZE.")

    representative_samples = []
    for i in range(NUM_REPRESENTATIVE):
        start = i * GROUP_SIZE
        end = start + GROUP_SIZE
        representative = np.mean(samples[start:end], axis=0)
        representative_samples.append(representative.astype(np.float32))

    return np.asarray(representative_samples, dtype=np.float32)


def normalize_pressure_database_schema() -> None:
    """기존 name/sensor1 형식이 있으면 nickname/sensor_1 형식으로 최대한 맞춘다."""

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


def save_pressure_database(user_id: int | str, nickname: str, representative_samples: np.ndarray) -> int:
    """
    UI가 생성한 user_id를 그대로 사용해 pressure_database.csv에 저장한다.
    이 함수에서 새 user_id를 만들지 않는다.
    """

    user_id = int(user_id)
    nickname = str(nickname).strip()

    if nickname == "":
        raise ValueError("nickname cannot be empty.")

    rows = []
    for sample in representative_samples:
        row = {
            "user_id": user_id,
            "nickname": nickname,
        }
        for i in range(NUM_SENSORS):
            row[f"sensor_{i + 1}"] = float(sample[i])
        rows.append(row)

    dataframe = pd.DataFrame(rows)

    normalize_pressure_database_schema()

    if DATABASE_PATH.exists():
        existing = pd.read_csv(DATABASE_PATH)
        if not existing.empty and "user_id" in existing.columns:
            # 같은 user_id가 있으면 기존 체압 데이터를 덮어쓴다.
            existing = existing[existing["user_id"].astype(int) != user_id]
            dataframe = pd.concat([existing, dataframe], ignore_index=True)

    dataframe.to_csv(DATABASE_PATH, index=False, encoding="utf-8-sig")
    return user_id


def print_representative_samples(representative_samples: np.ndarray) -> None:
    if not DEBUG_MODE:
        return

    print("\nRepresentative Samples")
    for sample_idx, sample in enumerate(representative_samples, start=1):
        print(f"\nRepresentative Sample {sample_idx}")
        print("-" * 40)
        for sensor_idx, value in enumerate(sample, start=1):
            print(f"Sensor {sensor_idx:02d} : {value:8.2f}")


def print_registration_result(user_id: int, nickname: str) -> None:
    print("\n")
    print("=" * 45)
    print(" Registration Complete")
    print("=" * 45)
    print(f"User ID : {user_id}")
    print(f"Name    : {nickname}")
    print(f"Measured Samples : {NUM_SAMPLES}")
    print(f"Saved Samples    : {NUM_REPRESENTATIVE}")
    print("\nDatabase successfully updated.")
    print(DATABASE_PATH)
    print("=" * 45)


def register_pressure_user(user_id: int | str, nickname: str, port: str | None = None) -> int:
    """UI에서 호출할 수 있는 신규 사용자 체압 등록 함수."""

    connection = None
    try:
        baseline = load_resources()
        connection = open_serial_port(port=port)
        samples = collect_pressure_samples(connection, baseline)
        representative_samples = create_representative_samples(samples)
        print_representative_samples(representative_samples)
        saved_user_id = save_pressure_database(user_id, nickname, representative_samples)
        print_registration_result(saved_user_id, nickname)
        return saved_user_id
    finally:
        if connection is not None and connection.is_open:
            connection.close()
            if DEBUG_MODE:
                print("\nSerial port closed.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pressure database registration")
    parser.add_argument("--user-id", type=int, default=None, help="UI에서 생성한 user_id")
    parser.add_argument("--nickname", type=str, default=None, help="사용자 이름")
    parser.add_argument("--port", type=str, default=None, help="예: /dev/ttyACM0, COM4, auto")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        print("=" * 45)
        print(" Pressure Database Registration")
        print("=" * 45)

        user_id = args.user_id
        nickname = args.nickname

        if user_id is None:
            user_id_text = input("\nEnter User ID : ").strip()
            if user_id_text == "":
                raise ValueError("User ID cannot be empty.")
            user_id = int(user_id_text)

        if nickname is None:
            nickname = input("Enter User Name : ").strip()

        if str(nickname).strip() == "":
            raise ValueError("User name cannot be empty.")

        register_pressure_user(user_id, nickname, port=args.port)

    except KeyboardInterrupt:
        print("\nRegistration cancelled.")
    except Exception as exc:
        print(f"\n[ERROR] {exc}")


if __name__ == "__main__":
    main()