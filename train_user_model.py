from __future__ import annotations

import math
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC


BASE_DIR = Path(__file__).resolve().parent
DATABASE_PATH = BASE_DIR / "pressure_database.csv"
MODEL_PATH = BASE_DIR / "user_model.pkl"
SCALER_PATH = BASE_DIR / "user_scaler.pkl"

NUM_SENSORS = 16
RANDOM_STATE = 42


def normalize_database_schema(database: pd.DataFrame) -> pd.DataFrame:
    """name/sensor1 형식도 nickname/sensor_1 형식으로 변환한다."""

    renamed: dict[str, str] = {}

    if "name" in database.columns and "nickname" not in database.columns:
        renamed["name"] = "nickname"

    for index in range(1, NUM_SENSORS + 1):
        old_name = f"sensor{index}"
        new_name = f"sensor_{index}"

        if old_name in database.columns and new_name not in database.columns:
            renamed[old_name] = new_name

    if renamed:
        database = database.rename(columns=renamed)

    return database


def load_training_data() -> tuple[np.ndarray, np.ndarray]:
    if not DATABASE_PATH.exists():
        raise FileNotFoundError(
            f"데이터베이스 파일이 없습니다: {DATABASE_PATH}"
        )

    database = pd.read_csv(DATABASE_PATH)
    database = normalize_database_schema(database)

    sensor_columns = [
        f"sensor_{index}"
        for index in range(1, NUM_SENSORS + 1)
    ]

    required_columns = {"user_id", *sensor_columns}
    missing_columns = required_columns - set(database.columns)

    if missing_columns:
        raise ValueError(
            "pressure_database.csv에 필요한 열이 없습니다: "
            + ", ".join(sorted(missing_columns))
        )

    if database.empty:
        raise ValueError(
            "pressure_database.csv에 학습 데이터가 없습니다."
        )

    numeric_frame = database[
        ["user_id", *sensor_columns]
    ].apply(
        pd.to_numeric,
        errors="coerce",
    )

    before_count = len(numeric_frame)
    numeric_frame = numeric_frame.dropna().copy()
    removed_count = before_count - len(numeric_frame)

    if removed_count:
        print(f"빈 값 또는 잘못된 숫자 행 제외: {removed_count}개")

    if numeric_frame.empty:
        raise ValueError(
            "학습에 사용할 수 있는 실제 숫자 데이터가 없습니다."
        )

    x = numeric_frame[
        sensor_columns
    ].to_numpy(dtype=np.float32)

    y = numeric_frame[
        "user_id"
    ].to_numpy(dtype=int)

    unique_users, counts = np.unique(
        y,
        return_counts=True,
    )

    if unique_users.size < 2:
        raise ValueError(
            "사용자 식별 SVM은 실제 센서 데이터가 있는 "
            "최소 2명의 사용자가 필요합니다. "
            f"현재 유효 사용자 수: {unique_users.size}"
        )

    print("=" * 60)
    print("User Identification Model Training")
    print("=" * 60)
    print(f"Database      : {DATABASE_PATH}")
    print(f"Valid samples : {len(y)}")
    print(f"Feature shape : {x.shape}")
    print(f"User IDs      : {unique_users.tolist()}")
    print(
        "Samples/user : "
        f"{dict(zip(unique_users.tolist(), counts.tolist()))}"
    )

    return x, y


def can_make_stratified_split(
    y: np.ndarray,
) -> tuple[bool, int]:
    unique_users, counts = np.unique(
        y,
        return_counts=True,
    )

    class_count = int(unique_users.size)
    sample_count = int(y.size)

    if counts.min() < 2:
        return False, 0

    test_count = max(
        class_count,
        int(math.ceil(sample_count * 0.2)),
    )
    train_count = sample_count - test_count

    if train_count < class_count:
        return False, 0

    if test_count >= sample_count:
        return False, 0

    return True, test_count


def build_model() -> SVC:
    return SVC(
        kernel="rbf",
        probability=True,
        class_weight="balanced",
        random_state=RANDOM_STATE,
    )


def evaluate_model(
    x: np.ndarray,
    y: np.ndarray,
) -> None:
    can_split, test_count = can_make_stratified_split(y)

    if not can_split:
        print(
            "\nEvaluation skipped: "
            "사용자별 검증 샘플이 충분하지 않습니다."
        )
        return

    x_train, x_test, y_train, y_test = train_test_split(
        x,
        y,
        test_size=test_count,
        random_state=RANDOM_STATE,
        stratify=y,
    )

    scaler = StandardScaler()
    x_train_scaled = scaler.fit_transform(x_train)
    x_test_scaled = scaler.transform(x_test)

    model = build_model()
    model.fit(x_train_scaled, y_train)

    prediction = model.predict(x_test_scaled)

    print("\nValidation result")
    print(
        f"Accuracy : "
        f"{accuracy_score(y_test, prediction):.4f}"
    )
    print(
        classification_report(
            y_test,
            prediction,
            labels=np.unique(y),
            zero_division=0,
        )
    )


def atomic_joblib_dump(
    value,
    destination: Path,
) -> None:
    temporary_path = destination.with_name(
        destination.name + ".tmp"
    )

    joblib.dump(value, temporary_path)
    os.replace(temporary_path, destination)


def train_and_save_final_model(
    x: np.ndarray,
    y: np.ndarray,
) -> None:
    scaler = StandardScaler()
    x_scaled = scaler.fit_transform(x)

    model = build_model()
    model.fit(x_scaled, y)

    atomic_joblib_dump(model, MODEL_PATH)
    atomic_joblib_dump(scaler, SCALER_PATH)

    print("\nSaved model files")
    print(f"Model   : {MODEL_PATH}")
    print(f"Scaler  : {SCALER_PATH}")
    print(f"Classes : {model.classes_.tolist()}")
    print("MODEL_UPDATE_COMPLETE")


def main() -> int:
    try:
        x, y = load_training_data()
        evaluate_model(x, y)
        train_and_save_final_model(x, y)
        return 0

    except Exception as error:
        print(f"\n[ERROR] {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
