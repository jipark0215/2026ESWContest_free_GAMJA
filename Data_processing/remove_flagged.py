                                                           
                   
                                                 
                                                
              
 
                                                
                                    
                                                  
                                        
                                                           

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

DATASET_PATH = BASE_DIR / "posture_database.csv"
FLAGGED_PATH = BASE_DIR / "flagged_samples.csv"
PER_USER_DIR = BASE_DIR / "per_user_data"
BACKUP_DIR = BASE_DIR / "backup"

MATCH_COLS = [
    "user_id",
    "posture",
    "trial_id",
    "timestamp",
] + [f"sensor_{i+1}" for i in range(16)]


def make_key(df: pd.DataFrame) -> pd.Series:
    return df[MATCH_COLS].astype(str).agg("|".join, axis=1)


def backup_file(path: Path, stamp: str):
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backup_path = BACKUP_DIR / f"{path.stem}_before_flag_removal_{stamp}{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def main():

    if not FLAGGED_PATH.exists():
        raise FileNotFoundError(
            f"{FLAGGED_PATH.name}이 없습니다. "
            "review_dataset.py에서 's'로 먼저 저장해주세요."
        )

    flagged = pd.read_csv(FLAGGED_PATH)

    if len(flagged) == 0:
        print("flagged_samples.csv에 표시된 샘플이 없습니다.")
        return

    flagged_keys = set(make_key(flagged))
    print(f"제거 대상 : {len(flagged_keys)}개 (flagged_samples.csv 기준)")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

                                            
    if DATASET_PATH.exists():

        df = pd.read_csv(DATASET_PATH)
        before = len(df)

        keys = make_key(df)
        removed_mask = keys.isin(flagged_keys)
        removed_count = int(removed_mask.sum())

        if removed_count > 0:
            backup_path = backup_file(DATASET_PATH, stamp)
            print(f"[backup] {DATASET_PATH.name} -> {backup_path}")

            cleaned = df[~removed_mask].reset_index(drop=True)
            cleaned["sample_id"] = range(1, len(cleaned) + 1)
            cleaned.to_csv(DATASET_PATH, index=False)

            print(f"{DATASET_PATH.name} : {before} -> {len(cleaned)} ({removed_count}개 제거)")
        else:
            print(f"{DATASET_PATH.name} : 제거 대상 없음")

                                             
    for user_file in sorted(PER_USER_DIR.glob("posture_user*.csv")):

        df = pd.read_csv(user_file)
        keys = make_key(df)
        removed_mask = keys.isin(flagged_keys)
        removed_count = int(removed_mask.sum())

        if removed_count == 0:
            continue

        backup_path = backup_file(user_file, stamp)
        print(f"[backup] {user_file.name} -> {backup_path}")

        cleaned = df[~removed_mask].reset_index(drop=True)
        cleaned.to_csv(user_file, index=False)

        print(f"{user_file.name} : {len(df)} -> {len(cleaned)} ({removed_count}개 제거)")

    print()
    print("완료.")


if __name__ == "__main__":
    main()
