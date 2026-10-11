# SPDX-License-Identifier: LGPL-3.0-or-later
"""Every number on the documentation pages that a run produces.

Each registry entry names a page, a text as printed there (runs of
whitespace count as one space) and a producer that rebuilds that text
from the code. The test asserts that the page contains the text and that
the producer returns it exactly, so a code change that moves a number
fails, and so does a page edit that no longer matches the code. This is
separate from the verification tests, which compare with hand values
within tolerances.

The python blocks of the snippet pages run as printed, in page order,
and must print the ``text`` block that follows them.

Timings ("about 0.1 s") are not documented numbers and are not checked.
Entries marked ``slow`` (the 300-run case study, the max_density sweep
and the snippets that call ``run_many(500)``) run in their own CI job;
``uv run pytest -m slow`` runs them.
"""

import contextlib
import functools
import io
import json
import math
import os
import pathlib
import re
import sys
import tempfile
import warnings
from dataclasses import dataclass

import docpages
import numpy as np
import pytest
import test_evacuationz_verification as enz
import test_network as tn

from jupedsim_network import (
    Fixed,
    LogNormal,
    Network,
    NetworkSimulation,
    Normal,
    Population,
    Triangular,
    Uniform,
    hydraulic,
)

sys.path.insert(0, str(docpages.ROOT / "scripts" / "figures"))
import scenarios  # noqa: E402

# Snippet pages ----------------------------------------------------------------

# Python blocks that run, by index among the page's python blocks; the
# others show signatures. Pages in one group share their names (results
# and running continue the getting-started scenario). The first group
# calls run_many(500) on two simulations, so it runs in the slow job.
SNIPPETS = [
    [
        ("getting-started.md", (0, 1, 2)),
        ("using/results.md", (0,)),
        ("using/running.md", (1, 2, 3, 4)),
        ("using/command-line.md", (0,)),
    ],
    [("using/populations.md", (2,))],
]
SLOW_GROUPS = {0}


@dataclass
class Snippet:
    page: str
    code: str
    stdout: str
    warnings: list
    shown: list


def _shown_after(page):
    """Text blocks that follow each python block, before the next one."""
    shown, current = {}, None
    count = 0
    for tag, body in docpages.fences(page):
        if tag == "python":
            current, count = count, count + 1
            shown[current] = []
        elif tag == "text" and current is not None:
            shown[current].append(body)
    return shown


def _run_many_once():
    """Wrap run_many so that repeated identical calls run once.

    The pages call ``simulation.run_many(500, seed=1)`` three times; the
    result depends only on the simulation, the run count and the seed
    (P5 in test_properties.py).
    """
    original = NetworkSimulation.run_many
    cache = {}

    # wraps keeps the signature, which the scenario loader reads.
    @functools.wraps(original)
    def run_many(self, runs, seed=None):
        key = (id(self), runs, seed)
        if not isinstance(seed, int) or cache.get(key, (None,))[0] is not self:
            cache[key] = (self, original(self, runs, seed))
        return cache[key][1]

    return run_many


@contextlib.contextmanager
def _in_tmp_dir():
    with tempfile.TemporaryDirectory() as tmp:
        previous = os.getcwd()
        os.chdir(tmp)
        try:
            yield
        finally:
            os.chdir(previous)


@functools.cache
def snippets(group):
    """Run one group of snippet pages once: the blocks, output, names.

    The blocks run in an empty directory, because some write files.
    """
    done, names = [], {}
    with pytest.MonkeyPatch.context() as mp, _in_tmp_dir():
        mp.setattr(NetworkSimulation, "run_many", _run_many_once())
        _run_group(SNIPPETS[group], done, names)
    return done, names


def _run_group(group, done, names):
    namespace = {}
    for page, indices in group:
        done += _run_page(page, indices, namespace)
        names[page] = namespace


def _run_page(page, indices, namespace):
    code = docpages.blocks(page, "python")
    shown = _shown_after(page)
    done = []
    for i in indices:
        out = io.StringIO()
        with (
            warnings.catch_warnings(record=True) as caught,
            contextlib.redirect_stdout(out),
        ):
            warnings.simplefilter("always")
            exec(compile(code[i], f"{page}[{i}]", "exec"), namespace)
        messages = [f"{w.category.__name__}: {w.message}" for w in caught]
        done.append(Snippet(page, code[i], out.getvalue(), messages, shown[i]))
    return done


def _snippet_ids(group):
    return [f"{p}[{i}]" for p, ix in SNIPPETS[group] for i in ix]


def _group_marks(group):
    return [pytest.mark.slow] if group in SLOW_GROUPS else []


def _snippet_params():
    return [
        pytest.param(group, index, marks=_group_marks(group), id=name)
        for group in range(len(SNIPPETS))
        for index, name in enumerate(_snippet_ids(group))
    ]


def _group_params():
    return [
        pytest.param(
            group, marks=_group_marks(group), id=_snippet_ids(group)[0]
        )
        for group in range(len(SNIPPETS))
    ]


@pytest.mark.parametrize(("group", "index"), _snippet_params())
def test_snippet_prints_its_output(group, index):
    snippet = snippets(group)[0][index]
    is_warning = [b.split(":")[0].endswith("Warning") for b in snippet.shown]
    stdout = [b for b, w in zip(snippet.shown, is_warning) if not w]
    shown_warnings = [b.strip() for b, w in zip(snippet.shown, is_warning) if w]
    assert snippet.stdout == "".join(stdout)
    for message in shown_warnings:
        assert message in snippet.warnings


@pytest.mark.parametrize("group", _group_params())
def test_snippets_show_their_output_as_text(group):
    """Every executed block that prints is followed by a text block."""
    for snippet in snippets(group)[0]:
        assert bool(snippet.stdout) == bool(snippet.shown), snippet.code


# Producers --------------------------------------------------------------------

COUNTERFLOW = ("independent", "estimate", "bounding")


def f1(x):
    return f"{x:.1f}"


@functools.cache
def getting_started():
    """The getting-started scenario: network, population, seed-1 run."""
    net = Network()
    net.add_room("office", area=200.0)
    net.add_stair("flight", area=10.8, riser=0.18, tread=0.28)
    net.add_safe("street")
    net.connect("office", "flight", width=0.9, length=25.0, bidirectional=False)
    net.connect(
        "flight",
        "street",
        width=1.2,
        kind="stair",
        length=9.0,
        bidirectional=False,
    )
    pop = Population(
        "office", 120, speed=1.2, pre_movement=LogNormal(120.0, 60.0)
    )
    return net, pop, NetworkSimulation(net, [pop], dt=0.5).run(seed=1)


def at_once(width):
    net = Network()
    net.add_room("office", area=200.0)
    net.add_stair("flight", area=10.8, riser=0.18, tread=0.28)
    net.add_safe("street")
    net.connect(
        "office", "flight", width=width, length=25.0, bidirectional=False
    )
    net.connect(
        "flight",
        "street",
        width=1.2,
        kind="stair",
        length=9.0,
        bidirectional=False,
    )
    sim = NetworkSimulation(net, [Population("office", 120, speed=1.2)])
    return net, sim.run(seed=1)


def getting_started_prose():
    net, _, result = getting_started()
    first, second = at_once(0.9)[1], at_once(1.2)[1]
    door = net.links[0].capacity
    stair = net.links[1].capacity
    return (
        f"In the first run the last agent starts at "
        f"{round(result.pre_movement_times.max(), 1)} s and leaves at "
        f"{result.evacuation_time} s. The pre-movement times set the "
        "evacuation time, and a wider door changes nothing. When everyone "
        f"starts at once, the door decides: the 0.9 m door passes {door:.2f} "
        f"persons/s, and widening it to 1.2 m cuts the time from "
        f"{f1(first.evacuation_time)} s to {f1(second.evacuation_time)} s. "
        f"The stair link, at {stair:.2f} persons/s, is then the narrowest point."
    )


def results_prose():
    _, _, r = getting_started()
    flight = r.node_occupancy[:, r.node_names.index("flight")].max()
    door = r.link_flow[:, r.link_names.index("office->flight")].sum()
    dt = r.times[1] - r.times[0]
    return (
        f"At most {flight} agents are on the flight at once, all {door} pass "
        f"the door, and the run ends at {r.times[-1]} s in steps of {dt} s."
    )


def running_replay():
    names = snippets(0)[1]["using/running.md"]
    worst = int(np.nanargmax(names["runs"].evacuation_times))
    return f"`replay` is a full `SimulationResult` of run {worst}"


def running_dt():
    net, pop, _ = getting_started()
    times = [
        NetworkSimulation(net, [pop], dt=dt).run(seed=1).evacuation_time
        for dt in (1.0, 0.1)
    ]
    return (
        f"Here the result changes by {abs(times[0] - times[1]):.1f} s between "
        "1.0 s and 0.1 s."
    )


def running_short():
    names = snippets(0)[1]["using/running.md"]
    cut, full = names["cut"], names["runs"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        same = cut.quantile(0.5) == full.quantile(0.5)
    word = "the same" if same else "not the same"
    return (
        f"The median is {word} as with the default `t_max`. The 95th "
        f"percentile needs some of the {cut.incomplete} unfinished runs"
    )


def zero_length_chain(links=6):
    """One agent through six zero-length links in a row."""
    net = Network()
    names = [f"n{i}" for i in range(links)]
    for name in names:
        net.add_room(name, area=10.0)
    net.add_safe("exit")
    for a, b in zip(names, names[1:] + ["exit"]):
        net.connect(a, b, width=1.0, bidirectional=False)
    t = (
        NetworkSimulation(net, [Population("n0", 1)])
        .run(seed=1)
        .evacuation_time
    )
    return f"zero-length links in a row take {t} s at $\\Delta t = 0.5$ s"


# The full-node example of #55 (limitations.md, Numerics).
LOBBY = dict(
    agents=200,
    speed=1.2,
    room=100.0,
    door=(2.0, 0.3),
    lobby=4.0,
    opening=(4.0, 10.0),
)
FINE_DT = 1 / 64


@functools.cache
def lobby_time(dt, max_density, supply_reduction):
    p = LOBBY
    net = Network()
    net.add_room("room", area=p["room"])
    net.add_room("lobby", area=p["lobby"])
    net.add_safe("exit")
    width, length = p["door"]
    net.connect(
        "room", "lobby", width=width, length=length, bidirectional=False
    )
    width, length = p["opening"]
    net.connect(
        "lobby",
        "exit",
        width=width,
        kind="opening",
        length=length,
        bidirectional=False,
    )
    pop = Population("room", p["agents"], speed=p["speed"])
    sim = NetworkSimulation(
        net,
        [pop],
        dt=dt,
        max_density=max_density,
        supply_reduction=supply_reduction,
    )
    return sim.run(seed=1).evacuation_time


def _lobby_error(max_density, supply_reduction):
    """T at dt 0.5 and 1/64, and the relative error in %, unsigned."""
    coarse = lobby_time(0.5, max_density, supply_reduction)
    fine = lobby_time(FINE_DT, max_density, supply_reduction)
    side = "short" if coarse < fine else "on the long side"
    return coarse, fine, f"{abs(coarse - fine) / fine * 100:.1f} % {side}"


def lobby_numbers():
    p = LOBBY
    (dw, dl), (ow, ol) = p["door"], p["opening"]
    coarse1, fine1, e1 = _lobby_error(3.5, False)
    coarse2, fine2, e2 = _lobby_error(2.75, True)
    return (
        f"In this example, {p['agents']} agents (`speed={p['speed']}`, no "
        f"pre-movement, `start_distance=0`) leave a {p['room']:g} m² room "
        f"through a one-way {dw:g} m door of length {dl:g} m into a "
        f"{p['lobby']:g} m² lobby, which leads through a one-way {ow:g} m "
        f"opening of length {ol:g} m to a safe node.",
        f"the evacuation time is {f1(coarse1)} s at $\\Delta t = 0.5$ s "
        f"against {f1(fine1)} s at $\\Delta t = 1/{1 / FINE_DT:g}$ s, {e1}. With the "
        f"defaults (2.75 m⁻², supply reduction on) the same network gives "
        f"{f1(coarse2)} s against {f1(fine2)} s, {e2}.",
    )


def full_node_threshold():
    """1/(2a) + 1/(2A) for the lobby of the full-node example."""
    area = LOBBY["lobby"]
    density = hydraulic.PEAK_FLOW_DENSITY + 1 / (2 * area)
    return (
        f"plus half an agent per node area: {density:.1f} m⁻² for a "
        f"{area:g} m² node"
    )


def lobby_halving():
    """ "Halving dt roughly halves the error", for (3.5, supply off)."""
    fine = lobby_time(FINE_DT, 3.5, False)
    ratio = (lobby_time(0.5, 3.5, False) - fine) / (
        lobby_time(0.25, 3.5, False) - fine
    )
    word = "roughly halves" if 1.8 < ratio < 2.3 else f"divides by {ratio:.2f}"
    return f"In the first case, halving $\\Delta t$ {word} the error."


def ci_docs_numbers():
    """verification.md on CI: the docs-numbers job runs ``-m slow`` and
    deploy needs it."""
    ci = (docpages.ROOT / ".github" / "workflows" / "ci.yml").read_text()
    job = re.search(r"\n  docs-numbers:\n((?:    .*\n|\n)*)", ci)
    slow = r"uv run (?:--extra \S+ )*pytest -m slow"
    runs_slow = job is not None and re.search(slow, job.group(1)) is not None
    needs = re.search(r"\n  deploy:\n(?:    .*\n)*?    needs: \[(.*)\]", ci)
    gated = needs is not None and "docs-numbers" in needs.group(1).split(", ")
    name = "`docs-numbers`" if runs_slow else "(no slow job)"
    when = "only when it passes" if gated else "without waiting for it"
    return f"CI runs it as its own job, {name}, and the site deploys {when}."


def populations_walk():
    net = Network()
    net.add_room("corridor", area=100.0)
    net.add_safe("exit")
    net.connect("corridor", "exit", width=2.0, kind="opening", length=40.0)
    sim = NetworkSimulation(net, [Population("corridor", 1, speed=1.5)])
    t = sim.run(seed=1).evacuation_time
    level = hydraulic.speed(0.0, hydraulic.LEVEL_SPEED_CONSTANT)
    return f"A 40 m walk at `speed=1.5` takes {t} s, which is 40 m at {level:.3f} m/s"


def populations_ceilings():
    level = hydraulic.speed(0.0, hydraulic.LEVEL_SPEED_CONSTANT)
    stair = hydraulic.speed(0.0, hydraulic.stair_speed_constant(0.18, 0.28))
    return (
        f"{level:.3f} m/s on level ground, and - {stair:.3f} m/s on an "
        "18/28 cm stair"
    )


def populations_truncation():
    rng = np.random.default_rng(1)
    mean = Normal(10.0, 20.0).sample(rng, 100_000).mean()
    return f"Truncated at 0, `Normal(10, 20)` has a mean of about {mean:.0f}, not 10."


def networks_warning():
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Network().add_stair("flight", area=8.0, riser=0.20, tread=0.28)
    (w,) = caught
    return f"{w.category.__name__}: {w.message}"


def counterflow_two_agents():
    """One agent each way, B's after 0.5 s: the shared carry delays B."""
    net = Network()
    for name in ("A", "B"):
        net.add_room(name, area=200.0)
    net.add_safe("xA")
    net.add_safe("xB")
    net.connect("A", "B", width=1.0)
    net.connect("A", "xA", width=20.0, kind="opening", bidirectional=False)
    net.connect("B", "xB", width=20.0, kind="opening", bidirectional=False)
    pops = [
        Population("A", 1, target="xB"),
        Population("B", 1, pre_movement=0.5, target="xA"),
    ]
    out = {}
    for cf in ("independent", "estimate", "bounding"):
        r = NetworkSimulation(net, pops, counterflow=cf).run(seed=1)
        out[cf] = " and ".join(f"{t} s" for t in sorted(r.exit_times))
    assert out["estimate"] == out["bounding"]
    return (
        f'| `"independent"` | {out["independent"]} | '
        f'| `"estimate"`, `"bounding"` | {out["bounding"]} |'
    )


def counterflow_changes():
    ind, bnd = (
        tn.door_swap(36, 4, "independent"),
        tn.door_swap(36, 4, "bounding"),
    )
    minor = tn.passage_times(bnd, "B->A")
    gaps = np.diff(minor)
    major = [tn.passage_times(r, "A->B")[-1] for r in (ind, bnd)]
    return (
        'Under `"bounding"` the 4 agents of the minor stream pass at '
        f"{', '.join(f1(t) for t in minor[:-1])} and {f1(minor[-1])} s, "
        f"{gaps.min():.1f}–{gaps.max():.1f} s apart, instead of waiting for the "
        "whole opposing queue. The last passage of the major stream moves "
        f'from {major[0]} s (`"independent"`) to {major[1]} s.'
    )


def counterflow_responders():
    runs = {cf: tn.stair_responders(cf) for cf in COUNTERFLOW}
    out = {cf: max(r.exit_times[20:]) for cf, r in runs.items()}
    t = {cf: r.evacuation_time for cf, r in runs.items()}
    return (
        f'The responders are out by {out["bounding"]} s (`"bounding"`) or '
        f'{out["estimate"]} s (`"estimate"`) instead of {out["independent"]} s. '
        f"The evacuees' clearance rises from {t['independent']} s to "
        f"{t['bounding']} s or {t['estimate']} s."
    )


# Verification page.


def imo_rows():
    imo1 = NetworkSimulation(
        tn.single_room(width=2.0, kind="opening", length=40.0),
        [Population("room", 1, speed=1.0)],
    )
    door = NetworkSimulation(
        tn.single_room(area=40.0, specific_flow=1.33),
        [Population("room", 100, speed=1.0)],
    )
    opening = NetworkSimulation(
        tn.single_room(width=0.6, kind="opening"), [Population("room", 50)]
    )
    crowd = NetworkSimulation(
        tn.single_room(width=1000.0, kind="opening", length=20.0),
        [Population("room", 200, speed=1.2)],
    )
    t = [
        f1(s.run(seed=1).evacuation_time) for s in (imo1, door, opening, crowd)
    ]
    return (
        f"| IMO test 1: 40 m at 1.0 m/s | 40 s | {t[0]} s |",
        f"= 106.3$ s | {t[1]} s | 1 s |",
        f"= 62.8$ s | {t[2]} s | 0.5 s |",
        f"= 30.5$ s | {t[3]} s | 0.6 s |",
    )


def imo3(dt):
    net = Network()
    net.add_room("room", area=20.0)
    net.add_stair("flight", area=20.0, riser=0.18, tread=0.28)
    net.add_safe("exit")
    net.connect("room", "flight", width=2.0, kind="stair")
    net.connect("flight", "exit", width=2.0, kind="stair", length=10.0)
    sim = NetworkSimulation(net, [Population("room", 1, speed=2.0)], dt=dt)
    return round(sim.run(seed=1).evacuation_time, 6)


def merge_ratio():
    r = scenarios.merge_run()
    a = r.link_flow[:, r.link_names.index("a->corridor")].sum()
    b = r.link_flow[:, r.link_names.index("b->corridor")].sum()
    return b / a


def merge_stall():
    r = scenarios.merge_run()
    flow = r.link_flow[:, r.link_names.index("a->corridor")]
    passes = r.times[flow > 0]
    i = int(np.argmax(np.diff(passes)))
    last, resume = passes[i], passes[i + 1] - (r.times[1] - r.times[0])
    return f"room a passes no one from {last} s to {resume} s"


def stair_k_row():
    k = hydraulic.stair_speed_constant(0.178, 0.279)
    return f"| {k:.3f}, {hydraulic.max_specific_flow(k):.3f} | 0.01 |"


def steady_density_row():
    means, peaks = [], []
    for width, count, t_max, window in [
        (0.7, 600, 800.0, 500.0),
        (0.9, 900, 1000.0, 800.0),
    ]:
        net = Network()
        net.add_room("C", area=40.0)
        net.add_room("R", area=1000.0)
        net.add_safe("exit")
        net.connect("R", "C", width=1.0, bidirectional=False)
        net.connect("C", "exit", width=width, bidirectional=False)
        r = NetworkSimulation(net, [Population("R", count)], t_max=t_max).run(
            seed=1
        )
        occ = r.node_occupancy[:, r.node_names.index("C")][r.times >= window]
        means.append(f"{occ.mean():.2f}")
        peaks.append(f"{occ.max()}")
    return f"mean {means[0]} and {means[1]}, maximum {peaks[0]} and {peaks[1]}"


def enz_rows():
    net = Network()
    net.add_room("corridor", length=40.0, width=2.0)
    net.add_safe("exit")
    net.connect(
        "corridor",
        "exit",
        width=2.0,
        kind="opening",
        length=40.0,
        specific_flow=enz.FS,
    )
    t = NetworkSimulation(
        net, [Population("corridor", 1, speed=1.0)], dt=enz.DT
    )
    door = enz.room_clearance(Fixed(0.0), 0.0, seed=1)[1].evacuation_time
    return (
        f"| 40 s | 40.5 s | {f1(t.run(seed=1).evacuation_time)} s |",
        f"| 12 s | {f1(imo3(0.1))} s ($\\Delta t = 0.1$ s), {f1(imo3(0.5))} s "
        "($\\Delta t = 0.5$ s) |",
        f"| 108 s | {f1(door)} s |",
    )


def fedg_numbers():
    net, r = enz.fedg()
    first = np.min(r.exit_times)
    cap = enz.stair_fs(enz.STAIR_K) * (1.2 - 0.3)
    room = r.link_flow[:, r.link_names.index("room->stairs")]
    reach = r.times[np.argmax(room > 0)]
    # Hand value of test_fedg_first_exit: 20.1 m in the room, 10 m of stair.
    room_speed = enz.K_LEVEL * (1 - enz.A * 0.9)
    stair_speed = enz.free_speed(enz.STAIR_K)
    free = enz.steps(20.1, room_speed) + enz.steps(10.0, stair_speed)
    stair = r.node_occupancy[:, r.node_names.index("stairs")].max()
    return (
        f"first exit {f1(first)} s; last exit {f1(r.evacuation_time)} s",
        f"Capacity bound ${f1(first)} + 89/{cap:.3f} = {first + 89 / cap:.1f}$ s",
        f"door B at {f1(reach)} s and leaves the stair at {f1(first)} s: "
        f"{f1(free)} s at the free stair speed",
        f"this model gives {f1(r.evacuation_time)} s.",
        f"In this model the stair holds at most {stair} agents.",
    )


@functools.cache
def sfpe(start=0.0, landing_on_stair=False, split_ties=True):
    """The SFPE nine-storey building of test_sfpe_nine_storey, varied."""
    net = Network()
    for s in "RL":
        net.add_safe(f"Exit{s}")
        for f in range(1, 10):
            net.add_room(f"Landing_{f}{s}", length=enz.LANDING, width=1.2)
        net.connect(
            f"Landing_1{s}",
            f"Exit{s}",
            width=0.91,
            length=enz.LANDING,
            bidirectional=False,
            specific_flow=enz.FS,
        )
    for f in range(2, 10):
        net.add_room(f"Corridor_{f}", length=300 * enz.FT, width=8 * enz.FT)
    for f in range(2, 10):
        _sfpe_floor(net, f, landing_on_stair)
    pops = [
        Population(f"Room_{f}.{r}", 150, speed=1.2, start_distance=start)
        for f in range(2, 10)
        for r in (1, 2)
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        sim = NetworkSimulation(net, pops, dt=enz.DT, split_ties=split_ties)
    return sim.run(seed=1)


def _sfpe_floor(net, f, landing_on_stair):
    """``sfpe_floor``; with ``landing_on_stair`` the 4.8 m of landing
    travel are walked on the stair link, and every corridor is 45.5 m."""
    top = f == 9 or landing_on_stair
    for r in (1, 2):
        net.add_room(f"Room_{f}.{r}", length=300 * enz.FT, width=10.8)
        net.connect(
            f"Room_{f}.{r}",
            f"Corridor_{f}",
            width=5.79,
            length=14.12,
            bidirectional=False,
            specific_flow=enz.FS,
        )
    for s in "RL":
        net.add_stair(
            f"Stairs_{f}{s}",
            length=enz.SFPE_STAIR,
            width=1.12,
            riser=0.18,
            tread=0.28,
        )
        net.connect(
            f"Corridor_{f}",
            f"Landing_{f}{s}",
            width=0.91,
            length=45.5 if top else 45.5 - enz.LANDING,
            bidirectional=False,
            specific_flow=enz.FS,
        )
        net.connect(
            f"Landing_{f}{s}",
            f"Stairs_{f}{s}",
            width=1.12,
            kind="stair",
            length=0.0 if top else enz.LANDING,
            bidirectional=False,
        )
        net.connect(
            f"Stairs_{f}{s}",
            f"Landing_{f - 1}{s}",
            width=1.2,
            kind="opening",
            length=enz.SFPE_STAIR + (enz.LANDING if landing_on_stair else 0.0),
            bidirectional=False,
            specific_flow=enz.FS,
        )


def exit_flow(r):
    flow = r.link_flow[:, r.link_names.index("Landing_1R->ExitR")]
    passed = np.cumsum(flow)
    first = r.times[np.argmax(passed >= 1)]
    return (passed[-1] - 1) / (r.times[-1] - first)


def sfpe_landing_row():
    landing = sfpe(landing_on_stair=True).evacuation_time
    return f"With the landing travel walked on the stair link instead, {f1(landing)} s."


def sfpe_numbers():
    base = sfpe()
    start = sfpe(start=Uniform(0, 91.44))
    door = enz.FS * (0.91 - 0.3)
    first = np.min(base.exit_times)
    return (
        f"| {f1(base.evacuation_time)} s | 300 per floor",
        f"${f1(first)} + 1199/{door:.3f}$",
        f"With a start $U(0, 91.44)$ m, {f1(start.evacuation_time)} s (seed 1; "
        f"first exit {f1(np.min(start.exit_times))} s instead of {f1(first)} s",
    )


def sfpe_landing_prose():
    base, landing = sfpe(), sfpe(landing_on_stair=True)
    door = enz.FS * (0.91 - 0.3)
    return (
        f"lowers the exit flow from {door:.3f} to about {exit_flow(landing):.2f} "
        f"persons/s and raises the evacuation time from "
        f"{f1(base.evacuation_time)} s to {f1(landing.evacuation_time)} s"
    )


def guide_numbers():
    t = [enz.guide(start)[1].evacuation_time for start in (0.0, 200 * enz.FT)]
    return (f"| 221.5 s | {f1(t[0])} s |", f"| 283 s | {f1(t[1])} s |")


def guide_unsplit(start):
    """``guide`` with split_ties=False."""
    net, _ = enz.guide(start)
    speed = 275 * enz.FT / 60
    pop = Population("room", 300, speed=speed, start_distance=start)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        sim = NetworkSimulation(net, [pop], dt=enz.DT, split_ties=False)
    return sim.run(seed=1).evacuation_time


def tied_stairs():
    a, b = guide_unsplit(0.0), guide_unsplit(200 * enz.FT)
    sfpe_one = sfpe(split_ties=False).evacuation_time
    return (
        f"leave after {f1(a)} s (start at the door) and {f1(b)} s (start "
        "200 ft away)",
        f"one stair and leave after {f1(sfpe_one)} s.",
    )


def distribution_moments():
    dists = (Uniform(10, 100), Normal(120, 30), LogNormal(5, 2))
    values = [d.sample(np.random.default_rng(1), 20000) for d in dists]
    means = ", ".join(f"{v.mean():.2f}" for v in values)
    sds = ", ".join(f"{v.std():.2f}" for v in values)
    return f"means {means}; sd {sds} (20 000 samples)"


def clearance_numbers():
    fixed = [
        enz.room_clearance(Fixed(d), 0.0, seed=1)[1].evacuation_time
        for d in (0.0, 30.0, 120.0)
    ]
    dispersed = np.array(
        [
            enz.room_clearance(Fixed(0.0), Uniform(0, 8.0), s)[
                1
            ].evacuation_time
            for s in range(20)
        ]
    )
    span = f"{f1(dispersed.min())}–{f1(dispersed.max())} s"
    return (
        f"| {', '.join(f1(t) for t in fixed)} s (start 0) |",
        f"this model gives {f1(fixed[0])} s at the door and {span} with a "
        "dispersed start",
        f"| {span}, mean {dispersed.mean():.1f} s |",
    )


def triangular_numbers():
    times, bounds = [], []
    for mode, upper in [(15, 30), (30, 60), (60, 120)]:
        _, r = enz.room_clearance(Triangular(0, mode, upper), 0.0, seed=0)
        tau = np.sort(r.pre_movement_times)
        bounds.append(
            max(tau[i] + (99 - i) / (enz.FS * 0.7) for i in range(100))
        )
        times.append(r.evacuation_time)
    gaps = np.array(times) - np.array(bounds)
    return (
        f"{', '.join(f'{b:.2f}' for b in bounds)} s",
        f"| {', '.join(f1(t) for t in times)} s |",
        f"Each lies {gaps.min():.2f}–{gaps.max():.2f} s above its bound.",
    )


def door_table():
    rows = []
    for width, kind, label in [
        (1.0, "door", "1 m door"),
        (2.0, "door", "2 m door"),
        (3.0, "door", "3 m door"),
        (1.0, "opening", "1 m opening"),
    ]:
        cells = []
        for n in (1, 10, 100):
            net = Network()
            net.add_room("room", length=8.0, width=5.0)
            net.add_safe("exit")
            net.connect(
                "room",
                "exit",
                width=width,
                kind=kind,
                length=0.1,
                specific_flow=enz.FS,
            )
            sim = NetworkSimulation(
                net, [Population("room", n, speed=1.0)], dt=enz.DT
            )
            cells.append(f"{f1(sim.run(seed=1).evacuation_time)} s")
        rows.append(f"| {label} | {' | '.join(cells)} |")
    return " ".join(rows)


def stair_row(length, width, n):
    net, r = enz.stair_flow(n, length, width)
    peak = r.node_occupancy[:, r.node_names.index("stair")].max()
    limit = math.floor(2.75 * length * width + 1e-9)
    mark = " (limit)" if peak == limit else ""
    hand = enz.stair_hand(n, length, width)
    return (
        f"| {length} × {width} m | {n} | {f1(r.evacuation_time)} s "
        f"| {hand:.2f} s | {peak}{mark} |"
    )


def stair_prose():
    _, short = enz.stair_flow(1000, 10, 1)
    _, long = enz.stair_flow(1000, 200, 1)
    added = short.evacuation_time - enz.stair_hand(1000, 10, 1)
    full = short.node_occupancy[:, short.node_names.index("stair")].max()
    at = "at its limit of" if full == math.floor(2.75 * 10 + 1e-9) else "at"
    held = long.node_occupancy[:, long.node_names.index("stair")].max()
    speed = hydraulic.speed(held / 200.0, enz.STAIR_K)
    flows = []
    for width in (1, 5):
        _, r = enz.stair_flow(1000, 200, width)
        span = r.exit_times.max() - r.exit_times.min()
        flows.append(f"{999 / span / (width - 0.3):.3f}")
    assert flows[0] == flows[1]
    return (
        f"{at} {full} agents ({full / 10:.1f} m⁻²), and the slower walk adds "
        f"about {added:.0f} s",
        f"the node holds {held} agents, its limit, and all walk at about "
        f"{speed:.2f} m/s. The flow from the first to the last exit is "
        f"{flows[0]} persons/s",
    )


# The hand recursion of contract_issue8 section 16.1 (cf8r/hand_t6.py),
# for one A agent against B's 50 in 20 m² under each supply rate: the
# effective share of the door (the model), the full rate and zero.
_PRESETS = {"bounding": (0.17, 0.84, 0.94), "estimate": (0.17, 0.90, 1.00)}


def hand_door_share(preset, mode, n_a=1, n_b=50, area_b=20.0):
    """Exit times of A's agents; does not use the package."""
    dt, rate, peak, maxd = 0.5, 1.3 * 0.7 * 0.5, 1 / (2 * 0.266), 2.75
    y0, g0, gh = _PRESETS[preset]
    state = dict(na=n_a, nb=n_b, c=1.0, tau=[0.0, 0.0], gamma=0.0, entered=0)
    exits, k = [], 0
    while state["na"] or state["nb"]:
        q = _hand_step(state, (y0, g0, gh), mode, (rate, peak, maxd, area_b))
        exits += [(k + 2) * dt] * q[0]
        k += 1
    return exits


def _hand_step(st, preset, mode, const):
    y0, g0, gh = preset
    rate, peak, maxd, area_b = const
    na, nb = st["na"], st["nb"]
    load_b = nb + st["entered"]
    factor = min(max((maxd - load_b / area_b) / (maxd - peak), 0.0), 1.0)
    active = na > 0 and nb > 0
    phi = [na / (na + nb), nb / (na + nb)] if active else [1.0, 1.0]
    g = g0 + (gh - g0) * 2 * min(phi) if active else 1.0
    y = [y0 + (1 - 2 * y0) * p for p in phi] if active else [1.0, 1.0]
    pair_rate = g * rate
    r_ab = {"effective": y[0] * pair_rate, "full": rate, "zero": 0.0}[mode]
    r_ab = r_ab if active else rate
    budget = st["c"] + pair_rate
    cand = math.floor(budget + 1e-9)
    offered = r_ab if na else 0.0
    allowance = math.inf if factor >= 1 else st["gamma"] + factor * offered
    lim = min(maxd * area_b - load_b, allowance)
    q = [min(na, cand, math.floor(lim + 1e-9)), min(nb, cand)]
    if active and sum(q) > cand:
        keys = [(st["tau"][0] + (i + 1) / y[0], 0) for i in range(q[0])]
        keys += [(st["tau"][1] + (i + 1) / y[1], 1) for i in range(q[1])]
        q = [0, 0]
        for _, d in sorted(keys)[:cand]:
            q[d] += 1
    head = 1.0 if na - q[0] > 0 else 0.0
    st["gamma"] = min(max(allowance - q[0], 0.0), max(offered, 1.0, head))
    st["c"] = min(max(budget - q[0] - q[1], 0.0), 1.0)
    st["tau"] = (
        [st["tau"][d] + q[d] / y[d] for d in (0, 1)] if active else [0.0, 0.0]
    )
    st["na"], st["nb"], st["entered"] = na - q[0], nb - q[1], q[0]
    return q


def door_share_variants():
    for preset in _PRESETS:
        model = tn.door_swap(1, 50, preset, area_b=20.0).exit_times[0]
        assert hand_door_share(preset, "effective") == [model], preset
    full = [hand_door_share(p, "full")[0] for p in ("bounding", "estimate")]
    zero = [hand_door_share(p, "zero")[0] for p in ("bounding", "estimate")]
    return (
        f"it would exit at {full[0]} s ({full[1]} s under `estimate`); with "
        "$\\tilde C_A = 0$, only after $D_B$ falls below "
        f"$1.88\\,\\mathrm{{m^{{-2}}}}$, at {zero[0]} s ({zero[1]} s)."
    )


def _times(values):
    return ", ".join(f1(t) for t in values)


def counterflow_rows():
    """The counterflow rows of the verification table, and their prose."""
    swap = {cf: tn.door_swap(20, 20, cf).evacuation_time for cf in COUNTERFLOW}
    minor = {cf: tn.door_swap(36, 4, cf) for cf in COUNTERFLOW}
    stair = {cf: tn.stair_responders(cf) for cf in COUNTERFLOW}
    t2 = " / ".join(f1(minor[cf].evacuation_time) for cf in COUNTERFLOW)
    b2 = " / ".join(
        _times(tn.passage_times(minor[cf], "B->A")) for cf in COUNTERFLOW
    )
    t3 = " / ".join(f1(stair[cf].evacuation_time) for cf in COUNTERFLOW)
    out = [sorted(stair[cf].exit_times[20:]) for cf in COUNTERFLOW]
    first = tn.passage_times(minor["bounding"], "B->A")[0]
    chain = [
        tn.chain_run(split, "bounding").evacuation_time
        for split in (True, False)
    ]
    share = [
        tn.door_swap(1, 50, cf, area_b=20.0) for cf in ("estimate", "bounding")
    ]
    return (
        f"| {' / '.join(f1(swap[cf]) for cf in COUNTERFLOW)} s; pair passes",
        f"recursion: $T$ = {t2} s; B's passages at {b2} s | equal |",
        f"recursion: evacuees' $T$ = {t3} s; responders out at "
        f"{f1(out[0][0])}–{f1(out[0][-1])} / {_times(out[1])} / {_times(out[2])} s "
        "| equal |",
        f"so B's first agent passes and is recorded at {f1(first)} s.",
        f"`independent`: evacuees $\\lceil 19/0.4554 - 1\\rceil = 41$, so "
        f"{f1(stair['independent'].evacuation_time)} s; responders in steps 0, "
        f"2, 4, 6, so out at {_times(out[0][:-1])} and {f1(out[0][-1])} s.",
        f"$\\Delta t\\,\\lceil (N_A - 1)/(C\\,\\Delta t)\\rceil$ = "
        f"{f1(chain[0])} s ($N_A = 25$) and {f1(chain[1])} s ($N_A = 30$)",
        f"A's agent exits at {f1(share[0].exit_times[0])} s (`estimate`) and "
        f"{f1(share[1].exit_times[0])} s (`bounding`); $T$ = "
        f"{f1(share[0].evacuation_time)} s and {f1(share[1].evacuation_time)} s",
    )


def supply_ramp_prose():
    r = tn.room_swap(45, 1.0, False, two_way=False)
    first = tn.door_passages(r, "A->B")[0]
    return f"so the first agent to pass, at {f1(first)} s, exits at {f1(np.nanmin(r.exit_times))} s."


def passage_time_repeats():
    door = (
        NetworkSimulation(
            tn.single_room(area=40.0, specific_flow=1.33),
            [Population("room", 100, speed=1.0)],
        )
        .run(seed=1)
        .evacuation_time
    )
    opening = (
        NetworkSimulation(
            tn.single_room(width=0.6, kind="opening"), [Population("room", 50)]
        )
        .run(seed=1)
        .evacuation_time
    )
    sfpe = 100 / (1.33 * 0.7)
    return (
        f"({f1(imo3(0.1))} s in the run at $\\Delta t = 0.1$ s)",
        f"the mean flow of 100/{f1(door)} s = {100 / door:.2f} persons/s",
        f"| IMO 4 geometry | {f1(door)} s | 106.3 s | {sfpe:.1f} s |",
        f"| 0.6 m opening | {f1(opening)} s | 62.8 s |",
        f"The model result lies {sfpe - door:.1f} s below it.",
    )


# Figures.


def route_tie_numbers():
    runs = scenarios.route_tie_runs()
    split, first, one = (
        runs[k].evacuation_time for k in ("split", "first", "one")
    )
    assert first == one
    stair = runs["split"].link_names.index("A1->exitA")
    per_stair = runs["split"].link_flow[:, stair].sum()
    used = [
        runs["first"]
        .link_flow[:, runs["first"].link_names.index(f"{s}1->exit{s}")]
        .sum()
        for s in "AB"
    ]
    return (
        f"({split} s against {first} s, see [Routes](#routes))",
        f"With ties split, {per_stair} agents take each stair and the building "
        f"is clear after {split} s. With `split_ties=False` all {max(used)} take "
        "one stair and evacuate as slowly as a building with a single stair "
        f"({one} s); splitting the tie cuts the time by "
        f"{(1 - split / first) * 100:.0f} %.",
    )


def densest_flight():
    net, r = scenarios.building_run()
    stairs = [n.index for n in net.nodes if n.kind == "stair"]
    area = np.array([net.nodes[i].area for i in stairs])
    peak = (r.node_occupancy[:, stairs] / area).max()
    return f"The densest flight reaches {peak:.2f} m⁻²."


def mechanics_numbers():
    """The mechanics animation. "1 : 3" is checked against the input
    merge weights only; in the run the full corridor takes 14 from a and
    33 from b (about 1 : 2.4)."""
    sim = scenarios.mechanics_simulation()
    r = sim.run(seed=4)
    occ = r.node_occupancy[:, r.node_names.index("corridor")]
    links = {lk.name: lk for lk in sim.network.links}
    weights = [links[f"{r}->corridor"].merge_weight for r in "ab"]
    assert (occ >= occ.max() - 1).mean() > 0.5  # "most of the time"
    return (
        f"Two rooms of 40 agents each empty into a corridor of "
        f"{sim.network.node('corridor').area:g} m², which holds at most "
        f"{occ.max()} agents. The corridor is close to its limit most of the "
        f"time. Its inflow is then reduced and shared between the rooms by "
        f"the merge weights {weights[0]:g} : {weights[1]:g}"
    )


def lockup():
    """Two full 20 m² rooms swap through one door: the run never ends."""
    times = []
    for t_max in (600.0, 1200.0):
        net = Network()
        for name in ("A", "B"):
            net.add_room(name, area=20.0)
        net.add_safe("xA")
        net.add_safe("xB")
        net.connect("A", "B", width=1.0)
        net.connect("A", "xA", width=1.0, bidirectional=False)
        net.connect("B", "xB", width=1.0, bidirectional=False)
        pops = [
            Population("A", 55, target="xB"),
            Population("B", 55, target="xA"),
        ]
        r = NetworkSimulation(net, pops, t_max=t_max).run(seed=1)
        assert r.node_occupancy[-1].tolist()[:2] == [55, 55]
        times.append(r.evacuation_time)
    assert all(math.isnan(t) for t in times)
    return (
        "two 20 m² rooms holding 55 agents each ($2.75 \\times 20$) and "
        "swapping occupants through one door stay full for good. The "
        "evacuation time is `nan`, and a larger `t_max` doesn't help."
    )


def population_order():
    times = {}
    for first in (1, 2):
        r = tn.one_door_two_groups(first)
        group = slice(0, 20) if first == 1 else slice(20, 40)
        times[first] = (r.evacuation_time, r.exit_times[group].max())
    assert times[1][0] == times[2][0]
    return (
        f"The evacuation time is {times[1][0]} s in both orders, but the last "
        f"agent of the area-factor-1 group leaves at {times[1][1]} s when that "
        f"group is listed first and at {times[2][1]} s when it is listed second."
    )


def merge_figure():
    return f"Over 150 s the flows reach {merge_ratio():.0f} : 1."


def merge_row():
    return f"| Merge weights 1 : 3 over 150 s | flow ratio 3 | {merge_ratio():.1f} |"


def merge_comparison():
    return f"1 : 3 gives about {merge_ratio():.0f} : 1"


# Slow: the case study and the max_density sweep.


def monte_carlo_sentence():
    mc = scenarios.monte_carlo_runs()
    finished = "All" if mc.incomplete == 0 else "Not all"
    return (
        f"The median evacuation time is {mc.quantile(0.5):.0f} s and the 95th "
        f"percentile {mc.quantile(0.95):.0f} s. {finished} "
        f"{mc.evacuation_times.size} runs finished; the fastest took "
        f"{mc.complete.min()} s and the slowest {mc.complete.max()} s."
    )


@functools.cache
def sweep():
    return {
        (m, on): scenarios.density_sweep_runs(m, on)
        for m in scenarios.DENSITY_LIMITS
        for on in (True, False)
    }


def sweep_claims():
    runs = sweep()
    median = {k: np.median(v) for k, v in runs.items()}
    limits = scenarios.DENSITY_LIMITS
    on = np.array([median[m, True] for m in limits])
    off = np.array([median[m, False] for m in limits])
    steady = on.max() - on.min() < 0.01 * on.min()
    sharp = off[limits > 3.0].min() > 1.2 * off[limits <= 3.0].max()
    level = np.all(np.abs(off[limits < 3.0] / on[limits < 3.0] - 1) < 0.01)
    incomplete = sum(np.isnan(v).sum() for v in runs.values())
    assert steady and sharp and level
    claim = (
        "With a hard limit only, the evacuation time grows sharply above "
        "3 m⁻². With supply reduction it stays almost constant."
    )
    return claim, f"{'No' if incomplete == 0 else 'A'} run was incomplete."


def sweep_slowest():
    slowest = np.nanmax(sweep()[3.7, False])
    return f"with a hard limit of 3.7 m⁻², the slowest of 30 runs takes {slowest:.0f} s"


# Registry ---------------------------------------------------------------------


@dataclass
class Number:
    page: str
    text: str | tuple
    produce: object
    slow: bool = False


def _texts(value):
    return value if isinstance(value, tuple) else (value,)


V = "verification.md"
L = "limitations.md"
CF = "model/counterflow.md"


# The stair-flow table of verification.md, one entry per row.
STAIR_ROWS = {
    (10, 1, 1): "| 10 × 1 m | 1 | 11.5 s | 10.84 s | 1 |",
    (10, 1, 10): "| 10 × 1 m | 10 | 26.0 s | 23.55 s | 10 |",
    (10, 1, 100): "| 10 × 1 m | 100 | 169.0 s | 150.60 s | 27 (limit) |",
    (10, 1, 1000): "| 10 × 1 m | 1000 | 1439.5 s | 1421.07 s | 27 (limit) |",
    (200, 1, 1): "| 200 × 1 m | 1 | 217.5 s | 216.90 s | 1 |",
    (200, 1, 10): "| 200 × 1 m | 10 | 230.0 s | 229.60 s | 10 |",
    (200, 1, 100): "| 200 × 1 m | 100 | 357.0 s | 356.65 s | 100 |",
    (200, 1, 1000): "| 200 × 1 m | 1000 | 1984.5 s | 1627.12 s | 550 (limit) |",
    (200, 5, 1): "| 200 × 5 m | 1 | 217.5 s | 216.90 s | 1 |",
    (200, 5, 10): "| 200 × 5 m | 10 | 219.0 s | 218.79 s | 10 |",
    (200, 5, 100): "| 200 × 5 m | 100 | 238.0 s | 237.71 s | 100 |",
    (200, 5, 1000): "| 200 × 5 m | 1000 | 444.5 s | 426.93 s | 1000 |",
}

REGISTRY = [
    # Getting started and Using pages, besides the snippet outputs.
    Number(
        "getting-started.md",
        "In the first run the last agent starts at 291.9 s and leaves at "
        "323.0 s. The pre-movement times set the evacuation time, and a wider "
        "door changes nothing. When everyone starts at once, the door decides: "
        "the 0.9 m door passes 0.78 persons/s, and widening it to 1.2 m cuts "
        "the time from 184.0 s to 162.5 s. The stair link, at 0.91 persons/s, "
        "is then the narrowest point.",
        getting_started_prose,
    ),
    Number(
        "using/results.md",
        "At most 9 agents are on the flight at once, all 120 pass the door, "
        "and the run ends at 323.0 s in steps of 0.5 s.",
        results_prose,
    ),
    Number(
        "using/running.md",
        "`replay` is a full `SimulationResult` of run 426",
        running_replay,
        slow=True,
    ),
    Number(
        "using/running.md",
        "Here the result changes by 0.4 s between 1.0 s and 0.1 s.",
        running_dt,
    ),
    Number(
        "using/running.md",
        "The median is the same as with the default `t_max`. The 95th "
        "percentile needs some of the 59 unfinished runs",
        running_short,
        slow=True,
    ),
    Number(
        "using/running.md",
        "zero-length links in a row take 3.0 s at $\\Delta t = 0.5$ s",
        zero_length_chain,
    ),
    Number(
        "using/running.md",
        "with a hard limit of 3.7 m⁻², the slowest of 30 runs takes 2948 s",
        sweep_slowest,
        slow=True,
    ),
    Number(
        "using/populations.md",
        "A 40 m walk at `speed=1.5` takes 33.5 s, which is 40 m at 1.199 m/s",
        populations_walk,
    ),
    Number(
        "using/populations.md",
        "1.199 m/s on level ground, and - 0.922 m/s on an 18/28 cm stair",
        populations_ceilings,
    ),
    Number(
        "using/populations.md",
        "Truncated at 0, `Normal(10, 20)` has a mean of about 20, not 10.",
        populations_truncation,
    ),
    Number(
        "using/networks.md",
        "UserWarning: Stair 'flight': riser 200.0 mm and tread 280.0 mm lie "
        "outside the SFPE range (risers 165-191 mm, treads 254-330 mm, SFPE "
        "Handbook Table 67.2); the speed constant k = 51.8 sqrt(T/R) m/min is "
        "extrapolated.",
        networks_warning,
    ),
    # Verification: the results of rows that test a tolerance only.
    Number(
        V,
        (
            "| IMO test 1: 40 m at 1.0 m/s | 40 s | 40.0 s |",
            "= 106.3$ s | 106.5 s | 1 s |",
            "= 62.8$ s | 63.0 s | 0.5 s |",
            "= 30.5$ s | 31.0 s | 0.6 s |",
        ),
        imo_rows,
    ),
    Number(
        V,
        "| 11.0 s ($\\Delta t = 0.1$ s) | 0.25 s |",
        lambda: f"| {f1(imo3(0.1))} s ($\\Delta t = 0.1$ s) | 0.25 s |",
    ),
    Number(
        V, "| Merge weights 1 : 3 over 150 s | flow ratio 3 | 3.0 |", merge_row
    ),
    Number(V, "| 1.081, 1.016 | 0.01 |", stair_k_row),
    Number(V, "mean 90.11 and 80.16, maximum 91 and 81", steady_density_row),
    # Verification: rows and prose of exact tests, and their repeats.
    Number(
        V,
        (
            "| 21.5 / 44.0 / 46.5 s; pair passes",
            "recursion: $T$ = 39.0 / 45.5 / 47.0 s; B's passages at 0.5, 1.5, "
            "2.5, 3.5 / 4.0, 8.5, 14.5, 20.5 / 4.0, 9.0, 15.5, 22.0 s | equal |",
            "recursion: evacuees' $T$ = 21.5 / 29.0 / 30.0 s; responders out at "
            "1.5–4.5 / 4.0, 9.0, 12.5, 19.5 / 4.0, 9.5, 13.5, 20.5 s | equal |",
            "so B's first agent passes and is recorded at 4.0 s.",
            "`independent`: evacuees $\\lceil 19/0.4554 - 1\\rceil = 41$, so "
            "21.5 s; responders in steps 0, 2, 4, 6, so out at 1.5, 2.5, 3.5 "
            "and 4.5 s.",
            "$\\Delta t\\,\\lceil (N_A - 1)/(C\\,\\Delta t)\\rceil$ = 26.5 s "
            "($N_A = 25$) and 32.0 s ($N_A = 30$)",
            "A's agent exits at 13.0 s (`estimate`) and 14.0 s (`bounding`); "
            "$T$ = 57.0 s and 58.0 s",
        ),
        counterflow_rows,
    ),
    Number(
        V,
        "so the first agent to pass, at 5.5 s, exits at 94.5 s.",
        supply_ramp_prose,
    ),
    Number(
        V,
        (
            "(11.0 s in the run at $\\Delta t = 0.1$ s)",
            "the mean flow of 100/106.5 s = 0.94 persons/s",
            "| IMO 4 geometry | 106.5 s | 106.3 s | 107.4 s |",
            "| 0.6 m opening | 63.0 s | 62.8 s |",
            "The model result lies 0.9 s below it.",
        ),
        passage_time_repeats,
    ),
    # Verification: EvacuatioNZ cases.
    Number(
        V,
        (
            "| 40 s | 40.5 s | 40.0 s |",
            "| 12 s | 11.0 s ($\\Delta t = 0.1$ s), 11.5 s ($\\Delta t = 0.5$ s) |",
            "| 108 s | 106.5 s |",
        ),
        enz_rows,
    ),
    Number(
        V,
        (
            "first exit 30.5 s; last exit 129.0 s",
            "Capacity bound $30.5 + 89/0.911 = 128.2$ s",
            "door B at 19.0 s and leaves the stair at 30.5 s: 30.0 s at the "
            "free stair speed",
            "this model gives 129.0 s.",
            "In this model the stair holds at most 14 agents.",
        ),
        fedg_numbers,
    ),
    Number(
        V,
        (
            "| 1548.5 s | 300 per floor",
            "$70.0 + 1199/0.811$",
            "With a start $U(0, 91.44)$ m, 1542.5 s (seed 1; first exit 64.0 s "
            "instead of 70.0 s",
        ),
        sfpe_numbers,
    ),
    Number(
        V,
        "With the landing travel walked on the stair link instead, 1915.5 s.",
        sfpe_landing_row,
    ),
    Number(V, ("| 221.5 s | 235.5 s |", "| 283 s | 286.0 s |"), guide_numbers),
    Number(
        V,
        "means 54.88, 119.66, 4.97; sd 26.07, 29.82, 1.99 (20 000 samples)",
        distribution_moments,
    ),
    Number(
        V,
        (
            "| 106.5, 136.5, 226.5 s (start 0) |",
            "this model gives 106.5 s at the door and 106.5–107.0 s with a "
            "dispersed start",
            "| 106.5–107.0 s, mean 106.6 s |",
        ),
        clearance_numbers,
    ),
    Number(
        V,
        (
            "107.84, 110.41, 128.01 s",
            "| 108.5, 111.0, 128.5 s |",
            "Each lies 0.49–0.66 s above its bound.",
        ),
        triangular_numbers,
    ),
    Number(
        V,
        "| 1 m door | 0.5 s | 10.0 s | 106.5 s | "
        "| 2 m door | 0.5 s | 4.0 s | 44.0 s | "
        "| 3 m door | 0.5 s | 3.0 s | 28.0 s | "
        "| 1 m opening | 0.5 s | 7.0 s | 74.5 s |",
        door_table,
    ),
    *[
        Number(
            V,
            row,
            functools.partial(stair_row, length, width, n),
        )
        for (length, width, n), row in STAIR_ROWS.items()
    ],
    Number(
        V,
        (
            "at its limit of 27 agents (2.7 m⁻²), and the slower walk adds "
            "about 18 s",
            "the node holds 550 agents, its limit, and all walk at about "
            "0.29 m/s. The flow from the first to the last exit is 1.012 "
            "persons/s",
        ),
        stair_prose,
    ),
    Number(
        V,
        (
            "leave after 455.5 s (start at the door) and 506.0 s (start 200 ft "
            "away)",
            "one stair and leave after 3027.5 s.",
        ),
        tied_stairs,
    ),
    Number(
        V,
        "it would exit at 6.0 s (5.5 s under `estimate`); with "
        "$\\tilde C_A = 0$, only after $D_B$ falls below "
        "$1.88\\,\\mathrm{m^{-2}}$, at 17.5 s (16.5 s).",
        door_share_variants,
    ),
    # Verification: figures.
    Number(V, "Over 150 s the flows reach 3 : 1.", merge_figure),
    Number(V, "room a passes no one from 2.0 s to 17.0 s", merge_stall),
    Number(
        V,
        (
            "With a hard limit only, the evacuation time grows sharply above "
            "3 m⁻². With supply reduction it stays almost constant.",
            "No run was incomplete.",
        ),
        sweep_claims,
        slow=True,
    ),
    # Limitations.
    Number(
        L,
        (
            "(407.5 s against 725.5 s, see [Routes](#routes))",
            "With ties split, 300 agents take each stair and the building is "
            "clear after 407.5 s. With `split_ties=False` all 600 take one "
            "stair and evacuate as slowly as a building with a single stair "
            "(725.5 s); splitting the tie cuts the time by 44 %.",
        ),
        route_tie_numbers,
    ),
    Number(
        L,
        "lowers the exit flow from 0.811 to about 0.65 persons/s and raises "
        "the evacuation time from 1548.5 s to 1915.5 s",
        sfpe_landing_prose,
    ),
    Number(
        L,
        "zero-length links in a row take 3.0 s at $\\Delta t = 0.5$ s",
        zero_length_chain,
    ),
    Number(
        L,
        (
            "In this example, 200 agents (`speed=1.2`, no pre-movement, "
            "`start_distance=0`) leave a 100 m² room through a one-way 2 m "
            "door of length 0.3 m into a 4 m² lobby, which leads through a "
            "one-way 4 m opening of length 10 m to a safe node.",
            "the evacuation time is 1372.0 s at $\\Delta t = 0.5$ s against "
            "1442.8 s at $\\Delta t = 1/64$ s, 4.9 % short. With the defaults "
            "(2.75 m⁻², supply reduction on) the same network gives 453.5 s "
            "against 446.9 s, 1.5 % on the long side.",
        ),
        lobby_numbers,
        slow=True,
    ),
    Number(
        L,
        "plus half an agent per node area: 2.0 m⁻² for a 4 m² node",
        full_node_threshold,
    ),
    Number(
        L,
        "In the first case, halving $\\Delta t$ roughly halves the error.",
        lobby_halving,
        slow=True,
    ),
    Number(
        V,
        "CI runs it as its own job, `docs-numbers`, and the site deploys "
        "only when it passes.",
        ci_docs_numbers,
    ),
    Number(
        L,
        "The evacuation time is 43.0 s in both orders, but the last agent of "
        "the area-factor-1 group leaves at 21.0 s when that group is listed "
        "first and at 43.0 s when it is listed second.",
        population_order,
    ),
    Number(
        L,
        "two 20 m² rooms holding 55 agents each ($2.75 \\times 20$) and "
        "swapping occupants through one door stay full for good. The "
        "evacuation time is `nan`, and a larger `t_max` doesn't help.",
        lockup,
    ),
    # Counterflow.
    Number(
        CF,
        '| `"independent"` | 1.0 s and 1.5 s | '
        '| `"estimate"`, `"bounding"` | 1.0 s and 2.0 s |',
        counterflow_two_agents,
    ),
    Number(
        CF,
        'Under `"bounding"` the 4 agents of the minor stream pass at 4.0, '
        "9.0, 15.5 and 22.0 s, 5.0–6.5 s apart, instead of waiting for the "
        "whole opposing queue. The last passage of the major stream moves "
        'from 38.5 s (`"independent"`) to 46.5 s.',
        counterflow_changes,
    ),
    Number(
        CF,
        'The responders are out by 20.5 s (`"bounding"`) or 19.5 s '
        '(`"estimate"`) instead of 4.5 s. The evacuees\' clearance rises from '
        "21.5 s to 30.0 s or 29.0 s.",
        counterflow_responders,
    ),
    # Figures elsewhere.
    Number(
        "model/_index.md",
        "Two rooms of 40 agents each empty into a corridor of 4 m², which "
        "holds at most 11 agents. The corridor is close to its limit most of "
        "the time. Its inflow is then reduced and shared between the rooms "
        "by the merge weights 1 : 3",
        mechanics_numbers,
    ),
    Number("evacuationz.md", "1 : 3 gives about 3 : 1", merge_comparison),
    Number(
        "ten-storey.md", "The densest flight reaches 2.69 m⁻².", densest_flight
    ),
    Number(
        "ten-storey.md",
        "The median evacuation time is 529 s and the 95th percentile 647 s. "
        "All 300 runs finished; the fastest took 419.5 s and the slowest "
        "717.0 s.",
        monte_carlo_sentence,
        slow=True,
    ),
]


def _param(number):
    marks = []
    if number.slow:
        marks.append(pytest.mark.slow)
    first = _texts(number.text)[0]
    return pytest.param(number, marks=marks, id=f"{number.page}: {first[:40]}")


@pytest.mark.parametrize("number", [_param(n) for n in REGISTRY])
def test_page_shows_the_number_the_code_produces(number):
    page = docpages.text(number.page)
    texts = _texts(number.text)
    docpages.quoted(page, texts)
    produced = _texts(number.produce())
    assert produced == texts


# Command line (#46) -----------------------------------------------------------

CLI_PAGE = "using/command-line.md"
PACKAGED = docpages.ROOT / "src" / "jupedsim_network" / "scenarios"


def _collapse(text):
    """Runs of whitespace as one space, as in ``docpages.text``."""
    return re.sub(r"\s+", " ", text).strip()


# The terminal output the page shows, whitespace collapsed (brief §1.2).
CLI_INIT = _collapse("""
Wrote scenario.json (the getting-started scenario).
Next steps:
  1. Check it: jupedsim-network check scenario.json
  2. Run it: jupedsim-network run scenario.json
  3. Edit nodes, connections and populations for your building, then check and run again.
""")
CLI_CHECK = _collapse("""
Scenario scenario.json: 3 nodes, 2 links, 1 population.
Nodes:
  0   office           room   200 m²
  1   flight           stair  10.8 m²
  2   street           safe
Links:
  0   office->flight           door     0.78 persons/s
  1   flight->street           stair    0.91 persons/s
Populations:
  0   office           -> street
Trial run, seed 1: evacuation time 323.0 s; 120 of 120 agents safe.
The scenario is valid.
""")
CLI_RUN = _collapse("""
Scenario scenario.json: 3 nodes, 2 links, 1 population.
Run, seed 1: evacuation time 323.0 s; 120 of 120 agents safe.
Monte Carlo, 500 runs, seed 1: q 0.5 383.25 s, q 0.95 550.05 s; 0 incomplete.
Wrote scenario_results/: summary.json, agents.csv, link_flow.csv, occupancy.csv, runs.csv
""")


def _cli(args, files=None):
    """Exit status, stdout, stderr and result files of one command.

    It runs in an empty directory that holds ``files`` (name -> bytes);
    the result files are those of the ``*_results`` directory, by name.
    """
    from jupedsim_network import cli

    out, err = io.StringIO(), io.StringIO()
    with (
        _in_tmp_dir(),
        contextlib.redirect_stdout(out),
        contextlib.redirect_stderr(err),
    ):
        for name, raw in (files or {}).items():
            pathlib.Path(name).write_bytes(raw)
        code = cli.main(list(args))
        written = pathlib.Path().glob("*_results/*")
        results = {path.name: path.read_bytes() for path in written}
    return code, out.getvalue(), err.getvalue(), results


def _packaged():
    return (PACKAGED / "getting_started.json").read_bytes()


def _edited(edit):
    """The packaged getting-started file with ``edit`` applied."""
    data = json.loads(_packaged())
    edit(data)
    return json.dumps(data, indent=2).encode()


def _line(text, start):
    (line,) = [s for s in text.splitlines() if s.strip().startswith(start)]
    return line


def _ok(args, files):
    code, out, err, results = _cli(args, files)
    assert code == 0, err
    return out, results


def cli_init():
    return _collapse(_ok(["init"], {})[0])


def cli_check():
    return _collapse(
        _ok(["check", "scenario.json"], {"scenario.json": _packaged()})[0]
    )


@functools.cache
def _packaged_run():
    """``run scenario.json`` on the packaged file: 500 runs, about 18 s."""
    return _ok(["run", "scenario.json"], {"scenario.json": _packaged()})


def cli_run():
    return _collapse(_packaged_run()[0])


def capacity_rounding():
    """The door capacity as ``check`` prints it and as summary.json holds it."""
    check = _ok(["check", "scenario.json"], {"scenario.json": _packaged()})[0]
    shown = _line(check, "0   office->flight").split()[-2]
    summary = json.loads(_packaged_run()[1]["summary.json"])
    full = summary["links"][0]["capacity"]
    return (
        f"Capacities are rounded too: `{shown}` in the terminal is "
        f"`{full!r}` in `summary.json`."
    )


def first_run_numbers():
    """Capacities from ``check``, the run and the quantiles from ``run``."""
    check = _ok(["check", "scenario.json"], {"scenario.json": _packaged()})[0]
    door, stair = (
        _line(check, f"{i}   {link}").split()[-2]
        for i, link in ((0, "office->flight"), (1, "flight->street"))
    )
    out = _packaged_run()[0]
    run = re.search(r"seed (\d+): evacuation time (\S+) s", _line(out, "Run,"))
    mc = re.search(
        r"(\d+) runs, seed \d+: q 0.5 (\S+) s, q 0.95 (\S+) s",
        _line(out, "Monte Carlo,"),
    )
    return (
        f"the door passes {door} persons/s and the stair link {stair} "
        f"persons/s, the run with seed {run[1]} ends at {run[2]} s, and over "
        f"{mc[1]} runs the median is {mc[2]} s and the 95th percentile "
        f"{mc[3]} s."
    )


CSV_FILES = ("agents.csv", "link_flow.csv", "occupancy.csv", "runs.csv")


def csv_headers():
    """First line of each CSV file of the packaged run, in page order."""
    results = _packaged_run()[1]
    return tuple(results[name].decode().split("\n")[0] for name in CSV_FILES)


def try_one_change():
    """``check`` with the first connection 1.2 m wide instead of 0.9 m."""

    def wider(data):
        data["connections"][0]["width"] = 1.2

    check = ["check", "scenario.json"]
    before = _ok(check, {"scenario.json": _packaged()})[0]
    after = _ok(check, {"scenario.json": _edited(wider)})[0]
    capacity = [
        float(_line(t, "0   office->flight").split()[-2])
        for t in (before, after)
    ]
    trials = [_line(t, "Trial run") for t in (before, after)]
    larger = "a larger" if capacity[1] > capacity[0] else "no larger"
    same = "stays the same" if trials[0] == trials[1] else "changes"
    assert "evacuation time 323.0 s" in trials[0]
    return (
        f"The `office->flight` link gets {larger} capacity, but the "
        f"evacuation time of the trial run {same}"
    )


RESULT_FIELDS = (
    "exit_times",
    "pre_movement_times",
    "times",
    "node_occupancy",
    "link_flow",
)


def _same_result(a, b):
    return all(
        getattr(a, f).tobytes() == getattr(b, f).tobytes()
        for f in RESULT_FIELDS
    )


def export_sentences():
    """The export block of the page (snippet group 0), then the CLI on
    the file it writes against the CLI on the packaged file."""
    from jupedsim_network.scenario import dumps

    names = snippets(0)[1][CLI_PAGE]
    result = names["result"]
    same = _same_result(result, names["simulation"].run(seed=1))
    exported = dumps(names["scenario"].data).encode()
    out, results = _ok(["run", "office.json"], {"office.json": exported})
    packaged_out, packaged_results = _packaged_run()
    lines = [
        [_line(t, start) for start in ("Run,", "Monte Carlo,")]
        for t in (out, packaged_out)
    ]
    numbers = lines[0] == lines[1] and all(
        results[f] == packaged_results[f] for f in CSV_FILES
    )
    return (
        f"`result` {'is the same as' if same else 'differs from'} "
        "`simulation.run(seed=1)`, byte for byte. `jupedsim-network run "
        f"office.json` {'gives the same numbers as' if numbers else 'differs from'}"
        " the packaged file."
    )


ERROR_FILES = {
    "typo.json": lambda d: d["simulation"].update(max_densty=3.0),
    "speed0.json": lambda d: d["populations"][0].update(speed=0),
    "ln0.json": lambda d: d["populations"][0]["pre_movement"].update(mean=0),
}


def error_lines():
    """The error of ``check`` on each file of the Errors block."""
    lines = []
    for name, edit in ERROR_FILES.items():
        code, _, err, _ = _cli(["check", name], {name: _edited(edit)})
        assert code == 1
        lines.append(_collapse(err))
    return " ".join(lines)


def utf8_message():
    """``check`` on the packaged file saved as cp1252, byte and position
    replaced by the page's placeholders."""
    text = _packaged().decode().replace("\\u00b2", "²")
    files = {"bad.json": text.encode("cp1252")}
    code, _, err, _ = _cli(["check", "bad.json"], files)
    assert code == 1
    message = err.strip().split("bad.json: ", 1)[1]
    message = re.sub(r"byte 0x[0-9a-f]{2}", "byte 0xNN", message)
    return re.sub(r"position \d+", "position P", message)


CLI_REGISTRY = [
    Number(CLI_PAGE, CLI_INIT, cli_init),
    Number(CLI_PAGE, CLI_CHECK, cli_check),
    Number(CLI_PAGE, CLI_RUN, cli_run, slow=True),
    Number(
        CLI_PAGE,
        "The `office->flight` link gets a larger capacity, but the "
        "evacuation time of the trial run stays the same",
        try_one_change,
    ),
    Number(
        CLI_PAGE,
        "`result` is the same as `simulation.run(seed=1)`, byte for byte. "
        "`jupedsim-network run office.json` gives the same numbers as the "
        "packaged file.",
        export_sentences,
        slow=True,
    ),
    Number(
        CLI_PAGE,
        "jupedsim-network check: error: typo.json: simulation: unknown key "
        "'max_densty'; valid keys: counterflow, dt, max_density, split_ties, "
        "supply_reduction, t_max jupedsim-network check: error: speed0.json: "
        "populations[0]: Agent speeds must be positive. jupedsim-network "
        "check: error: ln0.json: populations[0].pre_movement: cannot sample "
        "LogNormal(lower=0.0, upper=None, mean=0, std=60.0): float division "
        "by zero",
        error_lines,
    ),
    Number(
        CLI_PAGE,
        "not UTF-8 text: byte 0xNN at position P; save the file as UTF-8",
        utf8_message,
    ),
    Number(
        CLI_PAGE,
        "the door passes 0.78 persons/s and the stair link 0.91 persons/s, "
        "the run with seed 1 ends at 323.0 s, and over 500 runs the median "
        "is 383.25 s and the 95th percentile 550.05 s.",
        first_run_numbers,
        slow=True,
    ),
    # These read the packaged run, which the run output above already
    # makes; in the slow job they add no run.
    Number(
        CLI_PAGE,
        "Capacities are rounded too: `0.78` in the terminal is "
        "`0.7800000000000001` in `summary.json`.",
        capacity_rounding,
        slow=True,
    ),
    Number(
        CLI_PAGE,
        (
            "agent,pre_movement_sampled,exit_time",
            "time,0:office->flight,1:flight->street",
            "time,office,flight",
            "run,evacuation_time,agents",
        ),
        csv_headers,
        slow=True,
    ),
]


@pytest.mark.parametrize("number", [_param(n) for n in CLI_REGISTRY])
def test_command_line_page_shows_what_the_command_prints(number):
    test_page_shows_the_number_the_code_produces(number)


def test_command_line_page_shows_the_packaged_scenario():
    """The scenario on the page is ``init``'s file, key for key."""
    scenarios = [
        data
        for data in map(json.loads, docpages.blocks(CLI_PAGE, "json"))
        if "populations" in data
    ]
    assert len(scenarios) == 1, "one scenario block expected on the page"
    assert scenarios[0] == json.loads(_packaged())
