           
               
                
                 
                  

                                                           
                         
                                
                                                           

from __future__ import annotations

import csv
import os
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import serial
from serial import SerialException
from serial.tools import list_ports

                                                           
                       
                                                           

BASE_DIR = Path(__file__).resolve().parent

OUTPUT_DIR = BASE_DIR / "per_user_data"

def get_output_path(user_id: int) -> Path:

    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    return OUTPUT_DIR / f"posture_user{user_id}.csv"

BASELINE_PATH = BASE_DIR / "selected_baseline.npy"

POSITION_PATH = BASE_DIR / "selected_sensor_positions.csv"

                                                           
                      
                                                           

PORT = "COM9"                                   
BAUDRATE = 115200
SERIAL_TIMEOUT = 1.0

                                                           
                      
                                                           

NUM_SENSORS = 16

ADC_MIN = 0
ADC_MAX = 1023

                                                           
                       
                                                           

                                         
                                                     
                                   
SAMPLES_PER_TRIAL = 30
TRIALS_PER_POSTURE = 5
SAMPLES_PER_POSTURE = SAMPLES_PER_TRIAL * TRIALS_PER_POSTURE

POSTURES = [

    "normal",

    "left_shift",

    "right_shift",

    "forward_lean",

    "backward_lean",

]

                                                           
                           
                                                           

                                                         
                                                   
                                             
                 
EDGE_BOTTOM = 0
EDGE_TOP = 15

EDGE_THRESHOLD = 30.0

def load_baseline():

    if not BASELINE_PATH.exists():
        raise FileNotFoundError(
            f"Baseline file not found:\n{BASELINE_PATH}"
        )

    baseline = np.load(BASELINE_PATH)

    baseline = np.asarray(
        baseline,
        dtype=np.float32,
    ).reshape(-1)

    if baseline.size != NUM_SENSORS:
        raise ValueError(
            f"Baseline has {baseline.size} values "
            f"(expected {NUM_SENSORS})"
        )

    return baseline

def find_arduino_port():

    ports = list(list_ports.comports())

    preferred = [

        port.device

        for port in ports

        if port.device.startswith("/dev/ttyACM")
        or port.device.startswith("/dev/ttyUSB")

    ]

    if preferred:
        return preferred[0]

    detected = [

        port.device

        for port in ports

    ]

    raise RuntimeError(

        "Arduino not found.\n"

        f"Detected ports : {detected}"

    )

                                                           
                
                                                           

def flush_and_resync(
    connection: serial.Serial,
):

    connection.reset_input_buffer()

                                               
                                      
                                           
                        
    connection.readline()


def open_serial_port():

    serial_port = (

        PORT

        if PORT is not None

        else find_arduino_port()

    )

    try:

        connection = serial.Serial(

            port=serial_port,

            baudrate=BAUDRATE,

            timeout=SERIAL_TIMEOUT,

        )

    except SerialException as exc:

        raise RuntimeError(

            f"Failed to open {serial_port}"

        ) from exc

    time.sleep(2)

    flush_and_resync(connection)

    print("=" * 50)
    print("Arduino Connected")
    print("=" * 50)
    print(f"Port      : {serial_port}")
    print(f"Baudrate  : {BAUDRATE}")
    print("=" * 50)

    return connection

                                                           
             
                                                           

def read_sensor(
    connection: serial.Serial,
) -> np.ndarray:

    while True:

        raw_line = connection.readline()

        if not raw_line:
            continue

        line = raw_line.decode(
            "ascii",
            errors="ignore",
        ).strip()

        if not line:
            continue

        try:

            sensor = np.array(
                line.split(","),
                dtype=np.float32,
            )

        except ValueError:

            print(
                f"[SKIP] Malformed line : {line}"
            )

            continue

        if sensor.size != NUM_SENSORS:

            print(
                f"[SKIP] Invalid sensor count : {line}"
            )

            continue

        if not np.all(np.isfinite(sensor)):

            print(
                "[SKIP] Invalid numeric value."
            )

            continue

        if (
            np.any(sensor < ADC_MIN)
            or np.any(sensor > ADC_MAX)
        ):

            print(
                "[SKIP] ADC value out of range."
            )

            continue

        return sensor


                                                           
                     
                                                           

def baseline_correction(

    sensor: np.ndarray,

    baseline: np.ndarray,

):

    corrected = (

        sensor.astype(
            np.float32,
            copy=False,
        )

        - baseline

    )

    corrected = np.clip(
        corrected,
        0,
        None,
    )

    return corrected


                                                           
                   
                                                           

def check_edge_sensor(

    corrected_sensor: np.ndarray,

):

    bottom = corrected_sensor[EDGE_BOTTOM]

    top = corrected_sensor[EDGE_TOP]

    return (

        bottom <= EDGE_THRESHOLD

        and

        top <= EDGE_THRESHOLD

    )


                                                           
                
                                                           

def select_posture():

    print("\n")

    print("=" * 50)

    print("Select Posture")

    print("=" * 50)

    for index, posture in enumerate(
        POSTURES,
        start=1,
    ):
        print(f"{index}. {posture}")

    print("=" * 50)

    while True:

        try:

            number = int(
                input("Select : ")
            )

            if 1 <= number <= len(POSTURES):

                return POSTURES[number - 1]

        except ValueError:
            pass

        print("Invalid selection.\n")


                                                           
           
                                                           

def countdown():

    print()

    for sec in [3, 2, 1]:

        print(f"{sec}...")

        time.sleep(1)

    print()

    print("Collecting started.\n")


                                                           
            
                                                           

def create_database(output_path: Path):

    if output_path.exists():

        return

    columns = [

        "sample_id",

        "user_id",

        "posture",

        "trial_id",

        "timestamp",

    ]

    columns.extend(

        [

            f"sensor_{i+1}"

            for i in range(NUM_SENSORS)

        ]

    )

    dataframe = pd.DataFrame(
        columns=columns
    )

    dataframe.to_csv(
        output_path,
        index=False,
    )

    print("Database created.")


                                                           
            
                                                           

def save_sample(

    output_path: Path,

    sample_id,

    user_id,

    posture,

    trial_id,

    corrected_sensor,

):

    row = {

        "sample_id": sample_id,

        "user_id": user_id,

        "posture": posture,

        "trial_id": trial_id,

        "timestamp": datetime.now().isoformat(timespec="seconds"),

    }

    for index in range(NUM_SENSORS):

        row[
            f"sensor_{index+1}"
        ] = round(
            float(corrected_sensor[index]),
            2,
        )

    dataframe = pd.DataFrame([row])

    dataframe.to_csv(

        output_path,

        mode="a",

        header=False,

        index=False,

    )

                                                           
                 
                                                           

def collect_samples() -> Path:

    print("=" * 60)

    user_id = int(
        input("User ID : ")
    )

    output_path = get_output_path(user_id)

    create_database(output_path)

    baseline = load_baseline()

    connection = open_serial_port()

                    
    if output_path.exists():

        database = pd.read_csv(output_path)

        if len(database) == 0:
            sample_id = 1
        else:
            sample_id = int(database["sample_id"].max()) + 1

    else:
        sample_id = 1

    print("\nDataset Collection Started.\n")

    try:

        while True:

            posture = select_posture()

            print(f"\nSelected Posture : {posture}")

            for trial in range(1, TRIALS_PER_POSTURE + 1):

                print("\n" + "-" * 60)

                print(f"Trial {trial}/{TRIALS_PER_POSTURE}")

                print("-" * 60)

                input(
                    "Stand up, then sit back down into "
                    f"'{posture}' and press Enter..."
                )

                countdown()

                                                                  
                                                
                flush_and_resync(connection)

                collected = 0

                while collected < SAMPLES_PER_TRIAL:

                    raw_sensor = read_sensor(
                        connection
                    )

                    corrected_sensor = baseline_correction(
                        raw_sensor,
                        baseline,
                    )

                                   
                    if not check_edge_sensor(
                        corrected_sensor
                    ):

                        print(
                            "[SKIP] Edge sensor activated."
                        )

                        continue

                    save_sample(

                        output_path=output_path,

                        sample_id=sample_id,

                        user_id=user_id,

                        posture=posture,

                        trial_id=trial,

                        corrected_sensor=corrected_sensor,

                    )

                    collected += 1

                    print(

                        f"\rCollected : "

                        f"{collected}/{SAMPLES_PER_TRIAL} "

                        f"(trial {trial}/{TRIALS_PER_POSTURE})",

                        end="",

                        flush=True,

                    )

                    sample_id += 1

                print()

            print("\n")

            print("=" * 60)

            print("Collection Complete!")

            print("=" * 60)

            print()

            print(f"User {user_id} - Output File : {output_path.name}")
            print()
            print("1. Another posture (same user)")
            print("2. Finish")

            while True:

                choice = input("Select : ").strip()

                if choice in ("1", "2"):
                    break

                print("Invalid selection.\n")

            if choice == "2":
                break

    except KeyboardInterrupt:

        print("\nInterrupted.")

    finally:

        if connection.is_open:
            connection.close()

        print("Serial closed.")

    return output_path

                                                           
      
                                                           

def print_program_info():

    print("=" * 60)
    print("        FSR Posture Dataset Collection")
    print("=" * 60)
    print(f"Output Dir  : {OUTPUT_DIR}")
    print(f"Samples     : {SAMPLES_PER_POSTURE} / posture "
          f"({TRIALS_PER_POSTURE} trials x {SAMPLES_PER_TRIAL})")
    print(f"Sensors     : {NUM_SENSORS}")
    print("=" * 60)


def main():

    print_program_info()

    output_path = collect_samples()

    print("\n")

    print("=" * 60)
    print("Dataset collection finished.")
    print("=" * 60)

    if output_path.exists():

        database = pd.read_csv(output_path)

        print(f"Saved Samples : {len(database)}")

        print(f"Saved File    : {output_path}")

        print("=" * 60)


if __name__ == "__main__":

    main()

