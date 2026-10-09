"""Animations of the network model: agent mechanics and a building.

Writes ``mechanics.gif`` and ``building.gif`` to ``_static/network`` or to
the directory given as the first argument. ``jupedsim_network`` must be
importable.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from make_figures import DEFAULT_OUT, GREY, ORANGE, PAL, RED, style
from matplotlib.animation import FuncAnimation, PillowWriter
from matplotlib.colors import Normalize
from matplotlib.patches import Rectangle
from scenarios import building, building_populations, merge_corridor, trace

from jupedsim_network import NetworkSimulation, Population, Uniform
from jupedsim_network.simulation import _QUEUED, _SAFE, _WAITING, _WALKING

STATE_COLOR = {
    _WAITING: "#b0b0b0",
    _WALKING: PAL[3],
    _QUEUED: RED,
    _SAFE: "#33a02c",
}

# Drawing layout of the merge scenario (illustrative positions only).
ROOMS = {"a": (0, 4.2, 6, 3), "b": (0, 0, 6, 3), "corridor": (7.6, 2.1, 3, 3)}
DOORS = {
    "a->corridor": (6.0, 5.7),
    "b->corridor": (6.0, 1.5),
    "corridor->exit": (10.6, 3.6),
}
ENTRY = {"a": None, "b": None, "corridor": (7.6, 3.6)}


def queue_slot(door, rank):
    row, col = divmod(rank, 3)
    return door[0] - 0.35 * (row + 1), door[1] + 0.35 * (col - 1)


def mechanics_positions(sim, frames, rng):
    """Map node, state and remaining distance to illustrative xy."""
    net = sim.network
    names = [n.name for n in net.nodes]
    links = [lk.name for lk in net.links]
    n = len(frames[0]["node"])
    spot = {
        k: np.column_stack(
            [
                rng.uniform(x + 0.3, x + w - 0.6, n),
                rng.uniform(y + 0.3, y + h - 0.3, n),
            ]
        )
        for k, (x, y, w, h) in ROOMS.items()
    }
    d0 = np.ones(n)
    seen = np.full(n, -1)
    out = []
    for f in frames:
        fresh = f["node"] != seen
        d0[fresh] = np.maximum(f["distance"][fresh], 1e-6)
        seen = f["node"].copy()
        xy = [agent_xy(i, f, names, links, spot, d0) for i in range(n)]
        out.append(np.array(xy, dtype=float))
    return out


def agent_xy(i, f, names, links, spot, d0):
    state, node = f["state"][i], names[f["node"][i]]
    if state == _SAFE:
        return 11.6 + 0.3 * (i % 5), 0.3 + 0.3 * (i // 5) * 0.5
    door = DOORS[links[f["link"][i]]]
    if state == _QUEUED:
        same = (f["state"] == _QUEUED) & (f["link"] == f["link"][i])
        order = np.flatnonzero(same)[
            np.argsort(f["arrival"][same], kind="stable")
        ]
        return queue_slot(door, int(np.flatnonzero(order == i)[0]))
    start = ENTRY[node] if ENTRY[node] is not None else spot[node][i]
    frac = np.clip(f["distance"][i] / d0[i], 0, 1)
    return door[0] + frac * (start[0] - door[0]), door[1] + frac * (
        start[1] - door[1]
    )


def mechanics(out):
    pops = [
        Population(
            r, 40, pre_movement=Uniform(0, 8), start_distance=Uniform(1, 12)
        )
        for r in "ab"
    ]
    sim = NetworkSimulation(merge_corridor(), pops)
    run, frames = trace(sim, seed=4)
    xy = mechanics_positions(sim, frames, np.random.default_rng(0))
    corridor = sim.network.node("corridor").index
    fig = plt.figure(figsize=(9.5, 4.6))
    ax = fig.add_axes([0.0, 0.0, 0.72, 0.9])
    bar = fig.add_axes([0.78, 0.15, 0.18, 0.65])
    for name, (x, y, w, h) in ROOMS.items():
        ax.add_patch(Rectangle((x, y), w, h, fc="#f3f7f8", ec="#324465"))
        ax.text(x + 0.1, y + h - 0.1, name, va="top", fontsize=9, color=GREY)
    ax.add_patch(Rectangle((11.3, 0), 1.8, 7.2, fc="#e9f4e4", ec="#33a02c"))
    ax.text(11.4, 7.1, "safe", va="top", fontsize=9, color=GREY)
    for door in DOORS.values():
        ax.plot(
            [door[0], door[0]],
            [door[1] - 0.35, door[1] + 0.35],
            color=ORANGE,
            lw=4,
            solid_capstyle="butt",
        )
    ax.set(xlim=(-0.2, 13.3), ylim=(-0.2, 7.4), aspect="equal")
    ax.axis("off")
    dots = ax.scatter(
        *xy[0].T, s=22, c=[STATE_COLOR[s] for s in frames[0]["state"]], zorder=3
    )
    title = fig.text(0.02, 0.95, "", fontsize=11, weight="semibold")
    for s, label in [
        (_WAITING, "pre-movement"),
        (_WALKING, "walking"),
        (_QUEUED, "queued at door"),
        (_SAFE, "safe"),
    ]:
        ax.scatter([], [], c=STATE_COLOR[s], s=22, label=label)
    ax.legend(
        loc="lower center", ncol=4, fontsize=8, bbox_to_anchor=(0.45, -0.05)
    )
    cap = sim.max_density * 4.0
    bar.set(
        xlim=(0, 1),
        ylim=(0, 3.3),
        xticks=[],
        ylabel="corridor density (1/m²)",
        title="corridor\n(shaded: inflow reduced)",
    )
    bar.axhspan(1.88, 2.75, color=ORANGE, alpha=0.15)
    bar.axhline(2.75, color=RED, lw=1)
    bar.text(0.5, 2.8, "max_density", ha="center", fontsize=8, color=RED)
    level = bar.bar([0.5], [0], width=0.6, color=PAL[3])[0]

    def update(k):
        f = frames[k]
        dots.set_offsets(xy[k])
        dots.set_color([STATE_COLOR[s] for s in f["state"]])
        inside = f["state"] != _SAFE
        load = np.sum(f["node"][inside] == corridor)
        level.set_height(load / 4.0)
        title.set_text(
            f"t = {f['t']:5.1f} s   ·   corridor {load} / "
            f"{cap:.0f} agents   ·   merge weights a : b = 1 : 3"
        )
        return dots, level, title

    anim = FuncAnimation(fig, update, frames=len(frames), blit=False)
    anim.save(out / "mechanics.gif", writer=PillowWriter(fps=8), dpi=80)
    plt.close(fig)


def building_cells(ax, floors):
    """Rectangles and count labels for stair A, the floor and stair B."""
    columns = {"A": 0.0, "F": 1.2, "B": 4.4}
    widths = {"A": 1.0, "F": 3.0, "B": 1.0}
    cells, labels = {}, {}
    names = [(f"{c}{f}", c, f) for f in range(1, floors + 1) for c in "AFB"]
    for name, col, f in names:
        rect = Rectangle(
            (columns[col], f - 1), widths[col], 0.9, ec="white", lw=1
        )
        ax.add_patch(rect)
        cells[name] = rect
        labels[name] = ax.text(
            columns[col] + widths[col] / 2,
            f - 0.55,
            "",
            ha="center",
            va="center",
            fontsize=7,
        )
    return cells, labels


def shade_cell(rect, label, density, count, color):
    rect.set_facecolor(color)
    label.set_text(str(count) if count else "")
    label.set_color("white" if density > 1.2 else "#1f253f")


def shade_cells(cells, labels, names, density, occupancy, color):
    for name, rect in cells.items():
        j = names.index(name)
        shade_cell(
            rect, labels[name], density[j], occupancy[j], color(density[j])
        )


def building_gif(out, floors=10, every=5):
    net = building(floors=floors)
    pops = building_populations(floors=floors, split="AB")
    sim = NetworkSimulation(net, pops)
    r = sim.run(seed=1)
    names = list(r.node_names)
    area = np.array([n.area for n in net.nodes])
    density = r.node_occupancy / np.where(np.isfinite(area), area, 1)
    exits = np.sort(r.exit_times)
    fig = plt.figure(figsize=(9.5, 5.2))
    ax = fig.add_axes([0.02, 0.05, 0.42, 0.85])
    cur = fig.add_axes([0.55, 0.14, 0.42, 0.72])
    norm = Normalize(0, 2.75)
    cmap = plt.get_cmap("magma_r")
    cells, labels = building_cells(ax, floors)
    ax.text(0.5, -0.5, "stair A", ha="center", fontsize=8, color=GREY)
    ax.text(4.9, -0.5, "stair B", ha="center", fontsize=8, color=GREY)
    ax.text(
        2.7,
        -0.5,
        "floors (60 agents each)",
        ha="center",
        fontsize=8,
        color=GREY,
    )
    ax.set(xlim=(-0.1, 5.5), ylim=(-0.8, floors + 0.2))
    ax.axis("off")
    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(
        sm, ax=ax, orientation="horizontal", fraction=0.04, pad=0.0, aspect=30
    )
    cb.set_label("density (1/m²)", color=GREY, fontsize=8)
    cb.ax.tick_params(labelsize=7, length=0, labelcolor=GREY)
    cur.step(
        exits,
        np.arange(1, len(exits) + 1),
        where="post",
        color="lightgrey",
        lw=2,
    )
    (line,) = cur.step([], [], where="post", color=PAL[3], lw=2)
    marker = cur.axvline(0, color=RED, lw=1)
    cur.set(
        xlabel="time (s)",
        ylabel="agents evacuated",
        title="evacuated over time",
    )
    cur.grid(alpha=0.4)
    title = fig.text(0.02, 0.95, "", fontsize=11, weight="semibold")

    def update(k):
        i = k * every
        t = r.times[i]
        shade_cells(
            cells,
            labels,
            names,
            density[i],
            r.node_occupancy[i],
            lambda d: cmap(norm(d)),
        )
        done = exits[exits <= t]
        line.set_data(
            np.append(done, t),
            np.append(np.arange(1, len(done) + 1), len(done)),
        )
        marker.set_xdata([t, t])
        title.set_text(
            f"t = {t:5.0f} s   ·   two stairs, half of each "
            f"floor to each   ·   pre-movement U(30, 120) s"
        )
        return list(cells.values())

    n = (len(r.times) - 1) // every + 1
    anim = FuncAnimation(fig, update, frames=n, blit=False)
    anim.save(out / "building.gif", writer=PillowWriter(fps=10), dpi=70)
    plt.close(fig)


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)
    style()
    mechanics(out)
    building_gif(out)


if __name__ == "__main__":
    main()
