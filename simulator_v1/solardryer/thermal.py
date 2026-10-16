"""
thermal.py - The energy balance of the dryer (the heart of the model).

The dryer is represented by FOUR temperatures ("nodes"):

    zone 1 (collector)          zone 2 (drying)
    ------------------          ---------------
    T_air1  air                 T_air2  air            -> leaves through the outlet
    T_plate black floor         T_prod  trays+product

    outside air (T_amb) --fans--> zone 1 air --> zone 2 air --> outlet

Each zone's air is treated as "well mixed": the air leaving a zone has the
zone's air temperature (tanks in series).

Heat flows considered (all in watts, W):

  black plate:  + sunlight absorbed
                - convection to the zone-1 air          h_in * A * (T_plate - T_air1)
                - heat radiation to the cover           (absorbed by the cover -> zone-1 air)
                - heat radiation through the cover to the sky (fraction ir_transmittance)
                - loss through the floor board to below U_back * A * (T_plate - T_amb)

  zone-1 air:   + convection from the plate, + radiation absorbed by the cover
                - heat carried away by the air          m_dot * cp * (T_air1 - T_amb)
                - loss through the plastic cover        U_cover * A * (T_air1 - T_amb)

  product:      + sunlight absorbed
                - convection to the zone-2 air, - radiation (as for the plate)
                - EVAPORATION: water leaving the product takes heat with it
                                                        evaporation_rate * latent_heat

  zone-2 air:   + air from zone 1, + convection from product, + radiation absorbed
                  by the cover, + sunlight absorbed by the floor next to the trays
                - air leaving through the outlet, - loss through cover and floor

Numerical method (how the computer steps through time):
  * Plate and product change slowly (big heat storage) -> simple "explicit
    Euler": new T = old T + dt * (net heat flow) / (heat capacity).
  * The air reacts fast -> "implicit Euler": the air temperature is solved
    from its energy balance at the new time. This never becomes unstable.
  * The airflow depends on the air temperature (density, natural draft) and
    the air temperature depends on the airflow, so both are repeated a few
    times per time step until they agree ("fixed-point iteration").
"""

import math

from . import airflow, psychro, solar

SIGMA = 5.670e-8  # Stefan-Boltzmann constant [W/(m2 K4)]


def _k(t_c):
    return t_c + 273.15


def sky_temperature(t_amb_c):
    """Effective temperature of the sky for heat radiation (Swinbank 1963) [degC]."""
    return 0.0552 * _k(t_amb_c) ** 1.5 - 273.15


class DryerModel:
    """Holds the constant properties of the dryer and computes one time step."""

    def __init__(self, cfg, geom):
        self.cfg = cfg
        self.geom = geom
        self.fan = airflow.FanCurve(cfg)
        self.p = psychro.pressure_at_altitude(cfg["location"]["altitude_m"])

        c, t, a = cfg["construction"], cfg["trays"], cfg["absorber"]
        self.r_board = c["board_thickness_m"] / c["board_conductivity_W_mK"]
        self.r_ins = c["insulation_thickness_m"] / c["insulation_conductivity_W_mK"]

        # Areas per zone
        self.a_cover = {z: sum(s.area for s in geom.surfaces_in_zone(z, "cover"))
                        for z in ("collector", "drying")}
        self.a_opaque = {z: sum(s.area for s in geom.surfaces_in_zone(z, "opaque"))
                         for z in ("collector", "drying")}
        self.a_contact_prod = t["air_contact_factor"] * geom.tray_area
        self.tray_floor_fraction = min(1.0, geom.tray_area / geom.drying_floor_area)

        # Heat capacities [J/K]
        self.c_plate = a["heat_capacity_J_m2K"] * geom.absorber_area
        self.c_prod = geom.tray_area * (t["product_load_kg_m2"] * t["product_specific_heat_J_kgK"]
                                        + t["tray_heat_capacity_J_m2K"])
        rho_cp_air = 1.15 * 1006.0
        c_cov = cfg["cover"]["heat_capacity_J_m2K"]
        self.c_air = {
            "collector": rho_cp_air * geom.volume_collector
                         + c_cov * (self.a_cover["collector"] + self.a_opaque["collector"]),
            "drying": rho_cp_air * geom.volume_drying
                      + c_cov * (self.a_cover["drying"] + self.a_opaque["drying"]),
        }

    # ------------------------------------------------------------------
    def solar_gains(self, hour, ghi, dhi):
        """Absorbed sunlight [W] on plate, product and drying-zone floor."""
        cfg = self.cfg
        loc = cfg["location"]
        day = solar.day_of_year(loc["date"]) + int(hour // 24)
        zen, az = solar.sun_position(day, hour % 24, loc["latitude_deg"], loc["longitude_deg"],
                                     loc["utc_offset_h"])
        dhi_in = None if (dhi is None or (isinstance(dhi, float) and math.isnan(dhi))) else dhi
        dni, dhi_used = solar.split_ghi(ghi, zen, day, dhi_in)
        tr = solar.transmitted_solar_by_zone(self.geom, cfg, dni, dhi_used, ghi, zen, az)
        f = self.tray_floor_fraction
        return {
            "sun_elevation": 90.0 - zen,
            "sun_azimuth": az,
            "dni": dni,
            "dhi": dhi_used,
            "q_in_collector": tr["collector"],
            "q_in_drying": tr["drying"],
            "q_sol_plate": cfg["absorber"]["solar_absorptance"] * tr["collector"],
            "q_sol_prod": cfg["trays"]["solar_absorptance"] * f * tr["drying"],
            "q_sol_floor2": cfg["trays"]["floor_absorptance"] * (1 - f) * tr["drying"],
            "per_surface": tr["per_surface"],
        }

    # ------------------------------------------------------------------
    def step(self, state, wx, hour, dt, evap_target):
        """
        Advance the model by one time step.

        state : dict with T_plate, T_prod, T_air1, T_air2 (degC) at the old time
        wx    : weather at the new time (dict: ghi, dhi, t_amb, rh_amb, wind)
        evap_target : desired evaporation rate [kg/s]

        Returns (new_state, out) where out holds every quantity for the results table.
        """
        cfg = self.cfg
        ht = cfg["heat_transfer"]
        geom = self.geom
        p = self.p

        t_amb = wx["t_amb"]
        w_amb = psychro.humidity_ratio(t_amb, wx["rh_amb"], p)
        rho_amb = psychro.density(t_amb, w_amb, p)
        cp = psychro.cp_humid(w_amb)
        t_sky = sky_temperature(t_amb)
        tau_ir = cfg["cover"]["ir_transmittance"]
        eps_p = cfg["absorber"]["thermal_emittance"]
        eps_t = cfg["trays"]["thermal_emittance"]

        sol = self.solar_gains(hour, wx["ghi"], wx["dhi"])
        speed = airflow.fan_speed_fraction(cfg, hour, wx["ghi"])

        tp, tt = state["T_plate"], state["T_prod"]
        ta1, ta2 = state["T_air1"], state["T_air2"]
        h_out = ht["outside_a"] + ht["outside_b"] * wx["wind"]

        for _ in range(50):  # fixed-point iteration: airflow <-> air temperatures
            # 1) airflow for the current guess of the air temperatures
            rho_box = psychro.density(0.5 * (ta1 + ta2), w_amb, p)
            flow = airflow.operating_point(cfg, geom, self.fan, speed, rho_amb, rho_box,
                                           psychro.density(ta2, w_amb, p))
            m = flow["m_dot"]

            # 2) heat transfer coefficients
            v_in = m / (rho_box * geom.cross_section_free_area)  # air speed in the box
            h_in = ht["inside_a"] + ht["inside_b"] * v_in
            u_cover = 1.0 / (1.0 / h_in + 1.0 / h_out)
            u_wall = 1.0 / (1.0 / h_in + self.r_board + 1.0 / h_out)
            u_back = 1.0 / (self.r_board + self.r_ins + 1.0 / h_out)
            u_floor2 = 1.0 / (1.0 / h_in + self.r_board + self.r_ins + 1.0 / h_out)
            ua1 = u_cover * self.a_cover["collector"] + u_wall * self.a_opaque["collector"]
            ua2 = (u_cover * self.a_cover["drying"] + u_wall * self.a_opaque["drying"]
                   + u_floor2 * geom.drying_floor_area)

            # 3) heat radiation of plate and product (uses the old plate/product temperature)
            rad_p = eps_p * SIGMA * geom.absorber_area
            q_rad_cov_p = (1 - tau_ir) * rad_p * (_k(tp) ** 4 - _k(ta1) ** 4)
            q_rad_sky_p = tau_ir * rad_p * (_k(tp) ** 4 - _k(t_sky) ** 4)
            rad_t = eps_t * SIGMA * geom.tray_area
            q_rad_cov_t = (1 - tau_ir) * rad_t * (_k(tt) ** 4 - _k(ta2) ** 4)
            q_rad_sky_t = tau_ir * rad_t * (_k(tt) ** 4 - _k(t_sky) ** 4)

            # 4) evaporation, limited so the outlet air does not exceed max_outlet_rh
            w_max = psychro.saturation_humidity_ratio(ta2, p, cfg["evaporation"]["max_outlet_rh"])
            evap = max(0.0, min(evap_target, m * (w_max - w_amb)))
            w_out = w_amb + evap / m

            # 5) air temperatures (implicit Euler: energy balance of each air node)
            c1 = self.c_air["collector"] / dt
            c2 = self.c_air["drying"] / dt
            ha_p = h_in * geom.absorber_area
            ha_t = h_in * self.a_contact_prod
            ta1_new = ((c1 * state["T_air1"] + m * cp * t_amb + ha_p * tp + q_rad_cov_p + ua1 * t_amb)
                       / (c1 + m * cp + ha_p + ua1))
            ta2_new = ((c2 * state["T_air2"] + m * cp * ta1_new + ha_t * tt + q_rad_cov_t
                        + sol["q_sol_floor2"] + ua2 * t_amb)
                       / (c2 + m * cp + ha_t + ua2))

            change = abs(ta1_new - ta1) + abs(ta2_new - ta2)
            ta1, ta2 = ta1_new, ta2_new
            if change < 1e-6:
                break

        else:
            print(f"WARNING: iteration did not converge at hour {hour:.2f}")

        # 6) plate and product (explicit Euler)
        q_evap = evap * psychro.latent_heat(tt)
        q_conv_p = ha_p * (tp - ta1)
        q_back = u_back * geom.absorber_area * (tp - t_amb)
        dq_plate = sol["q_sol_plate"] - q_conv_p - q_rad_cov_p - q_rad_sky_p - q_back
        q_conv_t = ha_t * (tt - ta2)
        dq_prod = sol["q_sol_prod"] - q_conv_t - q_rad_cov_t - q_rad_sky_t - q_evap

        new_state = {
            "T_plate": tp + dt * dq_plate / self.c_plate,
            "T_prod": tt + dt * dq_prod / self.c_prod,
            "T_air1": ta1,
            "T_air2": ta2,
        }

        # Energy balance check [W]: sun in = useful + losses + evaporation + storage
        q_useful = m * cp * (ta2 - t_amb)
        q_loss_cover = ua1 * (ta1 - t_amb) + ua2 * (ta2 - t_amb)
        q_loss_rad_sky = q_rad_sky_p + q_rad_sky_t
        q_storage = (dq_plate + dq_prod
                     + self.c_air["collector"] * (ta1 - state["T_air1"]) / dt
                     + self.c_air["drying"] * (ta2 - state["T_air2"]) / dt)
        q_sun = sol["q_sol_plate"] + sol["q_sol_prod"] + sol["q_sol_floor2"]
        residual = q_sun - (q_useful + q_loss_cover + q_back + q_loss_rad_sky + q_evap + q_storage)

        out = {
            "hour": hour,
            "ghi_W_m2": wx["ghi"],
            "dni_W_m2": sol["dni"],
            "dhi_W_m2": sol["dhi"],
            "sun_elevation_deg": sol["sun_elevation"],
            "t_amb_C": t_amb,
            "rh_amb_pct": 100 * wx["rh_amb"],
            "wind_m_s": wx["wind"],
            "fan_speed_fraction": speed,
            "T_plate_C": tp,
            "T_air_collector_C": ta1,
            "T_product_C": tt,
            "T_air_outlet_C": ta2,
            # RH is capped at 100 %. If the box is colder than the dew point (clear
            # nights: the cover radiates to the cold sky) water condenses -> flag = 1.
            "rh_outlet_pct": min(100.0, 100 * psychro.relative_humidity(ta2, w_out, p)),
            "rh_after_collector_pct": min(100.0, 100 * psychro.relative_humidity(ta1, w_amb, p)),
            "condensation_flag": int(psychro.relative_humidity(ta2, w_out, p) > 1.0),
            "m_dot_kg_s": m,
            "airflow_m3_h": m / rho_amb * 3600,
            "dp_fan_Pa": flow["dp_fan"],
            "dp_draft_Pa": flow["dp_draft"],
            "dp_inlet_Pa": flow["dp_inlet"],
            "dp_trays_Pa": flow["dp_trays"],
            "dp_outlet_Pa": flow["dp_outlet"],
            "evap_target_kg_h": evap_target * 3600,
            "evap_kg_h": evap * 3600,
            # "Drying capacity": how much water the air COULD carry away at most if it
            # kept evaporating water (and cooling down while doing so) until it reaches
            # max_outlet_rh. Uses the air state at the outlet.
            "water_capacity_kg_h": m * (psychro.adiabatic_saturation_w(
                ta2, w_out, p, cfg["evaporation"]["max_outlet_rh"]) - w_amb) * 3600,
            "q_sun_entering_W": sol["q_in_collector"] + sol["q_in_drying"],
            "q_in_collector_W": sol["q_in_collector"],   # sunlight landing inside zone 1
            "q_in_drying_W": sol["q_in_drying"],         # sunlight landing inside zone 2
            "w_amb": w_amb,                              # humidity ratio outside [kg/kg]
            "w_outlet": w_out,                           # humidity ratio in zone 2 [kg/kg]
            "air_velocity_m_s": v_in,                    # mean air speed inside the box
            "q_sun_absorbed_W": q_sun,
            "q_useful_air_W": q_useful,
            "q_evaporation_W": q_evap,
            "q_loss_cover_W": q_loss_cover,
            "q_loss_floor_W": q_back,
            "q_loss_radiation_sky_W": q_loss_rad_sky,
            "q_storage_W": q_storage,
            "energy_residual_W": residual,
            "h_in_W_m2K": h_in,
            "h_out_W_m2K": h_out,
        }
        for name, val in sol["per_surface"].items():
            out[f"sun_on_{name}_W"] = val
        return new_state, out
