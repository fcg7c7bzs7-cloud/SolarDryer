"""
weather.py - Outside conditions for every time step.

Two options (chosen in the YAML file, weather.source):
  * "synthetic": a typical day is generated from a few numbers
                 (sky clearness, min/max temperature, dew point, wind).
  * "csv":       measured data is read from a CSV file and interpolated
                 to the time steps of the simulation.

Both return a pandas DataFrame with one row per time step and columns:
  hour      local time in decimal hours since the start date 00:00
  ghi       global horizontal irradiance [W/m2]
  dhi       diffuse horizontal irradiance [W/m2] (NaN = estimate it)
  t_amb     outside temperature [degC]
  rh_amb    outside relative humidity [0..1]
  wind      wind speed [m/s]
"""

import math
import os

import numpy as np
import pandas as pd

from . import psychro, solar


def _daily_temperature(hour_of_day, t_min, t_max, h_min, h_max):
    """
    Smooth daily temperature curve: rises from t_min (at h_min) to t_max
    (at h_max) along half a cosine wave, then falls back to t_min at h_min of
    the next day.
    """
    h = hour_of_day % 24.0
    rise = h_max - h_min
    if h_min <= h <= h_max:
        x = (h - h_min) / rise
    else:
        fall = 24.0 - rise
        x = 1.0 - ((h - h_max) % 24.0) / fall
    return t_min + (t_max - t_min) * (1 - math.cos(math.pi * x)) / 2


def synthetic_weather(cfg, hours):
    s = cfg["weather"]["synthetic"]
    loc = cfg["location"]
    day0 = solar.day_of_year(loc["date"])
    p = psychro.pressure_at_altitude(loc["altitude_m"])
    w_amb = psychro.humidity_ratio_from_dew_point(s["dew_point_C"], p)

    rows = []
    for h in hours:
        day = day0 + int(h // 24)
        zen, _ = solar.sun_position(day, h % 24, loc["latitude_deg"], loc["longitude_deg"],
                                    loc["utc_offset_h"])
        ghi = s["sky_clearness"] * solar.clear_sky_ghi(zen)
        t = _daily_temperature(h, s["t_min_C"], s["t_max_C"], s["hour_t_min"], s["hour_t_max"])
        rh = min(psychro.relative_humidity(t, w_amb, p), 1.0)
        rows.append((h, ghi, np.nan, t, rh, s["wind_speed_m_s"]))
    return pd.DataFrame(rows, columns=["hour", "ghi", "dhi", "t_amb", "rh_amb", "wind"])


def csv_weather(cfg, hours):
    path = cfg["weather"]["csv_file"]
    if not os.path.isabs(path):
        # relative paths are relative to the simulator_v1 folder (one up from config/)
        base = os.path.dirname(cfg.get("_config_dir", "."))
        path = os.path.join(base, path)
    df = pd.read_csv(path)
    needed = ["hour", "ghi_W_m2", "t_amb_C", "rh_percent", "wind_m_s"]
    missing = [c for c in needed if c not in df.columns]
    if missing:
        raise ValueError(f"Weather CSV {path} is missing columns: {missing}")
    df = df.sort_values("hour")
    if hours[0] < df["hour"].iloc[0] or hours[-1] > df["hour"].iloc[-1]:
        print(f"WARNING: weather CSV covers hours {df['hour'].iloc[0]}..{df['hour'].iloc[-1]}, "
              f"simulation needs {hours[0]}..{hours[-1]:.2f}. Values are held constant outside.")
    out = pd.DataFrame({"hour": hours})
    out["ghi"] = np.interp(hours, df["hour"], df["ghi_W_m2"].clip(lower=0))
    out["dhi"] = (np.interp(hours, df["hour"], df["dhi_W_m2"]) if "dhi_W_m2" in df.columns
                  else np.nan)
    out["t_amb"] = np.interp(hours, df["hour"], df["t_amb_C"])
    out["rh_amb"] = np.interp(hours, df["hour"], df["rh_percent"]) / 100.0
    out["wind"] = np.interp(hours, df["hour"], df["wind_m_s"])
    return out


def get_weather(cfg, hours):
    src = cfg["weather"]["source"]
    if src == "synthetic":
        return synthetic_weather(cfg, hours)
    if src == "csv":
        return csv_weather(cfg, hours)
    raise ValueError(f"weather.source must be 'synthetic' or 'csv', not '{src}'")
