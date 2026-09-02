                                                           
                       
                                        
                             
                                                           

from __future__ import annotations

from pathlib import Path

import pandas as pd

BASE_DIR = Path(__file__).resolve().parent

INPUT_DIR = BASE_DIR / "per_user_data"

OUTPUT_PATH = BASE_DIR / "posture_database.csv"


def merge():

    csv_paths = sorted(INPUT_DIR.glob("posture_user*.csv"))

    if not csv_paths:
        raise FileNotFoundError(
            f"No per-user CSV files found in {INPUT_DIR}"
        )

    dataframes = []

    for path in csv_paths:

        dataframe = pd.read_csv(path)

        print(f"{path.name} : {len(dataframe)} rows")

        dataframes.append(dataframe)

    merged = pd.concat(
        dataframes,
        ignore_index=True,
    )

                                         
                              
    merged["sample_id"] = range(1, len(merged) + 1)

    merged.to_csv(
        OUTPUT_PATH,
        index=False,
    )

    print("=" * 60)
    print(f"Merged {len(csv_paths)} files -> {len(merged)} rows")
    print(f"Saved : {OUTPUT_PATH}")
    print("=" * 60)


if __name__ == "__main__":
    merge()
