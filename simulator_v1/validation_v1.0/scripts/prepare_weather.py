"""
prepare_weather.py - Weather input for the validation runs.

Sources (raw/weather, raw/pv):
  * Open-Meteo reanalysis (hourly): air temperature, humidity, wind, irradiance
  * Open-Meteo satellite irradiance (hourly)
  * PV system < 50 m from the dryer (5 min DC power, north-facing, 15 deg tilt)

Irradiance from the PV system (the best local cloud information we have):
  1. Clear-sky PV envelope: for every 5-min time of day, the highest (35-min smoothed)
     DC power of the clear days 13-16 Oct. On a clear day the PV follows this envelope.
     (Cloudy days are not used: around clouds the PV briefly produces MORE than on a
     clear day - "cloud enhancement" - and cool modules are more efficient.)
  2. Clear-sky index  kc = DC power / envelope   (1 = clear, 0.3 = heavy cloud)
  3. GHI = kc x clear-sky GHI. The clear-sky GHI is the average SATELLITE irradiance of
     the clear days 13-16 Oct for each time of day (the absolute level therefore comes
     from the satellite; the PV only tells WHEN and HOW MUCH the clouds reduce it).
     (The simple Haurwitz clear-sky model was tested too: it gives ~10 % less energy per
     day than the satellite, mainly in the morning and afternoon.)
  Battery: the PV has battery storage. On 14 Oct the battery was full from 10:00 but
  the PV power still followed the clear-sky shape, so no curtailment was found.

Outputs (data/):
  weather_5min_2026-10-07_16.csv   all sources side by side (for plots/checks)
  <RUN>_weather_sim.csv            simulator input (weather.source: csv), hour counted
                                   from 00:00 of the run's first day
  plots in results/weather/

Run from the validation_v1.0 folder:   python scripts/prepare_weather.py
"""
import glob
import os
import sys

import numpy as np
import pandas as pd
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.dirname(HERE)
sys.path.insert(0, os.path.dirname(BASE))  # simulator_v1 -> solardryer package
from solardryer import solar  # noqa: E402

LAT, LON, UTC = -7.768, 110.468, 7
CLEAR_DAYS = [13, 14, 15, 16]


def clear_sky_ghi(times):
    out = []
    for t in times:
        z, _ = solar.sun_position(t.timetuple().tm_yday, t.hour + t.minute / 60, LAT, LON, UTC)
        out.append(solar.clear_sky_ghi(z))
    return np.array(out)


def load_pv():
    fs = sorted(glob.glob(os.path.join(BASE, "raw", "pv", "*.csv")))
    pv = pd.concat([pd.read_csv(f, skiprows=1, encoding="utf-8-sig", parse_dates=["Time"])
                    for f in fs], ignore_index=True)
    pv.columns = ["time", "pv_dc_kW", "pv_ac_kW", "batt_charge_kW", "batt_discharge_kW"]
    return pv


def main():
    pv = load_pv()
    pv["slot"] = pv.time.dt.hour * 12 + pv.time.dt.minute // 5
    pv["day"] = pv.time.dt.day
    # 1. clear-sky envelope
    pv["dc_smooth"] = pv.groupby("day")["pv_dc_kW"].transform(
        lambda s: s.rolling(7, center=True, min_periods=1).median())
    env = pv[pv.day.isin(CLEAR_DAYS)].groupby("slot")["dc_smooth"].max()
    env = env.rolling(5, center=True, min_periods=1).mean()
    pv["dc_clear_kW"] = pv.slot.map(env)
    # 2. clear-sky index
    pv["kc"] = (pv.pv_dc_kW / pv.dc_clear_kW.where(pv.dc_clear_kW > 0.3)).clip(0, 1.3)
    # 3. clear-sky GHI, scaled to the satellite on clear days
    rea = pd.read_csv(os.path.join(BASE, "raw/weather/openmeteo_reanalysis_hourly_2026-10-05_16.csv"),
                      parse_dates=["time"])
    sat = pd.read_csv(os.path.join(BASE, "raw/weather/openmeteo_satellite_radiation_hourly_2026-10-05_16.csv"),
                      parse_dates=["time"])
    # satellite clear-day profile: hourly means of the PRECEDING hour -> centre of that hour
    sc = sat[sat.time.dt.day.isin(CLEAR_DAYS)].copy()
    sc["h_mid"] = sc.time.dt.hour - 0.5
    prof = sc.groupby("h_mid")["shortwave_radiation"].mean()
    prof = pd.concat([pd.Series({5.0: 0.0}), prof, pd.Series({18.5: 0.0})]).sort_index()
    h = pv.time.dt.hour + pv.time.dt.minute / 60
    pv["ghi_clear_W_m2"] = np.interp(h, prof.index, prof.values)
    pv["ghi_pv_W_m2"] = pv.kc.fillna(0) * pv.ghi_clear_W_m2
    hc = clear_sky_ghi(pv.time)
    print(f"Clear-day GHI from satellite: {pv.ghi_clear_W_m2.sum() / 12 / 1000 / 10:.2f} kWh/m2/day "
          f"(Haurwitz model: {hc.sum() / 12 / 1000 / 10:.2f})")

    # side-by-side table at 5 min
    t5 = pv[["time", "pv_dc_kW", "dc_clear_kW", "kc", "batt_charge_kW", "ghi_clear_W_m2", "ghi_pv_W_m2"]].copy()
    def interp_hourly(df, col, shift_h):
        x = (df.time - pd.Timedelta(hours=shift_h)).astype("int64") / 3.6e12
        return np.interp(t5.time.astype("int64") / 3.6e12, x, df[col].fillna(0))
    # irradiance = mean of the preceding hour -> place it at the middle of that hour
    t5["ghi_sat_W_m2"] = interp_hourly(sat, "shortwave_radiation", 0.5)
    t5["ghi_rea_W_m2"] = interp_hourly(rea, "shortwave_radiation", 0.5)
    for col, new in [("temperature_2m", "t_amb_C"), ("relative_humidity_2m", "rh_percent"),
                     ("wind_speed_10m", "wind10_m_s"), ("cloud_cover", "cloud_cover_pct")]:
        t5[new] = interp_hourly(rea, col, 0.0)  # instantaneous values at the full hour
    os.makedirs(os.path.join(BASE, "data"), exist_ok=True)
    t5.to_csv(os.path.join(BASE, "data", "weather_5min_2026-10-07_16.csv"), index=False,
              float_format="%.3f", date_format="%Y-%m-%d %H:%M")

    # daily totals
    t5["day"] = t5.time.dt.date
    daily = t5.groupby("day")[["ghi_pv_W_m2", "ghi_sat_W_m2", "ghi_rea_W_m2"]].sum() / 12 / 1000
    daily.columns = ["PV-derived", "satellite", "reanalysis"]
    print("Daily irradiation kWh/m2:\n" + daily.round(2).to_string())

    # simulator input per run
    meta = yaml.safe_load(open(os.path.join(BASE, "runs.yaml"), encoding="utf-8"))
    for run, info in meta["runs"].items():
        start = pd.Timestamp(info["start"]).normalize()
        dry = pd.read_csv(os.path.join(BASE, "data", f"{run}_dryer.csv"), parse_dates=["time_wib"])
        end = dry.time_wib.iloc[-1].normalize() + pd.Timedelta(days=1)
        w = t5[(t5.time >= start) & (t5.time <= end)]
        sim = pd.DataFrame({
            "hour": (w.time - start).dt.total_seconds() / 3600,
            "ghi_W_m2": w.ghi_pv_W_m2, "t_amb_C": w.t_amb_C, "rh_percent": w.rh_percent,
            "wind_m_s": w.wind10_m_s, "cloud_cover_pct": w.cloud_cover_pct,
        })
        sim.to_csv(os.path.join(BASE, "data", f"{run}_weather_sim.csv"), index=False, float_format="%.3f")
        print(f"{run}: simulator weather {start.date()} 00:00 + {sim.hour.iloc[-1]:.1f} h")

    # plot
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    out = os.path.join(BASE, "results", "weather")
    os.makedirs(out, exist_ok=True)
    fig, axes = plt.subplots(10, 1, figsize=(11, 22), sharey=True)
    for ax, (day, g) in zip(axes, t5.groupby("day")):
        h = g.time.dt.hour + g.time.dt.minute / 60
        ax.plot(h, g.ghi_pv_W_m2, color="#2a78d6", lw=1.5, label="from PV (5 min)")
        ax.plot(h, g.ghi_sat_W_m2, color="#eb6834", lw=1.5, label="satellite (hourly)")
        ax.plot(h, g.ghi_rea_W_m2, color="#8a8985", lw=1.5, ls="--", label="reanalysis (hourly)")
        ax.set_title(str(day), loc="left", fontsize=10)
        ax.set_xlim(5, 18.5); ax.grid(color="#e6e5e1"); ax.set_ylabel("GHI W/m²")
    axes[0].legend(frameon=False, fontsize=8, ncol=3)
    axes[-1].set_xlabel("Time WIB [h]")
    fig.tight_layout(); fig.savefig(os.path.join(out, "irradiance_sources.png"), dpi=110); plt.close(fig)


if __name__ == "__main__":
    main()
