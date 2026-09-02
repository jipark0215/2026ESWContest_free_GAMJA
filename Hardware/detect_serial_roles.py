#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import serial
from serial.tools import list_ports


BAUD = 115200
READ_SECONDS = 2.2
ARDUINO_BOOT_SECONDS = 1.0

LEONARDO_USB_IDS = {
    (0x2341, 0x8036),  # Arduino LLC Leonardo
    (0x2A03, 0x8036),  # Arduino SRL Leonardo
}


def stable_path(device: str) -> str:
    base = Path("/dev/serial/by-path")
    if base.exists():
        candidates = []
        for link in base.iterdir():
            try:
                if os.path.realpath(link) == os.path.realpath(device):
                    candidates.append(str(link))
            except OSError:
                pass
        if candidates:
            return sorted(candidates)[0]
    return device


def classify_line(line: str) -> str | None:
    line = line.strip()
    if not line:
        return None

    try:
        payload = json.loads(line)
    except Exception:
        payload = None

    if isinstance(payload, dict):
        keys = set(payload)
        if {"head_mm", "c7_mm"}.issubset(keys):
            return "neck"
        if {"s1", "s2", "s3", "s5"}.issubset(keys):
            return "back"

    parts = [part.strip() for part in line.split(",")]
    if len(parts) == 16:
        try:
            values = [float(part) for part in parts]
        except ValueError:
            values = []
        if len(values) == 16 and all(0.0 <= value <= 1023.0 for value in values):
            return "pressure"

    upper = line.upper()
    if (
        upper in {"READY", "DONE", "REFERENCE_SET", "STOPPED"}
        or upper.startswith("ERROR")
    ):
        return "actuator"

    return None


def open_port(device: str):
    kwargs = dict(port=device, baudrate=BAUD, timeout=0.08, write_timeout=0.2)
    try:
        return serial.Serial(exclusive=True, **kwargs)
    except TypeError:
        return serial.Serial(**kwargs)


def is_leonardo_port(port_info: object) -> bool:
    """HID 버튼용 Leonardo를 액추에이터 후보에서 제외한다."""

    vid = getattr(port_info, "vid", None)
    pid = getattr(port_info, "pid", None)
    if vid is not None and pid is not None and (int(vid), int(pid)) in LEONARDO_USB_IDS:
        return True

    searchable = " ".join(
        str(getattr(port_info, key, "") or "")
        for key in ("description", "product", "manufacturer", "interface", "hwid")
    ).lower()
    return "leonardo" in searchable


def probe(device: str) -> str | None:
    try:
        connection = open_port(device)
    except Exception as exc:
        print(f"[건너뜀] {device}: {exc}")
        return None

    try:
        time.sleep(ARDUINO_BOOT_SECONDS)
        deadline = time.monotonic() + READ_SECONDS
        while time.monotonic() < deadline:
            try:
                line = connection.readline().decode("utf-8", errors="ignore").strip()
            except Exception:
                break
            role = classify_line(line)
            if role:
                return role

        # 액추에이터는 평소 출력이 없을 수 있으므로 PING만 보낸다. 모터 동작 명령은 아니다.
        try:
            connection.write(b"PING\n")
            connection.flush()
            ping_deadline = time.monotonic() + 0.7
            while time.monotonic() < ping_deadline:
                line = connection.readline().decode("utf-8", errors="ignore").strip()
                role = classify_line(line)
                if role == "actuator":
                    return role
        except Exception:
            pass

        return None
    finally:
        try:
            connection.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", type=Path, default=Path("seat_id_detected_ports.env"))
    args = parser.parse_args()

    port_infos = [
        p
        for p in list_ports.comports()
        if p.device.startswith("/dev/ttyACM") or p.device.startswith("/dev/ttyUSB")
    ]

    if not port_infos:
        print("탐지할 ttyACM/ttyUSB 장치가 없습니다.")
        return 1

    print("Seat ID Arduino 역할 자동 탐지 시작")
    found: dict[str, str] = {}
    unknown_candidates: list[str] = []
    leonardo_devices: list[str] = []

    for port_info in sorted(port_infos, key=lambda item: item.device):
        device = str(port_info.device)
        role = probe(device)
        if role and role not in found:
            found[role] = stable_path(device)
            print(f"  {device:<16} -> {role}")
        elif is_leonardo_port(port_info):
            leonardo_devices.append(device)
            print(f"  {device:<16} -> Leonardo/HID 버튼")
        else:
            unknown_candidates.append(device)
            print(f"  {device:<16} -> 응답 없는 장치")

    # 액추에이터 펌웨어가 PING 명령을 구현하지 않은 경우 평소에는 아무
    # 문자열도 출력하지 않는다. 압력/등/목과 Leonardo를 제거한 뒤 남은
    # 포트가 하나뿐이면 그 포트를 액추에이터로 안전하게 추정한다.
    if "actuator" not in found and len(unknown_candidates) == 1:
        actuator_device = unknown_candidates[0]
        found["actuator"] = stable_path(actuator_device)
        print(
            f"  [추론] {actuator_device} -> actuator "
            "(압력/등/목/Leonardo 제외 후 남은 유일한 포트)"
        )
    elif "actuator" not in found and len(unknown_candidates) > 1:
        print(
            "  [주의] 응답 없는 포트가 여러 개라 액추에이터를 자동 확정할 수 없습니다: "
            + ", ".join(unknown_candidates)
        )

    mapping = {
        "pressure": "SEAT_ID_PRESSURE_PORT",
        "actuator": "SEAT_ID_ACTUATOR_PORT",
        "back": "SEAT_ID_ULTRASONIC_PORT",
        "neck": "SEAT_ID_NECK_PORT",
    }

    lines = [
        "# 자동 생성 파일 - run_all.sh 시작 시 갱신",
        f"# generated_at={time.strftime('%Y-%m-%d %H:%M:%S')}",
    ]

    for role, env_name in mapping.items():
        if role in found:
            lines.append(f'export {env_name}="{found[role]}"')

    args.write.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\n탐지 결과:")
    for role in ("pressure", "actuator", "back", "neck"):
        print(f"  {role:<9}: {found.get(role, '미탐지')}")

    required = ("pressure", "actuator", "back", "neck")
    missing = [role for role in required if role not in found]
    if missing:
        print(f"\n주의: 자동 탐지 실패 역할={missing}")
        print("기존 seat_id_ports.env 값으로 fallback할 수 있습니다.")
        return 2

    print(f"\n저장 완료: {args.write}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
