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
from matplotlib.patches import (
    Circle,
    ConnectionPatch,
    FancyArrowPatch,
    FancyBboxPatch,
    Rectangle,
)
from scenarios import building, building_populations, merge_corridor

from jupedsim_network import (
    LogNormal,
    Network,
    NetworkSimulation,
    Population,
    hydraulic,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "examples"))
import office_wing  # noqa: E402

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


# Office wing example (examples/office_wing.py). Plan coordinates in m:
# x runs east along the wing, y north. Rooms lie south of the corridor,
# the stair north of its east end.
OFFICE_PLAN = {
    "U": {
        "U1": (0.0, 0.0),
        "U2": (9.0, 0.0),
        "TR": (18.0, 0.0),
        "UW": (0.0, 7.0),
        "UE": (18.0, 7.0),
    },
    "G": {
        "G1": (0.0, 0.0),
        "G2": (9.0, 0.0),
        "G3": (18.0, 0.0),
        "G4": (27.0, 0.0),
        "GW": (0.0, 7.0),
        "GE": (18.0, 7.0),
    },
}
OFFICE_TEXT = {"TR": "60 people"}
STAIR_XY = (33.4, 9.0)
STAIR_SIZE = (
    2 * office_wing.FLIGHT_WIDTH,
    office_wing.FLIGHT_GOING + office_wing.LANDING_DEPTH,
)
# Per floor: link -> door centre, wall orientation ("h" or "v") and the
# position of the width label.
OFFICE_DOORS = {
    "U": {
        ("U1", "UW"): ((4.5, 7.0), "h", (5.2, 6.3, "left")),
        ("U2", "UW"): ((13.5, 7.0), "h", (14.2, 6.3, "left")),
        ("TR", "UE"): ((27.0, 7.0), "h", (27.7, 6.3, "left")),
        ("UE", "stair"): ((34.0, 9.0), "h", (33.1, 9.7, "right")),
    },
    "G": {
        ("G1", "GW"): ((4.5, 7.0), "h", (5.2, 6.3, "left")),
        ("G2", "GW"): ((13.5, 7.0), "h", (14.2, 6.3, "left")),
        ("G3", "GE"): ((22.5, 7.0), "h", (23.2, 6.3, "left")),
        ("G4", "GE"): ((31.5, 7.0), "h", (32.2, 6.3, "left")),
        ("GW", "main"): ((0.0, 8.0), "v", (-0.6, 9.7, "center")),
        ("GE", "side"): ((36.0, 8.0), "v", (36.4, 9.6, "left")),
        ("stair", "GE"): ((35.0, 9.0), "h", (33.1, 9.7, "right")),
    },
}
SAFE_XY = {"main": (-3.6, 8.0), "side": (39.6, 8.0)}
WALL = "#1f253f"
DOOR_BLUE = PAL[3]
EXIT_GREEN = "#1b7837"
STAIR_ORANGE = "#d9622b"
PLAN_FONT = 14
# Link colour, line style and width: colour plus a second cue.
OFFICE_LINK_STYLE = {
    "door": (DOOR_BLUE, "-", 1.8),
    "exit": (EXIT_GREEN, "-", 3.2),
    "stair": (STAIR_ORANGE, "--", 1.8),
}


def office_rooms(floor):
    """Plan rectangles (x, y, length, width) of one floor."""
    rooms = {}
    for name, (x, y) in OFFICE_PLAN[floor].items():
        length, width = office_wing.ROOMS[name]
        rooms[name] = (x, y, length, width)
    return rooms


def office_check_plan(net):
    """Fail if the drawing and the network of the example disagree."""
    for floor in OFFICE_PLAN:
        for name, (_, _, w, h) in office_rooms(floor).items():
            assert abs(w * h - net.node(name).area) < 1e-9, name
    stair = STAIR_SIZE[0] * STAIR_SIZE[1]
    assert abs(stair - net.node("stair").area) < 0.05
    links = {(s, t) for s, t, *_ in office_wing.LINKS}
    for doors in OFFICE_DOORS.values():
        assert set(doors) <= links


def office_widths():
    return {(s, t): w for s, t, _, w, _ in office_wing.LINKS}


def node_xy(floor, name):
    if name == "stair":
        return (STAIR_XY[0] + STAIR_SIZE[0] / 2, STAIR_XY[1] + 1.9)
    if name in SAFE_XY:
        return SAFE_XY[name]
    x, y, w, h = office_rooms(floor)[name]
    return (x + w / 2, y + h / 2)


def plan_room(ax, name, rect):
    x, y, w, h = rect
    corridor = h < 3
    ax.add_patch(
        Rectangle(
            (x, y),
            w,
            h,
            fc="#eef3f5" if corridor else "white",
            ec=WALL,
            lw=1.6,
            zorder=1,
        )
    )
    cx, cy = x + w / 2, y + h / 2
    if corridor:
        ax.text(cx, 9.5, name, fontsize=PLAN_FONT, ha="center", va="bottom")
        return
    ax.text(cx + 0.8, cy, name, fontsize=PLAN_FONT, va="center", ha="left")
    text = OFFICE_TEXT.get(name, "6 people")
    ax.text(cx, 1.5, text, ha="center", va="center", fontsize=12, color=GREY)


def plan_stair(ax):
    sx, sy = STAIR_XY
    ax.add_patch(
        Rectangle(STAIR_XY, *STAIR_SIZE, fc="#fde4d4", ec=WALL, lw=1.6)
    )
    for i in range(10):
        y = sy + 0.2 + i * office_wing.TREAD
        ax.plot(
            [sx, sx + STAIR_SIZE[0]], [y, y], color="#c46a3a", lw=0.6, zorder=1
        )
    ax.plot(
        [sx + STAIR_SIZE[0] / 2] * 2,
        [sy, sy + office_wing.FLIGHT_GOING + 0.2],
        color=WALL,
        lw=1.0,
    )


def plan_door(ax, door, width, color):
    (x, y), wall, (tx, ty, ha) = door
    half = width / 2
    if wall == "h":
        seg = ([x - half, x + half], [y, y])
    else:
        seg = ([x, x], [y - half, y + half])
    ax.plot(*seg, color="white", lw=3.4, zorder=2, solid_capstyle="butt")
    ax.text(
        tx,
        ty,
        f"{width:g}",
        fontsize=PLAN_FONT,
        color=color,
        ha=ha,
        va="center",
        zorder=6,
        fontweight="semibold",
    )


def plan_node(ax, xy, kind):
    marker = {"room": "o", "stair": "s", "safe": "^"}[kind]
    color = {"room": PAL[4], "stair": STAIR_ORANGE, "safe": EXIT_GREEN}[kind]
    ax.plot(*xy, marker=marker, ms=9, color=color, mec="white", zorder=7)


def plan_link(ax, points, color, ls="-", lw=1.8):
    xs, ys = zip(*points)
    ax.plot(xs[:-1], ys[:-1], color=color, ls=ls, lw=lw, zorder=5)
    ax.add_patch(
        FancyArrowPatch(
            points[-2],
            points[-1],
            arrowstyle="-|>",
            mutation_scale=13,
            color=color,
            lw=lw,
            ls=ls,
            shrinkA=0,
            shrinkB=6,
            zorder=5,
        )
    )


def office_link_kind(link):
    if link[0] == "stair":
        return "stair"
    return "exit" if link[1] in SAFE_XY else "door"


def plan_floor(ax, floor, title):
    widths = office_widths()
    for name, rect in office_rooms(floor).items():
        plan_room(ax, name, rect)
        plan_node(ax, node_xy(floor, name), "room")
    plan_stair(ax)
    plan_node(ax, node_xy(floor, "stair"), "stair")
    for link, door in OFFICE_DOORS[floor].items():
        color, ls, lw = OFFICE_LINK_STYLE[office_link_kind(link)]
        plan_door(ax, door, widths[link], color)
        plan_link(ax, office_link_path(floor, link, door), color, ls, lw)
    # Corridor halves are separate nodes; the dashed line is not a wall.
    ax.plot([18, 18], [7, 9], color=GREY, lw=1.0, ls=(0, (3, 2)), zorder=2)
    ax.set_title(title, loc="left", fontsize=14)
    ax.set_xlim(-6.0, 42.0)
    ax.set_ylim(-2.6, 13.0)
    ax.set_aspect("equal")
    ax.axis("off")


def office_link_path(floor, link, door):
    """Arrow from the source node through the door into the target."""
    (x, y), wall, _ = door
    src, dst = (node_xy(floor, n) for n in link)
    if link[0] == "stair":
        return [src, (x, y + 0.4), (x, 8.3)]
    if wall == "v":
        return [src, (x, y), dst]
    if link[1] == "stair":
        return [src, (x, src[1]), (x, dst[1])]
    return [src, (x, y), dst]


def plan_dimension(ax, a, b, text, offset):
    ax.annotate(
        "",
        xy=a,
        xytext=b,
        arrowprops=dict(arrowstyle="<->", color=GREY, lw=0.8),
    )
    mid = ((a[0] + b[0]) / 2 + offset[0], (a[1] + b[1]) / 2 + offset[1])
    ax.text(*mid, text, fontsize=11.5, color=GREY, ha="center", va="center")


def office_plan_legend(fig):
    def line(**kw):
        return plt.Line2D([], [], **kw)

    handles = [
        line(marker="o", ls="", color=PAL[4], ms=8, label="room node"),
        line(color=DOOR_BLUE, lw=1.8, label="door, width in m"),
        line(marker="s", ls="", color=STAIR_ORANGE, ms=8, label="stair node"),
        line(color=STAIR_ORANGE, lw=1.8, ls="--", label="stair link"),
        line(marker="^", ls="", color=EXIT_GREEN, ms=8, label="safe node"),
        line(color=EXIT_GREEN, lw=3.2, label="exit door"),
    ]
    fig.legend(
        handles=handles,
        loc="upper center",
        ncol=3,
        fontsize=11,
        bbox_to_anchor=(0.5, 0.06),
        handlelength=1.6,
        columnspacing=1.0,
    )


def office_plan(out):
    office_check_plan(office_wing.build_network())
    fig, (up, gr) = plt.subplots(2, 1, figsize=(5.6, 5.4))
    plan_floor(up, "U", "Upper floor")
    plan_floor(gr, "G", "Ground floor")
    plan_link(up, [node_xy("U", "UW"), node_xy("U", "UE")], DOOR_BLUE)
    gw, ge = node_xy("G", "GW"), node_xy("G", "GE")
    gr.add_patch(
        FancyArrowPatch(
            (gw[0] + 1.0, 8.45),
            (ge[0] - 1.0, 8.45),
            arrowstyle="<|-|>",
            mutation_scale=10,
            color=DOOR_BLUE,
            lw=1.2,
            zorder=5,
        )
    )
    for name, xy in SAFE_XY.items():
        plan_node(gr, xy, "safe")
        gr.text(xy[0], xy[1] - 1.0, name, ha="center", va="top", fontsize=12)
    # One stair node spans both floors: agents walk down inside it.
    dotted = dict(color=STAIR_ORANGE, lw=1.2, ls=(0, (1, 1.5)), zorder=3)
    up.plot([35.8, 38.0], [10.9, 10.9], **dotted)
    gr.plot([38.0, 35.8], [10.9, 10.9], **dotted)
    fig.add_artist(
        ConnectionPatch(
            (38.0, 10.9),
            (38.0, 10.9),
            coordsA=up.transData,
            coordsB=gr.transData,
            **dotted,
        )
    )
    up.text(38.5, 11.6, "stair\nnode", fontsize=12, color=STAIR_ORANGE)
    plan_dimension(gr, (0, -1.2), (36, -1.2), "36 m", (0, -0.9))
    plan_dimension(gr, (-1.0, 0), (-1.0, 7), "7 m", (-1.6, 0))
    plan_dimension(up, (-1.0, 7), (-1.0, 9), "2 m", (-1.6, 0))
    plan_dimension(up, (0, -1.2), (9, -1.2), "9 m", (0, -0.9))
    office_plan_legend(fig)
    fig.tight_layout(h_pad=0.2)
    fig.savefig(out / "office_plan.png")
    plt.close(fig)


def office_run(side_door=0.9):
    return office_wing.simulation(side_door=side_door).run(seed=1)


def office_capacity(link):
    net = office_wing.build_network()
    return next(lk.capacity for lk in net.links if lk.name == link)


def office_flow(r, links):
    """Cumulative number of agents through ``links``."""
    columns = [r.link_names.index(name) for name in links]
    return np.cumsum(r.link_flow[:, columns].sum(axis=1))


def office_evacuated(out):
    base, wide = office_run(0.9), office_run(1.2)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    lines = [
        (
            base,
            None,
            PAL[4],
            "-",
            f"all, side door 0.9 m ({base.evacuation_time:.1f} s)",
        ),
        (base, "GE->side", RED, "--", "through the side door"),
        (base, "GW->main", GREY, ":", "through the main door"),
        (
            wide,
            None,
            ORANGE,
            "-.",
            f"all, side door 1.2 m ({wide.evacuation_time:.1f} s)",
        ),
    ]
    for r, link, color, ls, label in lines:
        y = office_flow(r, [link] if link else ["GW->main", "GE->side"])
        ax.step(r.times, y, where="post", color=color, ls=ls, lw=2, label=label)
    capacity = office_capacity("GE->side")
    side = office_flow(base, ["GE->side"])
    at = int(0.8 * len(side))
    ax.annotate(
        f"side door at capacity,\n{capacity:.2f} persons/s",
        (base.times[at], side[at]),
        (base.times[at], side[at] * 0.45),
        fontsize=9,
        color=RED,
        ha="center",
        arrowprops=dict(arrowstyle="-", color=RED, lw=0.8),
    )
    ax.set(
        xlabel="time (s)",
        ylabel="agents safe",
        title="Agents safe over time, seed 1",
        xlim=(0, None),
    )
    ax.legend(loc="upper left", fontsize=9)
    frame(ax)
    fig.savefig(out / "office_evacuated.png")
    plt.close(fig)


def office_occupancy(out):
    r = office_run(0.9)
    fig, ax = plt.subplots(figsize=(6.4, 4.2))
    for node, color, ls, label in [
        ("TR", PAL[2], "-", "TR, training room"),
        ("UE", PAL[4], ":", "UE, upper corridor east"),
        ("stair", ORANGE, "-.", "stair"),
        ("GE", RED, "--", "GE, ground corridor east"),
    ]:
        y = r.node_occupancy[:, r.node_names.index(node)]
        ax.plot(r.times, y, color=color, ls=ls, lw=2, label=label)
    ge = r.node_occupancy[:, r.node_names.index("GE")]
    tr = r.node_occupancy[:, r.node_names.index("TR")]
    top, half = int(np.argmax(ge)), int(np.argmin(np.abs(tr - 40)))
    ax.annotate(
        "queue at the side door",
        (r.times[top], ge[top]),
        (r.times[top] + 10, ge[top] + 11),
        fontsize=9,
        color=RED,
        ha="center",
        arrowprops=dict(arrowstyle="-", color=RED, lw=0.8),
    )
    ax.annotate(
        "queue at the\ntraining-room door",
        (r.times[half], tr[half]),
        (2, 28),
        fontsize=9,
        color=PAL[2],
        ha="left",
        arrowprops=dict(arrowstyle="-", color=PAL[2], lw=0.8),
    )
    ax.set(
        xlabel="time (s)",
        ylabel="agents in the space",
        title="Where the agents wait, seed 1",
        xlim=(0, None),
    )
    ax.legend(loc="upper right", fontsize=9)
    frame(ax)
    fig.savefig(out / "office_occupancy.png")
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
    office_plan(out)
    office_evacuated(out)
    office_occupancy(out)


if __name__ == "__main__":
    main()
