## **Seat-ID — A Smarter Seat That Understands You.**

### 압력센서 기반 사용자 식별·자세 분석 스마트 시트 시스템

**FSR Pressure Sensing · SFS Sensor Optimization · SVM · COP Analysis · Ultrasonic Posture Estimation · Raspberry Pi 5 · Arduino · Linear Actuator**

`Python` `scikit-learn` `SVM` `Arduino` `Raspberry Pi` `FSR-406` `HC-SR04P`

**제24회 임베디드SW경진대회 자유공모 부문**

[시연 동영상] · [빠른 실행] · [시스템 구조] · [AI 모델] · [하드웨어]

---

## 1. 개발 배경과 목표

### 개발 배경

장시간 운전은 지속적인 착석과 부적절한 자세로 인해 운전자의 근골격계 부담을 증가시킬 수 있다.

기존 운전자 관리 시스템에서는 카메라 기반 영상 분석이나 주행 시간에 따른 일률적인 휴식 알림 등이 활용되고 있지만, 이러한 방식은 개인별 착석 특성과 실제 자세 변화를 지속적으로 반영하기 어렵다는 한계가 있다.

Seat-ID는 이러한 문제를 해결하기 위해 **카메라 대신 압력센서와 초음파센서를 활용하여 운전자의 착석 상태와 자세 변화를 실시간으로 분석**하고, 사용자 식별부터 개인별 시트 설정 복원, 자세 판단 및 상태 기반 피드백까지 하나의 시스템으로 통합하였다.

### 구현 목표

1. **사용자 식별 및 개인별 시트 자동 조절**
   - FSR 압력 데이터를 이용한 사용자 식별
   - 사용자별 저장된 시트 위치 및 등받이 각도 적용

2. **실시간 체압 데이터 수집 및 분석**
   - 시트에 배치된 FSR 센서를 이용한 착석 압력 측정
   - 실시간 압력 분포 및 자세 변화 분석

3. **자세 패턴 분석 및 피드백**
   - SVM 기반 5종 자세 분류
   - COP 기반 좌우 하중 불균형 분석
   - 초음파센서를 이용한 등·목 자세 보조 분석
   - 이상 자세가 일정 시간 이상 지속될 경우 사용자에게 경고

---

## 2. 핵심 차별점

Seat-ID는 단순한 압력센서 측정 시스템이 아니라 **센서 최적화 → AI 기반 상태 판단 → 사용자 맞춤 제어 → 실시간 피드백**을 하나의 시스템으로 연결하였다.

### 핵심 기술

- **144 → 16 Sensor Optimization**
  - 12×12 배열의 144개 FSR 센서를 후보군으로 설정
  - SFS를 이용해 자세 분류에 유효한 16개 센서 선정

- **SFS + SVM 기반 경량 AI**
  - 선정된 16개 센서 데이터를 SVM의 입력으로 사용
  - 임베디드 환경에서 실시간 자세 분류

- **Camera-less User Identification**
  - 카메라 대신 사용자의 압력 분포를 이용한 사용자 식별

- **COP-based Load Analysis**
  - 압력 분포의 중심을 이용한 좌우 하중 분석

- **Ultrasonic Posture Estimation**
  - 등 곡률 및 목 전방 이동을 초음파센서로 분석

- **Personalized Seat Control**
  - 사용자별 시트 위치 및 등받이 각도를 저장
  - 저장된 설정을 액추에이터 구동시간으로 변환하여 실제 시트 모형에 적용

- **End-to-End Embedded Integration**
  - 센서 데이터 수집부터 AI 추론, 상태 판단, 액추에이터 제어까지 통합

---

## 3. System Architecture

Seat-ID의 전체 시스템은 다음과 같은 구조로 동작한다.

```text
                    ┌─────────────────────┐
                    │    FSR-406 Array    │
                    │  Pressure Sensing   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Arduino Mega     │
                    │ Sensor Data Acquire │
                    └──────────┬──────────┘
                               │
                         Serial Data
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Raspberry Pi 5   │
                    │ Data Preprocessing  │
                    └──────────┬──────────┘
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
       ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
       │ User SVM    │  │ Posture SVM │  │ Ultrasonic  │
       │ Recognition │  │ 5-Class     │  │ Analysis    │
       └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                    ┌─────────────────────┐
                    │  State / Posture    │
                    │      Analysis       │
                    └──────────┬──────────┘
                               │
                  ┌────────────┴────────────┐
                  │                         │
                  ▼                         ▼
        ┌─────────────────┐       ┌─────────────────┐
        │ User Seat       │       │ Warning /       │
        │ Profile         │       │ Feedback / Log  │
        └────────┬────────┘       └─────────────────┘
                 │
                 ▼
        ┌─────────────────┐
        │ Arduino UNO     │
        │ Actuator Control│
        └────────┬────────┘
                 │
                 ▼
        ┌─────────────────┐
        │ Linear Actuator │
        │ Seat Adjustment │
        └─────────────────┘
```

---

## 4. 전체 동작 흐름

Seat-ID는 사용자의 착석부터 주행 종료까지 다음과 같은 흐름으로 동작한다.

```text
IDLE
 ↓
사용자 입력 / 착석
 ↓
FSR 센서 측정
 ↓
사용자 식별
 ↓
 ┌──────────────────────┐
 │ 기존 사용자           │
 │ → 저장된 프로필 조회  │
 │ → 시트 설정 적용      │
 └──────────────────────┘
          │
          │ 신규 사용자
          ▼
    사용자 등록
    압력 데이터 수집
    사용자 SVM 학습
          │
          ▼
       DRIVE 상태
          │
          ├── FSR 압력 분석
          ├── SVM 자세 분류
          ├── 좌우 하중 분석
          ├── 등 초음파 분석
          └── 목 초음파 분석
          │
          ▼
      자세 상태 판단
          │
      이상 자세 지속?
       ↙          ↘
     NO            YES
      │             │
      │          경고 출력
      │             │
      └──────┬──────┘
             ▼
        운전 데이터 기록
             │
             ▼
        주행 종료 / REPORT
```

### 동작 단계

| 단계 | 동작 |
|---|---|
| **① IDLE** | 시스템 대기 및 사용자 입력을 준비한다. |
| **② 사용자 식별** | FSR 센서의 체압 데이터를 기반으로 등록 사용자를 식별한다. |
| **③ 사용자 설정 적용** | 식별된 사용자의 시트 위치와 등받이 각도를 불러와 적용한다. |
| **④ 실시간 분석** | FSR 및 초음파센서를 이용하여 자세와 좌우 하중 상태를 실시간으로 분석한다. |
| **⑤ 이상 상태 판단** | 이상 자세 또는 하중 불균형이 일정 시간 지속되는지 판단하고 필요한 경우 경고를 제공한다. |
| **⑥ 주행 기록** | 주행 중 발생한 자세 상태, 점수 및 경고 정보를 기록한다. |
| **⑦ REPORT** | 주행 종료 후 사용자별 주행 결과를 확인할 수 있도록 리포트를 생성한다. |

---

## 5. Hardware

### Hardware 구성

| 구성 요소 | 역할 |
|---|---|
| **FSR-406** | 착석 압력 및 체압 분포 측정 |
| **Arduino Mega** | FSR 센서 데이터 수집 및 정리 |
| **Raspberry Pi 5** | 데이터 전처리 및 실시간 AI 추론 |
| **Arduino UNO** | 초음파센서 및 액추에이터 제어 |
| **Ultrasonic Sensor** | 등·목 자세 측정을 위한 거리 데이터 수집 |
| **Touch Screen** | 사용자 입력 및 실시간 분석 결과 표시 |
| **Linear Actuator** | 시트 위치 및 등받이 각도 조절 |
| **Motor Driver** | 액추에이터 모터 구동 및 전원 제어 |
| **Rack & Pinion** | 등받이 회전 메커니즘 구현 |
| **3D Printed Seat** | 실제 차량 시트 구조를 모사한 프로토타입 제작 |

### 전체 Hardware 구조

```text
                    ┌─────────────────────┐
                    │      FSR-406        │
                    │  Pressure Sensors   │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Arduino Mega     │
                    │  Sensor Acquisition │
                    └──────────┬──────────┘
                               │
                         Serial Communication
                               │
                               ▼
                    ┌─────────────────────┐
                    │    Raspberry Pi 5   │
                    │ Real-Time Processing│
                    └──────────┬──────────┘
                               │
                ┌──────────────┼──────────────┐
                │              │              │
                ▼              ▼              ▼
          User SVM       Posture SVM    Ultrasonic
          Recognition    Classification   Analysis
                │              │              │
                └──────────────┼──────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   State Analysis    │
                    │  Warning / Feedback  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │   Arduino UNO       │
                    │ Actuator Controller  │
                    └──────────┬──────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Linear Actuators   │
                    │ Seat / Backrest     │
                    └─────────────────────┘
```

### FSR Pressure Sensing

Seat-ID는 시트에 배치된 FSR(Force Sensitive Resistor) 센서를 이용하여 사용자의 착석 압력을 측정한다.

초기에는 **12 × 12 배열의 총 144개 센서**를 후보군으로 구성하고, 이후 SFS(Sequential Forward Selection)를 적용하여 자세 분류에 유효한 센서를 선정하였다.

```text
12 × 12 FSR Array
       │
       │ 144 Candidate Sensors
       ▼
Sequential Forward Selection
       │
       ▼
16 Selected Sensors
       │
       ▼
Real-Time Pressure Analysis
```

최종 선정된 16개 센서는 Raspberry Pi 5에서 수행되는 사용자 식별 및 자세 분류의 입력으로 사용된다.

### Sensor Data Acquisition

FSR 센서 데이터는 Arduino Mega에서 수집하고 Raspberry Pi 5로 전달한다.

```text
FSR Sensors
    ↓
Arduino Mega
    ↓
ADC Data Acquisition
    ↓
Serial Communication
    ↓
Raspberry Pi 5
```

Raspberry Pi 5에서는 전달받은 압력 데이터를 기반으로 baseline 보정, 데이터 전처리 및 AI 추론을 수행한다.

### Ultrasonic Sensor

FSR 센서만으로 판단하기 어려운 등과 목의 자세 변화를 보완하기 위해 초음파센서를 함께 사용한다.

#### 등 자세 분석

등받이에 배치된 초음파센서를 이용하여 등 표면과 센서 사이의 거리를 측정하고, 측정된 거리 데이터를 기반으로 등 곡률의 변화를 분석한다.

```text
Ultrasonic Sensor
       ↓
Back Surface Distance
       ↓
Back Curve Estimation
       ↓
Posture Analysis
```

#### 목 자세 분석

헤드레스트에 배치된 초음파센서를 이용하여 머리와 센서 사이의 거리 변화를 측정하고, 기준 상태와 비교하여 목의 전방 이동을 분석한다.

```text
Ultrasonic Sensor
       ↓
Head Distance
       ↓
Baseline Comparison
       ↓
Forward Head Movement
       ↓
Posture Warning
```

### Seat Actuator

개인별 시트 설정을 실제 프로토타입에 적용하기 위해 Linear Actuator를 사용한다.

시트의 전후 위치와 등받이 각도를 각각 액추에이터의 구동시간으로 변환하여 제어한다.

```text
User Profile
     ↓
Seat Position / Backrest Angle
     ↓
Actuator Operating Time
     ↓
Arduino UNO
     ↓
Motor Driver
     ↓
Linear Actuator
     ↓
Seat Adjustment
```

시트 이동 시에는 두 액추에이터를 동일 시간 동안 반대 방향으로 구동하여 등받이 각도를 유지하도록 구성하였다.

### Backrest Mechanism

등받이 각도 조절에는 **Rack & Pinion 구조**를 적용하였다.

```text
Linear Actuator
       ↓
Rack
       ↓
Pinion Gear
       ↓
Backrest Rotation
```

액추에이터의 직선 운동을 랙과 피니언을 통해 회전 운동으로 변환하여 등받이의 각도를 조절한다.

### Prototype

소프트웨어에서 계산된 결과를 실제 하드웨어 동작으로 연결하기 위해 3D 프린팅 기반의 시트 구조 모형을 제작하였다.

센서 데이터 수집부터 사용자 식별, 자세 분석, 사용자별 시트 설정 적용 및 액추에이터 제어까지 하나의 프로토타입에서 통합적으로 구현하였다.

---

## 6. AI & Data Processing

Seat-ID는 FSR 센서에서 수집한 체압 데이터를 기반으로 **사용자 식별과 자세 분류를 수행하는 SVM 기반 AI 시스템**을 구현하였다.

특히 144개의 센서를 그대로 사용하는 대신 **SFS(Sequential Forward Selection)**를 적용하여 입력 센서를 16개로 최적화하고, 임베디드 환경에서 실시간 추론이 가능하도록 구성하였다.

### AI Processing Pipeline

```text
FSR Pressure Data
        ↓
Baseline Correction
        ↓
Noise Reduction / Averaging
        ↓
16 Selected Sensors
        ↓
StandardScaler
        ↓
RBF Kernel SVM
        ↓
Prediction
        ↓
User / Posture State
```

### 6.1 Sensor Optimization — SFS

초기 센서 구성은 **12 × 12 배열, 총 144개의 FSR 센서**를 후보군으로 사용하였다.

모든 센서를 AI 모델의 입력으로 사용하는 대신, 자세 분류에 기여도가 높은 센서를 순차적으로 선택하는 **SFS(Sequential Forward Selection)**를 적용하였다.

```text
144 Candidate Sensors
        │
        ▼
Sequential Forward Selection
        │
        ├── 센서 조합 평가
        ├── 분류 성능 비교
        └── 유효 센서 순차 선택
        │
        ▼
16 Selected Sensors
```

이를 통해 센서 수를 **144개 → 16개**로 줄이면서도 체압 분포의 주요 특징을 유지하도록 센서 구성을 최적화하였다.

### 6.2 Pressure Data Preprocessing

실시간으로 입력되는 FSR 데이터는 센서별 기준값과 측정 노이즈의 영향을 받을 수 있기 때문에 다음과 같은 전처리 과정을 거친다.

```text
Raw FSR ADC Data
        ↓
Baseline Correction
        ↓
Averaging / Noise Reduction
        ↓
Selected 16 Channels
        ↓
StandardScaler
        ↓
SVM Input
```

Baseline 보정을 통해 센서별 기준값의 차이를 제거하고, 여러 번 측정된 값을 평균화하여 순간적인 측정 노이즈의 영향을 줄였다.

이후 최종 선정된 16개 센서의 데이터를 StandardScaler를 통해 정규화한 뒤 학습된 SVM 모델에 입력한다.

### 6.3 User Identification

사용자 등록 과정에서는 사용자의 압력 데이터를 수집하여 사용자별 압력 프로파일을 구성한다.

```text
User Registration
        ↓
Pressure Data Collection
        ↓
Representative Pressure Data
        ↓
User Model Training
        ↓
RBF SVM
        ↓
User Model
```

사용자 모델은 **StandardScaler + RBF Kernel SVM** 구조로 구성하며, 학습이 완료된 모델과 스케일러를 저장하여 이후 실시간 사용자 식별에 활용한다.

실제 주행에서는 착석 후 입력되는 압력 패턴을 학습된 사용자 모델과 비교하여 사용자를 자동으로 식별한다.

### 6.4 Posture Classification

자세 분류 역시 SVM을 기반으로 구현하였다.

```text
16-Channel Pressure Data
        ↓
Preprocessing
        ↓
StandardScaler
        ↓
RBF SVM
        ↓
5 Posture Classes
```

학습된 모델은 입력된 체압 분포를 기반으로 **5가지 자세 상태**를 분류한다.

분류 결과는 단순히 한 번의 예측으로 판단하지 않고, 일정 시간 동안 자세 상태가 지속되는지를 함께 확인하여 일시적인 움직임과 지속적인 이상 자세를 구분하도록 구성하였다.

### 6.5 COP & Pressure Balance Analysis

자세 분류와 함께 센서별 압력 분포를 이용하여 사용자의 **좌우 하중 분포**를 분석한다.

```text
FSR Pressure Data
        ↓
Pressure Distribution
        ↓
Center of Pressure (COP)
        ↓
Left / Right Load Analysis
        ↓
Balance State
```

이를 통해 사용자가 한쪽으로 지속적으로 치우쳐 앉아 있는지 확인하고, 자세 분류 결과와 함께 종합적인 착석 상태를 판단한다.

### 6.6 Ultrasonic-Based Posture Analysis

FSR 기반 분석으로 확인하기 어려운 등과 목의 자세 변화를 보완하기 위해 초음파 거리 데이터를 추가로 활용한다.

```text
Back Ultrasonic
      ↓
Back Curve Analysis
      ↓
Posture Information

Neck Ultrasonic
      ↓
Head / C7 Distance
      ↓
Neck Posture Information
```

등 부분은 4채널 초음파센서를 이용하여 등 표면과의 거리 변화를 측정하고, 목 부분은 2채널 초음파센서를 이용하여 머리 및 C7 부위의 거리 변화를 분석한다.

### 6.7 Integrated State Decision

최종적으로 사용자 식별, 자세 분류, 좌우 하중 분석, 초음파 분석 결과를 통합하여 현재 사용자의 상태를 판단한다.

```text
             ┌───────────────┐
             │ User SVM      │
             │ Identification │
             └───────┬───────┘
                     │
             ┌───────▼───────┐
             │ Posture SVM   │
             │ Classification│
             └───────┬───────┘
                     │
        ┌────────────┼────────────┐
        │            │            │
        ▼            ▼            ▼
   COP Balance   Back Curve   Neck Posture
        │            │            │
        └────────────┼────────────┘
                     ▼
             ┌───────────────┐
             │ State Analysis│
             └───────┬───────┘
                     ▼
             Warning / Feedback
```

이러한 구조를 통해 단순히 특정 자세를 분류하는 것에 그치지 않고, **사용자 식별 → 자세 분류 → 하중 분석 → 자세 상태 판단 → 경고**로 이어지는 통합적인 운전자 상태 분석이 가능하도록 구성하였다.

### 6.8 Embedded Real-Time Inference

학습 과정은 PC 환경에서 수행하고, 학습이 완료된 모델을 Raspberry Pi 5에 탑재하여 실시간 추론에 활용하였다.

```text
PC
│
├── Dataset
├── Preprocessing
├── SFS
└── SVM Training
        │
        ▼
Saved Model
        │
        ▼
Raspberry Pi 5
        │
        ├── Real-Time Sensor Input
        ├── Preprocessing
        ├── User Prediction
        ├── Posture Prediction
        └── Balance Analysis
        │
        ▼
Real-Time State
```

이를 통해 무거운 학습 과정은 사전에 수행하고, 실제 차량 시트 환경에서는 Raspberry Pi 5가 저장된 모델을 이용하여 센서 데이터를 실시간으로 처리하도록 구성하였다.

---

## 7. Software Architecture

Seat-ID의 소프트웨어는 **사용자 인터페이스, 실시간 센서 분석, AI 추론, 하드웨어 제어**를 각각 모듈화하여 구성하였다.

### Software Structure

```text
Seat-ID
│
├── app.py
│   └── UI 및 전체 시스템 상태 관리
│
├── real_time_prediction_rasp.py
│   └── 실시간 FSR 데이터 처리 및 AI 추론
│
├── pressure_database.py
│   └── 사용자 압력 데이터 등록 및 관리
│
├── train_user_model.py
│   └── 사용자 식별 모델 학습 및 저장
│
├── collect_posture_data.py
│   └── 자세 데이터 수집 및 전처리
│
├── Final_SVM_Model.py
│   └── 자세 분류 SVM 학습 및 평가
│
├── hardware_bridge.py
│   └── UI와 하드웨어 제어 모듈 연결
│
├── smart_chair_actuator_module.py
│   └── 사용자별 시트 설정 및 액추에이터 제어
│
├── spine_curve_monitor_4ch_no_s4.py
│   └── 등 곡률 초음파 분석
│
└── neck_cva_monitor_2ch.py
    └── 목 자세 초음파 분석
```

### 7.1 Main Application — `app.py`

`app.py`는 Seat-ID의 전체 UI와 시스템 상태를 관리하는 메인 애플리케이션이다.

주요 기능은 다음과 같다.

| 기능 | 설명 |
|---|---|
| **User Registration** | 신규 사용자 등록 및 사용자 정보 입력 |
| **User Selection** | 등록된 사용자 선택 및 사용자 식별 결과 관리 |
| **Real-Time Analysis** | 실시간 압력 데이터 및 자세 분석 결과 표시 |
| **Posture Score** | 현재 자세 상태 및 점수 표시 |
| **Pressure Heatmap** | 센서 압력 분포 시각화 |
| **Warning** | 이상 자세 및 하중 불균형 경고 |
| **Drive Report** | 주행 종료 후 운전 상태 및 기록 확인 |
| **State Management** | 시스템 전체 동작 상태 관리 |

전체 시스템은 다음과 같은 상태 흐름으로 동작한다.

```text
IDLE
  ↓
USER_SELECT
  ↓
DRIVE
  ↓
PARK_SAFE
  ↓
REPORT
```

### 7.2 Real-Time Prediction — `real_time_prediction_rasp.py`

Raspberry Pi 5에서 실행되는 실시간 AI 추론 모듈이다.

Arduino Mega로부터 전달받은 16채널 FSR 데이터를 전처리한 후 사용자 및 자세를 실시간으로 예측한다.

```text
Arduino Mega
      │
      │ 16-Channel FSR Data
      ▼
real_time_prediction_rasp.py
      │
      ├── Sensor Data Reading
      ├── Baseline Correction
      ├── Preprocessing
      ├── User Prediction
      ├── Posture Prediction
      └── Balance Calculation
      │
      ▼
Real-Time Result
```

주요 기능은 다음과 같다.

- `load_resources()` — 학습된 모델 및 전처리 리소스 로드
- `read_sensor()` — 센서 데이터 수신
- `baseline_correction()` — 센서 기준값 보정
- `predict_posture()` — 자세 예측
- `predict_user_detailed()` — 사용자 식별 및 상세 결과 출력
- `calculate_balance()` — 좌우 하중 분석
- `PressurePredictionService.predict_once()` — 단일 시점의 통합 예측
- `PressureBackgroundService.get_latest_result()` — 실시간 분석 결과 제공

### 7.3 User Database — `pressure_database.py`

사용자 등록 시 압력 데이터를 수집하고 사용자별 압력 프로파일을 생성한다.

```text
User Information
      +
Pressure Samples
      ↓
pressure_database.py
      ↓
Representative Samples
      ↓
User Pressure Database
```

주요 함수:

```text
collect_pressure_samples()
        ↓
create_representative_samples()
        ↓
save_pressure_database()
        ↓
register_pressure_user()
```

사용자 정보에는 사용자 ID, 닉네임, 시트 위치, 등받이 각도 등의 정보가 함께 관리된다.

### 7.4 User Model Training — `train_user_model.py`

사용자 식별을 위한 SVM 모델을 학습하고 저장하는 모듈이다.

```text
Pressure Database
      ↓
Training Data Loading
      ↓
StandardScaler
      ↓
RBF Kernel SVM
      ↓
Model Evaluation
      ↓
Model Save
```

주요 함수:

- `load_training_data()`
- `build_model()`
- `evaluate_model()`
- `train_and_save_final_model()`
- `atomic_joblib_dump()`

학습 결과는 다음과 같이 저장된다.

```text
user_model.pkl
user_scaler.pkl
```

### 7.5 Posture Data Collection — `collect_posture_data.py`

자세 분류 모델을 학습하기 위한 데이터를 수집하고 전처리한다.

주요 기능:

- 센서 baseline 로드
- 실시간 센서 데이터 읽기
- baseline 보정
- Edge Sensor 상태 확인
- 자세 클래스 선택
- 반복 데이터 수집
- CSV 데이터 저장

```text
Sensor Input
    ↓
Baseline Correction
    ↓
Edge Sensor Check
    ↓
Posture Selection
    ↓
Sample Collection
    ↓
Dataset
```

### 7.6 Posture Model — `Final_SVM_Model.py`

수집된 자세 데이터를 이용하여 최종 자세 분류 SVM 모델을 생성한다.

```text
Posture Dataset
      ↓
Data Preprocessing
      ↓
StandardScaler
      ↓
RBF Kernel SVM
      ↓
Model Evaluation
      ↓
Save Model
```

학습 결과는 다음 파일로 저장된다.

```text
svm_model.pkl
scaler.pkl
```

### 7.7 Hardware Bridge — `hardware_bridge.py`

UI에서 발생한 이벤트와 실제 하드웨어 동작을 연결하는 인터페이스 모듈이다.

```text
User Interface
      ↓
hardware_bridge.py
      ↓
Hardware Command
      ↓
Arduino / Actuator
```

이를 통해 애플리케이션의 사용자 입력을 실제 시트 제어 및 센서 시스템으로 전달할 수 있도록 구성하였다.

### 7.8 Smart Chair Actuator — `smart_chair_actuator_module.py`

사용자별 저장된 시트 프로파일을 기반으로 시트 위치와 등받이 각도를 적용하는 모듈이다.

```text
User Profile
      ↓
Seat Position
Backrest Angle
      ↓
Actuator Control
      ↓
Arduino UNO
      ↓
Linear Actuator
```

주요 기능:

- 사용자 프로파일 관리
- 시트 설정 적용
- 시트 설정 초기화
- Arduino 연결
- 액추에이터 구동

### 7.9 Ultrasonic Monitoring

등과 목의 자세를 분석하기 위한 초음파 모듈을 별도로 구성하였다.

#### `spine_curve_monitor_4ch_no_s4.py`

4채널 초음파 데이터를 이용하여 등 곡률 변화를 분석하고 피드백 정보를 JSON 형태로 제공한다.

```text
4-Channel Ultrasonic
        ↓
Distance Measurement
        ↓
Spine Curve Analysis
        ↓
Feedback JSON
```

#### `neck_cva_monitor_2ch.py`

2채널 초음파 데이터를 이용하여 머리 및 C7 부위의 거리 변화를 분석하고 목 자세 정보를 제공한다.

```text
2-Channel Ultrasonic
        ↓
Head / C7 Distance
        ↓
Neck Posture Analysis
        ↓
Feedback JSON
```

### 7.10 Software–Hardware Integration

각 소프트웨어 모듈은 독립적으로 동작하는 것이 아니라 하나의 시스템으로 연결된다.

```text
                   ┌──────────────────┐
                   │      app.py      │
                   │   Main UI / FSM  │
                   └────────┬─────────┘
                            │
             ┌──────────────┼──────────────┐
             │              │              │
             ▼              ▼              ▼
      User Database    AI Prediction   Hardware Bridge
             │              │              │
             ▼              ▼              ▼
      User SVM Model   Posture SVM    Actuator Module
                            │              │
                            │              ▼
                            │         Arduino UNO
                            │              │
                            │         Actuators
                            │
                            ▼
                    Posture / Balance
                       Analysis
```

이를 통해 **데이터 수집 → AI 추론 → 상태 판단 → UI 출력 → 하드웨어 제어**가 하나의 소프트웨어 구조 안에서 연결되도록 구현하였다.

---

## 8. Data & Model Files

Seat-ID는 사용자 등록 데이터와 자세 분류 데이터를 분리하여 관리하며, 학습된 AI 모델은 별도의 파일로 저장하여 실시간 추론 과정에서 불러오도록 구성하였다.

### Data Structure

```text
data/
│
├── pressure_user_registration.csv
│   └── 사용자 등록 정보
│
├── pressure database
│   └── 사용자별 압력 데이터
│
└── posture dataset
    └── 자세 분류 학습 데이터
```

### 8.1 User Registration Data

사용자 등록 정보는 CSV 형태로 관리한다.

```text
user_id
user_nickname
seat_position
backrest_angle
pressure_csv
```

예시 구조:

| 항목 | 설명 |
|---|---|
| `user_id` | 사용자 식별 번호 |
| `user_nickname` | 사용자 이름 또는 닉네임 |
| `seat_position` | 사용자가 설정한 시트 위치 |
| `backrest_angle` | 사용자가 설정한 등받이 각도 |
| `pressure_csv` | 사용자 압력 데이터 파일 |

사용자 식별이 완료되면 해당 사용자 정보를 기반으로 저장된 시트 설정을 조회하고, 액추에이터 제어에 활용한다.

### 8.2 Pressure Database

사용자 등록 과정에서 측정한 압력 데이터를 사용자별로 저장한다.

```text
User
 ↓
Pressure Measurement
 ↓
Pressure Samples
 ↓
Representative Pressure Data
 ↓
User Pressure Database
```

사용자별 압력 프로파일은 이후 사용자 식별 모델의 학습 및 실시간 예측에 활용된다.

### 8.3 Posture Dataset

자세 분류를 위해 각 자세 상태에서 측정한 FSR 데이터를 학습 데이터로 구성한다.

```text
FSR Sensor Data
      ↓
Baseline Correction
      ↓
Selected 16 Sensors
      ↓
Posture Labeling
      ↓
Posture Dataset
```

각 데이터는 최종 선정된 16개 센서의 압력값을 기반으로 구성되며, 자세 클래스를 label로 사용한다.

### 8.4 Trained Models

학습이 완료된 모델과 전처리 정보를 파일로 저장하여 Raspberry Pi 5에서 재사용한다.

```text
model/
│
├── user_model.pkl
├── user_scaler.pkl
├── svm_model.pkl
└── scaler.pkl
```

| 파일 | 용도 |
|---|---|
| `user_model.pkl` | 사용자 식별용 SVM 모델 |
| `user_scaler.pkl` | 사용자 식별 데이터 정규화 |
| `svm_model.pkl` | 자세 분류용 SVM 모델 |
| `scaler.pkl` | 자세 분류 데이터 정규화 |

학습된 모델을 매번 새롭게 학습하지 않고 저장된 모델을 불러와 사용함으로써 Raspberry Pi 5에서 실시간 추론이 가능하도록 구성하였다.

### 8.5 Model Inference

실시간 동작에서는 저장된 모델과 센서 데이터를 결합하여 다음과 같이 추론을 수행한다.

```text
Stored Model
     +
Real-Time FSR Data
     ↓
Preprocessing
     ↓
SVM Inference
     ↓
Prediction Result
```

사용자 식별 결과와 자세 분류 결과는 시스템의 상태 판단 및 UI 출력에 전달된다.

---
## 9. Real-Time System

Seat-ID는 Raspberry Pi 5를 중심으로 센서 입력부터 AI 추론, 상태 판단 및 사용자 피드백까지 실시간으로 처리하도록 구성하였다.

### Real-Time Processing Flow

```text
FSR / Ultrasonic Sensors
          ↓
     Arduino
          ↓
   Serial Communication
          ↓
     Raspberry Pi 5
          ↓
   Data Preprocessing
          ↓
 ┌────────┼─────────┐
 ↓        ↓         ↓
User    Posture    Balance
SVM       SVM      Analysis
 ↓        ↓         ↓
 └────────┼─────────┘
          ↓
   Ultrasonic Analysis
          ↓
    State Evaluation
          ↓
 ┌────────┴────────┐
 ↓                 ↓
Normal         Abnormal
 ↓                 ↓
Monitoring       Warning
          ↓
      Data Logging
```

### 9.1 Sensor Data Acquisition

FSR 센서에서 측정된 압력 데이터는 Arduino Mega에서 수집하여 Raspberry Pi 5로 전달한다.

```text
FSR Sensors
    ↓
Arduino Mega
    ↓
16-Channel ADC Data
    ↓
Serial Communication
    ↓
Raspberry Pi 5
```

Raspberry Pi 5에서는 수신된 센서 데이터를 실시간 분석에 사용할 수 있도록 전처리한다.

### 9.2 Real-Time Preprocessing

수신된 FSR 데이터는 다음 과정을 거쳐 AI 모델의 입력으로 변환된다.

```text
Raw Sensor Data
      ↓
Baseline Correction
      ↓
Averaging
      ↓
Selected 16 Channels
      ↓
StandardScaler
      ↓
AI Model Input
```

센서의 기준값을 보정하고 측정값을 평균화하여 입력 데이터의 변동성을 줄인 후, 학습 과정과 동일한 전처리를 적용한다.

### 9.3 Real-Time User Identification

전처리된 압력 데이터를 사용자 식별 모델에 입력하여 현재 착석한 사용자를 판단한다.

```text
Pressure Data
     ↓
User Scaler
     ↓
User SVM
     ↓
User ID / Confidence
```

식별된 사용자의 프로파일을 기반으로 저장된 시트 위치와 등받이 각도를 조회할 수 있다.

### 9.4 Real-Time Posture Classification

동일한 압력 데이터를 자세 분류 모델에도 입력한다.

```text
Pressure Data
     ↓
Posture Scaler
     ↓
Posture SVM
     ↓
Posture Class / Confidence
```

현재 자세가 일시적으로 변화한 것인지 지속적인 이상 상태인지 판단하기 위해 시간에 따른 상태 변화를 함께 관리한다.

### 9.5 Balance Analysis

센서별 압력 분포를 이용하여 사용자의 좌우 하중 상태를 계산한다.

```text
16-Channel Pressure
        ↓
Pressure Distribution
        ↓
COP Calculation
        ↓
Left / Right Balance
```

이를 통해 특정 방향으로 하중이 지속적으로 편중되는 상태를 분석할 수 있다.

### 9.6 Ultrasonic Monitoring

FSR 기반 분석과 함께 등 및 목에 설치된 초음파센서의 거리 데이터를 활용한다.

```text
          Ultrasonic Data
                 ↓
       ┌─────────┴─────────┐
       ↓                   ↓
  Spine Monitor       Neck Monitor
       ↓                   ↓
 Back Curve         Head / C7 Position
 Analysis              Analysis
       └─────────┬─────────┘
                 ↓
          Posture Feedback
```

FSR에서 확인되는 착석 압력 변화와 초음파 기반의 상체 자세 정보를 함께 활용하여 자세 상태를 보완적으로 판단한다.

### 9.7 Abnormal Posture Warning

실시간 자세 분석 결과가 이상 상태로 판단되더라도 순간적인 움직임만으로 바로 경고하지 않도록 지속 여부를 확인한다.

```text
Posture Prediction
        ↓
Abnormal State?
     ↙       ↘
   NO         YES
   ↓           ↓
Monitoring   Duration Check
               ↓
        ┌──────┴──────┐
        ↓             ↓
    Short-term     Sustained
        ↓             ↓
     Ignore        Warning
```

이를 통해 운전 중 발생할 수 있는 일시적인 자세 변화와 지속적인 이상 자세를 구분하도록 구성하였다.

### 9.8 Integrated Result

최종적으로 실시간 분석 결과는 UI에 전달되어 사용자에게 현재 상태를 제공한다.

```text
User Identification
        +
Posture Classification
        +
Balance Analysis
        +
Spine Analysis
        +
Neck Analysis
        ↓
Integrated State
        ↓
Posture Score / Heatmap
        ↓
Warning / Feedback
        ↓
Driving Log
```

이와 같이 Seat-ID는 단일 센서나 단일 AI 모델의 결과만 사용하는 것이 아니라, **압력 기반 사용자 식별·자세 분류·좌우 하중 분석과 초음파 기반 자세 분석을 실시간으로 통합**하여 운전자의 착석 상태를 판단하도록 구현하였다.

---

## 10. Driving Report & User Interface

Seat-ID는 주행 중 수집된 센서 및 분석 결과를 단순히 실시간으로 표시하는 것에 그치지 않고, 주행 종료 후 사용자의 착석 상태와 경고 이력을 확인할 수 있도록 **Driving Report** 기능을 구성하였다.

### 10.1 Main UI

메인 애플리케이션은 사용자의 현재 상태에 따라 화면과 기능을 전환하도록 구성하였다.

```text
                 Seat-ID UI
                     │
        ┌────────────┴────────────┐
        │                         │
   User Registration         User Selection
        │                         │
        └────────────┬────────────┘
                     ↓
                  DRIVE
                     │
        ┌────────────┼────────────┐
        ↓            ↓            ↓
   Pressure      Posture       Ultrasonic
    Heatmap       Status         Status
        │            │            │
        └────────────┼────────────┘
                     ↓
              Warning / Feedback
                     │
                     ↓
                   REPORT
```

### 10.2 Pressure Heatmap

FSR 센서에서 측정된 압력 분포를 시각화하여 사용자가 현재 어느 부분에 하중이 집중되어 있는지 확인할 수 있도록 구성하였다.

```text
16-Channel FSR Data
        ↓
Pressure Distribution
        ↓
Heatmap Visualization
        ↓
Real-Time UI
```

압력 분포 변화는 자세 분류 및 좌우 하중 분석 결과와 함께 사용자의 착석 상태를 확인하는 데 활용된다.

### 10.3 Posture Status

실시간 SVM 추론 결과를 기반으로 현재 자세 상태를 UI에 표시한다.

```text
FSR Data
   ↓
SVM Inference
   ↓
Posture Class
   ↓
Posture Score / Status
```

자세 상태가 일정 시간 이상 이상 상태로 유지되는 경우 경고 상태로 전환되도록 구성하였다.

### 10.4 Warning & Feedback

이상 자세 또는 좌우 하중 불균형이 지속되는 경우 사용자에게 경고를 제공한다.

```text
Posture / Balance Analysis
           ↓
      Abnormal State
           ↓
     Duration Check
           ↓
      Warning Output
```

순간적인 자세 변화에는 불필요한 경고가 발생하지 않도록 지속 시간을 고려하여 상태를 판단한다.

### 10.5 Driving Report

주행 중 분석된 결과를 기록하고, 주행 종료 후 사용자가 자신의 주행 상태를 확인할 수 있도록 리포트를 구성하였다.

```text
                 DRIVE
                   ↓
        Real-Time Analysis
                   ↓
      ┌────────────┼────────────┐
      ↓            ↓            ↓
 Posture        Balance       Warning
  State          State         History
      └────────────┼────────────┘
                   ↓
              Data Logging
                   ↓
                 REPORT
```

리포트에서는 주행 중 발생한 자세 상태와 경고 등의 기록을 확인할 수 있도록 구성하였다.

### 10.6 System State Management

전체 UI는 다음과 같은 상태 머신을 기반으로 동작한다.

```text
┌───────┐
│ IDLE  │
└───┬───┘
    ↓
┌────────────┐
│USER_SELECT │
└─────┬──────┘
      ↓
┌───────────┐
│   DRIVE   │
└─────┬─────┘
      ↓
┌────────────┐
│ PARK_SAFE  │
└─────┬──────┘
      ↓
┌───────────┐
│  REPORT   │
└───────────┘
```

각 상태에서 수행되는 주요 기능은 다음과 같다.

| State | 주요 기능 |
|---|---|
| **IDLE** | 시스템 대기 |
| **USER_SELECT** | 사용자 선택 및 등록 |
| **DRIVE** | 센서 측정, AI 추론, 자세 분석 및 경고 |
| **PARK_SAFE** | 주행 종료 및 안전 상태 전환 |
| **REPORT** | 주행 데이터 및 분석 결과 확인 |

이를 통해 센서 입력과 AI 분석뿐만 아니라 **사용자 입력 → 주행 → 종료 → 결과 확인**까지 전체 시스템의 동작 흐름을 하나의 애플리케이션에서 관리하도록 구현하였다.

---

---

## 11. Hardware–Software Integration

Seat-ID는 센서 데이터 수집부터 AI 추론, 사용자별 시트 제어 및 UI 출력까지 각 구성 요소를 실제 하드웨어와 연결하여 하나의 시스템으로 통합하였다.

### 11.1 Overall Integration

```text
                 ┌─────────────────────┐
                 │     FSR Sensors     │
                 └──────────┬──────────┘
                            ↓
                 ┌─────────────────────┐
                 │    Arduino Mega     │
                 │  Sensor Acquisition │
                 └──────────┬──────────┘
                            │
                     Serial Data
                            │
                            ▼
                 ┌─────────────────────┐
                 │    Raspberry Pi 5   │
                 │                     │
                 │  Data Processing    │
                 │  User SVM           │
                 │  Posture SVM        │
                 │  Balance Analysis   │
                 └──────────┬──────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
            ▼               ▼               ▼
       Touch Screen    Ultrasonic       Hardware
          / UI          Analysis          Bridge
                                            │
                                            ▼
                                   ┌────────────────┐
                                   │   Arduino UNO  │
                                   └───────┬────────┘
                                           ↓
                                   Motor Driver
                                           ↓
                                  Linear Actuators
                                           ↓
                                  Seat / Backrest
```

### 11.2 Sensor–AI Integration

Arduino Mega에서 수집된 FSR 데이터를 Raspberry Pi 5로 전달하고, Raspberry Pi 5에서 사용자 식별과 자세 분류를 수행한다.

```text
FSR
 ↓
Arduino Mega
 ↓
16-Channel Pressure Data
 ↓
Raspberry Pi 5
 ↓
Preprocessing
 ↓
┌─────────────────┐
│ User SVM        │ → User Identification
│ Posture SVM     │ → Posture Classification
│ COP Analysis    │ → Balance Analysis
└─────────────────┘
```

### 11.3 AI–Actuator Integration

사용자 식별 결과는 단순한 사용자 확인에만 사용하지 않고, 등록된 사용자의 시트 설정을 조회하여 실제 액추에이터 제어로 연결한다.

```text
User Identification
        ↓
User Profile
        ↓
Seat Position
Backrest Angle
        ↓
Actuator Operating Time
        ↓
Arduino UNO
        ↓
Motor Driver
        ↓
Linear Actuator
        ↓
Personalized Seat Setting
```

따라서 사용자가 등록된 경우 별도의 수동 설정 없이 저장된 시트 프로파일을 기반으로 시트 위치와 등받이 각도를 적용할 수 있도록 구성하였다.

### 11.4 Hardware Control

액추에이터 제어는 Arduino UNO와 Motor Driver를 통해 수행한다.

```text
Raspberry Pi 5
      ↓
Hardware Bridge
      ↓
Arduino UNO
      ↓
Motor Driver
      ↓
Linear Actuator
```

시트 위치 조절에는 Linear Actuator를 사용하며, 등받이 각도 조절에는 Rack & Pinion 구조를 적용하여 액추에이터의 직선 운동을 회전 운동으로 변환한다.

### 11.5 Physical Prototype

소프트웨어에서 구현한 기능을 실제 하드웨어 동작으로 검증하기 위해 **3D 프린팅 기반의 시트 구조 모형**을 제작하였다.

```text
                    3D Printed Seat
                          │
          ┌───────────────┼───────────────┐
          ↓               ↓               ↓
      FSR Sensors     Ultrasonic      Actuators
          │               │               │
          └───────────────┼───────────────┘
                          ↓
                    Embedded System
                          ↓
                    Real-Time Analysis
                          ↓
                  Seat Control / Feedback
```

센서 장착 위치와 시트 구조를 실제 프로토타입에 반영하여, 단순한 소프트웨어 시뮬레이션이 아닌 **센서 측정 → 데이터 처리 → AI 추론 → 제어 명령 → 액추에이터 구동**의 전체 과정을 실제 하드웨어 환경에서 연결하였다.

### 11.6 End-to-End System

최종적으로 Seat-ID는 다음과 같은 End-to-End 구조로 동작한다.

```text
        User
         ↓
      Seating
         ↓
    FSR Measurement
         ↓
   Arduino Mega
         ↓
   Raspberry Pi 5
         ↓
 ┌───────┼────────┐
 ↓       ↓        ↓
User   Posture   Balance
SVM      SVM     Analysis
 └───────┼────────┘
         ↓
 Ultrasonic Analysis
         ↓
  Integrated State
         ↓
 ┌───────┴────────┐
 ↓                ↓
Normal          Abnormal
 ↓                ↓
Monitoring      Warning
         ↓
     Drive Log
         ↓
       Report
```

동시에 사용자 식별 결과를 기반으로 저장된 시트 설정을 액추에이터 제어와 연결하여 다음과 같은 제어 루프를 구성하였다.

```text
User Identification
        ↓
User Profile
        ↓
Seat Setting
        ↓
Actuator Control
        ↓
Physical Seat Movement
```

이를 통해 Seat-ID는 **AI 모델만 구현한 시스템이 아니라 실제 센서와 임베디드 보드, 시트 구조물, 액추에이터까지 연결된 통합 프로토타입**으로 구현하였다.

---


## 12. Development & Verification

Seat-ID는 소프트웨어 알고리즘 개발에 그치지 않고, 실제 센서와 임베디드 보드 및 시트 구조물을 단계적으로 연결하면서 시스템을 검증하였다.

### 12.1 Development Process

```text
System Planning
      ↓
Sensor & Hardware Configuration
      ↓
Pressure Data Collection
      ↓
Sensor Optimization
      ↓
AI Model Development
      ↓
Real-Time Inference
      ↓
Ultrasonic Integration
      ↓
Actuator Integration
      ↓
UI / System Integration
      ↓
Physical Prototype Verification
```

### 12.2 Sensor Configuration Verification

FSR 센서의 측정 특성을 확인하기 위해 저항값에 따른 ADC 응답을 비교하고, 실제 프로토타입 환경에서 사용할 저항값을 선정하였다.

```text
FSR
 ↓
Resistance Test
 ↓
ADC Response Comparison
 ↓
Resistor Selection
 ↓
Final Sensor Configuration
```

테스트 결과 **10 kΩ 저항값**을 최종 센서 구성에 적용하였다.

### 12.3 Sensor Reduction Verification

초기 144개 센서를 모두 사용하는 방식에서 벗어나 SFS를 적용하여 최종 16개 센서를 선정하였다.

```text
144 Sensors
    ↓
SFS
    ↓
Candidate Combination Evaluation
    ↓
Optimal Sensor Selection
    ↓
16 Sensors
```

선정된 센서는 실제 하드웨어에 적용하여 이후 실시간 데이터 수집 및 AI 추론에 사용하였다.

### 12.4 AI Model Verification

자세 분류를 위해 수집한 데이터를 기반으로 SVM 모델을 학습하고 평가하였다.

```text
Posture Dataset
      ↓
Preprocessing
      ↓
StandardScaler
      ↓
RBF SVM
      ↓
Model Evaluation
      ↓
Saved Model
```

학습된 모델은 `svm_model.pkl` 형태로 저장하여 Raspberry Pi 5에서 실시간 추론에 활용하였다.

사용자 식별 역시 별도의 사용자 압력 데이터베이스를 구축하고 SVM 기반 모델을 학습하여 실시간 식별에 사용할 수 있도록 구성하였다.

### 12.5 Real-Time Verification

학습된 모델을 Raspberry Pi 5에 적용하고 Arduino Mega에서 전달되는 실시간 FSR 데이터를 이용하여 추론 구조를 검증하였다.

```text
Physical FSR Input
        ↓
Arduino Mega
        ↓
Serial Communication
        ↓
Raspberry Pi 5
        ↓
Preprocessing
        ↓
SVM Inference
        ↓
User / Posture Result
```

이를 통해 학습 단계에서 생성된 모델이 실제 센서 입력 환경에서도 동작할 수 있도록 실시간 추론 구조를 구현하였다.

### 12.6 Actuator Verification

사용자 프로파일에 저장된 시트 위치 및 등받이 각도를 액추에이터 구동 명령으로 변환하여 실제 시트 구조물의 움직임으로 연결하였다.

```text
User Profile
      ↓
Seat / Backrest Setting
      ↓
Operating Time Calculation
      ↓
Arduino UNO
      ↓
Motor Driver
      ↓
Linear Actuator
      ↓
Physical Movement
```

시트의 위치 조절과 등받이 각도 조절을 실제 프로토타입에서 구현함으로써 개인별 시트 설정 복원 기능을 하드웨어 수준까지 연결하였다.

### 12.7 Integrated Prototype Verification

최종적으로 각 기능을 개별적으로 검증하는 것에서 나아가 하나의 시트 프로토타입에서 통합 동작하도록 구성하였다.

```text
┌─────────────────────────────────────┐
│          Physical Seat Prototype    │
│                                     │
│  FSR ───────┐                        │
│             │                        │
│  Ultrasonic┼──→ Embedded System     │
│             │        │               │
│             │        ↓               │
│             │   AI / State Analysis │
│             │        │               │
│             │        ↓               │
│             │   Control Command      │
│             │        │               │
│             └────────┼───────────────│
│                      ↓               │
│                  Actuator            │
└─────────────────────────────────────┘
```

최종 시스템에서는 다음 기능을 하나의 흐름으로 연결하였다.

```text
User Registration
      ↓
Pressure Measurement
      ↓
User Identification
      ↓
Personal Seat Setting
      ↓
Posture Analysis
      ↓
Balance / Ultrasonic Analysis
      ↓
Warning & Feedback
      ↓
Driving Data Logging
      ↓
Driving Report
```

이를 통해 Seat-ID의 핵심 기능을 **실제 센서 입력과 임베디드 시스템, AI 모델, UI 및 액추에이터가 연결된 형태로 검증**하였다.

---
## 13. Project Structure

Seat-ID는 센서 데이터 수집, AI 모델, 실시간 추론, 하드웨어 제어 및 UI를 기능별로 분리하여 관리할 수 있도록 구성하였다.

```text
Seat-ID/
│
├── README.md
│
├── software/
│   ├── app.py
│   ├── real_time_prediction_rasp.py
│   ├── pressure_database.py
│   ├── train_user_model.py
│   ├── collect_posture_data.py
│   ├── Final_SVM_Model.py
│   ├── hardware_bridge.py
│   ├── smart_chair_actuator_module.py
│   ├── spine_curve_monitor_4ch_no_s4.py
│   └── neck_cva_monitor_2ch.py
│
├── arduino/
│   └── Arduino Source Codes
│
├── data/
│   ├── pressure_user_registration.csv
│   ├── pressure database
│   └── posture dataset
│
├── model/
│   ├── user_model.pkl
│   ├── user_scaler.pkl
│   ├── svm_model.pkl
│   └── scaler.pkl
│
├── hardware/
│   ├── FSR Sensor Array
│   ├── Ultrasonic Sensors
│   ├── Linear Actuators
│   ├── Motor Driver
│   └── 3D Printed Seat
│
└── docs/
    ├── System Architecture
    ├── Hardware Design
    └── Development Report
```

### Software

| 파일 | 주요 역할 |
|---|---|
| `app.py` | UI 및 전체 시스템 상태 관리 |
| `real_time_prediction_rasp.py` | 실시간 센서 처리 및 AI 추론 |
| `pressure_database.py` | 사용자 압력 데이터 등록 및 관리 |
| `train_user_model.py` | 사용자 식별 SVM 학습 |
| `collect_posture_data.py` | 자세 데이터 수집 |
| `Final_SVM_Model.py` | 자세 분류 SVM 학습 |
| `hardware_bridge.py` | UI와 하드웨어 연결 |
| `smart_chair_actuator_module.py` | 사용자별 시트 설정 및 액추에이터 제어 |
| `spine_curve_monitor_4ch_no_s4.py` | 등 곡률 초음파 분석 |
| `neck_cva_monitor_2ch.py` | 목 자세 초음파 분석 |

### Data & Model

```text
data/
   ↓
Dataset
   ↓
Preprocessing
   ↓
SFS / SVM Training
   ↓
model/
   ↓
Real-Time Inference
```

학습 과정에서 생성된 모델 파일과 스케일러는 별도로 관리하여 실시간 추론 모듈에서 불러올 수 있도록 구성하였다.

### Hardware

```text
FSR
 ↓
Arduino Mega
 ↓
Raspberry Pi 5
 ↓
AI / State Analysis
 ↓
Arduino UNO
 ↓
Motor Driver
 ↓
Linear Actuator
 ↓
Physical Seat
```

소프트웨어와 하드웨어를 기능별로 분리하면서도 각 모듈 간 인터페이스를 통해 전체 시스템을 하나의 구조로 통합하였다.

---

## 14. Expected Effects & Future Development

Seat-ID는 체압 기반 사용자 식별과 자세 분석, 개인별 시트 설정 및 실시간 상태 피드백을 하나의 시스템으로 통합함으로써 기존 운전자 관리 시스템의 한계를 보완하는 것을 목표로 한다.

### 14.1 Camera-Less Driver Monitoring

기존의 영상 기반 운전자 모니터링과 달리 Seat-ID는 **FSR 압력센서와 초음파센서**를 이용하여 사용자의 상태를 분석한다.

```text
Camera-Based System
        ↓
Image Acquisition
        ↓
Image Processing
        ↓
Driver Analysis

             VS

Seat-ID
        ↓
Pressure / Distance Data
        ↓
Sensor Processing
        ↓
AI / State Analysis
```

이를 통해 차량 내부 영상을 직접 촬영하지 않고도 사용자의 착석 상태와 자세 변화를 분석할 수 있는 구조를 제안하였다.

### 14.2 Personalized Seat Experience

사용자 식별 결과와 저장된 사용자 프로파일을 연계하여 개인별 시트 설정을 자동으로 적용할 수 있다.

```text
User
 ↓
Pressure-Based Identification
 ↓
User Profile
 ↓
Saved Seat Position
Saved Backrest Angle
 ↓
Actuator Control
 ↓
Personalized Seat
```

사용자가 차량에 탑승할 때마다 시트 위치와 등받이 각도를 직접 조절해야 하는 과정을 줄이고, 사용자별 선호 설정을 자동으로 복원하는 방향으로 확장할 수 있다.

### 14.3 Adaptive Driver Monitoring

현재 시스템은 자세 이상 및 좌우 하중 불균형이 일정 시간 지속되는지를 판단하여 피드백을 제공한다.

향후에는 주행 중 축적되는 데이터를 활용하여 사용자의 자세 변화 패턴을 장기적으로 분석할 수 있다.

```text
Driving Data
      ↓
Posture History
      ↓
Individual Pattern Analysis
      ↓
Personalized Warning
```

사용자마다 다른 착석 습관과 자세 변화를 고려하여 보다 개인화된 운전자 상태 관리 시스템으로 발전시킬 수 있다.

### 14.4 Autonomous Driving Environment

자율주행 기술이 발전하면서 운전자가 차량 제어에 직접 개입하는 시간이 감소할 경우, 차량 내부에서 운전자의 착석 자세와 신체 상태를 관리하는 기능의 중요성이 높아질 수 있다.

Seat-ID는 이러한 환경에서 다음과 같은 기능으로 확장할 수 있다.

```text
Autonomous Driving
        ↓
Driver / Passenger Monitoring
        ↓
Posture & Load Analysis
        ↓
Personalized Seat Adjustment
        ↓
Comfort / Safety Feedback
```

특히 운전자가 핸들을 직접 조작하지 않는 상황에서도 시트와 사용자의 상태를 지속적으로 관리할 수 있는 기반으로 활용할 수 있다.

### 14.5 Shared Mobility

차량 공유 환경에서는 동일한 차량을 여러 사용자가 이용하기 때문에 사용자별 시트 설정을 자동으로 복원하는 기능을 적용할 수 있다.

```text
Shared Vehicle
      ↓
User Identification
      ↓
Personal Profile
      ↓
Seat Setting Recovery
```

향후 차량 공유 플랫폼과 사용자 계정을 연계한다면, 차량에 등록된 사용자가 탑승했을 때 개인별 시트 설정을 자동으로 불러오는 형태로 발전시킬 수 있다.

### 14.6 Elderly & Special-Use Seating

Seat-ID의 센서 기반 착석 분석 구조는 일반 차량뿐만 아니라 다양한 좌석 환경에도 적용할 수 있다.

```text
Vehicle Seat
Bus / Truck
Elderly Seating
Industrial Seating
Shared Mobility
        ↓
Pressure-Based Monitoring
        ↓
Posture / Balance Analysis
        ↓
User-Specific Feedback
```

향후 센서 배치와 분석 알고리즘을 각 환경에 맞게 최적화한다면 차량 이외의 다양한 스마트 시트 시스템으로 확장할 수 있다.

### 14.7 Future Hardware Development

현재 제작한 3D 프린팅 기반 시트 구조물을 기반으로 향후 실제 차량 시트에 가까운 형태로 하드웨어를 발전시킬 수 있다.

```text
Current Prototype
      ↓
Sensor / Actuator Optimization
      ↓
Vehicle Seat Integration
      ↓
Real Vehicle Environment
```

또한 향후에는 사용자의 자세 상태에 따라 시트 자체가 물리적인 피드백을 제공할 수 있도록 **에어셀 기반 능동형 시트 조절 구조** 등을 추가적으로 고려할 수 있다.

### 14.8 Future AI Development

현재 SFS를 통해 센서 수를 최적화하고 SVM 기반 경량 모델을 적용한 구조를 바탕으로 향후 더 다양한 운전자 상태 분석으로 확장할 수 있다.

```text
Current
16 FSR + SVM
      ↓
More Driving Data
      ↓
Individual State Modeling
      ↓
Advanced Driver Monitoring
```

향후 축적되는 실제 주행 데이터를 활용하여 자세 변화뿐만 아니라 사용자의 장시간 착석 패턴과 상태 변화를 함께 분석하는 방향으로 발전시킬 수 있다.

---

## 15. Team Roles

| Member | Role | Main Responsibilities |
|---|---|---|
| **유나현** | Team Leader | - 리니어 액추에이터 기반 시트 전후·등받이 각도 조절 모형 3D 모델링 및 3D 프린팅 부품 설계<br>- Arduino Uno 기반 다채널 초음파 센서 측정 HW 구성 및 거리 데이터 수집 구조 구현<br>- 센서 기준값 측정, 중앙값·EMA 필터링, 오류 처리 및 자세 경고 로직 구현<br>- 초음파 기반 목·등 자세 측정 시스템 통합 테스트 및 오류 디버깅<br>- 후두부-C7 거리 기반 목 전방 자세 및 2차 곡선 적합 기반 등 곡률 판정 알고리즘 구현 |
| **구여은** | Hardware / Actuator | - 리니어 액추에이터 기반 시트 전후·등받이 각도 구동부 3D 설계<br>- 랙·피니언 기어를 활용한 등받이 각도 조절 메커니즘 구현<br>- Arduino 및 모터드라이버 기반 리니어 액추에이터 제어 회로 구현<br>- 액추에이터 스트로크·속도 기반 위치 및 각도-구동시간 변환 로직 설계 |
| **박정인** | Embedded / AI | - SW 개발 일정 수립 및 업무 진행상황 관리<br>- FSR 압력센서 데이터 전처리 및 SFS 기반 최적 센서 위치 선정 알고리즘 구현<br>- SVM 기반 사용자 식별 및 5종 착석 자세 분류 모델 개발·검증<br>- Raspberry Pi 기반 실시간 압력 데이터 수집·전처리·추론 코드 구현 및 센서 통신 연동<br>- FSR 압력센서 배열을 고려한 시트 구조 설계 및 하중 전달·분산 구조 구현<br>- 실시간 사용자·자세 판정 로직 통합 및 임베디드 환경 동작 검증 |
| **성호원** | UI / System Integration | - Raspberry Pi 5·PyQt5 기반 터치 UI 및 한글·숫자 가상 키보드 구현<br>- 사용자 식별·등록, 시트 설정·주행 대시보드·자세 경고·운전 리포트 화면 구성<br>- S·P·F 롤리 버튼과 주행·주차·종료 UI 상태 전환 연동<br>- 체압 사용자 식별 결과와 연동한 사용자 데이터 수집 및 SVM 재학습 과정 자동화<br>- 16채널 압력 히트맵과 등록 분석 기반 자세 점수·그래프·경고 로직 구현<br>- 사용자·시트·HW 명령·주행 로그 CSV 연동 및 액추에이터 APPLY·RESET 통합 테스트·디버깅 |
| **장예은** | AI / Data | - CNN 기반 사용자·자세 분류 모델 구축 및 성능 비교·검증<br>- FSR 센서 민감도에 따른 저항값 선정 및 센서 회로 설계·배선 구현<br>- Arduino Mega 기반 다채널 FSR 압력센서 데이터 통신 구조 구현<br>- 압력센서 데이터 수집·통합·유사 데이터 제거·이상치 검토 과정 자동화<br>- 초기 가상데이터 구축 및 재학습용 데이터셋 구축<br>- 구축 데이터셋 기반 5종 착석 자세 분류 모델 학습 및 재학습·테스트를 통한 성능 검증 |

### Role Distribution

```text
┌─────────────────────────────────────────────────────────────┐
│                         Seat-ID Team                         │
├──────────────┬──────────────────────────────────────────────┤
│ 유나현       │ 초음파 센싱 · 자세 측정 · 액추에이터 모형    │
│ 구여은       │ 액추에이터 · 랙&피니언 · 구동 제어           │
│ 박정인       │ FSR · SFS · SVM · 실시간 추론 · 임베디드     │
│ 성호원       │ PyQt5 UI · 데이터 관리 · 시스템 통합        │
│ 장예은       │ CNN 비교 · FSR HW · 데이터셋 · 모델 검증     │
└──────────────┴──────────────────────────────────────────────┘
```

### Team Collaboration

각 팀원은 센서·AI·임베디드·구동부·UI 영역을 분담하여 개발하되, 개별 모듈을 독립적으로 구현하는 데 그치지 않고 최종 시스템 통합 및 실물 시트 모형 검증까지 공동으로 수행하였다.

특히 **FSR 압력센서 → 데이터 전처리 → SFS 기반 센서 최적화 → SVM 사용자·자세 판정 → Raspberry Pi 실시간 추론 → UI 상태 관리 → 액추에이터 제어**로 이어지는 전체 시스템을 연동하여, 센서 데이터 처리부터 실제 하드웨어 구동까지 하나의 통합 시스템으로 구현하였다.
---

## 16. Demo & Result

Seat-ID는 실제 시트 구조 모형에 센서와 액추에이터를 적용하여 **센서 입력부터 AI 분석, 사용자별 시트 제어 및 결과 출력까지의 전체 동작을 통합 구현**하였다.

### 16.1 End-to-End Demonstration

```text
          User Seating
               ↓
        FSR Pressure Input
               ↓
         User Identification
               ↓
       Personal Seat Setting
               ↓
        Actuator Adjustment
               ↓
          Driving Start
               ↓
       Real-Time Monitoring
               ↓
 ┌─────────────┼─────────────┐
 ↓             ↓             ↓
Posture      Balance      Ultrasonic
Analysis     Analysis       Analysis
 └─────────────┼─────────────┘
               ↓
        State Evaluation
               ↓
        Warning / Feedback
               ↓
         Driving Logging
               ↓
             Report
```

### 16.2 Physical Prototype

실제 차량 시트의 동작을 모사하기 위해 3D 프린팅 기반 시트 구조물을 제작하고, FSR 센서와 초음파센서 및 Linear Actuator를 통합하였다.

```text
┌──────────────────────────────┐
│       Physical Seat          │
│                              │
│   FSR Sensor Array           │
│        ↓                     │
│   Pressure Measurement       │
│                              │
│   Ultrasonic Sensors         │
│        ↓                     │
│   Posture Measurement        │
│                              │
│   Linear Actuators           │
│        ↓                     │
│   Seat / Backrest Control    │
│                              │
└──────────────────────────────┘
```

이를 통해 센서 데이터를 PC에서 단순히 분석하는 방식이 아니라 **실제 하드웨어에서 데이터를 취득하고 임베디드 시스템에서 처리한 뒤 물리적인 시트 동작으로 연결되는 구조**를 구현하였다.

### 16.3 Integrated Functions

최종 프로토타입에서는 다음 기능을 하나의 시스템으로 통합하였다.

| 기능 | 구현 내용 |
|---|---|
| **사용자 식별** | FSR 기반 압력 패턴을 이용한 사용자 식별 |
| **개인별 시트 설정** | 사용자별 저장된 시트 위치 및 등받이 각도 적용 |
| **자세 분류** | SVM 기반 5종 자세 분류 |
| **좌우 하중 분석** | COP 기반 좌우 하중 분포 분석 |
| **등 자세 분석** | 초음파센서를 이용한 등 곡률 변화 분석 |
| **목 자세 분석** | 초음파센서를 이용한 머리 및 C7 위치 분석 |
| **이상 자세 경고** | 지속적인 이상 상태에 대한 사용자 피드백 |
| **주행 기록** | 주행 중 상태 및 경고 정보 기록 |
| **주행 리포트** | 주행 종료 후 분석 결과 확인 |

### 16.4 System Demonstration Scenario

```text
[1] User Registration
        ↓
[2] Pressure Data Collection
        ↓
[3] User Model Training
        ↓
[4] User Seating
        ↓
[5] Automatic User Identification
        ↓
[6] Personal Seat Setting Recovery
        ↓
[7] Real-Time Driving Monitoring
        ↓
[8] Posture / Balance Analysis
        ↓
[9] Warning & Feedback
        ↓
[10] Driving Report
```

### 16.5 Implementation Scope

Seat-ID의 구현 범위는 다음과 같다.

```text
                 ┌─────────────────┐
                 │   SENSING       │
                 │ FSR / Ultrasonic│
                 └────────┬────────┘
                          ↓
                 ┌─────────────────┐
                 │   PROCESSING    │
                 │ Arduino / RPi5  │
                 └────────┬────────┘
                          ↓
                 ┌─────────────────┐
                 │       AI        │
                 │ SFS + SVM       │
                 └────────┬────────┘
                          ↓
                 ┌─────────────────┐
                 │ STATE ANALYSIS  │
                 │ Posture / COP   │
                 └────────┬────────┘
                          ↓
                 ┌─────────────────┐
                 │     CONTROL     │
                 │ Actuator / Seat │
                 └────────┬────────┘
                          ↓
                 ┌─────────────────┐
                 │     OUTPUT      │
                 │ UI / Warning    │
                 │ / Report        │
                 └─────────────────┘
```

Seat-ID는 **센서–AI–임베디드–제어–UI**를 개별적으로 구현하는 데 그치지 않고, 실제 시트 프로토타입에서 각 구성 요소를 연결하여 전체 시스템의 동작을 검증하였다.

---

## 17. Technical Summary

Seat-ID는 **체압 기반 사용자 식별과 AI 기반 자세 분석, 개인별 시트 설정 복원, 실시간 상태 피드백**을 하나의 임베디드 시스템으로 통합한 스마트 시트 프로토타입이다.

### System Summary

| Category | Implementation |
|---|---|
| **Sensing** | FSR-406 · Ultrasonic Sensor |
| **Sensor Optimization** | SFS · 144 → 16 Sensors |
| **AI** | RBF Kernel SVM |
| **Posture Classification** | 5 Posture Classes |
| **Balance Analysis** | COP 기반 좌우 하중 분석 |
| **Embedded** | Raspberry Pi 5 · Arduino Mega · Arduino UNO |
| **Communication** | Serial Communication |
| **Actuation** | Linear Actuator · Motor Driver |
| **Mechanism** | Rack & Pinion |
| **UI** | Touch Screen · Real-Time Monitoring |
| **Data** | CSV 기반 사용자 및 주행 데이터 관리 |
| **Prototype** | 3D Printed Seat Structure |

### Core Technology

```text
              SEAT-ID
                 │
       ┌─────────┴─────────┐
       │                   │
   PRESSURE             ULTRASONIC
    SENSING               SENSING
       │                   │
       ▼                   ▼
   FSR-406             Back / Neck
       │                   │
       └─────────┬─────────┘
                 ↓
           DATA PROCESSING
                 ↓
        ┌────────┴────────┐
        ↓                 ↓
       SFS              SVM
        │                 │
  Sensor Selection    AI Inference
        │                 │
        └────────┬────────┘
                 ↓
          STATE ANALYSIS
                 ↓
       ┌─────────┴─────────┐
       ↓                   ↓
   User / Posture       Balance
   Identification       Analysis
       │                   │
       └─────────┬─────────┘
                 ↓
          USER FEEDBACK
                 ↓
       ┌─────────┴─────────┐
       ↓                   ↓
    Warning            Seat Control
                           │
                           ↓
                      Actuator
```

### Key Features

**① Camera-less User Identification**

FSR 센서의 체압 패턴을 활용하여 사용자를 식별하고, 등록된 사용자 프로파일을 조회한다.

**② Sensor Optimization**

12 × 12 배열의 144개 센서를 SFS를 통해 16개 센서로 최적화하여 실시간 임베디드 시스템에 적용하였다.

**③ Lightweight AI Inference**

RBF Kernel SVM을 활용하여 Raspberry Pi 5에서 사용자 식별 및 자세 분류를 수행하도록 구성하였다.

**④ Multi-Modal Posture Analysis**

FSR 기반 자세 분류와 COP 기반 좌우 하중 분석에 더해 등·목 초음파 데이터를 활용하여 상체 자세 정보를 보완하였다.

**⑤ Personalized Seat Control**

사용자별 저장된 시트 위치와 등받이 각도를 액추에이터 제어와 연계하여 개인화된 시트 설정을 복원한다.

**⑥ End-to-End Integration**

```text
Sensing
  ↓
Data Acquisition
  ↓
AI Inference
  ↓
State Analysis
  ↓
Warning / Feedback
  ↓
Actuator Control
  ↓
Driving Report
```

센서 데이터 수집부터 AI 추론, 상태 판단, 사용자 피드백 및 물리적인 시트 제어까지 하나의 시스템으로 연결하였다.

### Final Architecture

```text
┌─────────────────────────────────────────────────────┐
│                    SEAT-ID SYSTEM                   │
├─────────────────────────────────────────────────────┤
│                                                     │
│  FSR-406 ──────┐                                    │
│                │                                    │
│  Ultrasonic ───┼──→ Arduino ──→ Raspberry Pi 5     │
│                │                    │                │
│                │                    ▼                │
│                │            ┌───────────────┐       │
│                │            │ Preprocessing │       │
│                │            └───────┬───────┘       │
│                │                    ↓                │
│                │            ┌───────────────┐       │
│                │            │   SFS + SVM   │       │
│                │            └───────┬───────┘       │
│                │                    ↓                │
│                │            State Analysis           │
│                │                    │                │
│                │       ┌────────────┼───────────┐    │
│                │       ↓            ↓           ↓    │
│                │     User        Posture      COP    │
│                │   Detection   Classification Balance│
│                │       │            │           │    │
│                │       └────────────┼───────────┘    │
│                │                    ↓                │
│                │             UI / Warning            │
│                │                    │                │
│                │                    ↓                │
│                │             Actuator Control        │
│                │                    │                │
│                │                    ▼                │
│                │              Physical Seat          │
│                │                                     │
└─────────────────────────────────────────────────────┘
```

Seat-ID는 최종적으로 **센서(Sensing) → 임베디드(Processing) → AI(Inference) → 상태판단(Analysis) → 제어(Control) → 사용자 피드백(Output)**으로 이어지는 End-to-End 스마트 시트 시스템을 구현하는 것을 목표로 한다.

---

## 18. References & Links

### GitHub Repository

Seat-ID의 전체 소스 코드와 프로젝트 자료는 아래 GitHub Repository에서 확인할 수 있다.

:contentReference[oaicite:0]{index=0}

### Project Documentation

프로젝트의 시스템 설계, 하드웨어 구성, AI 모델 및 개발 과정은 프로젝트 보고서를 통해 확인할 수 있다.

```text
Seat-ID
 │
 ├── System Architecture
 ├── Hardware Design
 ├── AI / Data Processing
 ├── Software Architecture
 ├── Real-Time System
 ├── Physical Prototype
 └── Development & Verification
```

### Main Technologies

| 분야 | 기술 |
|---|---|
| **Programming** | Python · Arduino |
| **AI / ML** | SFS · SVM · scikit-learn |
| **Embedded** | Raspberry Pi 5 · Arduino Mega · Arduino UNO |
| **Sensing** | FSR-406 · Ultrasonic Sensor |
| **Data Processing** | StandardScaler · Baseline Correction · COP |
| **Communication** | Serial Communication |
| **Actuation** | Linear Actuator · Motor Driver |
| **Mechanical** | Rack & Pinion · 3D Printing |
| **UI** | Touch Screen · Real-Time Monitoring |

---

## 19. Conclusion

Seat-ID는 기존의 단순한 운전자 모니터링을 넘어 **사용자를 이해하고, 사용자의 상태를 분석하며, 사용자에게 맞는 시트 환경을 제공하는 스마트 시트 시스템**을 구현하였다.

```text
        WHO?
         ↓
User Identification
         ↓
        HOW?
         ↓
Posture / Balance Analysis
         ↓
       STATUS?
         ↓
Warning / Feedback
         ↓
      WHAT NEXT?
         ↓
Personalized Seat Control
         ↓
      RECORD
         ↓
Driving Report
```

특히 **144개의 FSR 센서 후보군에서 SFS를 통해 16개 센서로 최적화하고, SVM 기반 AI를 Raspberry Pi 5에서 실시간으로 추론**하도록 구성하였다.

또한 FSR 기반 압력 분석만으로 끝내지 않고 **COP 기반 좌우 하중 분석과 등·목 초음파 분석을 결합**하여 운전자의 착석 상태를 다각도로 판단하도록 시스템을 확장하였다.

최종적으로 센서 데이터 수집, AI 추론, 사용자 인터페이스, 시트 액추에이터를 실제 프로토타입에 연결하여 다음과 같은 End-to-End 시스템을 구현하였다.

```text
┌─────────────────────────────────────────┐
│              SEAT-ID                    │
│                                         │
│  Sense → Identify → Analyze → Control  │
│                                         │
│  FSR / Ultrasonic                       │
│          ↓                              │
│  Arduino / Raspberry Pi 5              │
│          ↓                              │
│  SFS + SVM / COP                       │
│          ↓                              │
│  User & Posture Analysis               │
│          ↓                              │
│  Warning / Feedback                    │
│          ↓                              │
│  Personalized Seat Control              │
│          ↓                              │
│  Driving Report                         │
│                                         │
└─────────────────────────────────────────┘
```

**Seat-ID — A Smarter Seat That Understands You.**

---
