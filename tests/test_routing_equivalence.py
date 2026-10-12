# SPDX-License-Identifier: LGPL-3.0-or-later
"""Exact differential baseline captured from corrected implementation aa1460f.

The fixture records the public methods before extraction. It must not be
regenerated merely because a routing result changes: investigate that change.
"""

import copy
import json
import random
from pathlib import Path

import pytest

from jupedsim_network import Network

BASELINE = Path(__file__).parent / "data" / "routing_aa1460f.json"


def generated_network(seed):
    rng = random.Random(seed)
    net = Network()
    for index in range(6):
        if index == 1 and seed % 2:
            net.add_stair(f"r{index}", area=10, riser=0.18, tread=0.28)
            continue
        net.add_room(f"r{index}", area=10)
    net.add_room("isolated", area=10)
    net.add_safe("s0")
    net.add_safe("s1")
    scale = (1e-6, 1.0, 1e6)[seed % 3]
    delta = (0, 0.5e-9, 2e-9)[seed % 3]
    edges = [
        ("r0", "r1", 0),
        ("r0", "r2", 0),
        ("r1", "s0", 1),
        ("r2", "s0", 1 + delta),
        ("r3", "r4", 0),
        ("r4", "r3", 0),
        ("r4", "s1", 2),
        ("r5", "s1", 0),
    ]
    for _ in range(12):
        a, b = rng.sample(range(1, 6), 2)
        length = rng.choice([0, 0.1, 0.2, 0.3, 1, 1 + 0.5e-9, 1 + 2e-9, 2])
        edges.append((f"r{a}", f"r{b}", length))
    rng.shuffle(edges)
    for a, b, length in edges:
        net.connect(a, b, width=1, length=length * scale, bidirectional=False)
    return net


@pytest.fixture(scope="module")
def baseline():
    recorded = json.loads(BASELINE.read_text())
    assert recorded["baseline_commit"] == "aa1460f"
    assert len(recorded["cases"]) == 192
    return recorded["cases"]


@pytest.mark.parametrize("seed", range(32))
def test_exact_pre_extraction_equivalence(seed, baseline):
    net = generated_network(seed)
    before = copy.deepcopy(vars(net))
    nodes, links = net.nodes, net.links
    cases = [case for case in baseline if case["seed"] == seed]
    assert len(cases) == 6
    for case in cases:
        kwargs = dict(target=case["target"], routing_policy=case["policy"])
        assert net.route_table(**kwargs) == case["table"]
        assert net.route_choices(**kwargs) == [
            tuple(c) for c in case["choices"]
        ]
    assert vars(net) == before
    assert all(a is b for a, b in zip(nodes, net.nodes))
    assert all(a is b for a, b in zip(links, net.links))


def test_algorithms_use_supplied_costs_without_hydraulics(monkeypatch):
    from jupedsim_network import hydraulic, routing, routing_costs

    net = Network()
    net.add_room("A", area=10)
    net.add_room("B", area=10)
    net.add_safe("exit")
    net.connect("A", "exit", width=1, length=1, bidirectional=False)
    net.connect("A", "B", width=1, length=10, bidirectional=False)
    net.connect("B", "exit", width=1, length=10, bidirectional=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("Routing algorithms must not construct costs")

    monkeypatch.setattr(hydraulic, "speed", forbidden)
    monkeypatch.setattr(routing_costs, "edge_costs", forbidden)
    monkeypatch.setattr(routing_costs, "edge_cost", forbidden)
    # The longer geometric path is cheaper under the supplied costs.
    costs = [5.0, 1.0, 1.0]
    assert routing.route_table(net.nodes, net.links, [2], costs) == [1, 2, None]
    assert routing.route_choices(net.nodes, net.links, [2], costs) == [
        (1,),
        (2,),
        (),
    ]
    assert routing.distances(net.nodes, net.links, [2], costs) == (
        [2, 1, 0],
        [2, 1, 0],
    )
    assert costs == [5.0, 1.0, 1.0]
