# SPDX-License-Identifier: LGPL-3.0-or-later
"""Properties of the model on random networks (P1-P10 of issue #48).

Each example is built once and run once per configuration; all checks of
that example use these runs. Assertion messages start with the property:

- P1 conservation, P2 at most 1 + C t per link, P3 per two-way pair,
  P4 max_density, P10 exit times: on every run.
- P5 the same seed gives the same result.
- P6 "independent" equals the network rebuilt from one-way connections.
- P7 runs without counterflow are identical under all three values.
- P8 default routing has no counterflow.
- P9 route tables take tied links only.

The PR profile draws small networks with one area factor per run. The
tests marked ``fuzz`` draw larger networks with mixed area factors and
check the area-weighted density through the private ``_Run._step``
(decision D5), and report how T changes with dt (decision D1).
"""

import os

import netgen
import numpy as np
import pytest
from hypothesis import event, example, given, settings


def _run_all(spec, net):
    """One run per counterflow value, with the same seed."""
    return {
        cf: netgen.simulation(spec, cf, net).run(spec["seed"])
        for cf in netgen.COUNTERFLOW
    }


def _check_run(result, sim, cf, pairs):
    net = sim.network
    netgen.check_conservation(result, net)
    netgen.check_link_bound(result, net, sim.dt)
    if cf != "independent":
        netgen.check_pair_bound(result, net, sim.dt, pairs)
    netgen.check_exit_times(result, sim)


def _check_seed(spec, net):
    """P5 on the default counterflow value."""
    sim = netgen.simulation(spec, "bounding", net)
    seed = spec["seed"]
    first = sim.run(seed)
    assert netgen.same_result(first, sim.run(seed)), "P5: rerun differs"
    plain = sim.run(seed, record=False)
    assert np.array_equal(plain.exit_times, first.exit_times, equal_nan=True), (
        "P5: record=False changes exit times"
    )
    many = sim.run_many(2, seed).evacuation_times
    again = sim.run_many(2, seed).evacuation_times
    assert np.array_equal(many, again, equal_nan=True), "P5: run_many differs"
    for i, child in enumerate(np.random.SeedSequence(seed).spawn(2)):
        replay = sim.run(child).evacuation_time
        assert np.array_equal(many[i], replay, equal_nan=True), (
            f"P5: replay of run {i} differs"
        )


def _check_one_way_oracle(spec, net, independent):
    """P6: two one-way connections behave as "independent"."""
    one_way = netgen.build_network(spec, one_way=True)
    fields = (
        "index",
        "name",
        "source",
        "target",
        "capacity",
        "length",
        "kind",
        "merge_weight",
    )
    for a, b in zip(net.links, one_way.links, strict=True):
        for f in fields:
            assert getattr(a, f) == getattr(b, f), f"broken oracle: {f}"
    assert not one_way._reverse, "broken oracle: one-way network has pairs"
    oracle = netgen.simulation(spec, "bounding", one_way).run(spec["seed"])
    assert netgen.same_result(oracle, independent), (
        'P6: "independent" differs from one-way links'
    )


def _check_without_counterflow(spec, net, results):
    """P7 and P8."""
    pairs = netgen.pairs(spec, net)
    independent = results["independent"]
    default_routing = all(p["target"] is None for p in spec["populations"])
    if default_routing:
        event("P8: default routing")
        for cf, r in results.items():
            assert not netgen.two_way_flow(r, pairs), (
                f"P8: a pair passes agents both ways under {cf}"
            )
    finished = np.isfinite(independent.evacuation_time)
    quiet = finished and not netgen.two_way_flow(independent, pairs)
    event(f"P7: precondition {'holds' if quiet else 'fails'}")
    if not (quiet or default_routing):
        return
    label = "P8" if default_routing else "P7"
    for cf in ("estimate", "bounding"):
        assert netgen.same_result(results[cf], independent), (
            f"{label}: {cf} differs from independent without counterflow"
        )


def _door(source, target, width, bidirectional=False, kind="door", length=0.0):
    return dict(
        source=source,
        target=target,
        width=width,
        kind=kind,
        length=length,
        bidirectional=bidirectional,
        merge_weight=1.0,
    )


def _example(rooms, safes, connections, populations, speed="fixed", **options):
    spec = dict(
        seed=1,
        dt=0.5,
        max_density=2.75,
        supply_reduction=True,
        split_ties=True,
        t_max=1800.0,
        rooms=rooms,
        stairs=[],
        safes=safes,
        connections=connections,
        populations=[
            dict(node=n, count=c, speed=speed, area_factor=1.0, target=t)
            for n, c, t in populations
        ],
    )
    return spec | options


# Two full rooms swap their occupants through one two-way door.
SWAP = _example(
    [["A", 20.0], ["B", 20.0]],
    ["xA", "xB"],
    [
        _door("A", "B", 1.0, bidirectional=True),
        _door("A", "xA", 4.0, kind="opening"),
        _door("B", "xB", 4.0, kind="opening"),
    ],
    [("A", 40, "xB"), ("B", 40, "xA")],
)

# Two full rooms swap through one door: the documented lock (limitations).
# Nobody ever passes, so the run is unfinished; t_max keeps it short.
LOCK = _example(
    [["A", 20.0], ["B", 20.0]],
    ["xA", "xB"],
    [
        _door("A", "B", 1.0, bidirectional=True),
        _door("A", "xA", 4.0, kind="opening"),
        _door("B", "xB", 4.0, kind="opening"),
    ],
    [("A", 55, "xB"), ("B", 55, "xA")],
    t_max=60.0,
)

# Two equal doors merge into a nearly full corridor: the queue heads have
# equal keys, so the seeded tie-break decides who enters (P5); the walk
# to the exit makes the sampled speeds matter.
MERGE = _example(
    [["A", 20.0], ["B", 20.0], ["corridor", 4.0]],
    ["exit"],
    [
        _door("A", "corridor", 1.0),
        _door("B", "corridor", 1.0),
        _door("corridor", "exit", 0.8, length=10.0),
    ],
    [("A", 30, None), ("B", 30, None), ("corridor", 9, None)],
    speed="uniform",
)

# A crowded room fills a small corridor that drains through a narrow door.
BOTTLENECK = _example(
    [["room", 100.0], ["corridor", 4.0]],
    ["exit"],
    [
        _door("room", "corridor", 4.0, bidirectional=True, kind="opening"),
        _door("corridor", "exit", 0.8),
    ],
    [("room", 200, None)],
    supply_reduction=False,
)


def _check_all(spec):
    net = netgen.build_network(spec)
    results = _run_all(spec, net)
    af = netgen.area_factor_of(spec)
    pairs = netgen.pairs(spec, net)
    for cf, result in results.items():
        sim = netgen.simulation(spec, cf, net)
        _check_run(result, sim, cf, pairs)
        netgen.check_density(result, net, spec["max_density"], af)
        event(f"finished: {bool(np.isfinite(result.evacuation_time))}")
    _check_seed(spec, net)
    _check_one_way_oracle(spec, net, results["independent"])
    _check_without_counterflow(spec, net, results)


@example(spec=BOTTLENECK)
@example(spec=MERGE)
@given(spec=netgen.specs(targets=False))
def test_random_networks_default_routing(spec):
    _check_all(spec)


@example(spec=SWAP)
@example(spec=LOCK)
@given(spec=netgen.specs(targets=True))
def test_random_networks_with_targets(spec):
    _check_all(spec)


# To the nearest exit, r1 has two 0 m routes: r1->s1 (one hop) and
# r0 to s0 (two hops). Only r1->s1 is tied; Dijkstra alone may return
# r1->r0 (P9 (c)).
TIED = dict(
    rooms=[["r0", 4.0], ["r1", 4.0]],
    stairs=[],
    safes=["s0", "s1"],
    connections=[
        _door("r0", "s0", 0.6),
        _door("r1", "s0", 0.6, length=1.0),
        _door("r1", "s1", 0.6),
        _door("r0", "r1", 0.6, bidirectional=True),
    ],
)


@example(graph=TIED)
@given(graph=netgen.graphs())
def test_route_tables_take_tied_links(graph):
    _check_route_tables(graph)


def _check_route_tables(graph):
    spec = dict(graph, populations=[])
    net = netgen.build_network(spec)
    for target in [None, *graph["safes"]]:
        _check_route_table(net, target)


def _check_route_table(net, target):
    """P9 for one target."""
    dist, hops = netgen.oracle_distances(net, target)
    table = net.route_table(target)  # P9 (e): raises on a cycle
    choices = net.route_choices(target)
    links = net.links
    for u, node in enumerate(net.nodes):
        unreachable = node.kind == "safe" or dist[u] == float("inf")
        assert (table[u] is None) == unreachable, f"P9 (a): node {node.name}"
        expected = tuple(
            lk.index
            for lk in links
            if lk.source == u and netgen.tied(lk, dist, hops)
        )
        assert choices[u] == expected, f"P9 (d): ties at {node.name}"
        if table[u] is None:
            continue
        lk = links[table[u]]
        assert netgen.tied_distance(lk, dist), f"P9 (b): {lk.name} not shortest"
        if choices[u]:
            assert table[u] in choices[u], f"P9 (c): {lk.name} not tied"


# Scheduled job ----------------------------------------------------------------


@pytest.mark.fuzz
@given(spec=netgen.specs(wide=True))
def test_random_networks_wide(spec):
    net = netgen.build_network(spec)
    worst = [-np.inf]
    with pytest.MonkeyPatch.context() as mp:
        netgen.area_load_monitor(mp, worst)
        results = _run_all(spec, net)
    assert worst[0] <= 1e-9, f"P4: a node exceeds max_density by {worst[0]}"
    pairs = netgen.pairs(spec, net)
    for cf, result in results.items():
        _check_run(result, netgen.simulation(spec, cf, net), cf, pairs)
        if np.isfinite(result.evacuation_time):
            continue
        stalled = result.link_flow[-int(60 / spec["dt"]) :].sum() == 0
        event(f"unfinished, no flow in the last 60 s: {stalled}")
    _check_seed(spec, net)
    _check_one_way_oracle(spec, net, results["independent"])
    _check_without_counterflow(spec, net, results)


@pytest.mark.fuzz
@given(graph=netgen.graphs(wide=True))
def test_route_tables_take_tied_links_wide(graph):
    """P9 on the larger graphs of the scheduled job."""
    _check_route_tables(graph)


def _write_dt_report(rows, title):
    """Append the dt report to the job summary (decision D1, report only)."""
    if not rows:
        return
    rows = np.array(rows)
    lines = [f"## {title} (report only, #55)", ""]
    lines += ["| dt | runs | rises | median | max |", "|---|---|---|---|---|"]
    for col, dt in enumerate((0.5, 0.25)):
        d = rows[:, col]
        d = d[np.isfinite(d)]
        lines.append(
            f"| {dt} -> {dt / 2} | {d.size} | {(d > 0).sum()} "
            f"| {np.median(d):.3f} s | {d.max(initial=0):.3f} s |"
        )
    text = "\n".join(lines) + "\n"
    print(text)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write(text)


@pytest.fixture(scope="module")
def dt_report():
    rows = []
    yield rows
    _write_dt_report(rows, "T(dt/2) - T(dt) on random networks")


@pytest.fixture(scope="module")
def dt_median_report():
    rows = []
    yield rows
    _write_dt_report(rows, "Median of 30 seeds, T(dt/2) - T(dt)")


@pytest.mark.fuzz
@settings(max_examples=300)
@given(spec=netgen.specs())
def test_dt_report(spec, dt_report):
    """Report only: T is not guaranteed to fall with dt (#55)."""
    times = []
    for dt in (0.5, 0.25, 0.125):
        sim = netgen.simulation(dict(spec, dt=dt), "bounding")
        times.append(sim.run(spec["seed"]).evacuation_time)
    dt_report.append([times[1] - times[0], times[2] - times[1]])


@pytest.mark.fuzz
@settings(max_examples=30)
@given(spec=netgen.specs())
def test_dt_median_report(spec, dt_median_report):
    """Report only: the median over 30 seeds as dt falls (#55)."""
    medians = []
    for dt in (0.5, 0.25, 0.125):
        sim = netgen.simulation(dict(spec, dt=dt), "bounding")
        medians.append(np.median(sim.run_many(30, spec["seed"]).complete))
    dt_median_report.append([medians[1] - medians[0], medians[2] - medians[1]])
