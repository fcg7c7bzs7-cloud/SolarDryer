"""
calibrate.py - Fit uncertain model parameters to measurement runs.

    python scripts/calibrate.py joint_v1

A calibration set (CAL_SETS below) lists
  * the runs and the part of each run that is used for the fit (window)
  * the parameters with start value and allowed range; they are SHARED by all runs,
    except the clock offsets which belong to one run.
The fit minimises the difference between measured and simulated sensor temperatures
(all three sensors, 1-min data, first hour of each run skipped), every run weighted
equally, with scipy's bounded least squares. Fit time step 60 s; final check 30 s.

Results: results/calibration_<SET>.yaml (values, rough uncertainty, strongly correlated
pairs, metrics per run inside the fit window) and a log of every evaluation.
"""
import argparse
import json
import os
import time
import warnings

import numpy as np
import pandas as pd
import yaml
from scipy.optimize import least_squares

from validation_tools import BASE, SENSORS, compare, metrics, simulate

warnings.filterwarnings("ignore")

# parameter: (kind, target, start, low, high)
#   "cfg"    -> dotted config path          "sensor" -> ([sensor names], key)
#   "offset" -> clock offset of run <target> in minutes (+ = measurement started later)
CAL_SETS = {
    "LEN011": {
        "runs": {"LEN011": None},
        "fixed": {"trays.air_contact_factor": 10.0},
        "params": {
            "cover.solar_transmittance": ("cfg", "cover.solar_transmittance", 0.85, 0.55, 0.92),
            "cover.ir_transmittance": ("cfg", "cover.ir_transmittance", 0.30, 0.0, 0.85),
            "trays.floor_absorptance": ("cfg", "trays.floor_absorptance", 0.50, 0.1, 0.95),
            "leakage_kg_s": ("cfg", "heat_transfer.min_air_mass_flow_kg_s", 0.002, 0.0005, 0.03),
            "sun_exposure_trays": ("sensor", (["S2_tray", "S3_tray"], "sun_exposure_factor"), 1.0, 0.0, 1.0),
            "sun_exposure_S1": ("sensor", (["S1_collector"], "sun_exposure_factor"), 0.4, 0.0, 1.0),
            "offset_LEN011_min": ("offset", "LEN011", 0.0, -60.0, 60.0),
        },
    },
    # LEN011 (no fans) + LEN005 until 9 Oct 00:00 (PID, setpoint 50). 9 Oct is kept for validation.
    "joint_v1": {
        "runs": {"LEN011": None, "LEN005": "2026-10-09 00:00"},
        "fixed": {"trays.air_contact_factor": 10.0},
        "params": {
            "cover.solar_transmittance": ("cfg", "cover.solar_transmittance", 0.75, 0.55, 0.92),
            "cover.ir_transmittance": ("cfg", "cover.ir_transmittance", 0.45, 0.0, 0.85),
            "trays.floor_absorptance": ("cfg", "trays.floor_absorptance", 0.6, 0.1, 0.95),
            "leakage_kg_s": ("cfg", "heat_transfer.min_air_mass_flow_kg_s", 0.01, 0.0005, 0.03),
            "fan_free_airflow_m3_s": ("cfg", "fans.reference_fan.free_airflow_m3_s", 0.0236, 0.008, 0.045),
            "pwm_speed_at_stop_below": ("cfg", "fans.pwm.speed_at_stop_below", 0.30, 0.1, 0.7),
            "sun_exposure_trays": ("sensor", (["S2_tray", "S3_tray"], "sun_exposure_factor"), 0.9, 0.0, 1.0),
            "sun_exposure_S1": ("sensor", (["S1_collector"], "sun_exposure_factor"), 0.6, 0.0, 1.0),
            "S1_local_air_mix": ("sensor", (["S1_collector"], "local_air_mix"), 1.0, 0.0, 1.0),
            "offset_LEN011_min": ("offset", "LEN011", 20.0, -60.0, 60.0),
            "offset_LEN005_min": ("offset", "LEN005", 0.0, -60.0, 60.0),
        },
    },
    # As joint_v1, but the floor under the trays is bare aluminium (absorptance fixed at 0.2,
    # Felix 2026-11-06); starts from the best point of the interrupted joint_v1 fit.
    "joint_v2": {
        "runs": {"LEN011": None, "LEN005": "2026-10-09 00:00"},
        "fixed": {"trays.air_contact_factor": 10.0, "trays.floor_absorptance": 0.2},
        "params": {
            "cover.solar_transmittance": ("cfg", "cover.solar_transmittance", 0.786, 0.55, 0.92),
            "cover.ir_transmittance": ("cfg", "cover.ir_transmittance", 0.551, 0.0, 0.85),
            "leakage_kg_s": ("cfg", "heat_transfer.min_air_mass_flow_kg_s", 0.0038, 0.0005, 0.03),
            "fan_free_airflow_m3_s": ("cfg", "fans.reference_fan.free_airflow_m3_s", 0.0191, 0.008, 0.045),
            "pwm_speed_at_stop_below": ("cfg", "fans.pwm.speed_at_stop_below", 0.566, 0.1, 0.7),
            "sun_exposure_trays": ("sensor", (["S2_tray", "S3_tray"], "sun_exposure_factor"), 0.63, 0.0, 1.0),
            "sun_exposure_S1": ("sensor", (["S1_collector"], "sun_exposure_factor"), 0.27, 0.0, 1.0),
            "S1_local_air_mix": ("sensor", (["S1_collector"], "local_air_mix"), 0.2, 0.0, 1.0),
            "offset_LEN011_min": ("offset", "LEN011", 23.1, -60.0, 60.0),
            "offset_LEN005_min": ("offset", "LEN005", -14.6, -60.0, 60.0),
        },
    },
}


def unpack(cal, x):
    extra, sens, offs = dict(cal.get("fixed", {})), {}, {}
    for (name, (kind, target, *_)), v in zip(cal["params"].items(), x):
        if kind == "cfg":
            extra[target] = float(v)
        elif kind == "sensor":
            for s in target[0]:
                sens[(s, target[1])] = float(v)
        else:
            offs[target] = float(v)
    return extra, sens, offs


def in_window(c, until, offset_min):
    """Fit window, defined on the ORIGINAL clock so that it does not move with the offset."""
    if not until:
        return c.use
    return c.use & (c.time_wib - pd.Timedelta(minutes=offset_min) < pd.Timestamp(until))


def evaluate(cal, x, time_step_s=60):
    extra, sens, offs = unpack(cal, x)
    out = {}
    for run, until in cal["runs"].items():
        res, cfg = simulate(run, extra, sens, time_step_s=time_step_s)
        c = compare(run, res, cfg, offs.get(run, 0.0))
        out[run] = c[in_window(c, until, offs.get(run, 0.0))]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("set")
    ap.add_argument("--max-evals", type=int, default=400)
    a = ap.parse_args()
    cal = CAL_SETS[a.set]
    spec = cal["params"]
    names = list(spec)
    x0 = np.array([spec[n][2] for n in names])
    lo = np.array([spec[n][3] for n in names])
    hi = np.array([spec[n][4] for n in names])
    os.makedirs(os.path.join(BASE, "results"), exist_ok=True)
    log = open(os.path.join(BASE, "results", f"calibration_{a.set}.log"), "w")
    n_eval = [0]

    def resid(x):
        parts = []
        for run, c in evaluate(cal, x).items():
            r = np.concatenate([(c[f"sim_{s}_T"] - c[f"meas_{s}_T"]).values for s in SENSORS])
            n = len(r)
            r = np.nan_to_num(r)                       # fixed length (missing values count 0)
            parts.append(r / np.sqrt(n))                # every run counts equally
        r = np.concatenate(parts)
        n_eval[0] += 1
        log.write(f"{n_eval[0]:4d} rms {np.sqrt(np.sum(r**2) / len(parts)):6.3f}  " +
                  " ".join(f"{n}={v:.4g}" for n, v in zip(names, x)) + "\n"); log.flush()
        return r

    t0 = time.time()
    fit = least_squares(resid, x0, bounds=(lo, hi), diff_step=0.02, x_scale=(hi - lo),
                        max_nfev=a.max_evals)
    J = fit.jac
    try:
        n_res = len(fit.fun)
        cov = np.linalg.pinv(J.T @ J) * (2 * fit.cost) / max(1, n_res - len(x0)) * n_res / len(cal["runs"])
        sd = np.sqrt(np.abs(np.diag(cov)))
        corr = cov / np.outer(sd, sd)
    except np.linalg.LinAlgError:
        sd = np.full(len(x0), np.nan); corr = np.full((len(x0), len(x0)), np.nan)
    final = evaluate(cal, fit.x, time_step_s=30)
    out = {
        "set": a.set, "runs": cal["runs"], "evaluations": int(n_eval[0]),
        "seconds": round(time.time() - t0), "status": fit.message,
        "parameters": {n: {"value": round(float(v), 4), "sd_rough": round(float(s), 4),
                           "start": float(spec[n][2]), "range": [float(spec[n][3]), float(spec[n][4])],
                           "at_bound": bool(np.isclose(v, spec[n][3], atol=1e-3 * (spec[n][4] - spec[n][3]))
                                            or np.isclose(v, spec[n][4], atol=1e-3 * (spec[n][4] - spec[n][3])))}
                       for n, v, s in zip(names, fit.x, sd)},
        "correlations_above_0.7": {f"{names[i]} ~ {names[j]}": round(float(corr[i, j]), 2)
                                   for i in range(len(names)) for j in range(i + 1, len(names))
                                   if abs(corr[i, j]) > 0.7},
        "fixed": cal.get("fixed", {}),
        "metrics_in_fit_window": {run: json.loads(metrics(c).round(2).to_json(orient="index"))
                                  for run, c in final.items()},
    }
    yaml.safe_dump(out, open(os.path.join(BASE, "results", f"calibration_{a.set}.yaml"), "w"), sort_keys=False)
    print(yaml.safe_dump(out, sort_keys=False))


if __name__ == "__main__":
    main()
