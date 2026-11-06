# Validation v1.0 – UKRIM dryer measurements (October 2026)

Measurement data for validating the simulator against the UKRIM dryer v1.0
(reference config: `../config/UKRIM_dryer_v1.0_default.yaml`).

**Rule:** files in `raw/` are the original data. They have been renamed but
their contents are unchanged. Do not edit them. Cleaned or derived data
goes in separate folders (see "Planned" below).

## Folder layout

```
validation_v1.0/
  README.md          this file
  raw/
    dryer/           data logged by the dryer + description + Arduino code
    weather/         weather data from Open-Meteo for the measurement days
    pv/              output of the nearby PV system (cloud indicator)
```

## Files

| File | Content | Original name / source |
|---|---|---|
| `raw/dryer/LEN005_fans_PID.csv` | 1-min log, fans controlled by the Arduino PID | `LEN005, Messung mit Fans an Temeraturregler angeschlossen.CSV` |
| `raw/dryer/LEN009_fans_on_PV_panel.csv` | 1-min log, fans connected directly to the PV panel | `LEN009, Messung mit Fans direkt am Solarpanel.CSV` |
| `raw/dryer/LEN011_no_fans.csv` | 1-min log, fans disconnected | `LEN011, Messung ohne Fans.CSV` |
| `raw/dryer/LEN005_arduino_code.ino` | Arduino sketch used for LEN005 (PID_v1_bc) | `code_LEN005/code_LEN005.ino` |
| `raw/dryer/measurement_description.docx` | Description of the three measurements, start/end times | `Measurement_Data_Description.docx` |
| `raw/weather/openmeteo_T2m_measurement_periods.xlsx` | Hourly air temperature per measurement period | `Yogyakarta_Weather_Measurement.xlsx` (Open-Meteo, Best Match) |
| `raw/weather/openmeteo_reanalysis_hourly_2026-10-05_16.csv` | Hourly reanalysis: T, RH, dew point, pressure, wind (m/s), cloud cover, rain, global/direct/diffuse irradiance, DNI | Open-Meteo Historical Weather API, downloaded 2026-11-06 |
| `raw/weather/openmeteo_satellite_radiation_hourly_2026-10-05_16.csv` | Hourly satellite-based irradiance (global/direct/diffuse, DNI), daytime hours only | Open-Meteo Satellite Radiation API (`satellite_radiation_seamless`), downloaded 2026-11-06 |
| `raw/pv/pv_ukrim_2026-10-DD.csv` (07–16) | 5-min PV system log: DC power, AC power, battery charge/discharge (kW) | `Curve_PLTS IMC UKRIM_Energy Storage System1_<export time>.csv` |

### Weather data notes
- Location: grid point -7.768, 110.468 (the reanalysis returns the same values as the original xlsx). Satellite grid: -7.75, 110.45.
- Times are WIB (UTC+7). Open-Meteo irradiance is the **mean of the preceding hour**: the 10:00 value covers 09:00–10:00.
- Reanalysis and satellite irradiance differ considerably on cloudy days (e.g. 12 Oct: 4.6 vs 7.2 kWh/m²). The PV data is used to decide which is closer.
- Both downloads were checked against the source with checksums.

### PV system notes
- "PLTS IMC UKRIM", less than 50 m from the dryer. It has a battery storage system, so its output may be **reduced when the battery is full**. In that case low PV output does not mean clouds. Check against the battery charging power.
- System size, tilt and orientation: still to be filled in.

## Measurements

| Run | Period (WIB) | Fans | Notes |
|---|---|---|---|
| LEN005 | 07.10. ~12:05 – 09.10. ~21:26 (start estimated) | Arduino PID, PWM 80–255 | Setpoint 50 °C, changed to 40 °C on 09.10. (column `TargetTemp_C`) |
| LEN009 | 12.10. 12:37 – 14.10. 07:50 (start checked with an external clock) | Directly on the PV panel (18 Wp per v1 drawing) | `FanSpeed_PWM` meaningless |
| LEN011 | 14.10. ~09:05 – ~17:51 (start estimated) | Off (disconnected) | `FanSpeed_PWM` meaningless |

- **Dryer empty** in all runs (no product, so no evaporation).
- **Dryer orientation:** fan end exactly south, outlet north.
- **Sensors:** DHT21, logged every minute. Most likely DHT1 hangs above the black floor and DHT2/DHT3 lie on the tray. This is not certain, because cables may have been swapped during cleaning, but positions did not change during the measurements. DHT4 (outside sensor, pin 9) was not connected: all values are NaN.
- **PID (LEN005):** Kp 500, Ki 0.1, Kd 10, REVERSE, P_ON_E. The input is the maximum of DHT2–DHT4, so DHT1 is not used. Compute() runs every 3 s (library sample time 100 ms). Output limits 80–255, so the fans always turn, day and night (confirmed: they keep turning at PWM 80).
- **Invalid data is not used:** RH values of 99.9 % (sensor saturated or condensing, at night) and the NaN columns of DHT4.

## Planned (created during the validation)
- `data/` – cleaned data per run (WIB timestamps, sensor names, validity flags) and simulator weather input
- `configs/` – per-run configs (only the differences from the reference config)
- `scripts/` – data preparation, calibration and comparison
- `results/` – plots and metrics (not committed to git)
