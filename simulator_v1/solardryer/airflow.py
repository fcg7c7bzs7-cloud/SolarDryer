"""
airflow.py - How much air flows through the dryer?

The air is pushed by the FANS and (a little) by NATURAL DRAFT (warm air is
lighter and rises - like a chimney). It is slowed down by PRESSURE LOSSES at
the inlet, the trays and the outlet.

  Pressure loss of one element:   dp = K * m_dot^2 / (2 * rho * A^2)
      K      loss coefficient (from the YAML file)
      m_dot  air mass flow [kg/s]
      rho    air density at that element [kg/m3]
      A      open area of that element [m2]
  (this is the same as K * rho * v^2 / 2 with v = m_dot / (rho * A))

  Fan pressure:  from the fan curve (generic parabola or datasheet points)

  Natural draft: dp_draft = g * (height_outlet - height_inlet) * (rho_outside - rho_inside)

The "operating point" is the mass flow where
      fan pressure + natural draft = sum of all pressure losses.
We find it with the bisection method (halve the search interval until the
answer is accurate enough) - simple and always works.
"""

import numpy as np

from .geometry import fan_open_area

G = 9.81          # gravity [m/s2]
RHO_REF = 1.20    # air density at which fan curves are usually given [kg/m3]


class FanCurve:
    """Pressure-airflow curve of ONE fan."""

    def __init__(self, cfg):
        f = cfg["fans"]
        self.source = f["curve_source"]
        if self.source == "generic":
            ref = f["reference_fan"]
            n_ratio = f["speed_rpm"] / ref["speed_rpm"]
            d_ratio = f["frame_size_mm"] / ref["frame_size_mm"]
            # Fan laws: Q ~ n * D^3,  p ~ n^2 * D^2
            self.q_free = ref["free_airflow_m3_s"] * n_ratio * d_ratio ** 3
            self.p_shut = ref["shutoff_pressure_Pa"] * n_ratio ** 2 * d_ratio ** 2
        elif self.source == "datasheet":
            pts = np.array(f["datasheet_curve"], dtype=float)
            if pts[0, 0] != 0.0 or np.any(np.diff(pts[:, 0]) <= 0):
                raise ValueError("datasheet_curve must start at airflow 0 and increase")
            self.q_pts, self.p_pts = pts[:, 0], pts[:, 1]
            self.q_free = float(np.interp(0.0, -self.p_pts, self.q_pts))  # approx. for reports
            self.p_shut = float(self.p_pts[0])
        else:
            raise ValueError("fans.curve_source must be 'generic' or 'datasheet'")

    def pressure(self, q, speed_fraction=1.0, rho=RHO_REF):
        """
        Fan pressure [Pa] at volume flow q [m3/s] through this fan.
        speed_fraction scales the curve with the fan laws (q ~ s, p ~ s^2).
        Beyond the free airflow the pressure becomes negative (the fan then
        acts as a resistance).
        """
        s = speed_fraction
        if s <= 0:
            return 0.0
        qn = q / s  # equivalent flow at full speed
        if self.source == "generic":
            p = self.p_shut * (1.0 - (qn / self.q_free) ** 2)
        else:
            if qn <= self.q_pts[-1]:
                p = float(np.interp(qn, self.q_pts, self.p_pts))
            else:  # linear extrapolation of the last segment
                slope = (self.p_pts[-1] - self.p_pts[-2]) / (self.q_pts[-1] - self.q_pts[-2])
                p = self.p_pts[-1] + slope * (qn - self.q_pts[-1])
        return p * s ** 2 * rho / RHO_REF


def pressure_losses(cfg, geom, m_dot, rho_in, rho_box, rho_out, fans_running):
    """Pressure loss [Pa] of every element for a given mass flow. Returns a dict."""
    o_in = cfg["openings"]["inlet"]
    o_out = cfg["openings"]["outlet"]
    k_in = o_in["loss_coefficient"]
    if not fans_running:
        k_in += cfg["fans"]["stopped_fan_loss_coefficient"]
    a_in = geom.inlet_area * o_in["mesh_open_fraction"]
    a_out = geom.outlet_area * o_out["mesh_open_fraction"]
    k_trays = cfg["trays"]["count"] * cfg["trays"]["flow_loss_coefficient"]

    def dp(k, rho, a):
        return k * m_dot ** 2 / (2.0 * rho * a ** 2)

    return {
        "inlet": dp(k_in, rho_in, a_in),
        "trays": dp(k_trays, rho_box, geom.cross_section_free_area),
        "outlet": dp(o_out["loss_coefficient"], rho_out, a_out),
    }


def natural_draft(geom, rho_amb, rho_box):
    """Chimney effect [Pa]: positive when the box is warmer than outside."""
    return G * (geom.outlet_elevation - geom.inlet_elevation) * (rho_amb - rho_box)


def operating_point(cfg, geom, fan, speed_fraction, rho_amb, rho_box, rho_out):
    """
    Find the air mass flow [kg/s] where fan pressure + draft = losses.

    Returns a dict with m_dot, fan pressure, draft and the individual losses.
    """
    n_fans = cfg["fans"]["count"]
    running = speed_fraction > 0
    draft = natural_draft(geom, rho_amb, rho_box)
    m_min = cfg["heat_transfer"]["min_air_mass_flow_kg_s"]

    def fan_dp(m):
        q_per_fan = m / rho_amb / n_fans  # fans move outside air at the inlet
        return fan.pressure(q_per_fan, speed_fraction, rho_amb)

    def imbalance(m):
        losses = pressure_losses(cfg, geom, m, rho_amb, rho_box, rho_out, running)
        return fan_dp(m) + draft - sum(losses.values())

    if imbalance(m_min) <= 0:
        m = m_min  # nothing pushes the air: only leakage
    else:
        lo, hi = m_min, 0.01
        while imbalance(hi) > 0:  # make the interval big enough
            hi *= 2
            if hi > 100:
                raise RuntimeError("Airflow calculation diverged - check the fan/opening inputs")
        for _ in range(60):       # bisection: 60 halvings = far more accurate than needed
            mid = 0.5 * (lo + hi)
            if imbalance(mid) > 0:
                lo = mid
            else:
                hi = mid
        m = 0.5 * (lo + hi)

    losses = pressure_losses(cfg, geom, m, rho_amb, rho_box, rho_out, running)
    return {
        "m_dot": m,
        "dp_fan": fan_dp(m) if running else 0.0,
        "dp_draft": draft,
        "dp_inlet": losses["inlet"],
        "dp_trays": losses["trays"],
        "dp_outlet": losses["outlet"],
    }


def fan_speed_fraction(cfg, hour, ghi):
    """Fan speed (0..1) at a given time, following the schedule in the YAML file."""
    f = cfg["fans"]
    h = hour % 24.0
    if not (f["on_hour"] <= h < f["off_hour"]):
        return 0.0
    if not f.get("speed_follows_sun", False):
        return 1.0
    s = min(1.0, ghi / f["sun_for_full_speed_W_m2"])
    return s if s >= f["min_speed_fraction"] else 0.0


# Re-exported for convenience (used in the README examples)
__all__ = ["FanCurve", "operating_point", "fan_speed_fraction", "fan_open_area"]
