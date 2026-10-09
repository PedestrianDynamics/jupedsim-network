"""Static figures for the network model documentation.

Writes PNGs to ``site/static/images/network`` or to the directory given as
the first argument. ``jupedsim_network`` must be importable::

    uv run --group docs python scripts/figures/make_figures.py
    uv run --group docs python scripts/figures/make_gifs.py
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch
from scenarios import building, building_populations, merge_corridor

from jupedsim_network import (
    LogNormal,
    Network,
    NetworkSimulation,
    Population,
    hydraulic,
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUT = ROOT / "site" / "static" / "images" / "network"
PAL = ["#90c1c6", "#72a5b4", "#58849f", "#446485", "#324465", "#1f253f"]
RED = "#bd0c0c"
ORANGE = "#fc8d59"
GREY = "dimgrey"


def style():
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 10,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.spines.left": False,
            "axes.spines.bottom": False,
            "axes.grid": False,
            "axes.labelcolor": "#333333",
            "axes.titlesize": 11,
            "axes.titleweight": "semibold",
            "xtick.major.size": 0,
            "ytick.major.size": 0,
            "xtick.color": GREY,
            "ytick.color": GREY,
            "legend.frameon": True,
            "legend.facecolor": "white",
            "legend.framealpha": 0.8,
            "legend.edgecolor": "lightgrey",
            "legend.labelcolor": GREY,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def frame(*axes):
    for ax in axes:
        ax.patch.set_edgecolor("lightgrey")
        ax.patch.set_linewidth(0.8)
        ax.grid(alpha=0.4, linewidth=0.6)


def box(ax, xy, w, h, text, color):
    patch = FancyBboxPatch(
        xy,
        w,
        h,
        boxstyle="round,pad=0.02,rounding_size=0.08",
        fc=color,
        ec="#324465",
        lw=1.0,
    )
    ax.add_patch(patch)
    ax.text(
        xy[0] + w / 2,
        xy[1] + h / 2,
        text,
        ha="center",
        va="center",
        fontsize=9,
        color="#1f253f",
    )


def arrow(ax, a, b, text=None, offset=(0, 0.12)):
    ax.add_patch(
        FancyArrowPatch(
            a, b, arrowstyle="-|>", mutation_scale=12, color="#446485", lw=1.4
        )
    )
    if text:
        mid = ((a[0] + b[0]) / 2 + offset[0], (a[1] + b[1]) / 2 + offset[1])
        ax.text(*mid, text, ha="center", va="bottom", fontsize=8, color=GREY)


def schematic(out):
    fig, ax = plt.subplots(figsize=(10, 3.6))
    box(ax, (0.0, 1.4), 2.6, 1.8, "", "#e8f1f2")
    ax.text(
        1.3,
        2.95,
        "room a, area $A_a$",
        ha="center",
        va="center",
        fontsize=9,
        color="#1f253f",
    )
    box(ax, (0.0, 0.0), 2.6, 1.0, "room b\narea $A_b$", "#e8f1f2")
    box(ax, (4.0, 0.7), 1.8, 1.1, "corridor\narea $A_c$", "#e8f1f2")
    box(ax, (7.2, 0.7), 1.8, 1.1, "stair flight\n$k(R,T)$, area", "#d5e5ea")
    box(ax, (10.2, 0.7), 1.4, 1.1, "safe", "#e9f4e4")
    arrow(ax, (2.6, 2.45), (4.0, 1.5), "door, $w_a$", offset=(0.3, 0.12))
    arrow(ax, (2.6, 0.5), (4.0, 1.0), "door, $w_b$", offset=(0.25, -0.42))
    arrow(ax, (5.8, 1.25), (7.2, 1.25), "stair entry")
    arrow(ax, (9.0, 1.25), (10.2, 1.25), "door")
    for x in range(5):
        ax.add_patch(Circle((2.38 - 0.18 * x, 2.45), 0.06, color=RED))
    ax.text(1.5, 2.45, "queue", fontsize=8, color=RED, ha="right", va="center")
    ax.annotate(
        "",
        xy=(0.15, 2.08),
        xytext=(2.45, 2.08),
        arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.8),
    )
    ax.text(
        1.3,
        1.68,
        "link length $L$\nwalked in the source",
        ha="center",
        va="center",
        fontsize=8,
        color=GREY,
    )
    ax.text(
        5.8,
        -0.35,
        r"link capacity $C = F_s\,(w - 2b)$   ·   node density "
        r"$D = \sum_i a_i / A$",
        ha="center",
        fontsize=9,
        color=GREY,
    )
    ax.set_xlim(-0.2, 11.8)
    ax.set_ylim(-0.65, 3.4)
    ax.set_aspect("equal")
    ax.axis("off")
    fig.savefig(out / "schematic.png")
    plt.close(fig)


def mark_densities(ax, marks):
    top = ax.get_ylim()[1] * 0.98
    for x, text in marks:
        ax.axvline(x, color="lightgrey", lw=0.8, zorder=0)
        ax.text(
            x,
            top,
            text,
            fontsize=7.5,
            color=GREY,
            ha="center",
            va="top",
            bbox=dict(fc="white", ec="none", pad=1),
        )


def fundamental(out):
    d = np.linspace(0, hydraulic.JAM_DENSITY, 400)
    k_level = hydraulic.LEVEL_SPEED_CONSTANT
    k_stair = hydraulic.stair_speed_constant(0.18, 0.28)
    fig, axes = plt.subplots(1, 3, figsize=(13, 3.8))
    for k, label, color in [
        (k_level, "level, k = 1.40 m/s", PAL[3]),
        (k_stair, "stair 18/28 cm, k = 1.08 m/s", ORANGE),
    ]:
        s = hydraulic.speed(d, k)
        axes[0].plot(d, s, color=color, lw=2, label=label)
        axes[1].plot(d, s * d, color=color, lw=2, label=label)
    marks = [
        (hydraulic.MIN_DENSITY, "0.54"),
        (hydraulic.PEAK_FLOW_DENSITY, "1.88"),
        (2.75, "2.75"),
        (hydraulic.JAM_DENSITY, "3.76"),
    ]
    for ax in axes[:2]:
        mark_densities(ax, marks)
    axes[0].set(
        xlabel="density D (1/m²)",
        ylabel="speed S (m/s)",
        title="(a) speed, S = k (1 − 0.266 D)",
    )
    axes[1].set(
        xlabel="density D (1/m²)",
        ylabel="specific flow S·D (1/m/s)",
        title="(b) specific flow",
    )
    axes[0].legend(loc="lower left", fontsize=8)
    phi = np.clip((2.75 - d) / (2.75 - hydraulic.PEAK_FLOW_DENSITY), 0, 1)
    axes[2].plot(d, phi, color=PAL[4], lw=2, label="supply reduction on")
    axes[2].plot(
        d,
        np.where(d < 2.75, 1, 0),
        color=RED,
        lw=1.2,
        ls="--",
        label="hard limit only",
    )
    axes[2].set(
        xlabel="density of receiving node D (1/m²)",
        ylabel="accepted share of inflow φ",
        title="(c) supply factor",
        xlim=(0, hydraulic.JAM_DENSITY),
    )
    axes[2].legend(loc="lower left", fontsize=8)
    axes[2].annotate(
        "$D_{peak}$",
        (1.88, 1.0),
        (1.2, 0.7),
        color=GREY,
        arrowprops=dict(arrowstyle="-", color=GREY, lw=0.6),
    )
    axes[2].annotate(
        "$D_{max}$",
        (2.75, 0.0),
        (3.0, 0.35),
        color=GREY,
        arrowprops=dict(arrowstyle="-", color=GREY, lw=0.6),
    )
    frame(*axes)
    fig.tight_layout()
    fig.savefig(out / "fundamental_diagram.png")
    plt.close(fig)


def door_and_merge(out):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4))
    net = Network()
    net.add_room("room", area=40.0)
    net.add_safe("exit")
    net.connect("room", "exit", width=1.0, specific_flow=1.33)
    r = NetworkSimulation(net, [Population("room", 100, speed=1.0)]).run(1)
    exits = np.sort(r.exit_times)
    axes[0].step(
        exits,
        np.arange(1, 101),
        where="post",
        color=PAL[3],
        lw=2,
        label="network model, Δt = 0.5 s",
    )
    t = np.linspace(0, 99 / (1.33 * 0.7), 50)
    axes[0].plot(
        t,
        1 + 1.33 * 0.7 * t,
        color=RED,
        ls="--",
        lw=1.2,
        label="model convention 1 + C t",
    )
    t = np.linspace(0, 100 / (1.33 * 0.7), 50)
    axes[0].plot(
        t,
        1.33 * 0.7 * t,
        color=ORANGE,
        ls=":",
        lw=1.6,
        label="SFPE hand calculation C t",
    )
    axes[0].set(
        xlabel="time (s)",
        ylabel="agents through door",
        title="(a) IMO test 4 geometry: 100 agents, 1 m door",
    )
    axes[0].text(
        60,
        12,
        f"last agent: {r.evacuation_time:.1f} s\n"
        f"(N − 1)/C = {99 / 0.931:.1f} s\n"
        f"N/C = {100 / 0.931:.1f} s",
        color=GREY,
        fontsize=9,
    )
    axes[0].legend(loc="upper left", fontsize=8)

    pops = [Population("a", 300), Population("b", 300)]
    r = NetworkSimulation(merge_corridor(), pops, t_max=150.0).run(seed=2)
    for name, color, w, ls in [
        ("a->corridor", PAL[2], 1, "-"),
        ("b->corridor", ORANGE, 3, "--"),
    ]:
        flow = r.link_flow[:, r.link_names.index(name)]
        axes[1].plot(
            r.times,
            np.cumsum(flow),
            color=color,
            ls=ls,
            lw=2,
            label=f"{name.split('-')[0]}  (merge weight {w})",
        )
    axes[1].set(
        xlabel="time (s)",
        ylabel="agents into corridor",
        title="(b) merging into a full corridor, weights 1 : 3",
    )
    axes[1].legend(loc="upper left", fontsize=8)
    frame(*axes)
    fig.tight_layout()
    fig.savefig(out / "door_and_merge.png")
    plt.close(fig)


def rset_quantiles(max_density, supply_reduction, runs):
    sim = NetworkSimulation(
        building(stairs=("A",)),
        building_populations(),
        max_density=max_density,
        supply_reduction=supply_reduction,
    )
    times = sim.run_many(runs, seed=1).evacuation_times
    return np.quantile(times, [0.05, 0.5, 0.95])


def density_sweep(out, runs=30):
    limits = np.array([2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.7])
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for on, color, label, marker in [
        (True, PAL[3], "supply reduction on", "o"),
        (False, RED, "hard limit only", "s"),
    ]:
        q = np.array([rset_quantiles(m, on, runs) for m in limits])
        ax.fill_between(limits, q[:, 0], q[:, 2], color=color, alpha=0.15)
        ax.plot(limits, q[:, 1], color=color, marker=marker, lw=2, label=label)
    ax.set(
        xlabel="max_density (1/m²)",
        ylabel="evacuation time (s), median and 5–95 %",
        title="10 floors × 60 agents, one stair",
    )
    ax.legend(loc="upper left", fontsize=8)
    frame(ax)
    fig.savefig(out / "max_density_sweep.png")
    plt.close(fig)


def route_tie(out):
    cases = [
        (
            "two stairs, nearest exit (tie → one stair)",
            building(),
            building_populations(),
            RED,
            "-",
        ),
        (
            "two stairs, targets split 50/50",
            building(),
            building_populations(split="AB"),
            PAL[3],
            "--",
        ),
        (
            "one stair",
            building(stairs=("A",)),
            building_populations(),
            GREY,
            ":",
        ),
    ]
    fig, ax = plt.subplots(figsize=(7, 4.2))
    for label, net, pops, color, ls in cases:
        r = NetworkSimulation(net, pops).run(seed=1)
        e = np.sort(r.exit_times)
        ax.step(
            e,
            np.arange(1, len(e) + 1),
            where="post",
            color=color,
            ls=ls,
            lw=2,
            label=f"{label}: {r.evacuation_time:.1f} s",
        )
    ax.set(
        xlabel="time (s)",
        ylabel="agents evacuated",
        title="Equal-distance exits are not split",
    )
    ax.legend(loc="lower right", fontsize=8)
    frame(ax)
    fig.savefig(out / "route_tie.png")
    plt.close(fig)


def monte_carlo(out, runs=300):
    pre = LogNormal(120.0, 60.0, upper=600.0)
    pops = building_populations(pre=pre, split="AB")
    mc = NetworkSimulation(building(), pops).run_many(runs, seed=11)
    t = mc.complete
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.hist(t, bins=30, color=PAL[2], edgecolor="white")
    for q, ls in [(0.5, "--"), (0.95, "-")]:
        v = mc.quantile(q)
        ax.axvline(v, color=RED, ls=ls, lw=1.2)
        ax.text(
            v,
            ax.get_ylim()[1] * 0.95,
            f" {int(q * 100)} %: {v:.0f} s",
            color=RED,
            fontsize=8.5,
            va="top",
        )
    ax.set(
        xlabel="evacuation time (s)",
        ylabel="runs",
        title=f"{runs} runs, pre-movement LogNormal(120 s, 60 s)",
    )
    ax.grid(alpha=0.4, axis="y")
    fig.savefig(out / "monte_carlo.png")
    plt.close(fig)


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    style()
    schematic(out)
    fundamental(out)
    door_and_merge(out)
    density_sweep(out)
    route_tie(out)
    monte_carlo(out)


if __name__ == "__main__":
    main()
