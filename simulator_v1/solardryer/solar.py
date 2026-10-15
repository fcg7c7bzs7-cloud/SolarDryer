"""
solar.py - Where is the sun, and how much sunlight hits each surface?

Background (short):
  * Sunlight on the ground consists of
      - BEAM (direct) radiation: comes straight from the sun's disc,
      - DIFFUSE radiation: scattered by the sky/haze, comes from all directions.
    In Indonesia the diffuse part is large (40-60 %) because of the humid,
    hazy air.
  * A weather station / pyranometer measures GHI = Global Horizontal
    Irradiance = beam + diffuse on a flat surface [W/m2].
  * On a tilted surface (a roof slope, a wall) the sunlight is
        G = beam_normal * cos(incidence angle)              (direct part)
          + diffuse * (1 + cos(tilt)) / 2                   (sees part of the sky)
          + GHI * ground_reflectance * (1 - cos(tilt)) / 2  (sees part of the ground)
    This is the "isotropic sky model" (Liu & Jordan), standard in textbooks
    such as Duffie & Beckman, "Solar Engineering of Thermal Processes".

All angles in this file are in DEGREES unless the variable ends in _rad.
"""

import math
from datetime import date as _date

SOLAR_CONSTANT = 1361.0  # W/m2, sunlight outside the atmosphere


def _rad(x):
    return math.radians(x)


def day_of_year(date_str):
    """'2026-08-15' -> 227"""
    d = _date.fromisoformat(str(date_str))
    return d.timetuple().tm_yday


def sun_position(day, local_hour, latitude, longitude, utc_offset):
    """
    Sun position for a given day of the year and local clock time.

    Returns (zenith_deg, azimuth_deg):
      zenith  = angle between the sun and straight up (0 = sun overhead,
                90 = sun at the horizon, > 90 = night)
      azimuth = compass direction of the sun (0 = N, 90 = E, 180 = S, 270 = W)

    Equations: Spencer (1971) for declination and equation of time.
    """
    gamma = 2 * math.pi * (day - 1) / 365.0  # "day angle"
    # Declination: latitude where the sun is overhead at noon (-23.45 .. +23.45 deg)
    decl_rad = (0.006918 - 0.399912 * math.cos(gamma) + 0.070257 * math.sin(gamma)
                - 0.006758 * math.cos(2 * gamma) + 0.000907 * math.sin(2 * gamma)
                - 0.002697 * math.cos(3 * gamma) + 0.00148 * math.sin(3 * gamma))
    # Equation of time [minutes]: the sun runs a bit early/late during the year
    eot = 229.18 * (0.000075 + 0.001868 * math.cos(gamma) - 0.032077 * math.sin(gamma)
                    - 0.014615 * math.cos(2 * gamma) - 0.040849 * math.sin(2 * gamma))
    # Solar time: clock time corrected for longitude within the time zone and EoT
    solar_hour = local_hour + (4 * (longitude - 15 * utc_offset) + eot) / 60.0
    hour_angle_rad = _rad(15 * (solar_hour - 12))  # negative in the morning

    lat_rad = _rad(latitude)
    cos_z = (math.sin(lat_rad) * math.sin(decl_rad)
             + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(hour_angle_rad))
    cos_z = max(-1.0, min(1.0, cos_z))
    zenith = math.degrees(math.acos(cos_z))

    azimuth = math.degrees(math.atan2(
        math.sin(hour_angle_rad),
        math.cos(hour_angle_rad) * math.sin(lat_rad) - math.tan(decl_rad) * math.cos(lat_rad)
    )) + 180.0
    return zenith, azimuth % 360


def extraterrestrial_normal(day):
    """Sunlight outside the atmosphere [W/m2] (varies +-3 % over the year)."""
    return SOLAR_CONSTANT * (1 + 0.033 * math.cos(2 * math.pi * day / 365.0))


def clear_sky_ghi(zenith):
    """
    Global horizontal irradiance on a perfectly clear day [W/m2].
    Haurwitz (1945) model - very simple, needs only the sun height.
    """
    cos_z = math.cos(_rad(zenith))
    if cos_z <= 0.01:
        return 0.0
    return 1098.0 * cos_z * math.exp(-0.057 / cos_z)


def diffuse_fraction_erbs(kt):
    """
    Fraction of GHI that is diffuse, from the clearness index kt (Erbs 1982).
    kt = GHI / (sunlight on a horizontal surface outside the atmosphere).
    Clear sky: kt ~ 0.75 -> ~17 % diffuse.   Overcast: kt ~ 0.2 -> ~99 % diffuse.
    """
    if kt <= 0.22:
        return 1.0 - 0.09 * kt
    if kt <= 0.80:
        return (0.9511 - 0.1604 * kt + 4.388 * kt ** 2 - 16.638 * kt ** 3
                + 12.336 * kt ** 4)
    return 0.165


def split_ghi(ghi, zenith, day, dhi=None):
    """
    Split GHI into beam-normal (DNI) and diffuse horizontal (DHI) [W/m2].
    If dhi is given (measured), it is used; otherwise Erbs is used.
    """
    cos_z = math.cos(_rad(zenith))
    if ghi <= 0 or cos_z <= 0.01:
        return 0.0, max(ghi, 0.0)
    if dhi is None:
        g0h = extraterrestrial_normal(day) * cos_z
        kt = min(ghi / g0h, 1.0)
        dhi = ghi * diffuse_fraction_erbs(kt)
    dhi = min(dhi, ghi)
    dni = (ghi - dhi) / max(cos_z, 0.087)  # avoid huge DNI near sunrise (zenith > 85 deg)
    return dni, dhi


def cos_incidence(zenith, sun_azimuth, tilt, surface_azimuth):
    """
    Cosine of the angle between the sun rays and the surface normal.
    Negative value = the sun is behind the surface (no direct light).
    """
    z, b = _rad(zenith), _rad(tilt)
    return (math.cos(z) * math.cos(b)
            + math.sin(z) * math.sin(b) * math.cos(_rad(sun_azimuth - surface_azimuth)))


def surface_irradiance(dni, dhi, ghi, zenith, sun_azimuth, tilt, surface_azimuth,
                       ground_reflectance):
    """
    Sunlight on a tilted surface split into (beam, diffuse_and_reflected) [W/m2]
    plus the cosine of the incidence angle (needed for the plastic transmittance).
    """
    cos_t = cos_incidence(zenith, sun_azimuth, tilt, surface_azimuth)
    beam = dni * max(cos_t, 0.0)
    b = _rad(tilt)
    diffuse = dhi * (1 + math.cos(b)) / 2 + ghi * ground_reflectance * (1 - math.cos(b)) / 2
    return beam, diffuse, cos_t


def incidence_angle_modifier(cos_theta, b0):
    """
    How the transmittance of the plastic drops at flat angles (ASHRAE model):
        IAM = 1 - b0 * (1 / cos(theta) - 1)
    IAM = 1 for light hitting straight on, 0 at grazing angles.
    """
    if cos_theta <= 0.0:
        return 0.0
    return max(0.0, 1.0 - b0 * (1.0 / cos_theta - 1.0))


# Diffuse light comes from all directions; on average it behaves like light
# arriving at about 60 deg incidence (Duffie & Beckman, Fig. 5.4.1).
DIFFUSE_EQUIVALENT_COS = math.cos(math.radians(60))


def transmitted_solar_by_zone(geom, cfg, dni, dhi, ghi, zenith, sun_azimuth):
    """
    Sunlight [W] that passes through the transparent surfaces of each zone
    and lands inside the box.

    Returns dict:  {"collector": W, "drying": W, "per_surface": {name: W_outside}}
    "per_surface" is the sunlight hitting the OUTSIDE of each surface (for
    reporting the illuminated surfaces).
    """
    c = cfg["cover"]
    tau_n, b0 = c["solar_transmittance"], c["angle_loss_b0"]
    capture = c["interior_capture_fraction"]
    rho_g = cfg["weather"]["ground_reflectance"]
    tau_diffuse = tau_n * incidence_angle_modifier(DIFFUSE_EQUIVALENT_COS, b0)

    result = {"collector": 0.0, "drying": 0.0, "per_surface": {}}
    for s in geom.surfaces:
        beam, diff, cos_t = surface_irradiance(dni, dhi, ghi, zenith, sun_azimuth,
                                               s.tilt_deg, s.azimuth_deg, rho_g)
        beam *= (1.0 - s.beam_shading)
        result["per_surface"][s.name] = (beam + diff) * s.area
        if s.kind != "cover":
            continue  # opaque surfaces let no light in
        tau_beam = tau_n * incidence_angle_modifier(cos_t, b0)
        result[s.zone] += capture * s.area * (tau_beam * beam + tau_diffuse * diff)
    return result
