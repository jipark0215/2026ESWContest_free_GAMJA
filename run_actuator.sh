#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

[ -f "$APP_DIR/seat_id_ports.env" ] && source "$APP_DIR/seat_id_ports.env"
[ -f "$APP_DIR/seat_id_active_ports.env" ] && source "$APP_DIR/seat_id_active_ports.env"

if [ -z "${SEAT_ID_ACTUATOR_PORT:-}" ] || [ ! -e "$SEAT_ID_ACTUATOR_PORT" ]; then
  echo "[액추에이터] 설정 포트가 없어 실행 전 역할 탐지를 시도합니다."
  python3 "$APP_DIR/detect_serial_roles.py" \
    --write "$APP_DIR/seat_id_detected_ports.env" || true
  [ -f "$APP_DIR/seat_id_detected_ports.env" ] && source "$APP_DIR/seat_id_detected_ports.env"
fi

if [ -z "${SEAT_ID_ACTUATOR_PORT:-}" ] || [ ! -e "$SEAT_ID_ACTUATOR_PORT" ]; then
  echo "[ERROR] 액추에이터 포트를 확정하지 못했습니다."
  echo "        모든 Seat ID 프로그램을 끈 뒤 ./run_detect_ports.sh 결과를 확인하세요."
  exit 2
fi

echo "[액추에이터] 포트: $SEAT_ID_ACTUATOR_PORT"
exec env SEAT_ID_ACTUATOR_PORT="$SEAT_ID_ACTUATOR_PORT" \
  python3 -u "$APP_DIR/hardware_bridge.py"
