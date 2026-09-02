/*
  세로 일렬 HC-SR04 5채널 거리 측정기

  센서 설치 순서 (좌판에서 센서 중심 높이)
    S1:  70 mm  최하단
    S2: 130 mm
    S3: 190 mm
    S4: 250 mm
    S5: 310 mm  최상단

  배선 (Arduino Uno/Nano/Mega 기준)
    S1 TRIG D2,  ECHO D3
    S2 TRIG D4,  ECHO D5
    S3 TRIG D6,  ECHO D7
    S4 TRIG D8,  ECHO D9
    S5 TRIG D10, ECHO D11

  다섯 센서를 동시에 발사하지 않는다
  물리적으로 이웃하지 않은 S1 -> S3 -> S5 -> S2 -> S4 순서로
  한 센서씩 측정하고 각 발사 시작 사이를 65 ms 이상 띄운다

  시리얼 출력 예시
    {"t_ms":1234,"s1":95.2,"s2":111.8,"s3":126.4,"s4":110.7,"s5":91.9}

  측정 실패 또는 설정 범위 밖의 값은 null로 출력한다
*/

#include <Arduino.h>
#include <math.h>

const uint8_t SENSOR_COUNT = 5;

// S1(최하단)부터 S5(최상단)까지의 핀
const uint8_t TRIG_PINS[SENSOR_COUNT] = {2, 4, 6, 8, 10};
const uint8_t ECHO_PINS[SENSOR_COUNT] = {3, 5, 7, 9, 11};

// 인접 센서를 연속해서 쏘지 않는 순서: S1, S3, S5, S2, S4
const uint8_t MEASURE_ORDER[SENSOR_COUNT] = {0, 2, 4, 1, 3};

const unsigned long SERIAL_BAUDRATE = 115200;
const unsigned long SENSOR_START_GAP_MS = 65;
const unsigned long ECHO_TIMEOUT_US = 6000;

// 실제 의자에 맞게 바꿀 수 있는 유효 거리 범위
const float MIN_DISTANCE_MM = 20.0;
const float MAX_DISTANCE_MM = 500.0;

float distancesMm[SENSOR_COUNT];

float measureDistanceMm(uint8_t sensorIndex) {
  const uint8_t trigPin = TRIG_PINS[sensorIndex];
  const uint8_t echoPin = ECHO_PINS[sensorIndex];

  digitalWrite(trigPin, LOW);
  delayMicroseconds(3);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);

  const unsigned long durationUs = pulseIn(echoPin, HIGH, ECHO_TIMEOUT_US);
  if (durationUs == 0) {
    return NAN;
  }

  // 왕복 시간이므로 2로 나눈다
  const float distanceMm = durationUs * 0.343f / 2.0f;
  if (distanceMm < MIN_DISTANCE_MM || distanceMm > MAX_DISTANCE_MM) {
    return NAN;
  }

  return distanceMm;
}

void printJsonFrame() {
  Serial.print(F("{\"t_ms\":"));
  Serial.print(millis());

  for (uint8_t i = 0; i < SENSOR_COUNT; ++i) {
    Serial.print(F(",\"s"));
    Serial.print(i + 1);
    Serial.print(F("\":"));

    if (isnan(distancesMm[i])) {
      Serial.print(F("null"));
    } else {
      Serial.print(distancesMm[i], 1);
    }
  }

  Serial.println(F("}"));
}

void setup() {
  Serial.begin(SERIAL_BAUDRATE);

  for (uint8_t i = 0; i < SENSOR_COUNT; ++i) {
    pinMode(TRIG_PINS[i], OUTPUT);
    pinMode(ECHO_PINS[i], INPUT);
    digitalWrite(TRIG_PINS[i], LOW);
    distancesMm[i] = NAN;
  }

  delay(500);
}

void loop() {
  for (uint8_t orderIndex = 0; orderIndex < SENSOR_COUNT; ++orderIndex) {
    const uint8_t sensorIndex = MEASURE_ORDER[orderIndex];
    const unsigned long startedAtMs = millis();

    distancesMm[sensorIndex] = measureDistanceMm(sensorIndex);

    // pulseIn() 소요시간을 포함해 발사 시작 간격이 최소 65 ms가 되게 한다
    while ((unsigned long)(millis() - startedAtMs) < SENSOR_START_GAP_MS) {
      delay(1);
    }
  }

  printJsonFrame();
}
