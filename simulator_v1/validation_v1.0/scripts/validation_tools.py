"""
validation_tools.py - Run the simulator for a measurement run and compare with the data.

Used by validate.py and calibrate.py. Main functions:
  build_config(run, extra)   reference config + runs.yaml overrides + extra overrides
  simulate(run, extra)       run the simulator, returns (results, cfg)
  compare(run, results, cfg) measured vs simulated sensor values at the measured minutes
  metrics(cmp)               bias / RMSE / daily maximum ... per sensor
"""
import copy
import os
import sys

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)                  # validation_v1.0
SIM = os.path.dirname(BASE)                   # simulator_v1
sys.path.insert(0, SIM)
from solardryer import psychro  # noqa: E402
from solardryer.config import load_config, set_value  # noqa: E402
from solardryer.simulate import run_simulation  # noqa: E402

REFERENCE = os.path.join(SIM, "config", "UKRIM_dryer_v1.0_default.yaml")
SENSORS = ["S1_collector", "S2_tray", "S3_tray"]
SPINUP_MIN = 60          # first hour after the measurement start is not compared


def meta():
    return yaml.safe_load(open(os.path.join(BASE, "runs.yaml"), encoding="utf-8"))


def measured(run):
    return pd.read_csv(os.path.join(BASE, "data", f"{run}_dryer.csv"), parse_dates=["time_wib"])


def build_config(run, extra=None):
    m = meta()
    info = m["runs"][run]
    cfg = load_config(REFERENCE)
    cfg["_config_dir"] = os.path.join(BASE, "configs")   # relative csv paths -> validation_v1.0/
    meas = measured(run)
    start_day = pd.Timestamp(info["start"]).normalize()
    end_h = (meas.time_wib.iloc[-1] - start_day).total_seconds() / 3600
    over = dict(m["common_overrides"])
    over.update(info.get("overrides") or {})
    over.update({
        "run.name": f"validation_{run}",
        "location.date": str(start_day.date()),
        "run.days": round((end_h + 0.25) / 24, 4),
        "weather.csv_file": f"data/{run}_weather_sim.csv",
    })
    if "setpoint_C" in meas.columns:   # setpoint changes (buttons) from the log
        sp = meas[["time_wib", "setpoint_C"]]
        ch = sp[sp.setpoint_C.diff().fillna(0) != 0]
        sched = [[round((t - start_day).total_seconds() / 3600, 3), float(v)]
                 for t, v in zip(ch.time_wib, ch.setpoint_C)]
        over["fans.control.pid.setpoint_C"] = float(sp.setpoint_C.iloc[0])
        over["fans.control.pid.setpoint_schedule"] = sched
    over.update(extra or {})
    for k, v in over.items():
        cfg = _set(cfg, k, v)
    return cfg, over


def _set(cfg, path, value):
    try:
        return set_value(cfg, path, value)
    except KeyError:              # allow new optional keys (e.g. setpoint_schedule)
        new = copy.deepcopy(cfg)
        node = new
        keys = path.split(".")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
        return new


def set_sensor(cfg, name, key, value):
    """Change one value of one sensor (sensors.list is a list, not reachable by dotted path)."""
    new = copy.deepcopy(cfg)
    for s in new["sensors"]["list"]:
        if s["name"] == name:
            s[key] = value
            return new
    raise KeyError(name)


def simulate(run, extra=None, sensor_params=None, time_step_s=None):
    cfg, _ = build_config(run, extra)
    for (name, key), v in (sensor_params or {}).items():
        cfg = set_sensor(cfg, name, key, v)
    if time_step_s:
        cfg["run"]["time_step_s"] = time_step_s
    res, summary, _ = run_simulation(cfg)
    return res, cfg


def compare(run, res, cfg, time_offset_min=0.0):
    """
    Measured and simulated sensor values side by side at every measured minute.
    time_offset_min shifts the measured clock (positive = the measurement really
    started later than the time in runs.yaml).
    """
    meas = measured(run)
    meas["time_wib"] = meas.time_wib + pd.Timedelta(minutes=time_offset_min)
    start_day = pd.Timestamp(cfg["location"]["date"])
    h_meas = (meas.time_wib - start_day).dt.total_seconds() / 3600
    out = pd.DataFrame({"time_wib": meas.time_wib, "hour": h_meas,
                        "minute": meas.minute})
    p = psychro.pressure_at_altitude(cfg["location"]["altitude_m"])
    for col in ["ghi_W_m2", "t_amb_C", "fan_speed_fraction", "airflow_m3_h", "T_air_outlet_C",
                "T_air_collector_C", "T_plate_C", "T_product_C", "fan_pwm"]:
        if col in res.columns:
            out[f"sim_{col}"] = np.interp(h_meas, res.hour, res[col])
    for s in SENSORS:
        out[f"meas_{s}_T"] = meas[f"{s}_T_C"]
        out[f"sim_{s}_T"] = np.interp(h_meas, res.hour, res[f"sensor_{s}_T_C"])
        rh_m = meas[f"{s}_RH_pct"] / 100
        out[f"meas_{s}_w"] = [psychro.humidity_ratio(t, r, p) * 1000 if r == r else np.nan
                              for t, r in zip(out[f"meas_{s}_T"], rh_m)]
        rh_s = np.interp(h_meas, res.hour, res[f"sensor_{s}_RH_pct"]) / 100
        out[f"sim_{s}_w"] = [psychro.humidity_ratio(t, r, p) * 1000
                             for t, r in zip(out[f"sim_{s}_T"], rh_s)]
    if "pwm" in meas.columns:
        out["meas_pwm"] = meas.pwm
    out["use"] = out.minute >= SPINUP_MIN
    return out


def metrics(cmp, sensors=SENSORS):
    rows = []
    c = cmp[cmp.use]
    hod = c.time_wib.dt.hour + c.time_wib.dt.minute / 60
    day = (hod >= 6) & (hod < 18)
    for s in sensors:
        e = c[f"sim_{s}_T"] - c[f"meas_{s}_T"]
        ew = c[f"sim_{s}_w"] - c[f"meas_{s}_w"]
        r = {"sensor": s,
             "bias_K": e.mean(), "rmse_K": np.sqrt((e ** 2).mean()), "mae_K": e.abs().mean(),
             "rmse_day_K": np.sqrt((e[day] ** 2).mean()), "bias_day_K": e[day].mean(),
             "bias_night_K": e[~day].mean() if (~day).any() else np.nan,
             "rmse_hourly_K": np.sqrt(((c.assign(e=e).set_index("time_wib").e
                                        .resample("1h").mean()) ** 2).mean()),
             "bias_w_g_kg": ew.mean()}
        dmax = c.groupby(c.time_wib.dt.date).agg(meas=(f"meas_{s}_T", "max"), sim=(f"sim_{s}_T", "max"))
        r["daily_max_err_K"] = "; ".join(f"{(b - a):+.1f}" for a, b in zip(dmax.meas, dmax.sim))
        rows.append(r)
    return pd.DataFrame(rows).set_index("sensor")


def plot(cmp, run, path, title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    C = ["#2a78d6", "#eb6834", "#1baf7a"]
    has_pwm = "meas_pwm" in cmp.columns
    n = 4 if has_pwm else 3
    fig, ax = plt.subplots(n, 1, figsize=(12, 3.2 * n + 1), sharex=True,
                           gridspec_kw={"height_ratios": [3, 2, 1.4] + ([1.4] if has_pwm else [])})
    t = cmp.time_wib
    for i, s in enumerate(SENSORS):
        ax[0].plot(t, cmp[f"meas_{s}_T"], color=C[i], lw=1.4, label=f"{s} measured")
        ax[0].plot(t, cmp[f"sim_{s}_T"], color=C[i], lw=1.4, ls="--", label=f"{s} simulated")
        ax[1].plot(t, cmp[f"sim_{s}_T"] - cmp[f"meas_{s}_T"], color=C[i], lw=1.2, label=s)
    ax[0].plot(t, cmp["sim_t_amb_C"], color="#8a8985", lw=1.2, label="outside air (reanalysis)")
    ax[0].set_ylabel("Temperature [°C]"); ax[0].legend(fontsize=8, ncol=4, frameon=False)
    ax[0].set_title(title or run, loc="left")
    ax[1].axhline(0, color="#c3c2b7"); ax[1].set_ylabel("Sim - meas [K]")
    ax[1].legend(fontsize=8, ncol=3, frameon=False)
    ax[2].plot(t, cmp["sim_ghi_W_m2"], color="#eda100", lw=1.2)
    ax[2].set_ylabel("GHI (PV) [W/m²]")
    if has_pwm:
        ax[3].plot(t, cmp["meas_pwm"], color="#0b0b0b", lw=1.2, label="measured PWM")
        ax[3].plot(t, cmp["sim_fan_pwm"], color=C[0], lw=1.2, ls="--", label="simulated PWM")
        ax[3].set_ylabel("PWM"); ax[3].legend(fontsize=8, frameon=False)
    for a in ax:
        a.grid(color="#e6e5e1")
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=110); plt.close(fig)
