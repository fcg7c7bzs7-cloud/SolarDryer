"""
sensors.py - What do the temperature/humidity sensors in the dryer SHOW?

A DHT21 (AM2301) sensor does not measure the air temperature directly: it
measures the temperature of its own plastic case and the electronics inside
it. In a solar dryer the case is heated by the sun and by heat radiation
from the hot black floor or product, so it can read several degrees TOO HIGH.
And because relative humidity depends on temperature, a too-warm sensor also
shows a too-LOW relative humidity.

This module simulates each sensor as a small object with its own temperature
("lumped thermal node"):

  heat capacity * dT_sensor/dt =
        + sunlight absorbed by the case             (absorptance * sunlight * sunlit area)
        - convection to the surrounding air          h * A * (T_sensor - T_air)
        - heat radiation to the surfaces around it   (black floor / product below,
                                                      cover and sky above)
        - conduction into the tray/product           (only for sensors lying on a tray)

The sensors are tiny, so they do not change the dryer's own energy balance.

Reported per sensor (columns in timeseries.csv):
  sensor_<name>_T_C        temperature the sensor shows
  sensor_<name>_RH_pct     relative humidity the sensor shows
  sensor_<name>_air_T_C    TRUE air temperature at the sensor position
  sensor_<name>_air_RH_pct TRUE relative humidity of the air there
  sensor_<name>_error_K    shown minus true temperature

Numerical method: implicit Euler with linearised radiation - stable for any
time step, even though a sensor reacts within a few minutes.
"""

import math

from . import psychro

SIGMA = 5.670e-8
K_AIR = 0.027      # thermal conductivity of air [W/(m K)]
NU_AIR = 1.7e-5    # kinematic viscosity of air [m2/s]
PR_AIR = 0.71      # Prandtl number of air


def _k(t_c):
    return t_c + 273.15


def _g_rad(eps, area, t1, t2):
    """Linearised radiation conductance [W/K] between temperatures t1 and t2 (degC)."""
    a, b = _k(t1), _k(t2)
    return eps * SIGMA * area * (a * a + b * b) * (a + b)


def convection_coefficient(delta_t, air_velocity, length, char_size):
    """
    Heat transfer coefficient [W/(m2 K)] of a small object in slowly moving air.
      natural convection (warm object, still air):  h = 1.32 * (dT / size)^0.25
      forced convection (air flowing along it):     laminar flat plate,
                                                    Nu = 0.664 Re^0.5 Pr^(1/3)
    Both are combined: h = (h_nat^3 + h_forced^3)^(1/3)
    """
    h_nat = 1.32 * (max(abs(delta_t), 0.01) / char_size) ** 0.25
    re = max(air_velocity, 0.0) * length / NU_AIR
    h_forced = 0.664 * re ** 0.5 * PR_AIR ** (1 / 3) * K_AIR / length
    return (h_nat ** 3 + h_forced ** 3) ** (1 / 3)


class SensorModel:
    def __init__(self, cfg, geom, pressure):
        s = cfg.get("sensors") or {}
        self.enabled = bool(s.get("enabled", False)) and bool(s.get("list"))
        if not self.enabled:
            self.sensors = []
            return
        self.cfg = cfg
        self.geom = geom
        self.p = pressure
        self.tau_ir = cfg["cover"]["ir_transmittance"]
        case = s["case"]
        L = case["length_mm"] / 1000
        W = case["width_mm"] / 1000
        D = case["thickness_mm"] / 1000
        self.length, self.char_size = L, W
        self.area_total = 2 * (L * W + L * D + W * D)
        self.area_face = L * W  # one large face
        self.sensors = []
        for item in s["list"]:
            sens = {**case, **item}  # per-sensor values override the case defaults
            if sens["zone"] not in ("collector", "drying"):
                raise ValueError(f"sensor {sens['name']}: zone must be 'collector' or 'drying'")
            if sens["mounting"] not in ("hanging", "lying"):
                raise ValueError(f"sensor {sens['name']}: mounting must be 'hanging' or 'lying'")
            if sens["mounting"] == "lying" and sens["zone"] != "drying":
                raise ValueError(f"sensor {sens['name']}: 'lying' sensors must be in the drying zone (on a tray)")
            sens["heat_capacity"] = sens["mass_g"] / 1000 * sens["specific_heat_J_kgK"]
            self.sensors.append(sens)

    def initial_state(self, t0):
        return {s["name"]: t0 for s in self.sensors}

    def step(self, temps, o, dt):
        """
        temps : {name: sensor temperature at the old time}
        o     : the output row of the dryer model for this time step
        Returns (new temps, dict of output columns).
        """
        out = {}
        new = {}
        t_sky = 0.0552 * _k(o["t_amb_C"]) ** 1.5 - 273.15
        for s in self.sensors:
            name = s["name"]
            ts = temps[name]
            if s["zone"] == "collector":
                t_air = o["T_air_collector_C"]
                w = o["w_amb"]
                t_below = o["T_plate_C"]  # a hanging sensor "sees" the black floor below it
                sun = o["q_in_collector_W"] / self.geom.absorber_area  # W/m2 inside
            else:
                t_air = o["T_air_outlet_C"]
                w = o["w_outlet"]
                t_below = o["T_product_C"]
                sun = o["q_in_drying_W"] / self.geom.drying_floor_area

            q_sun = s["solar_absorptance"] * sun * s["sun_exposure_factor"] * self.area_face

            if s["mounting"] == "hanging":
                a_conv = self.area_total
                a_up = a_down = 0.5 * self.area_total
                g_contact = 0.0
            else:  # lying flat on the tray: bottom face touches the product/tray
                a_conv = self.area_total - self.area_face
                a_up, a_down = a_conv, 0.0
                g_contact = s["contact_conductance_W_m2K"] * self.area_face

            h = convection_coefficient(ts - t_air, o["air_velocity_m_s"], self.length, self.char_size)
            eps = s["thermal_emittance"]
            # (conductance [W/K], temperature it connects to)
            links = [
                (h * a_conv, t_air),
                (_g_rad(eps, a_up * (1 - self.tau_ir), ts, t_air), t_air),     # cover ~ air temperature
                (_g_rad(eps, a_up * self.tau_ir, ts, t_sky), t_sky),           # through the cover to the sky
                (_g_rad(eps, a_down, ts, t_below), t_below),                   # floor / product below
                (g_contact, o["T_product_C"]),                                 # contact with tray
            ]
            c = s["heat_capacity"] / dt
            t_new = (c * ts + q_sun + sum(g * t for g, t in links)) / (c + sum(g for g, _ in links))
            new[name] = t_new

            out[f"sensor_{name}_T_C"] = t_new
            out[f"sensor_{name}_RH_pct"] = min(100.0, 100 * psychro.relative_humidity(t_new, w, self.p))
            out[f"sensor_{name}_air_T_C"] = t_air
            out[f"sensor_{name}_air_RH_pct"] = min(100.0, 100 * psychro.relative_humidity(t_air, w, self.p))
            out[f"sensor_{name}_error_K"] = t_new - t_air
            out[f"sensor_{name}_sun_W"] = q_sun
        return new, out
