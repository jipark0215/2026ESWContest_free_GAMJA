#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

[ -f "$APP_DIR/seat_id_ports.env" ] && source "$APP_DIR/seat_id_ports.env"
[ -f "$APP_DIR/seat_id_active_ports.env" ] && source "$APP_DIR/seat_id_active_ports.env"

: "${SEAT_ID_NECK_PORT:?목 초음파 포트를 seat_id_ports.env에 설정해주세요}"
if [ ! -e "$SEAT_ID_NECK_PORT" ]; then
  echo "[ERROR] 목 초음파 포트가 없습니다: $SEAT_ID_NECK_PORT"
  echo "        센서 실행 전 ./run_detect_ports.sh를 사용하세요."
  exit 2
fi

echo "[목 초음파] 포트: $SEAT_ID_NECK_PORT"
exec python3 -u "$APP_DIR/neck_cva_monitor_2ch.py" \
  --port "$SEAT_ID_NECK_PORT" \
  --no-window \
  --wait-for-trigger "$APP_DIR/sensor_measurement_trigger.json" \
  --vertical-gap-mm "${SEAT_ID_NECK_VERTICAL_GAP_MM:-200}" \
  --angle-threshold "${SEAT_ID_NECK_ANGLE_THRESHOLD:-5}" \
  --posture-hold "${SEAT_ID_NECK_POSTURE_HOLD:-5}" \
  --recovery-hold "${SEAT_ID_NECK_RECOVERY_HOLD:-1.5}" \
  --output "$APP_DIR/neck_posture_feedback.json"
