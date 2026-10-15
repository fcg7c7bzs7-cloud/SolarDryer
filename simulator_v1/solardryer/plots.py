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
