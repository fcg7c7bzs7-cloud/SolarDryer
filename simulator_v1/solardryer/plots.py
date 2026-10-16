"""
plots.py - Figures of the simulation results (saved as PNG files).

  day_overview.png   temperatures, humidity, sunlight and airflow over time
  energy_split.png   where the absorbed solar energy goes (daily totals)
  sweep_<metric>.png results of a parameter sweep
"""

import matplotlib

matplotlib.use("Agg")  # draw into files, no window needed
import matplotlib.pyplot as plt  # noqa: E402

# Colour palette (fixed order, colour-blind checked)
C = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
GREY = "#8a8985"
INK = "#52514e"


def _style(ax, ylabel):
    ax.set_ylabel(ylabel, color=INK)
    ax.grid(True, color="#e6e5e1", linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color("#c3c2b7")
    ax.tick_params(colors=INK)


def day_overview(r, cfg, path):
    hours = r["hour"]
    fig, axes = plt.subplots(4, 1, figsize=(10, 12), sharex=True,
                             gridspec_kw={"height_ratios": [3, 2, 2, 2]})

    ax = axes[0]
    ax.plot(hours, r["t_amb_C"], color=GREY, lw=2, label="Outside air")
    ax.plot(hours, r["T_air_collector_C"], color=C[0], lw=2, label="Air after black floor (zone 1)")
    ax.plot(hours, r["T_air_outlet_C"], color=C[1], lw=2, label="Air at outlet (zone 2)")
    ax.plot(hours, r["T_plate_C"], color=C[2], lw=2, label="Black floor")
    ax.plot(hours, r["T_product_C"], color=C[3], lw=2, label="Product on trays")
    lim = cfg["evaluation"]["product_max_temperature_C"]
    ax.axhline(lim, color=C[7], lw=1, ls="--")
    ax.text(hours.iloc[-1], lim + 0.8, f"product limit {lim} °C", color=INK, fontsize=9,
            ha="right")
    _style(ax, "Temperature [°C]")
    ax.legend(loc="upper left", frameon=False, fontsize=9)
    ax.set_title(f"Solar dryer - {cfg['run']['name']} - {cfg['location']['date']}",
                 loc="left", color="#0b0b0b")

    ax = axes[1]
    ax.plot(hours, r["rh_amb_pct"], color=GREY, lw=2, label="Outside air")
    ax.plot(hours, r["rh_after_collector_pct"], color=C[0], lw=2, label="After black floor")
    ax.plot(hours, r["rh_outlet_pct"], color=C[1], lw=2, label="At outlet (with evaporation)")
    ax.set_ylim(0, 105)
    _style(ax, "Relative humidity [%]")
    ax.legend(loc="lower left", frameon=False, fontsize=9)

    ax = axes[2]
    ax.plot(hours, r["ghi_W_m2"], color=C[3], lw=2, label="Sun on horizontal ground [W/m²]")
    _style(ax, "Sunlight [W/m²]")
    ax.legend(loc="upper left", frameon=False, fontsize=9)

    ax = axes[3]
    ax.plot(hours, r["airflow_m3_h"], color=C[0], lw=2, label="Airflow")
    _style(ax, "Airflow [m³/h]")
    ax.set_ylim(bottom=0)
    ax.set_xlabel("Time [h]", color=INK)
    ax.set_xticks(range(0, int(hours.max()) + 1, 2))
    ax.legend(loc="upper left", frameon=False, fontsize=9)

    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def energy_split(summary_totals, path):
    """Horizontal bar chart: daily energy [kWh] per path."""
    names = list(summary_totals.keys())
    vals = list(summary_totals.values())
    fig, ax = plt.subplots(figsize=(8, 0.5 * len(names) + 1.2))
    bars = ax.barh(names, vals, color=C[0], height=0.6)
    for b, v in zip(bars, vals):
        ax.text(b.get_width() + max(vals) * 0.01, b.get_y() + b.get_height() / 2,
                f"{v:.2f} kWh", va="center", color=INK, fontsize=9)
    ax.invert_yaxis()
    _style(ax, "")
    ax.set_xlabel("Energy per day [kWh]", color=INK)
    ax.set_title("Where does the absorbed solar energy go?", loc="left", color="#0b0b0b")
    ax.set_xlim(0, max(vals) * 1.18)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def sweep_plot(df, params, metric, path):
    """Metric versus the first parameter; one line per value of the second parameter."""
    fig, ax = plt.subplots(figsize=(8, 5))
    x = params[0]
    if len(params) == 1:
        d = df.sort_values(x)
        ax.plot(d[x], d[metric], color=C[0], lw=2, marker="o", ms=8)
    else:
        group = params[1]
        others = params[2:]
        if others:
            print(f"Note: plot shows the first value of {others} only; see the CSV for all.")
            for o in others:
                df = df[df[o] == df[o].iloc[0]]
        for i, (val, d) in enumerate(df.groupby(group, sort=True)):
            d = d.sort_values(x)
            ax.plot(d[x], d[metric], color=C[i % len(C)], lw=2, marker="o", ms=8,
                    label=f"{group} = {val}")
        ax.legend(frameon=False, fontsize=9)
    _style(ax, metric)
    xs = sorted(df[x].unique())
    if len(xs) <= 12:
        ax.set_xticks(xs)  # show exactly the tested values
    ax.set_xlabel(x, color=INK)
    ax.set_title(metric, loc="left", color="#0b0b0b")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def sensors_plot(r, cfg, path):
    """What the sensors show versus the true air at their position.
    Sensors with identical settings give identical lines (drawn on top of each other)."""
    names = [s["name"] for s in cfg["sensors"]["list"]]
    hours = r["hour"]
    fig, axes = plt.subplots(3, 1, figsize=(10, 10), sharex=True,
                             gridspec_kw={"height_ratios": [3, 2, 2]})
    ax_t, ax_rh, ax_e = axes
    ax_t.plot(hours, r["t_amb_C"], color=GREY, lw=2, label="Outside air")
    ax_rh.plot(hours, r["rh_amb_pct"], color=GREY, lw=2, label="Outside air")
    zones = {s["name"]: s["zone"] for s in cfg["sensors"]["list"]}
    # true air: one dashed line per zone (sensors in the same zone share it)
    zone_style = {"collector": ("#0b0b0b", (0, (4, 3))), "drying": ("#0b0b0b", (0, (1, 2)))}
    for z in dict.fromkeys(zones.values()):
        n = next(k for k, v in zones.items() if v == z)
        col, ls = zone_style[z]
        ax_t.plot(hours, r[f"sensor_{n}_air_T_C"], color=col, lw=1.2, ls=ls, label=f"true air, {z} zone")
        ax_rh.plot(hours, r[f"sensor_{n}_air_RH_pct"], color=col, lw=1.2, ls=ls,
                   label=f"true air, {z} zone")
    for i, n in enumerate(names):
        col = C[i % len(C)]
        ax_t.plot(hours, r[f"sensor_{n}_T_C"], color=col, lw=2, label=f"{n} ({zones[n]})")
        ax_rh.plot(hours, r[f"sensor_{n}_RH_pct"], color=col, lw=2, label=f"{n} ({zones[n]})")
        ax_e.plot(hours, r[f"sensor_{n}_error_K"], color=col, lw=2, label=n)
    _style(ax_t, "Temperature [°C]")
    ax_t.legend(loc="upper left", frameon=False, fontsize=8, ncol=2)
    ax_t.set_title("What the sensors show (coloured) vs. the true air (black, dashed/dotted)",
                   loc="left", color="#0b0b0b")
    _style(ax_rh, "Relative humidity [%]")
    ax_rh.set_ylim(0, 105)
    ax_rh.legend(loc="lower left", frameon=False, fontsize=8, ncol=2)
    ax_e.axhline(0, color="#c3c2b7", lw=1)
    _style(ax_e, "Reading error [K]")
    ax_e.legend(loc="upper left", frameon=False, fontsize=8)
    ax_e.set_xlabel("Time [h]", color=INK)
    ax_e.set_xticks(range(0, int(hours.max()) + 1, 2))
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)
