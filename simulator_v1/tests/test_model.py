"""
Automatic checks of the model ("unit tests").

Run all of them with:      python -m pytest tests
Every function starting with "test_" is one check. If one fails after you
changed the code, the model probably has a bug.
"""

import math
import os

import pytest

from solardryer import airflow, psychro, solar
from solardryer.config import load_config, set_value
from solardryer.geometry import build_geometry
from solardryer.simulate import run_simulation

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(HERE, "..", "config", "default_dryer.yaml")


@pytest.fixture
def cfg():
    c = load_config(CONFIG)
    c["run"]["time_step_s"] = 60  # faster tests
    return c


# ---------------------------------------------------------------- geometry
def test_geometry_hand_calculation(cfg):
    g = build_geometry(cfg)
    assert g.absorber_area == pytest.approx(1.5 * 1.5)
    assert g.tray_area == pytest.approx(2 * 1.5 * 1.5)
    # cross-section = rectangle 1.5 x 0.2 + triangle 1.5 x 0.3 / 2
    assert g.cross_section_area == pytest.approx(0.3 + 0.225)
    assert g.volume == pytest.approx(0.525 * 4.5)
    # outlet = triangle 0.225 m2 minus small tip triangle (0.04 high, 0.2 wide)
    assert g.outlet_area == pytest.approx(0.225 - 0.5 * 0.2 * 0.04)
    roof = [s for s in g.surfaces if s.name.startswith("roof")][0]
    assert roof.tilt_deg == pytest.approx(math.degrees(math.atan(0.3 / 0.75)))


# ---------------------------------------------------------------- sun
def test_sun_overhead_at_equator_on_equinox():
    # 20 March, equator, longitude in the middle of UTC+0 -> sun almost overhead at noon
    zen, _ = solar.sun_position(79, 12.0, 0.0, 0.0, 0)
    assert zen < 3.0


def test_noon_sun_height_yogyakarta_august():
    # Declination mid-August ~ +14 deg -> noon elevation = 90 - |lat - decl| ~ 68 deg
    zens = [solar.sun_position(227, h / 10, -7.8, 110.4, 7)[0] for h in range(100, 140)]
    assert 90 - min(zens) == pytest.approx(68.3, abs=1.0)
    # sun is in the NORTH at noon (south of the equator in August)
    i = zens.index(min(zens))
    _, az = solar.sun_position(227, (100 + i) / 10, -7.8, 110.4, 7)
    assert az < 20 or az > 340


def test_south_facing_roof_gets_less_sun_when_sun_is_north():
    zen, az = 20.0, 0.0  # sun high in the north
    north, _, _ = solar.surface_irradiance(800, 0, 0, zen, az, 30, 0, 0)
    south, _, _ = solar.surface_irradiance(800, 0, 0, zen, az, 30, 180, 0)
    assert north > south


# ---------------------------------------------------------------- air & fans
def test_humid_air_basics():
    assert psychro.saturation_pressure(50.0) == pytest.approx(12352, rel=0.01)
    w = psychro.humidity_ratio(30, 0.75)
    assert psychro.relative_humidity(30, w) == pytest.approx(0.75)
    # heating air lowers RH: 30 degC/75 % -> 50 degC is about 26 %
    assert psychro.relative_humidity(50, w) == pytest.approx(0.26, abs=0.02)


def test_fan_laws(cfg):
    fan1 = airflow.FanCurve(cfg)
    cfg2 = set_value(cfg, "fans.speed_rpm", 2 * cfg["fans"]["speed_rpm"])
    fan2 = airflow.FanCurve(cfg2)
    assert fan2.q_free == pytest.approx(2 * fan1.q_free)
    assert fan2.p_shut == pytest.approx(4 * fan1.p_shut)


def test_operating_point_balances_pressures(cfg):
    g = build_geometry(cfg)
    fan = airflow.FanCurve(cfg)
    op = airflow.operating_point(cfg, g, fan, 1.0, 1.16, 1.08, 1.06)
    losses = op["dp_inlet"] + op["dp_trays"] + op["dp_outlet"]
    assert op["dp_fan"] + op["dp_draft"] == pytest.approx(losses, rel=1e-6)
    # with an almost closed outlet the airflow must drop
    small = set_value(cfg, "openings.outlet.mesh_open_fraction", 0.02)
    op2 = airflow.operating_point(small, g, fan, 1.0, 1.16, 1.08, 1.06)
    assert op2["m_dot"] < 0.8 * op["m_dot"]


# ---------------------------------------------------------------- whole model
def test_energy_balance_closes(cfg):
    _, s, _ = run_simulation(cfg)
    assert s["energy_balance_error_pct"] < 0.1


def test_no_sun_means_no_heating(cfg):
    c = set_value(cfg, "weather.synthetic.sky_clearness", 0.0)
    c = set_value(c, "evaporation.daily_water_removal_kg", 0.0)
    r, _, _ = run_simulation(c)
    excess = (r["T_air_outlet_C"] - r["t_amb_C"]).max()
    assert excess < 0.5  # never warmer than outside (can be colder: night sky)


def test_more_airflow_gives_lower_temperature(cfg):
    _, s1, _ = run_simulation(set_value(cfg, "fans.count", 1))
    _, s4, _ = run_simulation(set_value(cfg, "fans.count", 4))
    assert s4["airflow_daytime_mean_m3_h"] > s1["airflow_daytime_mean_m3_h"]
    assert s4["T_outlet_max_C"] < s1["T_outlet_max_C"]


def test_outlet_temperature_matches_hand_calculation(cfg):
    # useful heat = m_dot * cp * (T_out - T_amb)  ->  check at noon
    r, _, _ = run_simulation(cfg)
    row = r.iloc[(r["hour"] - 12).abs().idxmin()]
    dT = row["q_useful_air_W"] / (row["m_dot_kg_s"] * 1006 * 1.02)
    assert dT == pytest.approx(row["T_air_outlet_C"] - row["t_amb_C"], rel=0.03)


def test_insulation_helps(cfg):
    _, s0, _ = run_simulation(cfg)
    _, s1, _ = run_simulation(set_value(cfg, "construction.insulation_thickness_m", 0.03))
    assert s1["T_outlet_max_C"] > s0["T_outlet_max_C"]


def test_csv_weather_runs(cfg):
    c = set_value(cfg, "weather.source", "csv")
    _, s, _ = run_simulation(c)
    assert s["T_outlet_max_C"] > 35


def test_typo_in_parameter_name_is_reported(cfg):
    with pytest.raises(KeyError):
        set_value(cfg, "fans.cuont", 3)
