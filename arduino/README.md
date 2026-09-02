# Arduino Firmware

Seat-ID 시스템의 센서 데이터 수집 및 시트 제어를 담당하는 Arduino 펌웨어 코드입니다.

본 디렉토리에는 압력 센서, 초음파 센서, 버튼 및 Linear Actuator 제어에 사용되는 Arduino 코드를 포함하고 있습니다.

---

## 📁 파일 구성

| 구분 | 파일 | 보드 | 주요 기능 |
|---|---|---|---|
| 압력센서 | [`arduino_mega.ino`](./arduino_mega.ino) | Arduino Mega | 16-ELEMENT FSR-406 압력 센서 데이터 수집 |
| 등/상체 센서 | [`arduino_back.ino`](./arduino_back.ino) | Arduino Uno | 5채널 HC-SR04 기반 등/상체 거리 측정 |
| 목 센서 | [`arduino_neck_2ch.ino`](./arduino_neck_2ch.ino) | Arduino Uno | 2채널 HC-SR04 기반 목 자세 측정 |
| 시트 제어 | [`smart_chair_arduino_3.ino`](./smart_chair_arduino_3.ino) | Arduino Uno | 시트 및 등받이 Linear Actuator 제어 |
| UI | [`butten_code.ino`](./butten_code.ino) | Arduino Leonardo | START / PARK / END 버튼 및 LED 제어 |
---

## 🔧 Arduino 구성

- **Arduino Mega × 1** : 압력 센서 데이터 수집
- **Arduino Uno × 3** : 등/상체 센서, 목 센서, 시트 제어
- **Arduino Leonardo × 1** : 버튼 및 LED 제어

---
## 🔄 시스템 구성

```text
[Arduino Mega]
     │
     └─ 16-Element FSR-406 -> Pressure Data

[Arduino Uno]
     ├─ HC-SR04 × 5 → Back / Body
     ├─ HC-SR04 × 2 → Neck
     └─ Linear Actuator → Seat / Backrest

[Arduino Leonardo]
     └─ START / PARK / END

