# SolarDryer

All about our solar dryer.

The dryer is a house-shaped box covered with transparent plastic, intended for drying
fruits and vegetables in rural Indonesia. A black-painted floor section heats the
air, small 12 V fans push it over the product trays, and the moist air leaves through
the gable opening at the far end. Compared with drying on the ground it is more
hygienic and faster.

## Contents

| Folder | What it is |
|---|---|
| [`simulator_v1/`](simulator_v1/README.md) | Python simulation of the dryer: temperature, humidity and airflow over a day, for comparing inlet, outlet and fan designs. Start with its [README](simulator_v1/README.md). |

## Quick start (simulator)

```
cd simulator_v1
pip install -r requirements.txt
python run_day.py
```

Results are written to `simulator_v1/results/` (not tracked by git).

## License

MIT, see [LICENSE](LICENSE).
