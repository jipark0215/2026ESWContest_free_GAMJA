#include <Keyboard.h>

/*
  Seat ID 버튼/LED 제어 코드
  보드: Arduino Leonardo

  버튼 입력:
  - START 버튼: D2
  - PARK  버튼: D3
  - END   버튼: D4

  LED 출력:
  - START LED: D8
  - PARK  LED: D9
  - END   LED: D10

  실제 배선이 다르면 아래 START_LED_PIN, PARK_LED_PIN, END_LED_PIN 숫자만 바꾸면 됩니다.
*/

// =====================
// 버튼 입력 핀
// =====================
const int START_BUTTON_PIN = 2;
const int PARK_BUTTON_PIN  = 3;
const int END_BUTTON_PIN   = 4;

// =====================
// LED 출력 핀
// =====================
// 지금 증상은 기존 코드가 LED 핀을 1개만 제어해서 생긴 문제입니다.
// 각 버튼 LED를 각각 다른 핀으로 분리해서 제어합니다.
const int START_LED_PIN = 8;
const int PARK_LED_PIN  = 9;
const int END_LED_PIN   = 10;

// LED가 HIGH일 때 켜지는 배선이면 true.
// 만약 업로드 후 LED 동작이 전부 반대로 보이면 false로 바꾸세요.
const bool LED_ACTIVE_HIGH = true;

// 디바운스 시간
const unsigned long DEBOUNCE_MS = 120;

// 주행 종료 LED 동작
const unsigned long END_LED_HOLD_MS = 10000;  // 10초 켜짐
const unsigned long END_LED_FADE_MS = 1000;   // 1초 동안 점멸하며 종료

// 버튼 이전 상태
bool prevStartButton = HIGH;
bool prevParkButton  = HIGH;
bool prevEndButton   = HIGH;

unsigned long lastStartMs = 0;
unsigned long lastParkMs  = 0;
unsigned long lastEndMs   = 0;

// END LED 타이머 상태
bool endSequenceRunning = false;
unsigned long endSequenceStartMs = 0;

void setup() {
  pinMode(START_BUTTON_PIN, INPUT_PULLUP);
  pinMode(PARK_BUTTON_PIN, INPUT_PULLUP);
  pinMode(END_BUTTON_PIN, INPUT_PULLUP);

  pinMode(START_LED_PIN, OUTPUT);
  pinMode(PARK_LED_PIN, OUTPUT);
  pinMode(END_LED_PIN, OUTPUT);

  allLedsOff();

  // 업로드 직후 의도치 않은 키 입력 방지
  delay(2000);
  Keyboard.begin();
}

void loop() {
  checkStartButton();
  checkParkButton();
  checkEndButton();

  updateEndLedSequence();
}

// =====================
// LED 유틸
// =====================
void writeLed(int pin, bool on) {
  if (LED_ACTIVE_HIGH) {
    digitalWrite(pin, on ? HIGH : LOW);
  } else {
    digitalWrite(pin, on ? LOW : HIGH);
  }
}

void allLedsOff() {
  writeLed(START_LED_PIN, false);
  writeLed(PARK_LED_PIN, false);
  writeLed(END_LED_PIN, false);
}

void setDrivingLed() {
  endSequenceRunning = false;
  writeLed(START_LED_PIN, true);
  writeLed(PARK_LED_PIN, false);
  writeLed(END_LED_PIN, false);
}

void setParkLed() {
  endSequenceRunning = false;
  writeLed(START_LED_PIN, false);
  writeLed(PARK_LED_PIN, true);
  writeLed(END_LED_PIN, false);
}

void startEndLedSequence() {
  endSequenceRunning = true;
  endSequenceStartMs = millis();

  writeLed(START_LED_PIN, false);
  writeLed(PARK_LED_PIN, false);
  writeLed(END_LED_PIN, true);
}

// =====================
// 버튼 처리
// =====================
bool isPressedEdge(bool previousState, bool currentState) {
  // INPUT_PULLUP이라서 안 눌림=HIGH, 눌림=LOW
  return previousState == HIGH && currentState == LOW;
}

void checkStartButton() {
  bool current = digitalRead(START_BUTTON_PIN);
  unsigned long now = millis();

  if (isPressedEdge(prevStartButton, current) && (now - lastStartMs >= DEBOUNCE_MS)) {
    Keyboard.write('S');

    // 처음 시작 또는 주차 대기 화면에서 다시 시작할 때 START LED ON
    setDrivingLed();

    lastStartMs = now;
  }

  prevStartButton = current;
}

void checkParkButton() {
  bool current = digitalRead(PARK_BUTTON_PIN);
  unsigned long now = millis();

  if (isPressedEdge(prevParkButton, current) && (now - lastParkMs >= DEBOUNCE_MS)) {
    Keyboard.write('P');

    // 대시보드에서 주차 버튼을 누르면 PARK LED ON, START LED OFF
    setParkLed();

    lastParkMs = now;
  }

  prevParkButton = current;
}

void checkEndButton() {
  bool current = digitalRead(END_BUTTON_PIN);
  unsigned long now = millis();

  if (isPressedEdge(prevEndButton, current) && (now - lastEndMs >= DEBOUNCE_MS)) {
    Keyboard.write('E');

    // 주행 종료 버튼을 누르면 END LED ON
    startEndLedSequence();

    lastEndMs = now;
  }

  prevEndButton = current;
}

// =====================
// END LED 10초 ON + 1초 점멸 OFF
// =====================
void updateEndLedSequence() {
  if (!endSequenceRunning) {
    return;
  }

  unsigned long elapsed = millis() - endSequenceStartMs;

  if (elapsed < END_LED_HOLD_MS) {
    // 10초 동안 계속 켜짐
    writeLed(END_LED_PIN, true);
    return;
  }

  if (elapsed < END_LED_HOLD_MS + END_LED_FADE_MS) {
    // 마지막 1초 동안 점점 느리게 꺼지는 느낌의 점멸
    unsigned long fadeElapsed = elapsed - END_LED_HOLD_MS;

    if (fadeElapsed < 250) {
      writeLed(END_LED_PIN, (fadeElapsed / 80) % 2 == 0);
    } else if (fadeElapsed < 600) {
      writeLed(END_LED_PIN, (fadeElapsed / 140) % 2 == 0);
    } else {
      writeLed(END_LED_PIN, (fadeElapsed / 220) % 2 == 0);
    }
    return;
  }

  // 종료 시 전체 LED OFF
  allLedsOff();
  endSequenceRunning = false;
}
