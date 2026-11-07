"""
validate.py - Simulate a measurement run and compare with the data.

    python scripts/validate.py LEN011                 # reference config only
    python scripts/validate.py LEN011 --calibrated    # + values in calibration.yaml

Writes results/<RUN>[_calibrated]/: comparison.csv, metrics.csv, comparison.png and the
full config that was used (config_used.yaml).
"""
import argparse
import os

import yaml

from validation_tools import BASE, build_config, compare, metrics, plot, simulate


def load_calibration():
    p = os.path.join(BASE, "calibration.yaml")
    if not os.path.exists(p):
        return {}, {}, {}
    c = yaml.safe_load(open(p, encoding="utf-8")) or {}
    sens = {(k.split(".")[0], k.split(".")[1]): v for k, v in (c.get("sensors") or {}).items()}
    return c.get("parameters") or {}, sens, c.get("clock_offsets_min") or {}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("run")
    ap.add_argument("--calibrated", action="store_true")
    a = ap.parse_args()
    extra, sens, offs = load_calibration() if a.calibrated else ({}, {}, {})
    res, cfg = simulate(a.run, extra, sens)
    cmp = compare(a.run, res, cfg, offs.get(a.run, 0.0))   # clock offset found by the fit
    met = metrics(cmp)
    name = a.run + ("_calibrated" if a.calibrated else "")
    out = os.path.join(BASE, "results", name)
    os.makedirs(out, exist_ok=True)
    cmp.to_csv(os.path.join(out, "comparison.csv"), index=False, float_format="%.3f")
    met.to_csv(os.path.join(out, "metrics.csv"), float_format="%.2f")
    cfg_clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    yaml.safe_dump(cfg_clean, open(os.path.join(out, "config_used.yaml"), "w"), sort_keys=False)
    plot(cmp, a.run, os.path.join(out, "comparison.png"), f"{name}: measured vs simulated sensors")
    print(met.round(2).to_string())


if __name__ == "__main__":
    main()
