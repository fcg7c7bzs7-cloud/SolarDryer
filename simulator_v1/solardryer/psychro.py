"""
psychro.py - Properties of humid air ("psychrometrics").

Key quantities:
  T   air temperature [degC]
  RH  relative humidity, 0..1 (1 = saturated, air cannot take more water)
  w   humidity ratio [kg water / kg dry air]. This does NOT change when air is
      only heated - which is why heated air has a lower RH and can dry things.
  P   air pressure [Pa]
"""

import math

R_DRY_AIR = 287.05      # J/(kg K)
CP_DRY_AIR = 1006.0     # J/(kg K)
CP_VAPOUR = 1860.0      # J/(kg K)


def pressure_at_altitude(altitude_m):
    """Standard atmosphere pressure [Pa]."""
    return 101325.0 * (1 - 2.25577e-5 * altitude_m) ** 5.25588


def saturation_pressure(t_c):
    """Water vapour pressure of saturated air [Pa] (Magnus formula, Alduchov 1996)."""
    return 610.94 * math.exp(17.625 * t_c / (t_c + 243.04))


def humidity_ratio(t_c, rh, p=101325.0):
    """w [kg/kg] from temperature and relative humidity (0..1)."""
    pv = rh * saturation_pressure(t_c)
    return 0.622 * pv / (p - pv)


def relative_humidity(t_c, w, p=101325.0):
    """RH (0..1) from temperature and humidity ratio. Can exceed 1 if w is too high."""
    pv = w * p / (0.622 + w)
    return pv / saturation_pressure(t_c)


def saturation_humidity_ratio(t_c, p=101325.0, rh=1.0):
    """Maximum w the air can hold at temperature t_c (or at a given RH)."""
    return humidity_ratio(t_c, rh, p)


def humidity_ratio_from_dew_point(t_dew_c, p=101325.0):
    return humidity_ratio(t_dew_c, 1.0, p)


def density(t_c, w=0.0, p=101325.0):
    """Density of humid air [kg/m3]. Hot air is lighter -> natural draft."""
    t_k = t_c + 273.15
    return p / (R_DRY_AIR * t_k) * (1 + w) / (1 + 1.6078 * w)


def cp_humid(w):
    """Heat capacity of humid air per kg DRY air [J/(kg K)]."""
    return CP_DRY_AIR + CP_VAPOUR * w


def enthalpy(t_c, w):
    """Enthalpy of humid air [J per kg dry air] (0 degC dry air = 0)."""
    return CP_DRY_AIR * t_c + w * (2.501e6 + CP_VAPOUR * t_c)


def adiabatic_saturation_w(t_c, w, p=101325.0, rh_max=1.0):
    """
    Humidity ratio the air reaches when it picks up water WITHOUT extra heat
    (it cools down while the water evaporates, like air flowing over wet
    product) until it reaches rh_max. Found by bisection on the temperature.
    Returns w_end [kg/kg].
    """
    h = enthalpy(t_c, w)
    lo, hi = -20.0, t_c
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if enthalpy(mid, humidity_ratio(mid, rh_max, p)) > h:
            hi = mid
        else:
            lo = mid
    return max(w, humidity_ratio(0.5 * (lo + hi), rh_max, p))


def latent_heat(t_c):
    """Energy needed to evaporate 1 kg of water [J/kg] (~2.4 MJ/kg)."""
    return 2.501e6 - 2370.0 * t_c
