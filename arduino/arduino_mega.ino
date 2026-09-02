const int SENSOR_COUNT = 16;
const int sensorPins[SENSOR_COUNT] = {
  A0, A1, A2, A3, A4, A5, A6, A7, A8, A9, A10, A11, A12, A13, A14, A15
};

const unsigned long SAMPLE_INTERVAL_MS = 50;
unsigned long previousMillis = 0;

void setup() {
  Serial.begin(115200);
}

void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - previousMillis >= SAMPLE_INTERVAL_MS) {
    previousMillis = currentMillis;

    for (int i = 0; i < SENSOR_COUNT; i++) {
      int sensorValue = analogRead(sensorPins[i]);
      Serial.print(sensorValue);

      if (i < SENSOR_COUNT - 1) {
        Serial.print(",");
      }
    }

    Serial.println();
  }
}
