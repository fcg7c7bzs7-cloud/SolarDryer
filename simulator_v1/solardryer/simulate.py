"""
simulate.py - Runs the dryer model over one or more days.

Usage from Python:
    from solardryer.config import load_config
    from solardryer.simulate import run_simulation
    cfg = load_config("config/default_dryer.yaml")
    results, summary, geom = run_simulation(cfg)

'results' is a pandas DataFrame with one row per time step (all temperatures,
airflow, humidity, heat flows). 'summary' is a dictionary with the key numbers
(maximum temperatures, average airflow, water removed, ...).
"""

import numpy as np

from . import geometry, sensors, thermal, weather


def evaporation_targets(cfg, wx, dt):
    """Desired evaporation rate [kg/s] for every time step."""
    e = cfg["evaporation"]
    daily = e["daily_water_removal_kg"]
    n = len(wx)
    if daily <= 0:
        return np.zeros(n)
    if e["profile"] == "constant":
        return np.full(n, daily / 86400.0)
    if e["profile"] == "sun":
        rates = np.zeros(n)
        day_index = (wx["hour"].values // 24).astype(int)
        for d in np.unique(day_index):
            mask = day_index == d
            energy = wx["ghi"].values[mask].sum() * dt  # J/m2 on that day
            if energy > 0:
                rates[mask] = daily * wx["ghi"].values[mask] / energy
        return rates
    raise ValueError("evaporation.profile must be 'sun' or 'constant'")


def run_simulation(cfg, verbose=False):
    geom = geometry.build_geometry(cfg)
    model = thermal.DryerModel(cfg, geom)

    dt = float(cfg["run"]["time_step_s"])
    n_steps = int(round(cfg["run"]["days"] * 86400 / dt))
    hours = np.arange(n_steps + 1) * dt / 3600.0
    wx = weather.get_weather(cfg, hours)
    evap = evaporation_targets(cfg, wx, dt)

    # Start: everything at outside temperature
    t0 = float(wx["t_amb"].iloc[0])
    state = {"T_plate": t0, "T_prod": t0, "T_air1": t0, "T_air2": t0}

    # Virtual temperature/humidity sensors (see sensors.py and the YAML section "sensors")
    sensor_model = sensors.SensorModel(cfg, geom, model.p)
    sensor_temps = sensor_model.initial_state(t0)

    rows = []
    for i in range(n_steps + 1):
        w = wx.iloc[i]
        wxd = {"ghi": float(w["ghi"]), "dhi": float(w["dhi"]), "t_amb": float(w["t_amb"]),
               "rh_amb": float(w["rh_amb"]), "wind": float(w["wind"])}
        state, out = model.step(state, wxd, float(w["hour"]), dt, float(evap[i]))
        if sensor_model.enabled:
            sensor_temps, sensor_out = sensor_model.step(sensor_temps, out, dt)
            out.update(sensor_out)
        rows.append(out)
        if verbose and i % int(3600 / dt) == 0:
            print(f"  {out['hour']:5.1f} h  T_out = {out['T_air_outlet_C']:5.1f} degC")

    import pandas as pd
    results = pd.DataFrame(rows)
    summary = summarize(cfg, results, dt)
    return results, summary, geom


def summarize(cfg, r, dt):
    """Key numbers of a simulation run."""
    ev = cfg["evaluation"]
    hod = r["hour"] % 24
    day = (hod >= ev["daytime_start_hour"]) & (hod <= ev["daytime_end_hour"])
    days = cfg["run"]["days"]
    limit = ev["product_max_temperature_C"]
    fan_on_h = (r["fan_speed_fraction"] > 0).sum() * dt / 3600

    sun_absorbed = r["q_sun_absorbed_W"].sum() * dt
    s = {
        "T_outlet_max_C": r["T_air_outlet_C"].max(),
        "T_outlet_daytime_mean_C": r.loc[day, "T_air_outlet_C"].mean(),
        "T_rise_daytime_mean_K": (r.loc[day, "T_air_outlet_C"] - r.loc[day, "t_amb_C"]).mean(),
        "T_collector_air_max_C": r["T_air_collector_C"].max(),
        "T_plate_max_C": r["T_plate_C"].max(),
        "T_product_max_C": r["T_product_C"].max(),
        "hours_product_above_limit": (r["T_product_C"] > limit).sum() * dt / 3600,
        "airflow_daytime_mean_m3_h": r.loc[day, "airflow_m3_h"].mean(),
        "air_changes_per_hour_daytime": None,  # filled below
        "rh_outlet_daytime_mean_pct": r.loc[day, "rh_outlet_pct"].mean(),
        "rh_after_collector_daytime_mean_pct": r.loc[day, "rh_after_collector_pct"].mean(),
        "water_target_kg_per_day": r["evap_target_kg_h"].sum() * dt / 3600 / days,
        "water_removed_kg_per_day": r["evap_kg_h"].sum() * dt / 3600 / days,
        "water_capacity_kg_per_day": r["water_capacity_kg_h"].sum() * dt / 3600 / days,
        "sun_energy_absorbed_kWh_per_day": sun_absorbed / 3.6e6 / days,
        "useful_heat_to_air_kWh_per_day": r["q_useful_air_W"].clip(lower=0).sum() * dt / 3.6e6 / days,
        "fan_energy_Wh_per_day": fan_on_h * cfg["fans"]["count"] * cfg["fans"]["electric_power_W"] / days,
        "energy_balance_error_pct": 100 * abs(r["energy_residual_W"].sum() * dt) / max(sun_absorbed, 1.0),
    }
    # Sensors: largest and daytime-average reading error (shown minus true air temperature)
    for col in [c for c in r.columns if c.startswith("sensor_") and c.endswith("_error_K")]:
        name = col[len("sensor_"):-len("_error_K")]
        s[f"sensor_{name}_error_max_K"] = r[col].max()
        s[f"sensor_{name}_error_daytime_mean_K"] = r.loc[day, col].mean()
        s[f"sensor_{name}_RH_error_daytime_mean_pct"] = (
            r.loc[day, f"sensor_{name}_RH_pct"] - r.loc[day, f"sensor_{name}_air_RH_pct"]).mean()

    from .geometry import build_geometry
    vol = build_geometry(cfg).volume
    s["air_changes_per_hour_daytime"] = s["airflow_daytime_mean_m3_h"] / vol
    return s


def format_summary(summary):
    lines = ["Summary", "-------"]
    for k, v in summary.items():
        lines.append(f"  {k:<50}{v:10.2f}")
    return "\n".join(lines)
