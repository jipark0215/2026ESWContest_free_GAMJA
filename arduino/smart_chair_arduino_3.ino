/*
  Smart Chair - Arduino Uno Dual Linear Actuator Controller

  Firmware protocol version: SEAT_ID_ACTUATOR_R7

  수동 기준 위치 준비
    - 코드 실행 전에 시트 액추에이터는 50 mm,
      등받이 액추에이터는 25 mm 확장된 상태로 미리 맞춘다.
    - 등받이 각도는 해당 상태에서 사용자가 110도로 수동 설정한다.
    - 프로그램은 시작 위치를 곧바로 기준점으로 사용하며,
      최초 1회 자동 기준점 생성 동작은 수행하지 않는다.

  Python 명령

  APPLY,<seat_target_ms>,<backrest_target_ms>
    모든 APPLY:
      1) 현재 등받이 각도를 110도 기준으로 복귀
      2) 시트를 기준 위치로 복귀시키면서 등받이 액추에이터가 반대 방향으로 보상
      3) 새 시트 위치로 이동하면서 등받이 액추에이터가 반대 방향으로 보상
      4) 시트 이동이 끝난 뒤 등받이 각도만 따로 조절
      5) 전체 동작이 끝나면 DONE 전송

  MOVE,<seat_target_ms>,<backrest_target_ms>
    현재 위치에서 시트 보상 단계 후 등받이 각도 단계를 순차 실행하는 시험용 명령

  RESET
    등받이 각도를 110도로 복귀한 뒤 시트와 보상 액추에이터를 기준 위치로 복귀

  SET_REFERENCE
    시험용 수동 기준 설정 명령. 정상 UI 흐름에서는 사용하지 않는다.

  STOP
    두 액추에이터 긴급 정지

  시간값의 의미
    seat_target_ms:
      양수 = 시트 액추에이터 확장, 음수 = 수축
    backrest_target_ms:
      양수 = 등받이 액추에이터 확장(110도보다 작은 각도)
      음수 = 등받이 액추에이터 수축(110도보다 큰 각도)
*/

// ========================================================
// 1. BTS7960 핀 설정
// ========================================================

// 시트 위치 액추에이터용 BTS7960
const int SEAT_RPWM_PIN = 5;
const int SEAT_LPWM_PIN = 6;
const int SEAT_REN_PIN  = 7;
const int SEAT_LEN_PIN  = 8;

// 등받이 각도 액추에이터용 BTS7960
const int BACK_RPWM_PIN = 9;
const int BACK_LPWM_PIN = 10;
const int BACK_REN_PIN  = 11;
const int BACK_LEN_PIN  = 12;

const int MOTOR_PWM = 255;
const char FIRMWARE_VERSION[] = "SEAT_ID_ACTUATOR_R7";

// ========================================================
// 2. 실제 액추에이터 및 기구 사양
// ========================================================

// 시트 액추에이터: 12 V, 15 mm/s, 64 N, 100 mm stroke
const float SEAT_STROKE_MM = 100.0;
const float SEAT_REFERENCE_EXTENSION_MM = 50.0;
const float SEAT_SPEED_MM_S = 15.0;
const float SEAT_END_MARGIN_MM = 5.0;

// UI에서 허용하는 시트 입력 범위: -20~+20 mm
const float SEAT_SAFE_MIN_MM = -20.0;
const float SEAT_SAFE_MAX_MM = 20.0;

// 등받이 액추에이터: 12 V, 15 mm/s, 64 N, 50 mm stroke
const float BACKREST_STROKE_MM = 50.0;
const float BACKREST_REFERENCE_EXTENSION_MM = 25.0;
const float BACKREST_SPEED_MM_S = 15.0;
const float BACKREST_END_MARGIN_MM = 5.0;

// 랙·피니언 및 각도 범위
const float PINION_DIAMETER_MM = 25.0;
const float BACKREST_REFERENCE_ANGLE_DEG = 110.0;
const float BACKREST_SAFE_MIN_ANGLE_DEG = 90.0;
const float BACKREST_SAFE_MAX_ANGLE_DEG = 130.0;

// 시트 상대 위치를 목표시간으로 변환
const long SEAT_MIN_TARGET_MS =
    (long)(SEAT_SAFE_MIN_MM / SEAT_SPEED_MM_S * 1000.0);
const long SEAT_MAX_TARGET_MS =
    (long)(SEAT_SAFE_MAX_MM / SEAT_SPEED_MM_S * 1000.0);

// 등받이 각도가 커질수록 랙을 당기기 위해 액추에이터가 수축한다.
const float BACKREST_DIRECTION_SIGN = -1.0;

// 등받이 각도를 110도 기준의 액추에이터 이동시간으로 변환
const float BACKREST_AT_MIN_ANGLE_DISTANCE_MM =
    BACKREST_DIRECTION_SIGN
    * PI * PINION_DIAMETER_MM
    * (BACKREST_SAFE_MIN_ANGLE_DEG - BACKREST_REFERENCE_ANGLE_DEG)
    / 360.0;

const float BACKREST_AT_MAX_ANGLE_DISTANCE_MM =
    BACKREST_DIRECTION_SIGN
    * PI * PINION_DIAMETER_MM
    * (BACKREST_SAFE_MAX_ANGLE_DEG - BACKREST_REFERENCE_ANGLE_DEG)
    / 360.0;

const float BACKREST_MIN_DISTANCE_MM =
    BACKREST_AT_MIN_ANGLE_DISTANCE_MM < BACKREST_AT_MAX_ANGLE_DISTANCE_MM
    ? BACKREST_AT_MIN_ANGLE_DISTANCE_MM
    : BACKREST_AT_MAX_ANGLE_DISTANCE_MM;

const float BACKREST_MAX_DISTANCE_MM =
    BACKREST_AT_MIN_ANGLE_DISTANCE_MM > BACKREST_AT_MAX_ANGLE_DISTANCE_MM
    ? BACKREST_AT_MIN_ANGLE_DISTANCE_MM
    : BACKREST_AT_MAX_ANGLE_DISTANCE_MM;

const long BACKREST_MIN_TARGET_MS =
    (long)(BACKREST_MIN_DISTANCE_MM / BACKREST_SPEED_MM_S * 1000.0);
const long BACKREST_MAX_TARGET_MS =
    (long)(BACKREST_MAX_DISTANCE_MM / BACKREST_SPEED_MM_S * 1000.0);

// ========================================================
// 3. 액추에이터별 독립 상태
// ========================================================

struct MotorState {
    int rpwmPin;
    int lpwmPin;

    // 물리적 기준점으로부터 현재 위치를 시간값으로 추정
    long currentTargetMs;

    // 현재 단계에서 움직여야 할 부호 있는 시간
    long movementDeltaMs;

    unsigned long startTimeMs;
    unsigned long durationMs;
    bool active;
    const char *name;
};

MotorState seatMotor = {
    SEAT_RPWM_PIN, SEAT_LPWM_PIN,
    0, 0, 0, 0, false, "SEAT"
};

MotorState backMotor = {
    BACK_RPWM_PIN, BACK_LPWM_PIN,
    0, 0, 0, 0, false, "BACKREST"
};

enum OperationPhase {
    PHASE_IDLE,
    PHASE_DIRECT_SEAT,
    PHASE_DIRECT_BACKREST,
    PHASE_RESET_BACKREST,
    PHASE_RESET_SEAT,
    PHASE_APPLY_RESET_BACKREST,
    PHASE_APPLY_RESET_SEAT,
    PHASE_APPLY_SEAT,
    PHASE_APPLY_BACKREST
};

OperationPhase operationPhase = PHASE_IDLE;
bool operationActive = false;

// 코드 실행 전에 물리적으로 시트 50 mm, 등받이 25 mm,
// 등받이 110도 상태를 맞춰 둔다. 시작 위치를 즉시 기준점으로 사용한다.
bool referenceInitialized = true;

long pendingSeatTargetMs = 0;
long pendingBackTargetMs = 0;

// 등받이 각도 조절분만 별도로 저장한다.
// backMotor.currentTargetMs는 시트 보상 이동까지 포함한 실제 액추에이터 위치이다.
long currentBackAngleTargetMs = 0;

// checkOperationComplete()보다 아래에서 구현되므로 명시적으로 선언한다.
void emergencyStop();

// ========================================================
// 4. 공통 모터 함수
// ========================================================

long clampLong(long value, long minimumValue, long maximumValue) {
    if (value < minimumValue) return minimumValue;
    if (value > maximumValue) return maximumValue;
    return value;
}

void stopMotor(MotorState &motor) {
    analogWrite(motor.rpwmPin, 0);
    analogWrite(motor.lpwmPin, 0);
    motor.active = false;
}

void driveMotor(MotorState &motor, int direction) {
    if (direction > 0) {
        // 액추에이터 확장
        analogWrite(motor.rpwmPin, MOTOR_PWM);
        analogWrite(motor.lpwmPin, 0);
    }
    else if (direction < 0) {
        // 액추에이터 수축
        analogWrite(motor.rpwmPin, 0);
        analogWrite(motor.lpwmPin, MOTOR_PWM);
    }
    else {
        stopMotor(motor);
    }
}

void startMotorMovement(MotorState &motor, long movementDeltaMs) {
    motor.movementDeltaMs = movementDeltaMs;

    if (movementDeltaMs == 0) {
        motor.durationMs = 0;
        stopMotor(motor);
        Serial.print("MOVE_SKIP,");
        Serial.println(motor.name);
        return;
    }

    motor.durationMs = (unsigned long)labs(movementDeltaMs);
    motor.startTimeMs = millis();
    motor.active = true;

    driveMotor(motor, movementDeltaMs > 0 ? 1 : -1);

    Serial.print("MOVE_BEGIN,");
    Serial.print(motor.name);
    Serial.print(",");
    Serial.print(movementDeltaMs > 0 ? "EXTEND" : "RETRACT");
    Serial.print(",");
    Serial.println(motor.durationMs);
}

void updateMotor(MotorState &motor) {
    if (!motor.active) return;

    unsigned long elapsedMs = millis() - motor.startTimeMs;

    if (elapsedMs >= motor.durationMs) {
        stopMotor(motor);
        motor.currentTargetMs += motor.movementDeltaMs;

        Serial.print("MOVE_END,");
        Serial.print(motor.name);
        Serial.print(",");
        Serial.println(motor.currentTargetMs);

        motor.movementDeltaMs = 0;
    }
}

void beginSeatMoveWithBackCompensation(long seatTargetMs) {
    // 시트가 움직인 거리만큼 등받이 액추에이터를 반대 방향으로 움직여
    // 랙기어와 현재 등받이 각도가 변하지 않게 한다.
    long seatMovementMs = seatTargetMs - seatMotor.currentTargetMs;

    startMotorMovement(seatMotor, seatMovementMs);
    startMotorMovement(backMotor, -seatMovementMs);
}

void beginBackrestAngleMove(long backAngleTargetMs) {
    // 시트 이동이 끝난 뒤 등받이 액추에이터만 움직인다.
    long backAngleMovementMs =
        backAngleTargetMs - currentBackAngleTargetMs;

    startMotorMovement(backMotor, backAngleMovementMs);
}

void finishOperation() {
    stopMotor(seatMotor);
    stopMotor(backMotor);
    operationActive = false;
    operationPhase = PHASE_IDLE;
    Serial.println("DONE");
}

void checkOperationComplete() {
    // 0 ms 단계는 모터가 active가 되지 않는다. 한 번의 loop에서 다음
    // 실동작 단계까지 연속 진행해 APPLY,0,0이나 RESET이 중간에 멈추지 않게 한다.
    int transitionGuard = 0;

    while (
        operationActive
        && !seatMotor.active
        && !backMotor.active
        && transitionGuard < 10
    ) {
        transitionGuard++;

        if (operationPhase == PHASE_DIRECT_SEAT) {
            operationPhase = PHASE_DIRECT_BACKREST;
            beginBackrestAngleMove(pendingBackTargetMs);
            continue;
        }

        if (operationPhase == PHASE_DIRECT_BACKREST) {
            currentBackAngleTargetMs = pendingBackTargetMs;
            finishOperation();
            continue;
        }

        if (operationPhase == PHASE_RESET_BACKREST) {
            currentBackAngleTargetMs = 0;
            operationPhase = PHASE_RESET_SEAT;
            beginSeatMoveWithBackCompensation(0);
            continue;
        }

        if (operationPhase == PHASE_RESET_SEAT) {
            finishOperation();
            continue;
        }

        if (operationPhase == PHASE_APPLY_RESET_BACKREST) {
            currentBackAngleTargetMs = 0;
            operationPhase = PHASE_APPLY_RESET_SEAT;
            beginSeatMoveWithBackCompensation(0);
            continue;
        }

        if (operationPhase == PHASE_APPLY_RESET_SEAT) {
            Serial.println("REFERENCE_RETURNED");
            operationPhase = PHASE_APPLY_SEAT;
            beginSeatMoveWithBackCompensation(pendingSeatTargetMs);
            continue;
        }

        if (operationPhase == PHASE_APPLY_SEAT) {
            operationPhase = PHASE_APPLY_BACKREST;
            beginBackrestAngleMove(pendingBackTargetMs);
            continue;
        }

        if (operationPhase == PHASE_APPLY_BACKREST) {
            currentBackAngleTargetMs = pendingBackTargetMs;
            finishOperation();
            continue;
        }

        Serial.println("ERROR,INVALID_PHASE");
        emergencyStop();
    }

    if (transitionGuard >= 10 && operationActive) {
        Serial.println("ERROR,PHASE_GUARD");
        emergencyStop();
    }
}

// ========================================================
// 5. 목표값 및 사용자 적용 명령
// ========================================================

void clampTargets(
    long requestedSeatTargetMs,
    long requestedBackTargetMs,
    long &seatTargetMs,
    long &backTargetMs
) {
    seatTargetMs = clampLong(
        requestedSeatTargetMs,
        SEAT_MIN_TARGET_MS,
        SEAT_MAX_TARGET_MS
    );

    backTargetMs = clampLong(
        requestedBackTargetMs,
        BACKREST_MIN_TARGET_MS,
        BACKREST_MAX_TARGET_MS
    );

    if (
        seatTargetMs != requestedSeatTargetMs
        || backTargetMs != requestedBackTargetMs
    ) {
        Serial.println("LIMIT_APPLIED");
    }
}

void startDirectMove(long requestedSeatTargetMs, long requestedBackTargetMs) {
    if (operationActive) {
        Serial.println("ERROR,BUSY");
        return;
    }

    if (!referenceInitialized) {
        Serial.println("ERROR,NOT_INITIALIZED");
        return;
    }

    clampTargets(
        requestedSeatTargetMs,
        requestedBackTargetMs,
        pendingSeatTargetMs,
        pendingBackTargetMs
    );

    operationActive = true;
    Serial.print("ACK,MOVE,");
    Serial.print(pendingSeatTargetMs);
    Serial.print(",");
    Serial.println(pendingBackTargetMs);
    operationPhase = PHASE_DIRECT_SEAT;
    beginSeatMoveWithBackCompensation(pendingSeatTargetMs);
}

void startReset() {
    if (operationActive) {
        Serial.println("ERROR,BUSY");
        return;
    }

    if (!referenceInitialized) {
        Serial.println("ERROR,NOT_INITIALIZED");
        return;
    }

    operationActive = true;
    Serial.println("ACK,RESET");
    operationPhase = PHASE_RESET_BACKREST;

    // 1단계: 현재 각도를 110도로 복귀
    beginBackrestAngleMove(0);
}

void startApplySequence(long requestedSeatTargetMs, long requestedBackTargetMs) {
    if (operationActive) {
        Serial.println("ERROR,BUSY");
        return;
    }

    clampTargets(
        requestedSeatTargetMs,
        requestedBackTargetMs,
        pendingSeatTargetMs,
        pendingBackTargetMs
    );

    operationActive = true;

    Serial.print("ACK,APPLY,");
    Serial.print(pendingSeatTargetMs);
    Serial.print(",");
    Serial.println(pendingBackTargetMs);

    Serial.println("RETURNING_REFERENCE");

    // 사용자 변경 시 1단계: 등받이 각도를 먼저 110도로 복귀
    operationPhase = PHASE_APPLY_RESET_BACKREST;
    beginBackrestAngleMove(0);
}

// ========================================================
// 6. 긴급 정지
// ========================================================

long updatePartialPositionAndStop(MotorState &motor) {
    if (!motor.active) return 0;

    unsigned long elapsedMs = millis() - motor.startTimeMs;
    if (elapsedMs > motor.durationMs) elapsedMs = motor.durationMs;

    long movedDeltaMs;

    if (motor.movementDeltaMs > 0) {
        movedDeltaMs = (long)elapsedMs;
    }
    else {
        movedDeltaMs = -(long)elapsedMs;
    }

    motor.currentTargetMs += movedDeltaMs;
    motor.movementDeltaMs = 0;
    stopMotor(motor);

    return movedDeltaMs;
}

void emergencyStop() {
    OperationPhase stoppedPhase = operationPhase;
    updatePartialPositionAndStop(seatMotor);
    long backMovedDeltaMs = updatePartialPositionAndStop(backMotor);

    // 등받이만 움직이는 단계에서 멈춘 경우 현재 각도 추정값도 갱신한다.
    if (
        stoppedPhase == PHASE_DIRECT_BACKREST
        || stoppedPhase == PHASE_RESET_BACKREST
        || stoppedPhase == PHASE_APPLY_RESET_BACKREST
        || stoppedPhase == PHASE_APPLY_BACKREST
    ) {
        currentBackAngleTargetMs += backMovedDeltaMs;
    }

    operationActive = false;
    operationPhase = PHASE_IDLE;

    Serial.println("STOPPED");
}

// ========================================================
// 7. 시리얼 명령 해석
// ========================================================

bool parseTwoTargets(
    const String &command,
    long &seatTargetMs,
    long &backTargetMs
) {
    int firstComma = command.indexOf(',');
    int secondComma = command.indexOf(',', firstComma + 1);

    if (firstComma < 0 || secondComma < 0) return false;

    seatTargetMs = command.substring(firstComma + 1, secondComma).toInt();
    backTargetMs = command.substring(secondComma + 1).toInt();
    return true;
}

void handleCommand(String command) {
    command.trim();

    if (command == "PING") {
        Serial.print("PONG,");
        Serial.println(FIRMWARE_VERSION);
        return;
    }

    if (command == "RESET") {
        startReset();
        return;
    }

    if (command == "SET_REFERENCE") {
        if (operationActive) {
            Serial.println("ERROR,BUSY");
            return;
        }

        stopMotor(seatMotor);
        stopMotor(backMotor);
        seatMotor.currentTargetMs = 0;
        backMotor.currentTargetMs = 0;
        currentBackAngleTargetMs = 0;
        referenceInitialized = true;
        Serial.println("DONE");
        return;
    }

    if (command == "STOP") {
        emergencyStop();
        return;
    }

    if (command.startsWith("APPLY,")) {
        long seatTargetMs;
        long backTargetMs;

        if (!parseTwoTargets(command, seatTargetMs, backTargetMs)) {
            Serial.println("ERROR,BAD_COMMAND");
            return;
        }

        startApplySequence(seatTargetMs, backTargetMs);
        return;
    }

    if (command.startsWith("MOVE,")) {
        long seatTargetMs;
        long backTargetMs;

        if (!parseTwoTargets(command, seatTargetMs, backTargetMs)) {
            Serial.println("ERROR,BAD_COMMAND");
            return;
        }

        startDirectMove(seatTargetMs, backTargetMs);
        return;
    }

    Serial.println("ERROR,UNKNOWN_COMMAND");
}

// ========================================================
// 8. 초기 설정
// ========================================================

void setup() {
    Serial.begin(115200);
    Serial.setTimeout(50);

    pinMode(SEAT_RPWM_PIN, OUTPUT);
    pinMode(SEAT_LPWM_PIN, OUTPUT);
    pinMode(SEAT_REN_PIN, OUTPUT);
    pinMode(SEAT_LEN_PIN, OUTPUT);

    pinMode(BACK_RPWM_PIN, OUTPUT);
    pinMode(BACK_LPWM_PIN, OUTPUT);
    pinMode(BACK_REN_PIN, OUTPUT);
    pinMode(BACK_LEN_PIN, OUTPUT);

    digitalWrite(SEAT_REN_PIN, HIGH);
    digitalWrite(SEAT_LEN_PIN, HIGH);
    digitalWrite(BACK_REN_PIN, HIGH);
    digitalWrite(BACK_LEN_PIN, HIGH);

    stopMotor(seatMotor);
    stopMotor(backMotor);

    Serial.println("READY");
    Serial.print("FIRMWARE,");
    Serial.println(FIRMWARE_VERSION);
}

// ========================================================
// 9. 반복 실행
// ========================================================

void loop() {
    if (Serial.available() > 0) {
        String command = Serial.readStringUntil('\n');
        handleCommand(command);
    }

    // 두 액추에이터를 매 반복마다 각각 독립적으로 갱신한다.
    updateMotor(seatMotor);
    updateMotor(backMotor);

    // 둘 다 끝났을 때 다음 단계 또는 DONE 처리
    checkOperationComplete();
}
