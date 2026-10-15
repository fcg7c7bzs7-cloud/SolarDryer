"""
solardryer - a simple simulation model of a forced-convection solar dryer.

Modules (in the order the calculation uses them):
    config.py    read the YAML parameter file
    geometry.py  box dimensions -> surfaces, areas, volume, openings
    weather.py   outside conditions (synthetic day or CSV file)
    solar.py     sun position and sunlight on each surface
    airflow.py   fan curve, pressure losses, natural draft -> airflow
    psychro.py   humid-air properties (humidity, density, ...)
    thermal.py   energy balance of plate, product and air (one time step)
    simulate.py  loop over time, results table and summary
    plots.py     figures
    sweep.py     parameter studies
"""
