                                                           
                   
                               
                         
 
       
                  
                  
                              
                                     
                    
                                            
                                                    
                                                           

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib

                                                
                                                
                                           
matplotlib.use("TkAgg")

import matplotlib.pyplot as plt

                                         
                                 
plt.rcParams["font.family"] = "Malgun Gothic"
plt.rcParams["axes.unicode_minus"] = False

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_DATASET_PATH = BASE_DIR / "review_forward_lean_user2_7_8.csv"
POSITION_PATH = BASE_DIR / "selected_sensor_positions.csv"
FLAGGED_OUTPUT_PATH = BASE_DIR / "flagged_samples.csv"

NUM_SENSORS = 16
GRID_SIZE = 12

                                             
                                                           
                         
FALLBACK_POSITIONS = [
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


def parse_args():

    parser = argparse.ArgumentParser(
        description="Posture dataset visual review tool",
    )

    parser.add_argument(
        "--file",
        type=str,
        default=str(DEFAULT_DATASET_PATH),
        help="검토할 CSV 경로 (기본값 : posture_database.csv)",
    )

    parser.add_argument(
        "--posture",
        type=str,
        default=None,
        help="특정 posture만 검토 (예 : forward_lean)",
    )

    parser.add_argument(
        "--user-id",
        type=int,
        default=None,
        help="특정 user_id만 검토",
    )

    return parser.parse_args()


def load_sensor_positions():

    if not POSITION_PATH.exists():
        print(
            f"[INFO] {POSITION_PATH.name}이 없어 기본 좌표를 사용합니다."
        )
        return FALLBACK_POSITIONS

    try:
        positions_df = pd.read_csv(POSITION_PATH)

        row_col = "Row" if "Row" in positions_df.columns else "row"
        col_col = "Column" if "Column" in positions_df.columns else "column"

        positions = list(
            zip(
                positions_df[row_col].astype(int),
                positions_df[col_col].astype(int),
            )
        )

        if len(positions) != NUM_SENSORS:
            print(
                f"[WARN] 센서 위치 개수가 {len(positions)}개라 "
                f"기본 좌표를 사용합니다 (16개 필요)."
            )
            return FALLBACK_POSITIONS

        return positions

    except Exception as error:

        print(f"[WARN] 센서 위치 파일 읽기 실패, 기본 좌표 사용 : {error}")
        return FALLBACK_POSITIONS


class DatasetReviewer:

    def __init__(self, dataframe: pd.DataFrame, positions):

        self.df = dataframe.reset_index(drop=True)
        self.positions = positions
        self.sensor_cols = [f"sensor_{i+1}" for i in range(NUM_SENSORS)]

        self.index = 0
        self.flagged_ids = set()

        all_values = self.df[self.sensor_cols].values.astype(float)
        self.vmin = 0.0
        self.vmax = max(1.0, float(np.percentile(all_values, 99)))

                                                      
                                              
        self.group_totals = (
            self.df.groupby(["user_id", "posture"]).size().to_dict()
        )
        self.group_keys = sorted(self.group_totals.keys())
        self.user_ids = sorted(self.df["user_id"].unique())

                                                          
                                               
        self.table = None
        self.current_table_postures = []

        self.fig, (self.ax_grid, self.ax_table) = plt.subplots(
            1, 2, figsize=(12.5, 6.5),
            gridspec_kw={"width_ratios": [1.1, 1]},
        )

        self.fig.canvas.mpl_connect(
            "key_press_event", self.on_key,
        )
        self.fig.canvas.mpl_connect(
            "button_press_event", self.on_click,
        )

        self.render()

        print("=" * 60)
        print("조작법")
        print("  -> / n : 다음 샘플")
        print("  <- / p : 이전 샘플")
        print("  x / d  : 현재 샘플 이상치로 표시(토글)")
        print("  s      : 지금까지 표시한 이상치 목록 CSV로 저장")
        print("  q      : 저장 후 종료")
        print("  숫자키 (1~9) 또는 표의 자세 행 클릭 : 그 자세의 첫 샘플로 이동")
        print("  Ctrl + 숫자키 (1~9)                : 그 순번의 user로 이동")
        print("=" * 60)

        plt.show()

    def current_row(self):
        return self.df.iloc[self.index]

    def render(self):

        row = self.current_row()
        sample_id = row["sample_id"]
        is_flagged = sample_id in self.flagged_ids

        values = row[self.sensor_cols].values.astype(float)

                                
        self.ax_grid.clear()

        grid = np.full((GRID_SIZE, GRID_SIZE), np.nan)

        for value, (grid_row, grid_col) in zip(values, self.positions):
            grid[grid_row, grid_col] = value

        self.ax_grid.imshow(
            grid,
            cmap="viridis",
            vmin=self.vmin,
            vmax=self.vmax,
            origin="upper",
        )

        for sensor_index, (value, (grid_row, grid_col)) in enumerate(
            zip(values, self.positions), start=1,
        ):
            is_outlier = value > self.vmax

            self.ax_grid.text(
                grid_col,
                grid_row,
                f"S{sensor_index}\n{value:.0f}",
                ha="center",
                va="center",
                fontsize=8,
                color="#ff6666" if is_outlier else "white",
                fontweight="bold" if is_outlier else "normal",
            )

        self.ax_grid.set_title("Sensor Grid (baseline-corrected)")
        self.ax_grid.set_xticks([])
        self.ax_grid.set_yticks([])
        self.ax_grid.set_xlim(-0.5, GRID_SIZE - 0.5)
        self.ax_grid.set_ylim(GRID_SIZE - 0.5, -0.5)

                                    
                                                    
                                               
        self.ax_table.clear()
        self.ax_table.axis("off")

        current_user_id = row["user_id"]
        current_key = (current_user_id, row["posture"])

        user_group_keys = [
            key for key in self.group_keys if key[0] == current_user_id
        ]
        self.current_table_postures = user_group_keys

        flagged_rows = self.df[self.df["sample_id"].isin(self.flagged_ids)]
        flagged_counts = (
            flagged_rows.groupby(["user_id", "posture"]).size().to_dict()
        )

        cell_text = []
        for key in user_group_keys:
            _, posture = key
            flagged_n = flagged_counts.get(key, 0)
            total_n = self.group_totals[key]
            cell_text.append([posture, f"{flagged_n} / {total_n}"])

        user_flagged = sum(
            flagged_counts.get(key, 0) for key in user_group_keys
        )
        user_total = sum(
            self.group_totals[key] for key in user_group_keys
        )
        cell_text.append(["소계", f"{user_flagged} / {user_total}"])

        table = self.ax_table.table(
            cellText=cell_text,
            colLabels=["Posture", "Flagged"],
            loc="upper center",
            cellLoc="center",
            bbox=[0.05, 0.55, 0.9, 0.4],
        )
        table.auto_set_font_size(False)
        table.set_fontsize(10)
        self.table = table

        n_rows = len(cell_text)

        for row_index in range(n_rows + 1):
            for col_index in range(2):
                cell = table[row_index, col_index]

                if row_index == 0:
                    cell.set_facecolor("#3C6FEA")
                    cell.set_text_props(color="white", fontweight="bold")
                elif row_index == n_rows:
                    cell.set_facecolor("#EEF2FA")
                    cell.set_text_props(fontweight="bold")
                elif user_group_keys[row_index - 1] == current_key:
                    cell.set_facecolor("#FFF3CD")

        total_flagged = len(self.flagged_ids)
        total_all = len(self.df)

        self.ax_table.text(
            0.5, 0.15,
            f"전체 로드된 데이터 기준\n플래그 : {total_flagged} / {total_all}",
            ha="center", va="center",
            fontsize=10, color="#6E6E73",
            transform=self.ax_table.transAxes,
        )

        flag_text = "  [FLAGGED]" if is_flagged else ""

        self.fig.suptitle(
            f"Sample {self.index + 1}/{len(self.df)}  "
            f"(sample_id={sample_id}, user_id={row['user_id']}, "
            f"posture={row['posture']}, trial_id={row['trial_id']})"
            f"{flag_text}",
            color="#d62728" if is_flagged else "black",
        )

        self.fig.canvas.draw_idle()

    def on_key(self, event):

        if event.key in ("right", "n"):
            self.index = min(self.index + 1, len(self.df) - 1)
            self.render()

        elif event.key in ("left", "p"):
            self.index = max(self.index - 1, 0)
            self.render()

        elif event.key in ("x", "d"):
            sample_id = self.current_row()["sample_id"]

            if sample_id in self.flagged_ids:
                self.flagged_ids.discard(sample_id)
            else:
                self.flagged_ids.add(sample_id)

            self.render()

        elif event.key == "s":
            self.save_flagged()

        elif event.key == "q":
            self.save_flagged()
            plt.close(self.fig)

        elif event.key is not None and event.key.startswith("ctrl+"):
            suffix = event.key[len("ctrl+"):]
            if suffix.isdigit():
                self.jump_to_user_by_slot(int(suffix))

        elif event.key is not None and event.key.isdigit():
            self.jump_to_posture_by_slot(int(event.key))

    def on_click(self, event):

        if event.inaxes != self.ax_table or self.table is None:
            return

        renderer = self.fig.canvas.get_renderer()

        for (row_index, _col_index), cell in self.table.get_celld().items():

            if row_index == 0:
                continue            

            data_row_index = row_index - 1
            if data_row_index >= len(self.current_table_postures):
                continue              

            bbox = cell.get_window_extent(renderer)
            if bbox.contains(event.x, event.y):
                user_id, posture = self.current_table_postures[data_row_index]
                self.jump_to_group(user_id, posture)
                return

    def jump_to_posture_by_slot(self, slot):

        slot_index = slot - 1
        if not (0 <= slot_index < len(self.current_table_postures)):
            return

        user_id, posture = self.current_table_postures[slot_index]
        self.jump_to_group(user_id, posture)

    def jump_to_user_by_slot(self, slot):

        slot_index = slot - 1
        if not (0 <= slot_index < len(self.user_ids)):
            return

        self.jump_to_user(self.user_ids[slot_index])

    def jump_to_group(self, user_id, posture):

        matches = self.df.index[
            (self.df["user_id"] == user_id) & (self.df["posture"] == posture)
        ]
        if len(matches) == 0:
            return

        self.index = int(matches[0])
        self.render()

    def jump_to_user(self, user_id):

        matches = self.df.index[self.df["user_id"] == user_id]
        if len(matches) == 0:
            return

        self.index = int(matches[0])
        self.render()

    def save_flagged(self):

        if len(self.flagged_ids) == 0:
            print("표시된 이상치가 없습니다.")
            return

        flagged_df = self.df[
            self.df["sample_id"].isin(self.flagged_ids)
        ]

                                                       
                                                       
                                         
                                                
        try:
            flagged_df.to_csv(FLAGGED_OUTPUT_PATH, index=False)

            print(
                f"이상치 {len(flagged_df)}개 저장 완료 : {FLAGGED_OUTPUT_PATH}"
            )

        except (PermissionError, OSError) as error:

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            fallback_path = FLAGGED_OUTPUT_PATH.with_name(
                f"{FLAGGED_OUTPUT_PATH.stem}_fallback_{timestamp}"
                f"{FLAGGED_OUTPUT_PATH.suffix}"
            )

            print(
                f"[WARN] {FLAGGED_OUTPUT_PATH.name} 저장 실패"
                f"(다른 프로그램에서 열려 있을 수 있음) : {error}"
            )

            try:
                flagged_df.to_csv(fallback_path, index=False)
                print(f"[WARN] 대신 여기에 저장했습니다 : {fallback_path}")

            except (PermissionError, OSError) as fallback_error:
                print(f"[ERROR] 대체 저장도 실패했습니다 : {fallback_error}")
                print("[ERROR] 플래그 데이터를 저장하지 못했습니다. 창을 닫지 마세요.")


def main():

    args = parse_args()

    dataset_path = Path(args.file)

    if not dataset_path.exists():
        raise FileNotFoundError(f"파일을 찾을 수 없습니다 : {dataset_path}")

    df = pd.read_csv(dataset_path)

    if args.posture is not None:
        df = df[df["posture"] == args.posture]

    if args.user_id is not None:
        df = df[df["user_id"] == args.user_id]

    if len(df) == 0:
        raise ValueError("조건에 맞는 샘플이 없습니다.")

    print(f"총 {len(df)}개 샘플 로드 완료 ({dataset_path.name})")

    positions = load_sensor_positions()

    DatasetReviewer(df, positions)


if __name__ == "__main__":
    main()
