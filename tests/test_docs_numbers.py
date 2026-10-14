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
import html
import inspect
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
import test_routing_policy as trp

from jupedsim_network import (
    Fixed,
    LogNormal,
    Network,
    NetworkSimulation,
    Normal,
    Population,
    Triangular,
    Uniform,
    Weibull,
    hydraulic,
    routing,
    routing_costs,
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
    def run_many(self, runs, seed=None, *, progress=None):
        if progress is not None:  # the callbacks must happen
            return original(self, runs, seed, progress=progress)
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


def lobby_halving():
    """Factor by which halving dt divides the error, for (3.5, supply off)."""
    fine = lobby_time(FINE_DT, 3.5, False)
    ratio = (lobby_time(0.5, 3.5, False) - fine) / (
        lobby_time(0.25, 3.5, False) - fine
    )
    return f"In the first case, halving $\\Delta t$ divides the error by {ratio:.1f}."


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


def networks_slope_bounds():
    """Largest slopes the validation and the default max_density allow."""
    floor = 1 / (2 * hydraulic.MIN_DENSITY)
    default_density = 2.75
    low_flow = {"door_specific_flow": 0.3}  # k/(4a) is 0.378 at the bound
    with pytest.raises(ValueError):
        hydraulic.HydraulicParameters(
            speed_density_slope=floor + 1e-3, **low_flow
        )
    hydraulic.HydraulicParameters(speed_density_slope=floor, **low_flow)
    default = hydraulic.HydraulicParameters()
    door_bound = default.level_speed_constant / (4 * default.door_specific_flow)
    return (
        f"$a \\le {floor:.3f}$ m²/person",
        f"this bound is reached at a slope of {door_bound:.3f}, ",
        f"for a slope of {1 / default_density:.3f} (1/2.75) or more.",
    )


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


def routing_cost_row():
    net = trp.alternatives()
    costs, _ = routing.distances(
        net.nodes,
        net.links,
        [net.node("exit").index],
        routing_costs.edge_costs(net.nodes, net.links, trp.TIME),
    )
    k = net.node("stair").speed_constant
    floor = hydraulic.speed(0, 1.0)
    return (
        f"$k_\\text{{stair}} = 51.8\\sqrt{{28/18}}/60 = {k:.4f}$ m/s; costs "
        f"$30/({floor:.5f} \\cdot {k:.4f}) = {costs[1]:.2f}$ s (stair) and "
        f"$35/({floor:.5f} \\cdot 1.4) = {costs[2]:.2f}$ s (level), with "
        f"${floor:.5f} = 1 - 0.266 \\cdot 0.54$ the density floor factor"
    )


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


@functools.cache
def hydraulic_sweep():
    return {
        (name, v): scenarios.hydraulic_sweep_runs(name, v)
        for name, values in scenarios.HYDRAULIC_SWEEP.items()
        for v in values
    }


def hydraulic_sweep_claims():
    runs = hydraulic_sweep()
    median = {k: np.median(v) for k, v in runs.items()}
    bound = {k: scenarios.stair_capacity_bound(*k) for k in runs}
    stair = scenarios.HYDRAULIC_SWEEP["stair_speed_coefficient"]
    slope = scenarios.HYDRAULIC_SWEEP["speed_density_slope"]
    door = scenarios.HYDRAULIC_SWEEP["door_specific_flow"]
    stair_times = [median["stair_speed_coefficient", v] for v in stair]
    slope_times = [median["speed_density_slope", v] for v in slope]
    door_times = [median["door_specific_flow", v] for v in door]
    assert np.all(np.diff(stair_times) < 0) and np.all(np.diff(slope_times) > 0)
    offset = np.array([median[k] - bound[k] for k in runs])
    incomplete = sum(np.isnan(v).sum() for v in runs.values())
    door_spread = max(door_times) - min(door_times)
    return (
        f"from {stair_times[0]:.0f} s at {stair[0]:.0f} m/min to "
        f"{stair_times[-1]:.0f} s at {stair[-1]:.0f} m/min.",
        f"from {slope_times[0]:.0f} s at {slope[0]} to "
        f"{slope_times[-1]:.0f} s at {slope[-1]}.",
        f"The median moves by {door_spread:.0f} s "
        f"between {door[0]} and {door[-1]}.",
        f"the median lies {math.floor(offset.min())} to "
        f"{math.ceil(offset.max())} s above the bound",
        f"{'No' if incomplete == 0 else 'A'} run of the sweep was incomplete.",
    )


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
        "with a hard limit of 3.7 m⁻², the slowest of 30 runs takes 3102 s",
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
    Number(
        "using/networks.md",
        (
            "$a \\le 0.926$ m²/person",
            "this bound is reached at a slope of 0.269, ",
            "for a slope of 0.364 (1/2.75) or more.",
        ),
        networks_slope_bounds,
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
    Number(
        V,
        "$k_\\text{stair} = 51.8\\sqrt{28/18}/60 = 1.0768$ m/s; costs "
        "$30/(0.85636 \\cdot 1.0768) = 32.53$ s (stair) and "
        "$35/(0.85636 \\cdot 1.4) = 29.19$ s (level), with "
        "$0.85636 = 1 - 0.266 \\cdot 0.54$ the density floor factor",
        routing_cost_row,
    ),
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
    Number(
        V,
        (
            "from 924 s at 40 m/min to 590 s at 65 m/min.",
            "from 540 s at 0.19 to 726 s at 0.266.",
            "The median moves by 2 s between 0.7 and 1.3.",
            "the median lies 35 to 41 s above the bound",
            "No run of the sweep was incomplete.",
        ),
        hydraulic_sweep_claims,
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
            "the evacuation time is 1451.5 s at $\\Delta t = 0.5$ s against "
            "1445.3 s at $\\Delta t = 1/64$ s, 0.4 % on the long side. With the defaults "
            "(2.75 m⁻², supply reduction on) the same network gives 453.5 s "
            "against 446.9 s, 1.5 % on the long side.",
        ),
        lobby_numbers,
        slow=True,
    ),
    Number(
        L,
        "In the first case, halving $\\Delta t$ divides the error by 1.8.",
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
    "policy.json": lambda d: d["simulation"].update(routing_policy="fastest"),
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
        "'max_densty'; valid keys: counterflow, dt, max_density, routing_policy, split_ties, "
        "supply_reduction, t_max jupedsim-network check: error: speed0.json: "
        "populations[0]: Agent speeds must be positive. jupedsim-network "
        "check: error: ln0.json: populations[0].pre_movement: cannot sample "
        "LogNormal(lower=0.0, upper=None, mean=0, std=60.0): float division "
        "by zero jupedsim-network check: error: policy.json: "
        "simulation.routing_policy: routing_policy must be one of "
        "'shortest_distance', 'shortest_free_flow_time'; got 'fastest'.",
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


# Terminal UI figures (#47) ----------------------------------------------------

import copy_tui_snapshots as tui_figures  # noqa: E402

# Left pane of a 120x35 snapshot: the right pane starts at column 61,
# x = 744.2 at 12.2 px per column.
LEFT_PANE_X = 730.0


def test_tui_figures_are_the_snapshots(tmp_path):
    tui_figures.copy(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(
        tui_figures.FIGURES
    )
    for figure, source in tui_figures.FIGURES.items():
        expected = (tui_figures.SNAPSHOTS / source).read_bytes()
        assert (tmp_path / figure).read_bytes() == expected


# What only that screen shows, so a swapped or mis-themed source fails.
FIGURE_MARKS = {
    "scenario.svg": "office-wing",
    "edit-error.svg": 'expected a number, got the string "abc"',
    "check.svg": "The scenario is valid.",
    "run.svg": "Monte Carlo 132 / 500",
    "results.svg": "Command line output",
}
NETWORK_DARK_BACKGROUND = "#121a24"  # tui/theme.py NETWORK_DARK.background


def _screen(figure):
    """All text of a page figure, tags removed, unescaped, collapsed."""
    source = tui_figures.SNAPSHOTS / tui_figures.FIGURES[figure]
    return _collapse(html.unescape(re.sub(r"<[^>]+>", " ", source.read_text())))


@pytest.mark.parametrize("figure", sorted(FIGURE_MARKS))
def test_tui_figure_is_its_screen_in_network_dark(figure):
    assert sorted(FIGURE_MARKS) == sorted(tui_figures.FIGURES)
    assert FIGURE_MARKS[figure] in _screen(figure)
    others = [f for f in FIGURE_MARKS if f != figure]
    assert all(FIGURE_MARKS[figure] not in _screen(f) for f in others)
    source = tui_figures.SNAPSHOTS / tui_figures.FIGURES[figure]
    fills = re.findall(r'<rect fill="(#[0-9a-f]{6})"', source.read_text())
    assert NETWORK_DARK_BACKGROUND in fills


def _left_pane(figure):
    """Text of the left pane of a page figure, rows joined, collapsed."""
    source = tui_figures.SNAPSHOTS / tui_figures.FIGURES[figure]
    rows = {}
    for match in re.finditer(
        r'<text class="[^"]*-r\d+" x="([\d.]+)" y="([\d.]+)"[^>]*>([^<]*)</text>',
        source.read_text(),
    ):
        x, y, text = float(match[1]), float(match[2]), match[3]
        if x < LEFT_PANE_X:
            rows.setdefault(y, []).append((x, html.unescape(text)))
    return _collapse(
        " ".join(
            "".join(t for _, t in sorted(r)) for _, r in sorted(rows.items())
        )
    )


def test_check_figure_shows_what_check_prints():
    assert CLI_CHECK in _left_pane("check.svg")
    assert cli_check() in _left_pane("check.svg")


def test_results_figure_shows_what_run_prints():
    """The Results figure is a 20-run set (``_results_before`` in
    test_tui.py), not the registered 500-run output; it must still be
    what ``run`` prints for that file, and its occupancy what
    occupancy.csv holds at t = 120.0 s."""

    def twenty_runs(data):
        data["monte_carlo"]["runs"] = 20

    files = {"scenario.json": _edited(twenty_runs)}
    out, results = _ok(["run", "scenario.json"], files)
    assert "Monte Carlo, 20 runs," in out
    assert _collapse(out) in _left_pane("results.svg")
    csv = results["occupancy.csv"].decode().splitlines()
    assert csv[0] == "time,office,flight"
    (row,) = [line for line in csv[1:] if float(line.split(",")[0]) == 120.0]
    _, office, flight = row.split(",")
    shown = tui_figures.SNAPSHOTS / tui_figures.FIGURES["results.svg"]
    screen = _collapse(html.unescape(shown.read_text()))
    assert "occupancy of the single run, seed 1: t = 120.0 s<" in screen
    assert f"office room 200 m² ● {office}<" in screen
    assert f"flight stair 10.8 m² ● {flight}<" in screen


# Bounds and the run_many prefix (#47 PR 3) ------------------------------------


def _rejected(make) -> bool:
    """Whether building the distribution raises ``ValueError``."""
    try:
        make()
    except ValueError:
        return True
    return False


# Built lazily: each raises ``ValueError`` (issue #53).
def _inverted():
    return (
        lambda: Fixed(7, lower=2, upper=1),
        lambda: Uniform(0, 10, lower=2, upper=1),
        lambda: Normal(5, 1, lower=2, upper=1),
        lambda: LogNormal(5, 1, lower=2, upper=1),
        lambda: Triangular(0, 5, 10, lower=2, upper=1),
        lambda: Weibull(2, 3, lower=2, upper=1),
    )


def _fixed_outside_rejected() -> bool:
    return all(
        _rejected(m) for m in (lambda: Fixed(-5), lambda: Fixed(10, upper=3))
    )


def bounds_limitations():
    fixed = (
        "raise `ValueError`" if _fixed_outside_rejected() else "are accepted"
    )
    inverted = "so does" if all(_rejected(m) for m in _inverted()) else "not"
    return (
        f"`Fixed(-5)` and `Fixed(10, upper=3)` {fixed}, and {inverted} every "
        "distribution with `lower` greater than `upper`."
    )


def _load_rejects(pre_movement: dict) -> bool:
    """Whether the loader rejects ``pre_movement`` at its own key."""
    from jupedsim_network import ScenarioError, scenario_from_dict

    data = json.loads((PACKAGED / "getting_started.json").read_text())
    data["populations"][0]["pre_movement"] = pre_movement
    try:
        scenario_from_dict(data)
    except ScenarioError as exc:
        return exc.path == "populations[0].pre_movement"
    return False


def bounds_command_line():
    outside = {"distribution": "Fixed", "value": 10, "upper": 3}
    inverted = {
        "distribution": "Normal",
        "mean": 5,
        "std": 1,
        "lower": 2,
        "upper": 1,
    }
    rejected = _load_rejects(outside) and _load_rejects(inverted)
    verb = (
        "are rejected when the file is loaded" if rejected else "are accepted"
    )
    return (
        "A `Fixed` value outside its bounds and a distribution with `lower` "
        f"above `upper` {verb}."
    )


def run_many_prefix():
    """``run_many(100, seed=1)`` against the first 100 rows of runs.csv of
    the packaged ``run`` (500 runs, seed 1), which the slow job makes
    once for the command-line entries."""
    from jupedsim_network.scenario import load_scenario

    summary = json.loads(_packaged_run()[1]["summary.json"])
    assert (summary["monte_carlo"]["runs"], summary["monte_carlo"]["seed"]) == (
        500,
        1,
    )
    rows = _packaged_run()[1]["runs.csv"].decode().splitlines()[1:]
    five_hundred = [float(row.split(",")[1]) for row in rows]
    sim = load_scenario(PACKAGED / "getting_started.json").build()[0]
    hundred = sim.run_many(100, seed=1).evacuation_times.tolist()
    same = (
        "gives the first" if hundred == five_hundred[:100] else "differs from"
    )
    return (
        "runs do not depend on `runs`: `run_many(100, seed=1)` "
        f"{same} 100 runs of `run_many(500, seed=1)`."
    )


BOUNDS_REGISTRY = [
    Number(
        L,
        "`Fixed(-5)` and `Fixed(10, upper=3)` raise `ValueError`, and so does "
        "every distribution with `lower` greater than `upper`.",
        bounds_limitations,
    ),
    Number(
        CLI_PAGE,
        "A `Fixed` value outside its bounds and a distribution with `lower` "
        "above `upper` are rejected when the file is loaded.",
        bounds_command_line,
    ),
    Number(
        "using/running.md",
        "runs do not depend on `runs`: `run_many(100, seed=1)` gives the "
        "first 100 runs of `run_many(500, seed=1)`.",
        run_many_prefix,
        slow=True,
    ),
]


@pytest.mark.parametrize("number", [_param(n) for n in BOUNDS_REGISTRY])
def test_bounds_and_prefix_claims(number):
    test_page_shows_the_number_the_code_produces(number)


# The Station nightclub (examples/station.md) ----------------------------------

STATION_PAGE = "examples/station.md"
station = scenarios.station
PLATFORM_DOOR = "stageside->platform_exit"
# Published values of EvacuatioNZ v2.3 [8] and NIST [38]: source numbers,
# used here only to derive the differences the page prints.
PUBLISHED = {"S0": 493, "S1": 345, "S2": 195, "S2b": 272, "S3n": 201}
PUBLISHED_HAND = 428  # N/C of the paper, p. 169
STAGE_WORDS = {4: "four"}


def _st_run(label):
    return scenarios.station_runs()[label]


def _st_time(label):
    return f"{_st_run(label).evacuation_time:.1f}"


def _st_split(label):
    platform, side, kitchen, front = station.exit_counts(_st_run(label))
    return (
        f"{platform} through the platform door, {side} through the side "
        f"door, {kitchen} through the kitchen door and "
        f"{front or 'none'} through the front door"
    )


def _st_minus(value):
    return value.replace("-", "−")


def _st_percent(label, published=None):
    published = published or PUBLISHED[label]
    run = _st_run(label.split()[0]).evacuation_time
    return _st_minus(f"{(run / published - 1) * 100:+.0f} %")


def _st_signed(value):
    return "0.0" if abs(value) < 0.05 else _st_minus(f"{value:+.1f}")


def _st_capacity(name):
    net = station.build_network()
    return next(link.capacity for link in net.links if link.name == name)


def _st_last(label, link):
    result = _st_run(label)
    flow = result.link_flow[:, result.link_names.index(link)]
    return float(result.times[flow > 0][-1])


def _st_t5(label, link=PLATFORM_DOOR):
    return station.passage_time(_st_run(label), link, 5)


def station_intro():
    words = {4: "four", 10: "ten"}
    return (
        f"The nightclub has {words[len(station.ROOMS)]} spaces and "
        f"{words[len(station.SAFE)]} exits",
        f"it holds {sum(station.OCCUPANTS.values())} people",
    )


def station_tables():
    rows = []
    for name, (length, width) in station.ROOMS.items():
        area = length * width
        count = station.OCCUPANTS.get(name, 0)
        rows.append(
            f"| {name} | {length} × {width} | {area:.1f} | {count} | "
            f"{count / area:.2f} |"
        )
    net = station.build_network()
    capacity = {link.name: link.capacity for link in net.links}
    for source, target, width, length in station.LINKS:
        cap = capacity[f"{source}->{target}"]
        rows.append(f"| {source} → {target} | {width} | {length} | {cap:.3f} |")
    return tuple(rows)


def station_dance_floor():
    """Initial density of the dance floor and the limit below which it fails."""
    length, width = station.ROOMS["dance"]
    density = station.OCCUPANTS["dance"] / (length * width)
    slope = hydraulic.HydraulicParameters().speed_density_slope
    for limit, raises in ((density - 0.001, True), (density + 0.001, False)):
        sim = station.simulation(max_density=limit)
        try:
            sim.run(seed=1)
        except ValueError:
            assert raises
        else:
            assert not raises
    return (
        f"The dance floor starts at {density:.2f} m⁻², above the "
        f"{1 / (2 * slope):.2f} m⁻² where the supply reduction begins and "
        "below the default `max_density` of "
        f"{station.simulation().max_density} m⁻². The model refuses a limit "
        f"below {density:.3f} m⁻² for this start.",
    )


def station_door_flow_limit():
    """1.33 persons/s/m is above k/(4a), so it is set on each link."""
    p = hydraulic.HydraulicParameters()
    limit = 1.4 / (4 * p.speed_density_slope)
    with pytest.raises(ValueError):
        hydraulic.HydraulicParameters(door_specific_flow=station.SPECIFIC_FLOW)
    assert station.SPECIFIC_FLOW > limit
    return (
        f"A 0.91 m door passes {_st_capacity('kitchen->kitchen_exit'):.3f} "
        "persons/s.",
        f"1.33 persons/s/m is above the maximum flow k/(4a) = {limit:.3f} "
        "persons/s/m",
        f"which is {station.SPECIFIC_FLOW} × 0.91 to within rounding",
    )


def _st_length(source, target):
    return next(
        length
        for s, t, _, length in station.LINKS
        if (s, t) == (source, target)
    )


def station_routes():
    dart = _st_length("dart", "kitchen") + _st_length("kitchen", "kitchen_exit")
    dart_dance = (
        _st_length("dart", "dance")
        + _st_length("dance", "stageside")
        + _st_length("stageside", "platform_exit")
    )
    bar = _st_length("bar", "side")
    bar_front = _st_length("bar", "entrance") + _st_length("entrance", "front")
    platform = _st_length("dance", "stageside") + _st_length(
        "stageside", "platform_exit"
    )
    front = _st_length("dance", "entrance") + _st_length("entrance", "front")
    routes = station.build_network().route_table()
    net = station.build_network()
    first = {
        n: net.links[routes[net.node(n).index]].name for n in station.OCCUPANTS
    }
    assert first["dart"] == "dart->kitchen" and first["bar"] == "bar->side"
    assert first["dance"] == "dance->stageside"
    return (
        f"the dart room goes to the kitchen door ({_st_length('dart', 'kitchen')}"
        f" + {_st_length('kitchen', 'kitchen_exit')} = {dart:.1f} m against "
        f"{dart_dance:.1f} m by the dance floor), the main bar to its side "
        f"door ({bar} m against {bar_front:.1f} m through the entrance)",
        f"the platform door is {_st_length('dance', 'stageside')} + "
        f"{_st_length('stageside', 'platform_exit')} = {platform:.1f} m away "
        f"and the front door {_st_length('dance', 'entrance')} + "
        f"{_st_length('entrance', 'front')} = {front:.1f} m",
        f"The split is {_st_split('S0')}",
    )


def station_occupants():
    front = sum(
        p.count for p in station.populations("preferred") if p.target == "front"
    )
    sim = station.simulation()
    return (
        f"That gives {front} of the {sum(station.OCCUPANTS.values())} to the "
        f"front door, {front / sum(station.OCCUPANTS.values()) * 100:.1f} %.",
        f"{station.PREFERRED_SHARE * 100:.0f} % of each space, rounded",
        f"`t_max={sim.t_max}`",
        f"`max_density={sim.max_density}`",
    )


def station_baseline():
    inside = station.agents_inside(_st_run("S0"), 90.0)
    return (
        f"The model evacuates the {sum(station.OCCUPANTS.values())} people "
        f"in {_st_time('S0')} s: {_st_split('S0')}. {inside} are still "
        "inside at 90 s.",
    )


def _st_speed(density):
    p = hydraulic.HydraulicParameters()
    a, k = p.speed_density_slope, 84 / 60
    return min(station.SPEED, k * (1 - a * max(density, 0.54)))


def _st_hand_inside():
    """Agents left inside at 90 s by the hand sum of the three doors."""
    result = _st_run("S0")
    walk = _st_length("kitchen", "kitchen_exit") / station.SPEED
    dart = _st_t5("S0", "dart->kitchen")
    out = (
        31
        + 3
        + 5
        + _st_capacity("dart->kitchen") * (90 - walk - dart)
        + 5
        + _st_capacity(PLATFORM_DOOR) * (90 - _st_t5("S0"))
    )
    assert abs(station.agents_inside(result, 90.0) - (420 - out)) <= 8
    return 420 - out


def station_hand():
    result = _st_run("S0")
    cap = _st_capacity(PLATFORM_DOOR)
    t5 = _st_t5("S0")
    dance = station.OCCUPANTS["dance"] / math.prod(station.ROOMS["dance"])
    stage_side = _st_length("stageside", "platform_exit")
    walk = _st_length("dance", "stageside")
    low = walk / _st_speed(dance) + stage_side / _st_speed(0)
    high = walk / _st_speed(2.75) + stage_side / _st_speed(0)
    drain = (347 - 5) / cap
    evac = result.evacuation_time
    return (
        f"with $C$ = {cap:.4f} persons/s",
        f"The {STAGE_WORDS[station.OCCUPANTS['stage']]} occupants of the "
        "stage pass the platform",
        f"The side door has passed its 31 agents after "
        f"{_st_last('S0', 'bar->side'):.1f} s and the kitchen door its 42 "
        f"after {_st_last('S0', 'kitchen->kitchen_exit'):.1f} s, limited by "
        f"the 0.6 m door of the dart room ({_st_capacity('dart->kitchen'):.3f} "
        "persons/s)",
        f"door first, from {station.passage_time(result, PLATFORM_DOOR):.1f} "
        f"s. The fifth passage is the first agent of the dance floor, at "
        f"{t5:.1f} s",
        f"for $D$ between {dance:.2f} and 2.75 m⁻², then {stage_side} m in "
        f"the stage side: between {low:.1f} s and {high:.1f} s",
        f"342/{cap:.4f} = {drain:.1f} s, so $T = t_5 + 342/C$ = {t5:.1f} + "
        f"{drain:.1f} = {t5 + drain:.1f} s, the model's value",
        f"$N/C$ = 347/{cap:.3f} = {347 / cap:.0f} s",
        f"The model's {evac:.1f} s lies {evac - PUBLISHED_HAND:.0f} s above "
        f"it, less than the {t5:.1f} s of the first arrival",
        f"the dart door {_st_capacity('dart->kitchen'):.3f} persons/s from "
        f"{_st_t5('S0', 'dart->kitchen'):.1f} s (the kitchen door follows "
        f"{_st_length('kitchen', 'kitchen_exit') / station.SPEED:.0f} s "
        f"later, the walk of {_st_length('kitchen', 'kitchen_exit')} m)",
        f"then {cap:.3f} persons/s from {t5:.1f} s",
        f"That leaves {_st_hand_inside():.1f} inside, to within 8 agents",
        f"The model has {station.agents_inside(result, 90.0)} and "
        "EvacuatioNZ 291",
    )


def station_gap():
    evac = _st_run("S0").evacuation_time
    steps = [
        _st_run(label).evacuation_time for label in ("S0 dt 0.1", "S0 dt 1.0")
    ]
    cap = _st_capacity(PLATFORM_DOOR)
    supply = _st_run("S0s").evacuation_time - evac
    return (
        f"gives {PUBLISHED['S0']} s, {PUBLISHED['S0'] - evac:.0f} s more "
        f"than the model ({_st_percent('S0')} for the model)",
        f"so v2.3 lies {PUBLISHED['S0'] - PUBLISHED_HAND} s above its hand "
        f"value and this model {evac - PUBLISHED_HAND:.0f} s",
        f"({PUBLISHED['S0']} s against {evac:.0f} s)",
        f"do not account for {PUBLISHED['S0'] - evac:.0f} s",
        f"**Supply reduction** changes the result by {supply:.1f} s",
        f"moves it by at most {max(abs(t - evac) for t in steps):.1f} s",
        f"is at most {1 / cap:.1f} s per door",
    )


def station_variants():
    evac = _st_run("S0").evacuation_time
    rows = []
    for label, change, key in (
        ("S0s", "`supply_reduction=False`", "S0s"),
        ("S0, `dt=0.1`", "time step 0.1 s", "S0 dt 0.1"),
        ("S0, `dt=1.0`", "time step 1.0 s", "S0 dt 1.0"),
    ):
        t = _st_run(key).evacuation_time
        rows.append(
            f"| {label} | {change} | {t:.1f} | {_st_signed(t - evac)} |"
        )
    split = station.exit_counts(_st_run("S0"))
    for key in ("S0 dt 0.1", "S0 dt 1.0", "S0s"):
        assert station.exit_counts(_st_run(key)) == split
    return (
        *rows,
        f"Supply reduction changes the result by "
        f"{_st_run('S0s').evacuation_time - evac:.1f} s here",
        "while the dance floor is above "
        f"{1 / (2 * hydraulic.HydraulicParameters().speed_density_slope):.2f}"
        " m⁻²",
        f"The split is {', '.join(map(str, split[:3]))} and {split[3]} at "
        "every time step",
    )


def station_start_spread():
    times, splits = scenarios.station_start_spread()
    split = station.exit_counts(_st_run("S0"))
    assert np.all(splits == split)
    diagonal = max(math.hypot(*station.ROOMS[n]) for n in station.OCCUPANTS)
    net = station.build_network()
    routes = net.route_table()
    first = {
        n: net.links[routes[net.node(n).index]].length
        for n in station.OCCUPANTS
    }
    assert all(first[n] - math.hypot(*station.ROOMS[n]) < 0 for n in first)
    return (
        f"in {times.size} runs with seeds from `SeedSequence(1).spawn`",
        f"negative lower end for all {words_of(len(first))} occupied nodes",
        f"All {times.size} runs give the split "
        f"{', '.join(map(str, split[:3]))} and {split[3]}, and times from "
        f"{times.min():.1f} s to {times.max():.1f} s: a start spread of up "
        f"to {diagonal:.0f} m",
    )


def words_of(n):
    return {8: "eight"}[n]


def station_s1():
    cap = station.SPECIFIC_FLOW * 0.91
    t5 = _st_t5("S1")
    bound = 342 / cap
    r = _st_run("S1")
    return (
        f"$C$ = 1.33 × 0.91 = {cap:.3f} persons/s. The model evacuates in "
        f"{_st_time('S1')} s with the same split, and "
        f"{station.agents_inside(r, 90.0)} inside at 90 s",
        f"$t_5 + 342/C$ = {t5:.1f} + {bound:.1f} = {t5 + bound:.1f} s",
        f"gives {PUBLISHED['S1']} s",
        f"(the model is {_st_percent('S1')} below)",
        f"347/{cap:.3f} = {347 / cap:.0f} s (the model is "
        f"{_st_minus(f'{(r.evacuation_time / (347 / cap) - 1) * 100:+.0f} %')}"
        " above)",
        "the paper gives no hand value for this case",
        f"takes {_st_time('S1s')} s, and S1 at `dt=0.1` takes "
        f"{_st_time('S1 dt 0.1')} s",
    )


def _st_door_agents(case):
    """Agents through dance->entrance in a case of Table 5."""
    table = station.TABLE_5
    return sum(
        table[n].get("front", 0)
        for n in ("dance", "sunroom", "dart", "platform")
    )


def _st_width(source, target):
    return next(w for s, t, w, _ in station.LINKS if (s, t) == (source, target))


def station_s2():
    walk = _st_length("entrance", "front") / station.SPEED
    n = _st_door_agents("table5")
    rows = []
    for label, layer, published in (
        (
            "S2",
            0.0,
            '195 {{< cite 8 "p. 170" >}}; NIST 188 and 202; '
            'hand 177 {{< cite 8 "p. 169" >}}',
        ),
        (
            "S2b",
            0.15,
            '272 ± 2 {{< cite 8 "p. 170" >}}; hand 261 {{< cite 8 "p. 170" >}}',
        ),
    ):
        cap = station.SPECIFIC_FLOW * (0.91 - 2 * layer)
        t5 = _st_t5(label, "dance->entrance")
        bound = t5 + (n - 5) / cap + walk
        rows.append(
            f"| {label} | {_st_time(label)} | {t5:.1f} | {bound:.1f} | "
            f"{published} |"
        )
    platform, side, kitchen, front = station.exit_counts(_st_run("S2"))
    assert station.exit_counts(_st_run("S2b")) == [
        platform,
        side,
        kitchen,
        front,
    ]
    return (
        f"{front} to the front door, {platform} to the platform door, {side} "
        f"to the side door and {kitchen} to the kitchen door",
        f"controlling link is dance → entrance ({_st_width('dance', 'entrance')} m)",
        f"which {n} agents of the dance floor",
        f"the {station.TABLE_5['bar']['front']} of the main bar",
        f"$t_5 + ({n} - 5)/C$ + walk (s)",
        *rows,
        f"The walk is {_st_length('entrance', 'front')} m from the entrance "
        f"to the front door at {station.SPEED} m/s, {walk:.1f} s",
        f"S2 is {_st_percent('S2')} from the published {PUBLISHED['S2']} s "
        f"and S2b {_st_percent('S2b')}, "
        f"{PUBLISHED['S2b'] - 2 - _st_run('S2b').evacuation_time:.0f} s below "
        "the published mean minus one standard deviation (272 ± 2 s",
        f"S2 has {station.agents_inside(_st_run('S2'), 90.0)}.",
    )


def station_s3():
    platform, side, kitchen, front = station.exit_counts(_st_run("S3"))
    share = [f"{x / 420 * 100:.1f} %" for x in (front, platform, kitchen, side)]
    n = sum(
        p.count
        for p in station.populations("preferred")
        if p.target == "front" and p.node != "bar"
    )
    t = _st_run("S3n").evacuation_time
    return (
        f"The split is {front} through the front door, {platform} through "
        f"the platform door, {kitchen} through the kitchen door and {side} "
        f"through the side door: {share[0]}, {share[1]}, {share[2]} and "
        f"{share[3]}",
        f"which {n} agents pass",
        f"| S3 | {_st_time('S3')} | "
        f"{station.agents_inside(_st_run('S3'), 90.0)} | – |",
        f"| S3n | {_st_time('S3n')} | "
        f"{station.agents_inside(_st_run('S3n'), 90.0)} | 201 ± 8 s, about "
        "163 inside at 90 s |",
        f"S3n is {_st_percent('S3n')} above the published "
        f"{PUBLISHED['S3n']} s: {t - PUBLISHED['S3n']:.0f} s above the mean "
        f"and {t - (PUBLISHED['S3n'] + 8):.0f} s above the mean plus one "
        "standard deviation",
        f"S3n has {station.agents_inside(_st_run('S3n'), 90.0)} agents "
        "inside at 90 s",
    )


def station_s4a():
    times, front = scenarios.station_length_sweep()
    factors = scenarios.STATION_FACTORS
    assert np.array_equal(times[0], times[1])
    tie = int(np.flatnonzero(np.isclose(factors, 0.875))[0])
    low = int(np.flatnonzero(np.isclose(factors, 0.80))[0])
    above = int(np.flatnonzero(np.isclose(factors, 0.88))[0])
    length = _st_length("dance", "entrance")
    assert math.isclose(
        0.875 * length + _st_length("entrance", "front"),
        _st_length("dance", "stageside")
        + _st_length("stageside", "platform_exit"),
        abs_tol=1e-9,
    )
    assert np.all(times[0, above:] == times[0, above])
    assert np.all(np.diff(times[0, :tie]) >= 0)
    entrance = _st_length("entrance", "front")
    platform = _st_length("dance", "stageside") + _st_length(
        "stageside", "platform_exit"
    )
    return (
        f"in {factors.size} values: {factors.min():.2f} to {factors.max():.2f}"
        f" in steps of {np.diff(factors[:3])[0]:.2f} and the tie at 0.875",
        f"if ${length} f + {entrance} < {_st_length('dance', 'stageside')} + "
        f"{_st_length('stageside', 'platform_exit')}$, that is for "
        f"$f < {(platform - entrance) / length:.3f}$",
        f"$0.875 \\times {length} + {entrance} = "
        f"{_st_length('dance', 'stageside')} + "
        f"{_st_length('stageside', 'platform_exit')}$ exactly",
        f"which is $0.875 \\times {length}$",
        f"{front[low]} agents leave through the front door",
        "the time does not decrease as $f$ grows",
        f"The flip is at the exact tie $f$ = {factors[tie]}",
        f"the time is {times[0, above]:.1f} s from $f$ = 0.88",
        f"{front[tie]} go to the front door and "
        f"{front[low] - front[tie] + 4} to the platform door",
        f"the shortest time of the sweep, {times[0, tie]:.1f} s",
        f"the same time in all {factors.size} values",
        f"In this study the flip is at {0.875 * length:.1f} m",
    )


def station_s4b():
    times, capacity, fifth = scenarios.station_door_sweep()
    rows = [
        f"| {flow} | " + " | ".join(f"{t:.1f}" for t in times[i]) + " |"
        for i, flow in enumerate(scenarios.STATION_FLOWS)
    ]
    gap = times - (fifth + 342 / capacity)
    flow, layer = scenarios.STATION_FLOWS[-1], scenarios.STATION_LAYERS[-1]
    assert times[-1, -1] == _st_run("S0").evacuation_time
    return (
        *rows,
        f"$F_s$ = {flow} and $b$ = {layer}, is S0",
        f"In all {times.size} cases $T$ lies between {-gap.min():.2f} s and "
        f"{-gap.max():.2f} s below $t_5 + 342/C$",
    )


def station_s4c():
    times, _ = scenarios.station_density_sweep()
    rows = [
        f"| {limit} | {times[0, j]:.1f} | {times[1, j]:.1f} |"
        for j, limit in enumerate(scenarios.STATION_DENSITIES)
    ]
    limits = scenarios.STATION_DENSITIES

    def fifth(limit, supply):
        sim = station.simulation(max_density=limit, supply_reduction=supply)
        return station.passage_time(sim.run(seed=1), PLATFORM_DOOR, 5)

    assert np.all(times[0] <= times[1])
    return (
        *rows,
        f"`max_density` from {limits[0]} to {limits[-1]} m⁻²",
        f"beyond {station.simulation().max_density} m⁻²",
        f"the fifth passage is later ({fifth(limits[0], True):.1f} s at "
        f"{limits[0]} m⁻², {fifth(limits[-1], True):.1f} s at {limits[-1]} "
        f"m⁻² with supply reduction, {fifth(limits[-1], False):.1f} s "
        "without)",
        f"differ by {(times[1] - times[0]).max():.1f} s at most",
    )


UNEXPLAINED = (
    "the paper does not explain the excess of v2.3 over its own hand value"
)
ATTRIBUTED = {
    "S3n": "boundary layer of the case inferred, and the fixed 60 % split "
    "cannot give the published 67 % front share"
}


def _st_band(run, published, attributed):
    """Reporting band of a difference: up to 5 %, up to 15 %, above."""
    difference = abs(run / published - 1) * 100
    if difference <= 5:
        return "agrees"
    return f"differs; {attributed}" if difference <= 15 else "differs"


def station_comparison():
    inside = station.agents_inside(_st_run("S0"), 90.0)
    rows = [
        f'| S0, inside at 90 s | {inside} | 291 {{{{< cite 8 "p. 166" >}}}} | '
        f"{(inside / 291 - 1) * 100:.0f} % | {_st_band(inside, 291, '')} |"
    ]
    for label, published, text in (
        ("S0", 493, '493 s {{< cite 8 "p. 166" >}}'),
        ("S1", 345, '345 s {{< cite 8 "p. 169" >}}'),
        ("S2", 195, '195 s {{< cite 8 "p. 170" >}}'),
        ("S2b", 272, '272 ± 2 s {{< cite 8 "p. 170" >}}'),
        ("S3n", 201, '201 ± 8 s {{< cite 8 "p. 171" >}}'),
        ("S3", 201, '201 ± 8 s {{< cite 8 "p. 171" >}}'),
    ):
        run = _st_run(label).evacuation_time
        rows.append(
            f"| {label} | {_st_time(label)} s | {text} | "
            f"{_st_minus(f'{(run / published - 1) * 100:+.0f} %')} | "
            f"{_st_band(run, published, ATTRIBUTED.get(label, UNEXPLAINED))} |"
        )
    return tuple(rows)


def station_limits():
    length = _st_length("dance", "entrance")
    tie = 0.875 * length
    return (
        f"The length of dance → entrance is {(length - tie) / length * 100:.1f}"
        " % from the tie of the routes",
        f"effect is {_st_run('S0s').evacuation_time - _st_run('S0').evacuation_time:.1f} s here",
        f"The dance floor starts above {1 / (2 * hydraulic.HydraulicParameters().speed_density_slope):.2f} m⁻²",
    )


def station_settings():
    sim = station.simulation()
    steps = [
        scenarios.STATION_CASES[label]["dt"]
        for label in ("S0 dt 0.1", "S0 dt 1.0")
    ]
    layer = inspect.signature(station.build_network).parameters[
        "boundary_layer"
    ]
    return (
        f"`dt={sim.dt}`, repeated at {steps[0]} and {steps[1]}",
        f"`speed={station.SPEED}`, level $k$ = "
        f"{hydraulic.HydraulicParameters().level_speed_constant:.1f}"
        f" m/s, floor $D$ = {hydraulic.MIN_DENSITY} m⁻²",
        f"`specific_flow={station.SPECIFIC_FLOW}` on each link",
        f"`boundary_layer={layer.default}` everywhere",
        f"`max_density={sim.max_density}`, supply reduction on (S0) and off "
        "(S0s)",
    )


def station_next():
    group = sum(
        n
        for exit in ("front", "platform_exit")
        for node in station.TABLE_5.values()
        for e, n in node.items()
        if e == exit
    )
    return (
        f"5.5 % of the {group} agents of the front door and platform group "
        f"opt for the platform door, {0.055 * group:.0f} agents",
    )


STATION_REGISTRY = [
    Number(
        STATION_PAGE,
        (
            "The nightclub has ten spaces and four exits",
            "it holds 420 people",
        ),
        station_intro,
    ),
    Number(
        STATION_PAGE,
        (
            "| dart | 7.2 × 5.4 | 38.9 | 39 | 1.00 |",
            "| kitchen | 7.2 × 2.2 | 15.8 | 3 | 0.19 |",
            "| bar | 8.5 × 7.6 | 64.6 | 31 | 0.48 |",
            "| dance | 13.2 × 7.8 | 103.0 | 237 | 2.30 |",
            "| entrance | 2.0 × 4.6 | 9.2 | 0 | 0.00 |",
            "| sunroom | 10.9 × 4.6 | 50.1 | 76 | 1.52 |",
            "| hallway | 4.8 × 8.2 | 39.4 | 12 | 0.30 |",
            "| platform | 12.2 × 2.2 | 26.8 | 18 | 0.67 |",
            "| stage | 5.2 × 3.6 | 18.7 | 4 | 0.21 |",
            "| stageside | 2.4 × 3.6 | 8.6 | 0 | 0.00 |",
            "| dart → kitchen | 0.6 | 3.7 | 0.399 |",
            "| dart → dance | 2.5 | 10.4 | 2.926 |",
            "| kitchen → dance | 0.91 | 10.4 | 0.811 |",
            "| kitchen → kitchen_exit | 0.91 | 3.6 | 0.811 |",
            "| bar → side | 0.91 | 3.8 | 0.811 |",
            "| bar → dance | 1.2 | 11.6 | 1.197 |",
            "| bar → entrance | 0.91 | 5.2 | 0.811 |",
            "| dance → entrance | 0.91 | 9.6 | 0.811 |",
            "| sunroom → dance | 9.2 | 6.1 | 11.837 |",
            "| entrance → front | 1.83 | 2.3 | 2.035 |",
            "| hallway → dance | 1.6 | 8.0 | 1.729 |",
            "| platform → dance | 1.4 | 10.0 | 1.463 |",
            "| stage → stageside | 1.4 | 3.8 | 1.463 |",
            "| dance → stageside | 2.4 | 8.9 | 2.793 |",
            "| stageside → platform_exit | 0.91 | 1.8 | 0.811 |",
        ),
        station_tables,
    ),
    Number(
        STATION_PAGE,
        (
            "The dance floor starts at 2.30 m⁻², above the 1.88 m⁻² where the supply reduction begins and below the default `max_density` of 2.75 m⁻². The model refuses a limit below 2.302 m⁻² for this start.",
        ),
        station_dance_floor,
    ),
    Number(
        STATION_PAGE,
        (
            "A 0.91 m door passes 0.811 persons/s.",
            "1.33 persons/s/m is above the maximum flow k/(4a) = 1.316 persons/s/m",
            "which is 1.33 × 0.91 to within rounding",
        ),
        station_door_flow_limit,
    ),
    Number(
        STATION_PAGE,
        (
            "the dart room goes to the kitchen door (3.7 + 3.6 = 7.3 m against 21.1 m by the dance floor), the main bar to its side door (3.8 m against 7.5 m through the entrance)",
            "the platform door is 8.9 + 1.8 = 10.7 m away and the front door 9.6 + 2.3 = 11.9 m",
            "The split is 347 through the platform door, 31 through the side door, 42 through the kitchen door and none through the front door",
        ),
        station_routes,
    ),
    Number(
        STATION_PAGE,
        (
            "That gives 252 of the 420 to the front door, 60.0 %.",
            "60 % of each space, rounded",
            "`t_max=1800.0`",
            "`max_density=2.75`",
        ),
        station_occupants,
    ),
    Number(
        STATION_PAGE,
        (
            "The model evacuates the 420 people in 442.0 s: 347 through the platform door, 31 through the side door, 42 through the kitchen door and none through the front door. 291 are still inside at 90 s.",
        ),
        station_baseline,
    ),
    Number(
        STATION_PAGE,
        (
            "with $C$ = 0.8113 persons/s",
            "The four occupants of the stage pass the platform",
            "The side door has passed its 31 agents after 40.0 s and the kitchen door its 42 after 102.5 s, limited by the 0.6 m door of the dart room (0.399 persons/s)",
            "door first, from 5.5 s. The fifth passage is the first agent of the dance floor, at 20.5 s",
            "for $D$ between 2.30 and 2.75 m⁻², then 1.8 m in the stage side: between 17.9 s and 25.2 s",
            "342/0.8113 = 421.5 s, so $T = t_5 + 342/C$ = 20.5 + 421.5 = 442.0 s, the model's value",
            "$N/C$ = 347/0.811 = 428 s",
            "The model's 442.0 s lies 14 s above it, less than the 20.5 s of the first arrival",
            "the dart door 0.399 persons/s from 14.0 s (the kitchen door follows 3 s later, the walk of 3.6 m)",
            "then 0.811 persons/s from 20.5 s",
            "That leaves 290.5 inside, to within 8 agents",
            "The model has 291 and EvacuatioNZ 291",
        ),
        station_hand,
    ),
    Number(
        STATION_PAGE,
        (
            "gives 493 s, 51 s more than the model (−10 % for the model)",
            "so v2.3 lies 65 s above its hand value and this model 14 s",
            "(493 s against 442 s)",
            "do not account for 51 s",
            "**Supply reduction** changes the result by 1.5 s",
            "moves it by at most 0.7 s",
            "is at most 1.2 s per door",
        ),
        station_gap,
    ),
    Number(
        STATION_PAGE,
        (
            "| S0s | `supply_reduction=False` | 443.5 | +1.5 |",
            "| S0, `dt=0.1` | time step 0.1 s | 441.3 | −0.7 |",
            "| S0, `dt=1.0` | time step 1.0 s | 442.0 | 0.0 |",
            "Supply reduction changes the result by 1.5 s here",
            "while the dance floor is above 1.88 m⁻²",
            "The split is 347, 31, 42 and 0 at every time step",
        ),
        station_variants,
    ),
    Number(
        STATION_PAGE,
        (
            "in 100 runs with seeds from `SeedSequence(1).spawn`",
            "negative lower end for all eight occupied nodes",
            "All 100 runs give the split 347, 31, 42 and 0, and times from 441.5 s to 442.5 s: a start spread of up to 15 m",
        ),
        station_start_spread,
        slow=True,
    ),
    Number(
        STATION_PAGE,
        (
            "$C$ = 1.33 × 0.91 = 1.210 persons/s. The model evacuates in 303.0 s with the same split, and 258 inside at 90 s",
            "$t_5 + 342/C$ = 20.5 + 282.6 = 303.1 s",
            "gives 345 s",
            "(the model is −12 % below)",
            "347/1.210 = 287 s (the model is +6 % above)",
            "the paper gives no hand value for this case",
            "takes 304.5 s, and S1 at `dt=0.1` takes 302.4 s",
        ),
        station_s1,
    ),
    Number(
        STATION_PAGE,
        (
            "212 to the front door, 185 to the platform door, 20 to the side door and 3 to the kitchen door",
            "controlling link is dance → entrance (0.91 m)",
            "which 201 agents of the dance floor",
            "the 11 of the main bar",
            "$t_5 + (201 - 5)/C$ + walk (s)",
            '| S2 | 187.5 | 23.5 | 187.4 | 195 {{< cite 8 "p. 170" >}}; NIST 188 and 202; hand 177 {{< cite 8 "p. 169" >}} |',
            '| S2b | 269.0 | 25.0 | 268.5 | 272 ± 2 {{< cite 8 "p. 170" >}}; hand 261 {{< cite 8 "p. 170" >}} |',
            "The walk is 2.3 m from the entrance to the front door at 1.2 m/s, 1.9 s",
            "S2 is −4 % from the published 195 s and S2b −1 %, 1 s below the published mean minus one standard deviation (272 ± 2 s",
            "S2 has 214.",
        ),
        station_s2,
    ),
    Number(
        STATION_PAGE,
        (
            "The split is 252 through the front door, 139 through the platform door, 17 through the kitchen door and 12 through the side door: 60.0 %, 33.1 %, 4.0 % and 2.9 %",
            "which 233 agents pass",
            "| S3 | 308.0 | 257 | – |",
            "| S3n | 214.0 | 202 | 201 ± 8 s, about 163 inside at 90 s |",
            "S3n is +6 % above the published 201 s: 13 s above the mean and 5 s above the mean plus one standard deviation",
            "S3n has 202 agents inside at 90 s",
        ),
        station_s3,
    ),
    Number(
        STATION_PAGE,
        (
            "in 42 values: 0.80 to 1.20 in steps of 0.01 and the tie at 0.875",
            "if $9.6 f + 2.3 < 8.9 + 1.8$, that is for $f < 0.875$",
            "$0.875 \\times 9.6 + 2.3 = 8.9 + 1.8$ exactly",
            "which is $0.875 \\times 9.6$",
            "343 agents leave through the front door",
            "the time does not decrease as $f$ grows",
            "The flip is at the exact tie $f$ = 0.875",
            "the time is 442.0 s from $f$ = 0.88",
            "172 go to the front door and 175 to the platform door",
            "the shortest time of the sweep, 230.0 s",
            "the same time in all 42 values",
            "In this study the flip is at 8.4 m",
        ),
        station_s4a,
        slow=True,
    ),
    Number(
        STATION_PAGE,
        (
            "| 1.21 | 331.0 | 369.0 | 418.5 | 483.5 |",
            "| 1.25 | 321.0 | 358.0 | 405.5 | 469.0 |",
            "| 1.3 | 309.5 | 345.0 | 391.0 | 451.5 |",
            "| 1.33 | 303.0 | 337.5 | 382.5 | 442.0 |",
            "$F_s$ = 1.33 and $b$ = 0.15, is S0",
            "In all 16 cases $T$ lies between 0.46 s and 0.02 s below $t_5 + 342/C$",
        ),
        station_s4b,
    ),
    Number(
        STATION_PAGE,
        (
            "| 2.5 | 441.0 | 441.5 |",
            "| 2.75 | 442.0 | 443.5 |",
            "| 3.0 | 443.0 | 446.0 |",
            "| 3.25 | 444.0 | 451.0 |",
            "| 3.5 | 445.0 | 453.0 |",
            "`max_density` from 2.5 to 3.5 m⁻²",
            "beyond 2.75 m⁻²",
            "the fifth passage is later (19.5 s at 2.5 m⁻², 23.5 s at 3.5 m⁻² with supply reduction, 31.5 s without)",
            "differ by 8.0 s at most",
        ),
        station_s4c,
    ),
    Number(
        STATION_PAGE,
        (
            '| S0, inside at 90 s | 291 | 291 {{< cite 8 "p. 166" >}} | 0 % | agrees |',
            '| S0 | 442.0 s | 493 s {{< cite 8 "p. 166" >}} | −10 % | differs; the paper does not explain the excess of v2.3 over its own hand value |',
            '| S1 | 303.0 s | 345 s {{< cite 8 "p. 169" >}} | −12 % | differs; the paper does not explain the excess of v2.3 over its own hand value |',
            '| S2 | 187.5 s | 195 s {{< cite 8 "p. 170" >}} | −4 % | agrees |',
            '| S2b | 269.0 s | 272 ± 2 s {{< cite 8 "p. 170" >}} | −1 % | agrees |',
            '| S3n | 214.0 s | 201 ± 8 s {{< cite 8 "p. 171" >}} | +6 % | differs; boundary layer of the case inferred, and the fixed 60 % split cannot give the published 67 % front share |',
            '| S3 | 308.0 s | 201 ± 8 s {{< cite 8 "p. 171" >}} | +53 % | differs |',
        ),
        station_comparison,
    ),
    Number(
        STATION_PAGE,
        (
            "The length of dance → entrance is 12.5 % from the tie of the routes",
            "effect is 1.5 s here",
            "The dance floor starts above 1.88 m⁻²",
        ),
        station_limits,
    ),
    Number(
        STATION_PAGE,
        (
            "5.5 % of the 397 agents of the front door and platform group opt for the platform door, 22 agents",
        ),
        station_next,
    ),
    Number(
        STATION_PAGE,
        (
            "`dt=0.5`, repeated at 0.1 and 1.0",
            "`speed=1.2`, level $k$ = 1.4 m/s, floor $D$ = 0.54 m⁻²",
            "`specific_flow=1.33` on each link",
            "`boundary_layer=0.15` everywhere",
            "`max_density=2.75`, supply reduction on (S0) and off (S0s)",
        ),
        station_settings,
    ),
]


@pytest.mark.parametrize("number", [_param(n) for n in STATION_REGISTRY])
def test_station_page_numbers(number):
    test_page_shows_the_number_the_code_produces(number)
