#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

[ -f "$APP_DIR/seat_id_ports.env" ] && source "$APP_DIR/seat_id_ports.env"
[ -f "$APP_DIR/seat_id_active_ports.env" ] && source "$APP_DIR/seat_id_active_ports.env"

: "${SEAT_ID_ULTRASONIC_PORT:?등 초음파 포트를 seat_id_ports.env에 설정해주세요}"
if [ ! -e "$SEAT_ID_ULTRASONIC_PORT" ]; then
  echo "[ERROR] 등 초음파 포트가 없습니다: $SEAT_ID_ULTRASONIC_PORT"
  echo "        센서 실행 전 ./run_detect_ports.sh를 사용하세요."
  exit 2
fi

echo "[등 초음파] 포트: $SEAT_ID_ULTRASONIC_PORT"
exec python3 -u "$APP_DIR/spine_curve_monitor_4ch_no_s4.py" \
  --port "$SEAT_ID_ULTRASONIC_PORT" \
  --no-window \
  --wait-for-trigger "$APP_DIR/sensor_measurement_trigger.json" \
  --alert-hold 5 \
  --recovery-hold 1.5 \
  --output "$APP_DIR/posture_feedback.json"
