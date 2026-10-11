# SPDX-License-Identifier: LGPL-3.0-or-later
"""Fixed-seed fuzz sweeps of the scheduled job (marked ``fuzz``).

The generators fz1 (random graphs), fz2 (layers) and fz3 (crowded,
two-way, targets) of the earlier QA rounds, run with both ``split_ties``
values and max_density 2.75 and 3.5 under every ``counterflow`` value.
Each run is checked for P1, P2, P3, P4 (area-weighted, through the
private ``_Run._step``, decision D5), P5 and P10, and each seed for P7.
The generators do not ensure a route: networks without one are counted
and skipped. Start nodes hold at most max_density. Failing seeds
are written to ``fuzz-failures/`` for the job artifact.
"""

import json
import math
import random
import warnings
from collections import Counter

import netgen
import numpy as np
import pytest
from docpages import ROOT

from jupedsim_network import (
    Fixed,
    Network,
    NetworkSimulation,
    Population,
    Uniform,
)

pytestmark = pytest.mark.fuzz


def fuzz1(seed, max_density):
    """Random graph: rooms joined at random, some without a route."""
    rnd = random.Random(seed)
    net = Network()
    n_rooms, n_safe = rnd.randint(2, 7), rnd.randint(1, 3)
    rooms = [f"r{i}" for i in range(n_rooms)]
    safes = [f"s{i}" for i in range(n_safe)]
    areas = {r: rnd.choice([4.0, 10.0, 30.0, 100.0]) for r in rooms}
    for r in rooms:
        net.add_room(r, area=areas[r])
    for s in safes:
        net.add_safe(s)
    pairs = set()
    for _ in range(rnd.randint(n_rooms, 3 * n_rooms)):
        a = rnd.choice(rooms)
        b = rnd.choice(rooms + safes)
        if a == b or (a, b) in pairs or (b, a) in pairs:
            continue
        pairs.add((a, b))
        net.connect(
            a,
            b,
            width=rnd.choice([0.8, 1.0, 1.2, 2.0]),
            length=rnd.choice([0.0, 0.0, 1.0, 2.0, 3.0, 5.0, 0.1, 0.2, 0.3]),
            kind=rnd.choice(["door", "door", "opening"]),
            bidirectional=rnd.random() < 0.6,
        )
    # Start rooms hold at most max_density; the cap does not change the
    # draws, so the networks are the same for every max_density.
    free = {r: math.floor(max_density * areas[r] + 1e-9) for r in rooms}
    pops = []
    for _ in range(rnd.randint(1, 3)):
        room, count = rnd.choice(rooms), rnd.randint(1, 25)
        pre = rnd.choice([Fixed(0.0), Uniform(0, 20)])
        count = min(count, free[room])
        free[room] -= count
        if count:
            pops.append(Population(room, count, pre_movement=pre))
    return net, pops


def fuzz2(seed, max_density):
    """Layers of rooms towards the exits, with lateral links.

    Rooms of at least 20 m² never start above 1.5 agents/m², so
    ``max_density`` is not needed.
    """
    rnd = random.Random(seed)
    net = Network()
    n_layers = rnd.randint(2, 4)
    layers = [
        [f"r{lay}_{i}" for i in range(rnd.randint(1, 4))]
        for lay in range(n_layers)
    ]
    safes = [f"s{i}" for i in range(rnd.randint(1, 3))]
    for layer in layers:
        for r in layer:
            net.add_room(r, area=rnd.choice([20.0, 50.0, 200.0]))
    for s in safes:
        net.add_safe(s)
    for layer, after in zip(layers, layers[1:] + [safes]):
        _connect_layer(net, rnd, layer, after, safes)
    pops = [p for layer in layers for p in _layer_populations(rnd, layer)]
    if not pops:
        pops.append(Population(layers[0][0], 10))
    return net, pops


def _connect_layer(net, rnd, layer, after, safes):
    """Links of fz2 from one layer to the next, then within the layer."""
    for r in layer:
        _connect_forward(net, rnd, r, after, safes)
    for i in range(len(layer) - 1):
        if rnd.random() < 0.5:
            net.connect(
                layer[i],
                layer[i + 1],
                width=1.0,
                length=rnd.choice([0.0, 1.0]),
                bidirectional=rnd.random() < 0.7,
            )


def _connect_forward(net, rnd, r, after, safes):
    for b in rnd.sample(after, rnd.randint(1, len(after))):
        net.connect(
            r,
            b,
            width=rnd.choice([0.8, 1.0, 2.0]),
            length=rnd.choice([0.0, 1.0, 2.0]),
            kind=rnd.choice(["door", "opening"]),
            bidirectional=(b not in safes) and rnd.random() < 0.5,
        )


def _layer_populations(rnd, layer):
    pops = []
    for r in layer:
        if rnd.random() < 0.6:
            pops.append(
                Population(
                    r,
                    rnd.randint(1, 30),
                    pre_movement=rnd.choice([Fixed(0.0), Uniform(0, 20)]),
                    speed=rnd.choice([1.2, Uniform(0.8, 1.4)]),
                )
            )
    return pops


def fuzz3(seed, max_density):
    """Crowded: dense starts, narrow exits, two-way links, targets."""
    rnd = random.Random(10_000 + seed)
    net = Network()
    n_rooms, n_safe = rnd.randint(3, 8), rnd.randint(1, 3)
    rooms = [f"r{i}" for i in range(n_rooms)]
    safes = [f"s{i}" for i in range(n_safe)]
    areas = {r: rnd.choice([10.0, 20.0, 40.0, 80.0]) for r in rooms}
    for r in rooms:
        net.add_room(r, area=areas[r])
    for s in safes:
        net.add_safe(s)
    pairs = set()
    order = rooms[:]
    rnd.shuffle(order)
    edges = [(order[i], order[i + 1]) for i in range(len(order) - 1)]
    edges.append((order[-1], rnd.choice(safes)))
    for _ in range(rnd.randint(n_rooms, 3 * n_rooms)):
        edges.append((rnd.choice(rooms), rnd.choice(rooms + safes)))
    for a, b in edges:
        if a == b or (a, b) in pairs or (b, a) in pairs:
            continue
        pairs.add((a, b))
        to_safe = b in safes
        if to_safe:
            width = rnd.choice([0.6, 0.8, 1.0])
        else:
            width = rnd.choice([0.8, 1.2, 2.0, 4.0])
        net.connect(
            a,
            b,
            width=width,
            length=rnd.choice([0.0, 1.0, 3.0, 10.0]),
            kind=rnd.choice(["door", "opening"]),
            bidirectional=(not to_safe) and rnd.random() < 0.8,
            merge_weight=rnd.choice([1.0, 1.0, 2.0, 0.5]),
        )
    pops = []
    for r in rooms:
        if rnd.random() < 0.7:
            af = rnd.choice([1.0, 1.0, 1.0, 1.5, 2.0])
            # Up to 2.6/2.75 of max_density: 2.6 agents/m² at 2.75.
            cap = math.floor(2.6 / 2.75 * max_density * areas[r] / af + 1e-9)
            pops.append(
                Population(
                    r,
                    rnd.randint(max(1, cap // 3), cap),
                    pre_movement=rnd.choice([Fixed(0.0), Uniform(0, 30)]),
                    speed=rnd.choice([1.2, Uniform(0.6, 1.4)]),
                    area_factor=af,
                    target=rnd.choice([None, None, rnd.choice(safes)]),
                )
            )
    if not pops:
        pops.append(Population(rooms[0], 10))
    return net, pops


FAMILIES = {"fz1": (fuzz1, 2000), "fz2": (fuzz2, 600), "fz3": (fuzz3, 600)}

# Inputs the generators do not rule out; counted, not failures.
INVALID = ("No route from",)


def _simulations(net, pops, **options):
    sims = {}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        for cf in netgen.COUNTERFLOW:
            sims[cf] = NetworkSimulation(net, pops, counterflow=cf, **options)
    return sims


def _check_seed(net, pops, seed, options, mp):
    sims = _simulations(net, pops, t_max=1200.0, **options)
    pairs = sorted((i, j) for i, j in net._reverse.items() if i < j)
    worst = [-np.inf]
    netgen.area_load_monitor(mp, worst)
    results = {cf: sim.run(seed) for cf, sim in sims.items()}
    mp.undo()
    assert worst[0] <= 1e-9, f"P4: a node exceeds max_density by {worst[0]}"
    for cf, r in results.items():
        netgen.check_conservation(r, net)
        netgen.check_link_bound(r, net, sims[cf].dt)
        if cf != "independent":
            netgen.check_pair_bound(r, net, sims[cf].dt, pairs)
        netgen.check_exit_times(r, sims[cf])
    again = sims["bounding"].run(seed)
    assert netgen.same_result(again, results["bounding"]), "P5: rerun differs"
    independent = results["independent"]
    if np.isfinite(independent.evacuation_time) and not netgen.two_way_flow(
        independent, pairs
    ):
        for cf in ("estimate", "bounding"):
            assert netgen.same_result(results[cf], independent), f"P7: {cf}"


def _outcome(net, pops, seed, options, mp):
    """None if the seed passes, the reason if its input is invalid, or
    the failure; other errors propagate."""
    try:
        _check_seed(net, pops, seed, options, mp)
    except ValueError as error:
        reason = next((m for m in INVALID if m in str(error)), None)
        if reason is None:
            raise
        return reason
    except AssertionError as error:
        return dict(seed=seed, error=str(error).split("\n")[0])
    return None


@pytest.mark.parametrize("split_ties", [True, False])
@pytest.mark.parametrize("max_density", [2.75, 3.5])
@pytest.mark.parametrize("family", FAMILIES)
def test_fixed_seed_sweep(family, max_density, split_ties, monkeypatch):
    make, count = FAMILIES[family]
    options = dict(max_density=max_density, split_ties=split_ties)
    skipped, failures = Counter(), []
    for seed in range(count):
        net, pops = make(seed, max_density)
        outcome = _outcome(net, pops, seed, options, monkeypatch)
        monkeypatch.undo()
        if isinstance(outcome, dict):
            failures.append(outcome)
        elif outcome:
            skipped[outcome] += 1
    print(f"{family} max_density {max_density} split_ties {split_ties}:")
    print(f"  {count} seeds, skipped {dict(skipped)}, failed {len(failures)}")
    if failures:
        out = ROOT / "fuzz-failures"
        out.mkdir(exist_ok=True)
        name = f"{family}-{max_density}-{split_ties}.json"
        (out / name).write_text(json.dumps(failures, indent=1))
    assert not failures, failures[:5]
