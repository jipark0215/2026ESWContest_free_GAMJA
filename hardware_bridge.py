from __future__ import annotations

import csv
import time
from pathlib import Path

import smart_chair_actuator_module as hw


BASE_DIR = Path(__file__).resolve().parent
HARDWARE_COMMAND_CSV_PATH = BASE_DIR / "hardware_command.csv"

# 사용자를 적용해야 하는 UI 이벤트
APPLY_EVENTS = {
    "USER_SELECTED",
    "USER_CHANGED",
    "USER_RESUMED",
    "NEW_USER_REGISTERED",
    "SEAT_SETTING_UPDATED",
    "USER_CONFIRMED",
    "AUTO_CONFIRMED",
    "PROFILE_SELECTED",
    "APPLY_USER",
}

# P 주차 안전모드 또는 세션 종료가 들어오면
# 기준 위치로 복귀시키고 현재 사용자 상태를 비운다.
#
# UI에서는 P 입력 시 event="PARK_SAFE"를 보내는 것을 권장한다.
# event="P"도 같은 동작을 하도록 호환 처리한다.
RESET_EVENTS = {
    "SESSION_END",
    "PARK_SAFE",
    "P",
}

# 설정 저장 직후에는 동일 사용자여도 새 값을 다시 적용해야 한다.
FORCE_APPLY_EVENTS = {
    "NEW_USER_REGISTERED",
    "SEAT_SETTING_UPDATED",
    # 주차 후에는 Python/Arduino의 이전 상태와 관계없이 반드시 다시 적용한다.
    "USER_RESUMED",
    "USER_CHANGED",
}


def read_command_rows() -> list[dict[str, str]]:
    if not HARDWARE_COMMAND_CSV_PATH.exists():
        return []

    try:
        with open(HARDWARE_COMMAND_CSV_PATH, "r", encoding="utf-8-sig", newline="") as file:
            return list(csv.DictReader(file))
    except Exception as exc:
        print(f"[WARN] hardware_command.csv 읽기 실패: {exc}")
        return []


def main() -> None:
    print("======================================")
    print("Seat ID 하드웨어 브릿지 시작")
    print("======================================")
    print(f"작업 폴더: {BASE_DIR}")
    print(f"Arduino 포트: {hw.ACTUATOR_PORT}")
    print()

    print("[1] user_profile.csv → actuator_profile.csv 전체 동기화")
    try:
        hw.sync_all_actuator_profiles()
    except Exception as exc:
        print(f"[WARN] 초기 프로필 동기화 실패, 브릿지는 계속 실행합니다: {exc}")

    print()
    print("[2] Arduino Uno 연결")
    connection = hw.open_actuator_serial()
    applier = hw.UserSeatApplier(connection)

    try:
        print()
        print("[3] 수동 기준 위치 확인")
        print("코드 실행 전에 다음 상태로 미리 맞춰 두어야 합니다.")
        print("- 시트 액추에이터 50 mm 확장")
        print("- 등받이 액추에이터 25 mm 확장")
        print("- 등받이 각도 110도")
        print("최초 1회 자동 기준점 생성 동작은 수행하지 않습니다.")

        seen_count = len(read_command_rows())

        print()
        print("[4] UI 명령 대기 중")
        print("P/PARK_SAFE 입력: 기준 위치 복귀 후 현재 사용자 상태 초기화")
        print("그다음 UI의 확정 user_id를 받으면 해당 사용자 설정을 새로 적용")
        print("시트 이동 단계에서는 등받이 액추에이터가 반대 방향으로 동시에 보상합니다.")
        print("종료: Ctrl + C")
        print()

        while True:
            rows = read_command_rows()

            if len(rows) > seen_count:
                new_rows = rows[seen_count:]
                seen_count = len(rows)

                for row in new_rows:
                    user_id_raw = str(row.get("user_id", "")).strip()
                    event = str(row.get("event", "")).strip().upper()

                    if event in RESET_EVENTS:
                        print(f"\n[RESET] event={event}: 기준 위치로 복귀")
                        print("[RESET] 등받이 110도 복귀 → 시트 기준 위치 복귀")
                        try:
                            applier.reset_to_reference_and_clear_user()
                            print("[OK] 기준 위치 복귀 및 현재 사용자 상태 초기화 완료")
                        except Exception as exc:
                            # 브릿지는 다음 UI 명령을 받을 수 있도록 유지한다.
                            # 단, DONE 없는 동작은 성공으로 간주하지 않는다.
                            print(f"[ERROR] 기준 위치 복귀 확인 실패: {exc}")
                            print("[RECOVER] 브릿지를 종료하지 않고 다음 명령을 기다립니다.")
                        print("[WAIT] UI의 다음 확정 사용자 명령을 기다립니다.")
                        continue

                    if event and event not in APPLY_EVENTS:
                        print(f"[SKIP] 적용 대상 이벤트 아님: event={event}, user_id={user_id_raw}")
                        continue

                    if user_id_raw == "":
                        print(f"[SKIP] user_id가 없는 명령: {row}")
                        continue

                    try:
                        user_id = int(float(user_id_raw))
                    except ValueError:
                        print(f"[SKIP] user_id가 숫자가 아님: {user_id_raw}")
                        continue

                    print()
                    print(f"[COMMAND] UI 명령 감지: event={event or '(empty)'}, user_id={user_id}")

                    try:
                        print("[UPDATE] 최신 위치·각도를 초 데이터로 변환 후 저장")
                        hw.update_user_actuator_profile(user_id)

                        force = event in FORCE_APPLY_EVENTS
                        applied = applier.apply_user(user_id, force=force)

                        if applied:
                            print("[APPLY] 기준점 복귀 후 새 사용자 위치 적용 완료")
                        else:
                            print("[SKIP] 동일 사용자이며 설정 변경이 없어 재동작하지 않음")
                    except Exception as exc:
                        print(f"[ERROR] 사용자 {user_id} 적용 실패: {exc}")

            time.sleep(0.3)

    except KeyboardInterrupt:
        print("\n[EXIT] 하드웨어 브릿지 종료")

    finally:
        active_connection = applier.connection
        if active_connection.is_open:
            active_connection.close()
        print("[SERIAL] 포트 닫음")


if __name__ == "__main__":
    main()
