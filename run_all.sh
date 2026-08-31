#!/usr/bin/env bash
set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
mkdir -p "$APP_DIR/logs"

echo "[Seat ID] 통합 실행 준비"

if [ ! -f "$APP_DIR/seat_id_ports.env" ]; then
  echo "[ERROR] seat_id_ports.env가 없습니다. seat_id_ports.env.example을 복사해 포트를 설정하세요."
  exit 2
fi

source "$APP_DIR/seat_id_ports.env"

port_exists() {
  [ -n "${1:-}" ] && [ -e "$1" ]
}

manual_pressure="${SEAT_ID_PRESSURE_PORT:-}"
manual_actuator="${SEAT_ID_ACTUATOR_PORT:-}"
manual_back="${SEAT_ID_ULTRASONIC_PORT:-}"
manual_neck="${SEAT_ID_NECK_PORT:-}"

# 고정해 둔 허브 경로가 모두 살아 있으면 자동 탐지를 전혀 실행하지 않는다.
# 하나라도 없을 때만 모든 센서 프로세스를 시작하기 전에 한 번 탐지한다.
if ! port_exists "$manual_pressure" || ! port_exists "$manual_actuator" || ! port_exists "$manual_back" || ! port_exists "$manual_neck"; then
  echo "[Seat ID] 설정 포트 일부가 없어 역할 자동 탐지를 한 번 실행합니다."
  python3 "$APP_DIR/detect_serial_roles.py" \
    --write "$APP_DIR/seat_id_detected_ports.env" || true
  if [ -f "$APP_DIR/seat_id_detected_ports.env" ]; then
    source "$APP_DIR/seat_id_detected_ports.env"
  fi

  # 존재하는 수동 by-path 설정은 자동 탐지 결과보다 우선한다.
  port_exists "$manual_pressure" && SEAT_ID_PRESSURE_PORT="$manual_pressure"
  port_exists "$manual_actuator" && SEAT_ID_ACTUATOR_PORT="$manual_actuator"
  port_exists "$manual_back" && SEAT_ID_ULTRASONIC_PORT="$manual_back"
  port_exists "$manual_neck" && SEAT_ID_NECK_PORT="$manual_neck"
fi

for required_name in SEAT_ID_PRESSURE_PORT SEAT_ID_ACTUATOR_PORT SEAT_ID_ULTRASONIC_PORT SEAT_ID_NECK_PORT; do
  required_value="${!required_name:-}"
  if ! port_exists "$required_value"; then
    echo "[ERROR] $required_name 포트를 사용할 수 없습니다: ${required_value:-미설정}"
    echo "        ./run_detect_ports.sh 실행 후 seat_id_ports.env를 확인하세요."
    exit 2
  fi
done

pressure_real="$(readlink -f "$SEAT_ID_PRESSURE_PORT")"
back_real="$(readlink -f "$SEAT_ID_ULTRASONIC_PORT")"
neck_real="$(readlink -f "$SEAT_ID_NECK_PORT")"
actuator_real="$(readlink -f "$SEAT_ID_ACTUATOR_PORT")"

if [ "$pressure_real" = "$back_real" ] \
  || [ "$pressure_real" = "$neck_real" ] \
  || [ "$pressure_real" = "$actuator_real" ] \
  || [ "$back_real" = "$neck_real" ] \
  || [ "$back_real" = "$actuator_real" ] \
  || [ "$neck_real" = "$actuator_real" ]; then
  echo "[ERROR] 압력/액추에이터/등/목 포트가 서로 중복됩니다."
  echo "  pressure=$SEAT_ID_PRESSURE_PORT"
  echo "  actuator=$SEAT_ID_ACTUATOR_PORT"
  echo "  back=$SEAT_ID_ULTRASONIC_PORT"
  echo "  neck=$SEAT_ID_NECK_PORT"
  exit 2
fi

# 모든 자식 스크립트가 동일한 최종 포트를 사용하도록 이번 실행 전용 설정을 만든다.
{
  printf 'export SEAT_ID_PRESSURE_PORT=%q\n' "$SEAT_ID_PRESSURE_PORT"
  printf 'export SEAT_ID_ULTRASONIC_PORT=%q\n' "$SEAT_ID_ULTRASONIC_PORT"
  printf 'export SEAT_ID_NECK_PORT=%q\n' "$SEAT_ID_NECK_PORT"
  printf 'export SEAT_ID_ACTUATOR_PORT=%q\n' "$SEAT_ID_ACTUATOR_PORT"
} > "$APP_DIR/seat_id_active_ports.env"

echo "[Seat ID] 최종 포트"
echo "  압력: $SEAT_ID_PRESSURE_PORT"
echo "  등  : $SEAT_ID_ULTRASONIC_PORT"
echo "  목  : $SEAT_ID_NECK_PORT"
echo "  액추: ${SEAT_ID_ACTUATOR_PORT:-미사용}"

# 이전 인스턴스가 같은 포트를 잡고 있지 않게 정리한다.
pkill -f "spine_curve_monitor_4ch_no_s4.py" 2>/dev/null || true
pkill -f "neck_cva_monitor_2ch.py" 2>/dev/null || true
pkill -f "hardware_bridge.py" 2>/dev/null || true
pkill -f "$APP_DIR/app.py" 2>/dev/null || true
sleep 0.8

rm -f "$APP_DIR/sensor_measurement_trigger.json" \
      "$APP_DIR/sensor_measurement_trigger.json.tmp" \
      "$APP_DIR/posture_feedback.json" \
      "$APP_DIR/posture_feedback.json.tmp" \
      "$APP_DIR/neck_posture_feedback.json" \
      "$APP_DIR/neck_posture_feedback.json.tmp"

open_term() {
  local title="$1"
  local script="$2"
  local cmd="cd '$APP_DIR'; ./$script; code=\$?; echo; echo '[종료 코드]' \$code; exec bash"
  if command -v lxterminal >/dev/null 2>&1; then
    lxterminal --title="$title" -e bash -lc "$cmd" &
    return 0
  fi
  if command -v x-terminal-emulator >/dev/null 2>&1; then
    x-terminal-emulator -T "$title" -e bash -lc "$cmd" &
    return 0
  fi
  if command -v gnome-terminal >/dev/null 2>&1; then
    gnome-terminal --title="$title" -- bash -lc "$cmd" &
    return 0
  fi
  if command -v xterm >/dev/null 2>&1; then
    xterm -T "$title" -e bash -lc "$cmd" &
    return 0
  fi
  return 1
}

if open_term "Seat ID · 등 초음파" "run_back_ultrasonic.sh"; then
  sleep 1.4
  open_term "Seat ID · 목 초음파" "run_neck_monitor.sh"
  sleep 1.4
  open_term "Seat ID · 액추에이터" "run_actuator.sh"
  sleep 0.8
  open_term "Seat ID · 앱" "run_app.sh"
  exit 0
fi

# 터미널 앱이 없는 환경에서는 센서 서비스를 로그 파일로 실행하고 UI는 현재 터미널에서 연다.
nohup "$APP_DIR/run_back_ultrasonic.sh" > "$APP_DIR/logs/back_ultrasonic.log" 2>&1 &
echo $! > "$APP_DIR/logs/back_ultrasonic.pid"
sleep 1.2
nohup "$APP_DIR/run_neck_monitor.sh" > "$APP_DIR/logs/neck_monitor.log" 2>&1 &
echo $! > "$APP_DIR/logs/neck_monitor.pid"
sleep 1.2
nohup "$APP_DIR/run_actuator.sh" > "$APP_DIR/logs/actuator.log" 2>&1 &
echo $! > "$APP_DIR/logs/actuator.pid"
exec "$APP_DIR/run_app.sh"
