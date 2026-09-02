/*
  목 자세 전용 HC-SR04 2채널 거리 측정기

  센서와 배선
    HEAD  후두부 센서  TRIG D2, ECHO D3
    C7    C7 센서      TRIG D4, ECHO D5

  측정 속도
    서로 다른 센서는 55 ms 간격으로 발사한다
    같은 센서는 약 110 ms마다 다시 발사되므로 약 9 Hz로 한 쌍을 갱신한다
    35 ms보다 반사파 간섭 가능성을 낮추되, 화면 반응은 실시간으로 느껴질 정도를 유지한다

  Python 호환 JSON 출력 예시
    {"t_ms":1234,"head_mm":205.4,"c7_mm":187.2}

  오프셋 보정과 튀는 값 필터링은 Python 프로그램에서 수행한다
  Arduino는 범위를 벗어나거나 응답이 없는 값만 null로 보내고 원본 거리를 유지한다
*/

#include <Arduino.h>
#include <math.h>

const uint8_t SENSOR_COUNT = 2;
const uint8_t HEAD_INDEX = 0;
const uint8_t C7_INDEX = 1;

const uint8_t TRIG_PINS[SENSOR_COUNT] = {2, 4};
const uint8_t ECHO_PINS[SENSOR_COUNT] = {3, 5};

const unsigned long SERIAL_BAUDRATE = 115200;

// 500 mm의 초음파 왕복 시간은 약 2915 us다
// 여유를 포함해 6000 us까지만 기다려 무응답 때의 지연을 줄인다
const unsigned long ECHO_TIMEOUT_US = 6000UL;

// 같은 센서의 재발사 간격은 약 110 ms가 되며 실시간 한 쌍은 약 9 Hz로 출력된다.
// 헤드레스트 주변 반사파가 섞이는 것을 줄이기 위해 35 ms보다 여유를 둔다.
const unsigned long SENSOR_START_GAP_MS = 55UL;

const float MIN_DISTANCE_MM = 20.0f;
const float MAX_DISTANCE_MM = 500.0f;

float distancesMm[SENSOR_COUNT] = {NAN, NAN};

float measureDistanceMm(uint8_t sensorIndex) {
  const uint8_t trigPin = TRIG_PINS[sensorIndex];
  const uint8_t echoPin = ECHO_PINS[sensorIndex];

  digitalWrite(trigPin, LOW);
  delayMicroseconds(3);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  const unsigned long durationUs = pulseIn(echoPin, HIGH, ECHO_TIMEOUT_US);
  if (durationUs == 0UL) {
    return NAN;
  }

  // 음속 0.343 mm/us, 왕복 시간이므로 2로 나눈다
  const float distanceMm = durationUs * 0.343f / 2.0f;
  if (distanceMm < MIN_DISTANCE_MM || distanceMm > MAX_DISTANCE_MM) {
    return NAN;
  }
  return distanceMm;
}

void waitForNextPing(unsigned long pingStartedAtMs) {
  while ((unsigned long)(millis() - pingStartedAtMs) < SENSOR_START_GAP_MS) {
    delay(1);
  }
}

void printDistanceOrNull(float value) {
  if (isnan(value)) {
    Serial.print(F("null"));
  } else {
    Serial.print(value, 1);
  }
}

void printJsonFrame() {
  Serial.print(F("{\"t_ms\":"));
  Serial.print(millis());
  Serial.print(F(",\"head_mm\":"));
  printDistanceOrNull(distancesMm[HEAD_INDEX]);
  Serial.print(F(",\"c7_mm\":"));
  printDistanceOrNull(distancesMm[C7_INDEX]);
  Serial.println(F("}"));
}

void setup() {
  Serial.begin(SERIAL_BAUDRATE);

  for (uint8_t i = 0; i < SENSOR_COUNT; ++i) {
    pinMode(TRIG_PINS[i], OUTPUT);
    pinMode(ECHO_PINS[i], INPUT);
    digitalWrite(TRIG_PINS[i], LOW);
  }

  delay(500);
}

void loop() {
  unsigned long pingStartedAtMs = millis();
  distancesMm[HEAD_INDEX] = measureDistanceMm(HEAD_INDEX);
  waitForNextPing(pingStartedAtMs);

  pingStartedAtMs = millis();
  distancesMm[C7_INDEX] = measureDistanceMm(C7_INDEX);
  waitForNextPing(pingStartedAtMs);

  printJsonFrame();
}
