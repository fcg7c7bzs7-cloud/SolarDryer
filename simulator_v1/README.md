# Solar Dryer Simulator v1

A simple physical model of the team's forced-convection solar dryer. Use it to
see how the **inlet, outlet and fan sizes** (and many other design choices)
affect the **temperature, humidity and airflow** inside the dryer during a
day in Indonesia.

> Every number the model uses is in **`config/default_dryer.yaml`**, and every
> parameter there has a comment explaining it. You can change the design
> without touching the Python code.

---

## 1. Installation (once)

You need Python 3.9 or newer. In a terminal (Windows: "Command Prompt" or
"PowerShell"), go to this folder and install the required packages:

```
cd C:\docs\repos\SolarDryer\simulator_v1
pip install -r requirements.txt
```

## 2. Simulate one day

```
python run_day.py
```

This uses `config/default_dryer.yaml` and writes to `results/default_dryer/`:

| File | Content |
|---|---|
| `summary.txt` | geometry (areas, volume, openings) + key results |
| `timeseries.csv` | every quantity at every time step; open it in Excel |
| `day_overview.png` | temperatures, humidity, sunlight and airflow over the day |
| `energy_split.png` | where the absorbed solar energy goes |
| `sensors.png` | what the DHT21 sensors would show vs. the true air (see 5.4) |

**Try your own design:** copy the YAML file, change some values and change
`run: name:` so you don't overwrite the old results. Then run:

```
python run_day.py --config config/my_design.yaml
```

## 3. Compare many designs (parameter sweep)

```
python run_sweep.py --sweep config/sweep_example.yaml
```

The sweep file lists parameters and the values to try. The example runs every
combination of fan count (1–4) and fan size (80, 92, 120 mm). That's 12 runs,
taking about 30 seconds. The results go to `results/sweep_fan_study/`: one CSV
with all numbers, plus one plot per metric.

## 4. Check that the model still works

```
python -m pytest tests
```

Run the tests after changing any Python code. If one fails, the change probably
introduced a bug.

---

## 5. How the model works

### 5.1 The idea

The dryer is split into **two zones** along the airflow:

```
 outside air --fans--> [ zone 1: black floor ] --> [ zone 2: trays ] --> outlet
                         T_air1, T_plate              T_air2, T_prod
```

Each zone has one air temperature: all air in the zone is assumed to be at
the same temperature. Zone 1 also has the temperature of the black floor, and
zone 2 the temperature of the product. Every time step (30 s), the model:

1. **Sun** (`solar.py`): calculates where the sun is from the location, date
   and time. It then works out how much sunlight hits each roof slope, wall and
   end wall, using each surface's angle and direction. Of that light, it computes
   how much passes through the plastic (less when the sun hits at a flat angle)
   and is absorbed by the black floor or the product.
2. **Airflow** (`airflow.py`): finds the airflow where *fan pressure + natural
   draft = pressure losses* (see 5.2).
3. **Energy balance** (`thermal.py`): adds up all heat gains and losses of the
   floor, the product and the air in each zone, and calculates the new
   temperatures.
4. **Humidity** (`psychro.py`): the water evaporated from the product (the
   amount is set in the YAML file) is added to the air, giving the outlet
   humidity.

### 5.2 How inlet, outlet and fan size enter the model

Each opening and obstacle causes a pressure loss

    dp = K * rho * v^2 / 2        with  v = airflow / open area

The sum of all losses must equal what the fans deliver at that airflow (from
the fan curve). If an opening is made smaller, the air speed there goes up and
the loss rises with the speed squared, so the operating point moves to a lower
airflow. A bigger or faster fan moves its curve up and to the right.

| YAML parameter | What it changes |
|---|---|
| `fans.count`, `fans.frame_size_mm`, `fans.speed_rpm` | fan curve (fan laws) **and** inlet open area |
| `fans.curve_source: datasheet` + `datasheet_curve` | use a real fan curve instead |
| `openings.inlet.mesh_open_fraction`, `loss_coefficient` | inlet loss |
| `openings.outlet.*` | outlet area and loss (gable triangle or rectangle) |
| `trays.flow_loss_coefficient` | loss caused by the trays |

Each time step's `timeseries.csv` row contains the individual pressures
(`dp_fan_Pa`, `dp_inlet_Pa`, `dp_trays_Pa`, `dp_outlet_Pa`, `dp_draft_Pa`), so you
can see which element limits the airflow.

### 5.3 What the first results already tell us (default design, sunny dry-season day)

- Two 92 mm fans give about **115 m³/h**. The fans run close to their free airflow
  because the box resistance is small (~6 Pa, mostly at the fan inlet). In this
  design, the **fans** decide the airflow, not the outlet size.
- The outlet air reaches about **54 °C** (≈19 K above outside on average during
  the day), and the relative humidity drops from about 60 % outside to about 25 %
  at noon.
- The **product can get hotter than the air** (up to ~72 °C), because the sun shines
  directly on it through the roof. This is above the usual 60 °C quality limit.
  More airflow (see the sweep), shading of the drying zone or a lighter product
  colour reduces it.
- The biggest losses are heat **radiated to the sky** and heat lost **through the
  uninsulated floor**. Try `construction.insulation_thickness_m: 0.03` and
  `cover.ir_transmittance`.

### 5.4 Virtual sensors (DHT21) - comparing with measurements

The prototype has three DHT21 (AM2301) temperature/humidity sensors: **S1** hangs
in mid-air above the black floor, and **S2** and **S3** lie side by side on the tray
in the centre of the dryer. A DHT21 measures the temperature of **its own case**.
In the dryer that case is heated by the sun and by heat radiation from the hot
black floor or product, so it shows a temperature that is **too high**, and
therefore a relative humidity that is **too low**.

`solardryer/sensors.py` simulates each sensor case as a small object with its
own temperature. The case gains heat from sunlight and from radiation from the
surfaces below it (black floor or product), and through contact with the tray.
It loses heat to the air by convection and by radiation through the cover to
the sky. The sensors are set up in section 14 of the YAML file: position (zone),
mounting (hanging or lying), case size and colour, and how much sun reaches
them (`sun_exposure_factor`).

With the default settings (black case, unshielded), on a sunny day the model
expects the sensors to read about **10–12 K too high** around noon, and the
humidity to read about **20 % RH too low**. At night they read 1–2 K too low,
because they radiate heat to the cold sky.

**How to use it with real data:** compare the measurements with the
`sensor_<name>_T_C` / `sensor_<name>_RH_pct` columns, *not* with the air
temperature. If the shape matches but the level doesn't, adjust the
`[ESTIMATE]` values (sun exposure, absorptance, contact conductance). For
measurements that show the true air temperature, put the sensors in shade, for
example under a small white "roof" or inside a white tube that air can flow
through. Set `sun_exposure_factor: 0` to see how much that would help.

### 5.5 Limits of this version (be careful with conclusions)

- **Treat the results as comparisons between designs, not exact
  predictions.** Several inputs marked `[ESTIMATE]` in the YAML (plastic
  transmittance, fan curve, loss coefficients) can shift absolute temperatures
  by roughly 5–10 K. Measure the prototype (temperatures, airflow, sunlight) and
  adjust those values until the model matches.
- **Drying is not modelled** in this version: the water removed per day is an
  input. The model does check whether the air can actually carry that much
  water away (`water_removed_kg_per_day` vs `water_capacity_kg_per_day`).
- Each zone has a single air temperature. In reality the air gets gradually
  warmer along the box.
- Wind blowing through the openings, dust on the plastic and condensation at
  night are not modelled. If the box cools below the dew point at night,
  `condensation_flag = 1` is set in the CSV.
- The sun model uses a clear-sky shape scaled by `sky_clearness`. For real
  clouds, use measured data (`weather.source: csv`).

### 5.6 Files

```
simulator_v1/
  config/default_dryer.yaml   all parameters (start here!)
  config/sweep_example.yaml   example parameter study
  data/example_weather.csv    example measured-weather format (with two cloud periods)
  run_day.py                  simulate one day
  run_sweep.py                run a parameter study
  solardryer/                 the model (each file starts with an explanation)
    config.py   geometry.py   weather.py   solar.py
    airflow.py  psychro.py    thermal.py   simulate.py
    plots.py    sweep.py      sensors.py
  tests/test_model.py         automatic checks
```

### 5.7 Main references

- Duffie & Beckman, *Solar Engineering of Thermal Processes* (sun position, isotropic
  sky model, incidence angle, sky temperature).
- Erbs et al. (1982): splitting sunlight into direct and diffuse parts.
- McAdams / Watmuff correlations for the heat transfer coefficients.
- ASHRAE fundamentals: humid-air properties, fan laws, pressure-loss coefficients.
