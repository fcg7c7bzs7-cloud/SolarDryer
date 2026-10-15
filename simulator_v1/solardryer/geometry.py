"""
geometry.py - Turns the box dimensions from the YAML file into surfaces.

The dryer is a "house": a rectangular floor, low vertical walls and a
pitched (gable) roof whose ridge runs along the long axis.

Every outside surface is described by:
    area      [m2]
    tilt      [deg]  0 = horizontal facing up, 90 = vertical wall
    azimuth   [deg]  compass direction the surface FACES (outward):
                     0 = north, 90 = east, 180 = south, 270 = west
    zone      "collector" (black floor part) or "drying" (tray part)
    kind      "cover" (transparent plastic) or "opaque"

The sun calculation (solar.py) uses tilt and azimuth to find how much
sunlight hits each surface.
"""

import math
from dataclasses import dataclass, field


@dataclass
class Surface:
    name: str
    zone: str           # "collector" or "drying"
    area: float         # m2
    tilt_deg: float     # 0 = facing up, 90 = vertical
    azimuth_deg: float  # direction the surface faces, 0 = N, 90 = E, ...
    kind: str = "cover"  # "cover" (transparent) or "opaque"
    beam_shading: float = 0.0  # fraction of DIRECT sunlight blocked (0..1)


@dataclass
class DryerGeometry:
    surfaces: list = field(default_factory=list)  # outside surfaces (walls, roof)
    absorber_area: float = 0.0        # black floor of zone 1 [m2]
    drying_floor_area: float = 0.0    # floor under the trays [m2]
    tray_area: float = 0.0            # total tray area [m2]
    cross_section_area: float = 0.0   # inside cross-section of the box [m2]
    cross_section_free_area: float = 0.0  # cross-section minus the tray layer [m2]
    volume: float = 0.0               # inside volume [m3]
    volume_collector: float = 0.0
    volume_drying: float = 0.0
    inlet_area: float = 0.0           # total open area of the fan openings [m2]
    inlet_elevation: float = 0.0      # m above floor
    outlet_area: float = 0.0          # open area of the outlet (before mesh) [m2]
    outlet_elevation: float = 0.0     # height of the outlet centre above floor [m]

    def surfaces_in_zone(self, zone, kind=None):
        return [s for s in self.surfaces
                if s.zone == zone and (kind is None or s.kind == kind)]


def compass_name(azimuth_deg):
    """Turn an azimuth into a short compass label: 0 -> 'N', 90 -> 'E', ..."""
    labels = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return labels[int(((azimuth_deg % 360) + 22.5) // 45) % 8]


def fan_open_area(frame_size_mm, hub_ratio):
    """
    Open (annular) area of one fan opening in m2.
    Blade diameter is about 95 % of the frame size; the hub in the middle is
    closed.
    """
    d_blade = 0.95 * frame_size_mm / 1000.0
    return math.pi / 4.0 * d_blade ** 2 * (1.0 - hub_ratio ** 2)


def gable_outlet(width, roof_rise, top_cut):
    """
    Area and centre height of the gable-triangle outlet.
    The triangle sits on top of the walls; a strip of height 'top_cut' at the
    tip is closed (mounting). y is measured from the top of the walls.
    Returns (area, centroid height above the wall top).
    """
    h = roof_rise - top_cut  # open height
    if h <= 0:
        raise ValueError("outlet top_cut_m must be smaller than roof_rise_m")
    # width at height y: width * (1 - y / roof_rise)  -> integrate over y = 0..h
    area = width * (h - h ** 2 / (2 * roof_rise))
    first_moment = width * (h ** 2 / 2 - h ** 3 / (3 * roof_rise))
    return area, first_moment / area


def build_geometry(cfg):
    """Build all surfaces and characteristic areas from the configuration."""
    g = cfg["geometry"]
    L, W = g["length_m"], g["width_m"]
    h_wall, rise = g["wall_height_m"], g["roof_rise_m"]
    L_col = g["collector_length_m"]
    L_dry = L - L_col
    if not 0 < L_col < L:
        raise ValueError("collector_length_m must be between 0 and length_m")

    az_inlet = g["inlet_end_azimuth_deg"] % 360       # inlet end wall faces this way
    az_outlet = (az_inlet + 180) % 360                # outlet end wall
    az_side1 = (az_inlet + 90) % 360                  # one long side
    az_side2 = (az_inlet - 90) % 360                  # the other long side

    # Roof: two sloped planes, each covering half the width.
    roof_slope_len = math.hypot(W / 2, rise)
    roof_tilt = math.degrees(math.atan2(rise, W / 2))

    gable_area = W * h_wall + 0.5 * W * rise         # one end wall (rectangle + triangle)

    # Outlet opening
    o = cfg["openings"]["outlet"]
    if o["shape"] == "gable_triangle":
        outlet_area, y_c = gable_outlet(W, rise, o["top_cut_m"])
        outlet_elev = h_wall + y_c
    elif o["shape"] == "rectangle":
        outlet_area = o["width_m"] * o["height_m"]
        outlet_elev = o["elevation_m"]
    else:
        raise ValueError(f"Unknown outlet shape '{o['shape']}'")
    if outlet_area >= gable_area:
        raise ValueError("Outlet is larger than the end wall")

    surfaces = []
    for zone, length in (("collector", L_col), ("drying", L_dry)):
        for az in (az_side1, az_side2):
            c = compass_name(az)
            surfaces.append(Surface(f"roof_{c}_{zone}", zone, length * roof_slope_len, roof_tilt, az))
            surfaces.append(Surface(f"wall_{c}_{zone}", zone, length * h_wall, 90.0, az))
    surfaces.append(Surface(f"end_{compass_name(az_inlet)}_collector", "collector",
                            gable_area, 90.0, az_inlet))
    surfaces.append(Surface(f"end_{compass_name(az_outlet)}_drying", "drying",
                            gable_area - outlet_area, 90.0, az_outlet))

    # Apply user overrides: opaque surfaces and beam shading
    names = {s.name for s in surfaces}
    for name in cfg["cover"].get("opaque_surfaces") or []:
        if name not in names:
            raise KeyError(f"opaque_surfaces: unknown surface '{name}'. Known: {sorted(names)}")
    for name in (cfg["cover"].get("beam_shading") or {}):
        if name not in names:
            raise KeyError(f"beam_shading: unknown surface '{name}'. Known: {sorted(names)}")
    for s in surfaces:
        if s.name in (cfg["cover"].get("opaque_surfaces") or []):
            s.kind = "opaque"
        s.beam_shading = float((cfg["cover"].get("beam_shading") or {}).get(s.name, 0.0))

    # Trays
    t = cfg["trays"]
    tray_area = t["count"] * t["length_m"] * t["width_m"]
    if t["count"] * t["length_m"] > L_dry + 1e-9:
        raise ValueError("The trays are longer than the drying zone")
    if t["height_above_floor_m"] + t["layer_thickness_m"] > h_wall + rise:
        raise ValueError("The trays do not fit below the roof")

    cross = W * h_wall + 0.5 * W * rise
    cross_free = cross - min(t["width_m"], W) * t["layer_thickness_m"]

    f = cfg["fans"]
    inlet_area = f["count"] * fan_open_area(f["frame_size_mm"], f["hub_ratio"])

    return DryerGeometry(
        surfaces=surfaces,
        absorber_area=L_col * W,
        drying_floor_area=L_dry * W,
        tray_area=tray_area,
        cross_section_area=cross,
        cross_section_free_area=cross_free,
        volume=cross * L,
        volume_collector=cross * L_col,
        volume_drying=cross * L_dry,
        inlet_area=inlet_area,
        inlet_elevation=cfg["openings"]["inlet"]["elevation_m"],
        outlet_area=outlet_area,
        outlet_elevation=outlet_elev,
    )


def describe(geom):
    """Return a readable text table of the geometry (printed by run_day.py)."""
    lines = ["Surfaces (outside):",
             f"  {'name':<22}{'zone':<11}{'kind':<8}{'area m2':>9}{'tilt':>7}{'facing':>8}"]
    for s in geom.surfaces:
        lines.append(f"  {s.name:<22}{s.zone:<11}{s.kind:<8}{s.area:9.3f}{s.tilt_deg:7.1f}"
                     f"{compass_name(s.azimuth_deg):>8}")
    lines += [
        f"Black absorber floor      : {geom.absorber_area:.3f} m2",
        f"Floor under trays         : {geom.drying_floor_area:.3f} m2",
        f"Tray area                 : {geom.tray_area:.3f} m2",
        f"Box volume                : {geom.volume:.3f} m3",
        f"Box cross-section         : {geom.cross_section_area:.3f} m2 (free: {geom.cross_section_free_area:.3f} m2)",
        f"Inlet (fan) open area     : {geom.inlet_area * 1e4:.1f} cm2",
        f"Outlet open area          : {geom.outlet_area:.3f} m2, centre {geom.outlet_elevation:.3f} m above floor",
    ]
    return "\n".join(lines)
