"""
prepare_dryer_data.py - Clean the dryer logs (raw/dryer/*.csv) -> data/<run>_dryer.csv

What it does (the raw files are not changed):
  * adds the clock time (WIB) from the start time in runs.yaml + the minute column
  * renames DHT1..DHT4 to the sensor names used in the simulator (runs.yaml: sensor_map)
  * marks invalid values: missing (NaN) and saturated humidity (>= rh_invalid_above_pct)
  * keeps PWM and setpoint only where they mean something (run with fans: pid)

Run from the validation_v1.0 folder:   python scripts/prepare_dryer_data.py
"""
import os

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)


def main():
    meta = yaml.safe_load(open(os.path.join(BASE, "runs.yaml"), encoding="utf-8"))
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    for run, info in meta["runs"].items():
        raw = pd.read_csv(os.path.join(BASE, info["file"]), skipinitialspace=True,
                          na_values=["NAN", "nan", "NaN"])
        start = pd.Timestamp(info["start"])
        out = pd.DataFrame({
            "time_wib": start + pd.to_timedelta(raw["Time_min"], unit="min"),
            "minute": raw["Time_min"],
        })
        for i in range(1, 5):
            name = meta["sensor_map"][f"DHT{i}"]
            t = raw[f"Temp_DHT{i}_C"]
            rh = raw[f"Hum_DHT{i}_pct"]
            if t.isna().all():
                continue  # sensor not connected
            out[f"{name}_T_C"] = t
            out[f"{name}_RH_pct"] = rh.where(rh < meta["rh_invalid_above_pct"])
        if info["fans"] == "pid":
            out["pwm"] = raw["FanSpeed_PWM"]
            out["setpoint_C"] = raw["TargetTemp_C"]
        path = os.path.join(BASE, "data", f"{run}_dryer.csv")
        out.to_csv(path, index=False, float_format="%.2f", date_format="%Y-%m-%d %H:%M")
        n_rh = sum(out[c].isna().sum() for c in out.columns if c.endswith("_RH_pct"))
        print(f"{run}: {len(out)} rows, {out.time_wib.iloc[0]} .. {out.time_wib.iloc[-1]}, "
              f"{n_rh} humidity values marked invalid -> {os.path.relpath(path, BASE)}")


if __name__ == "__main__":
    main()
