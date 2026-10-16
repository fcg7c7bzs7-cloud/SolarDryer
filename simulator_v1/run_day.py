"""
run_day.py - Simulate the dryer for one (or more) days and save the results.

How to run (in a terminal, inside the simulator_v1 folder):

    python run_day.py                                   # uses config/default_dryer.yaml
    python run_day.py --config config/my_design.yaml    # your own parameter file

What you get in results/<run name>/:
    timeseries.csv     every quantity at every time step (open with Excel)
    summary.txt        the key numbers + the geometry
    day_overview.png   temperatures, humidity, sunlight, airflow over time
    energy_split.png   where the solar energy goes
    sensors.png        what the virtual DHT21 sensors show vs. the true air
"""

import argparse
import os

from solardryer import plots
from solardryer.config import load_config
from solardryer.geometry import describe
from solardryer.simulate import format_summary, run_simulation


def main():
    parser = argparse.ArgumentParser(description="Simulate the solar dryer for one day.")
    parser.add_argument("--config", default="config/default_dryer_copy.yaml",
                        help="Path to the YAML parameter file")
    args = parser.parse_args()

    cfg = load_config(args.config)
    print(f"Running '{cfg['run']['name']}' with {args.config} ...")
    results, summary, geom = run_simulation(cfg)

    out_dir = os.path.join(cfg["run"]["output_dir"], cfg["run"]["name"])
    os.makedirs(out_dir, exist_ok=True)

    results.to_csv(os.path.join(out_dir, "timeseries.csv"), index=False, float_format="%.4g")

    text = describe(geom) + "\n\n" + format_summary(summary) + "\n"
    with open(os.path.join(out_dir, "summary.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)

    plots.day_overview(results, cfg, os.path.join(out_dir, "day_overview.png"))
    if (cfg.get("sensors") or {}).get("enabled"):
        plots.sensors_plot(results, cfg, os.path.join(out_dir, "sensors.png"))

    dt = cfg["run"]["time_step_s"]
    days = cfg["run"]["days"]

    def kwh(col):
        return results[col].sum() * dt / 3.6e6 / days

    totals = {
        "Sun absorbed inside (input)": kwh("q_sun_absorbed_W"),
        "Heat carried out by the air (useful)": kwh("q_useful_air_W"),
        "Evaporating water (useful)": kwh("q_evaporation_W"),
        "Lost through plastic cover": kwh("q_loss_cover_W"),
        "Lost through black floor to below": kwh("q_loss_floor_W"),
        "Radiated to the sky through cover": kwh("q_loss_radiation_sky_W"),
    }
    plots.energy_split(totals, os.path.join(out_dir, "energy_split.png"))
    print(f"Results saved in: {out_dir}")


if __name__ == "__main__":
    main()
