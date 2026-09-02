                                                           
                     
                                             
                                   
                                       
                              
 
      
                                       
                                    
                                        
                                      
                                    
                            
 
                                                               
                                       
                                                       
                                                           

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

BASE_DIR = Path(__file__).resolve().parent
PER_USER_DIR = BASE_DIR / "per_user_data"
SOURCE_DIR = PER_USER_DIR / "backup_150_per_posture"                    

SENSOR_COLS = [f"sensor_{i+1}" for i in range(16)]
KEEP_TOTAL = 90
KEEP_RATIO = KEEP_TOTAL / 150                                   


def dedup_by_similarity(sub_df: pd.DataFrame, keep_k: int) -> pd.DataFrame:

    sub_df = sub_df.sort_values("sample_id").reset_index(drop=True)
    n = len(sub_df)

    if keep_k >= n:
        return sub_df

    X = sub_df[SENSOR_COLS].values.astype(float)
    alive = list(range(n))

    while len(alive) > keep_k:

        sub_X = X[alive]
        m = len(alive)

        diff = sub_X[:, None, :] - sub_X[None, :, :]
        dist = np.sqrt((diff ** 2).sum(axis=2))
        np.fill_diagonal(dist, np.inf)

        flat_idx = np.argmin(dist)
        i, j = divmod(flat_idx, m)

                                              
                          
        remove_pos = max(i, j)
        alive.pop(remove_pos)

    return sub_df.iloc[alive]


def process_user(user_id: int) -> None:

    fname = f"posture_user{user_id}.csv"
    src_path = SOURCE_DIR / fname
    dst_path = PER_USER_DIR / fname

    df = pd.read_csv(src_path)
    kept_groups = []

    print(f"user{user_id}:")

    for posture, group in df.groupby("posture"):

        group = group.sort_values("sample_id")
        trial_ids = sorted(group["trial_id"].unique())

        selected_parts = []
        detail = []

        for trial_id in trial_ids:
            trial_sub = group[group["trial_id"] == trial_id]
            k = round(len(trial_sub) * KEEP_RATIO)

            selected_parts.append(dedup_by_similarity(trial_sub, k))
            detail.append(f"trial{trial_id}:{len(trial_sub)}->{k}")

        kept = pd.concat(selected_parts)

                                      
        if len(kept) > KEEP_TOTAL:
            kept = kept.sample(n=KEEP_TOTAL, random_state=42).sort_values("sample_id")
        elif len(kept) < KEEP_TOTAL:
            missing = KEEP_TOTAL - len(kept)
            leftover = group[~group["sample_id"].isin(kept["sample_id"])]
            extra = leftover.sample(n=min(missing, len(leftover)), random_state=42)
            kept = pd.concat([kept, extra]).sort_values("sample_id")

        kept_groups.append(kept)
        print(f"  {posture:15s} {len(group):4d} -> {len(kept):4d}  (" + ", ".join(detail) + ")")

    cleaned = pd.concat(kept_groups).sort_values("sample_id").reset_index(drop=True)
    cleaned.to_csv(dst_path, index=False)
    print(f"  total: {len(cleaned)}")
    print()


def main():

    if not SOURCE_DIR.exists():
        raise FileNotFoundError(
            f"{SOURCE_DIR} 가 없습니다. "
            "자세당 150개짜리 원본 백업이 있어야 이 스크립트를 다시 돌릴 수 있습니다."
        )

    for user_id in range(1, 9):
        process_user(user_id)


if __name__ == "__main__":
    main()
