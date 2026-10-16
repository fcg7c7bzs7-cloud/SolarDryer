"""
run_sweep.py - Run a parameter study defined in a sweep YAML file.

    python run_sweep.py --sweep config/sweep_example.yaml

Results in results/sweep_<name>/:
    sweep_results.csv     one row per design variant, all summary numbers
    sweep_<metric>.png    one figure per metric listed in the sweep file
"""

import argparse
import os

import yaml

from solardryer import plots
from solardryer.config import load_config
from solardryer.sweep import run_sweep


def main():
    parser = argparse.ArgumentParser(description="Run a parameter sweep.")
    parser.add_argument("--sweep", default="config/sweep_example_copy.yaml")
    args = parser.parse_args()

    with open(args.sweep, "r", encoding="utf-8") as f:
        sweep = yaml.safe_load(f)
    base_path = os.path.join(os.path.dirname(os.path.abspath(args.sweep)), sweep["base_config"])
    base_cfg = load_config(base_path)

    df = run_sweep(base_cfg, sweep["parameters"])

    out_dir = os.path.join(base_cfg["run"]["output_dir"], f"sweep_{sweep['name']}")
    os.makedirs(out_dir, exist_ok=True)
    df.to_csv(os.path.join(out_dir, "sweep_results.csv"), index=False, float_format="%.4g")

    params = list(sweep["parameters"].keys())
    for metric in sweep.get("metrics_to_plot", []):
        plots.sweep_plot(df, params, metric, os.path.join(out_dir, f"sweep_{metric}.png"))

    cols = params + sweep.get("metrics_to_plot", [])
    print()
    print(df[cols].round(2).to_string(index=False))
    print(f"\nResults saved in: {out_dir}")


if __name__ == "__main__":
    main()
