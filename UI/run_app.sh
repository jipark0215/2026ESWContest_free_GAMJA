#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"

if [ ! -f "$APP_DIR/seat_id_ports.env" ]; then
  echo "[ERROR] seat_id_ports.env가 없습니다."
  exit 2
fi

source "$APP_DIR/seat_id_ports.env"
[ -f "$APP_DIR/seat_id_active_ports.env" ] && source "$APP_DIR/seat_id_active_ports.env"

: "${SEAT_ID_PRESSURE_PORT:?압력센서 포트를 seat_id_ports.env에 설정해주세요}"
if [ ! -e "$SEAT_ID_PRESSURE_PORT" ]; then
  echo "[ERROR] 압력센서 포트가 없습니다: $SEAT_ID_PRESSURE_PORT"
  exit 2
fi

export SEAT_ID_ULTRASONIC_FEEDBACK="$APP_DIR/posture_feedback.json"
export SEAT_ID_NECK_FEEDBACK="$APP_DIR/neck_posture_feedback.json"

echo "[메인 UI] 압력센서 포트: $SEAT_ID_PRESSURE_PORT"
exec python3 -u "$APP_DIR/app.py"
