# SPDX-License-Identifier: LGPL-3.0-or-later
"""Physical connection budgets and conservation through queue transitions."""

import netgen
import numpy as np
import pytest

from jupedsim_network import Network, NetworkSimulation, Population


def network(kind="door", reverse=False, area=30.0, paired=True):
    net = Network()
    if kind == "stair":
        net.add_stair("A", area=area, riser=0.18, tread=0.28)
    else:
        net.add_room("A", area=area)
    net.add_room("B", area=area)
    net.add_safe("xA")
    net.add_safe("xB")
    source, target = ("B", "A") if reverse else ("A", "B")
    kwargs = dict(width=1.0, boundary_layer=0.0, specific_flow=1.0, kind=kind)
    net.connect(source, target, bidirectional=paired, **kwargs)
    if not paired:
        net.connect(target, source, bidirectional=False, **kwargs)
    net.connect("A", "xA", width=4.0, boundary_layer=0.0, specific_flow=1.0)
    net.connect("B", "xB", width=4.0, boundary_layer=0.0, specific_flow=1.0)
    return net


def assert_window_budget(flow, capacity, dt):
    """Directly check every time window, independently of the carry algorithm."""
    cumulative = np.r_[0, np.cumsum(flow)]
    for start in range(len(flow)):
        count = cumulative[start + 1 :] - cumulative[start]
        elapsed = dt * np.arange(1, len(count) + 1)
        assert np.all(count <= 1 + capacity * elapsed + 1e-8)


DEMANDS = {
    "balanced": [("A", 8, 0), ("B", 8, 0)],
    "asymmetric": [("A", 15, 0), ("B", 1, 0)],
    "reversal": [("A", 1, 0), ("B", 1, 0.5), ("A", 1, 2)],
    "idle_then_counterflow": [("A", 1, 0), ("A", 4, 10), ("B", 4, 10)],
}


def populations(demand):
    return [
        Population(
            node,
            count,
            target="xB" if node == "A" else "xA",
            pre_movement=delay,
        )
        for node, count, delay in demand
    ]


def check_run(sim, result):
    netgen.check_conservation(result, sim.network)
    netgen.check_density(result, sim.network, sim.max_density, 1.0)
    for link in sim.network.links:
        assert_window_budget(
            result.link_flow[1:, link.index], link.capacity, sim.dt
        )
    if sim.counterflow != "independent":
        assert_window_budget(result.link_flow[1:, :2].sum(axis=1), 1.0, sim.dt)


@pytest.mark.parametrize("kind", ["door", "opening", "stair"])
@pytest.mark.parametrize("reverse", [False, True])
def test_pair_represents_one_connection(kind, reverse):
    net = network(kind, reverse)
    first, second = net.links[:2]
    assert net._reverse == {0: 1, 1: 0}
    assert (first.source, first.target) == (second.target, second.source)
    assert first.capacity == second.capacity == 1.0
    assert first.kind == second.kind == kind
    assert all(link.source < 2 for link in net.links)


@pytest.mark.parametrize("counterflow", ["bounding", "estimate", "independent"])
@pytest.mark.parametrize("dt", [0.1, 0.5, 2.0])
@pytest.mark.parametrize("demand", DEMANDS.values(), ids=DEMANDS)
def test_capacity_conservation_and_queue_transitions(counterflow, dt, demand):
    sim = NetworkSimulation(
        network(), populations(demand), counterflow=counterflow, dt=dt
    )
    result = sim.run(seed=7)
    check_run(sim, result)
    assert result.evacuated == sum(count for _, count, _ in demand)


@pytest.mark.parametrize("kind", ["door", "opening", "stair"])
@pytest.mark.parametrize("reverse", [False, True])
def test_independent_matches_two_separate_one_way_connections(kind, reverse):
    pops = populations(DEMANDS["asymmetric"])
    paired = NetworkSimulation(
        network(kind, reverse), pops, counterflow="independent"
    )
    separate = NetworkSimulation(network(kind, reverse, paired=False), pops)
    assert netgen.same_result(paired.run(seed=7), separate.run(seed=7))


@pytest.mark.parametrize("counterflow", ["bounding", "estimate", "independent"])
@pytest.mark.parametrize("reverse", [False, True])
def test_blocked_receiving_node_and_mixed_agent_sizes(
    counterflow, reverse, monkeypatch
):
    net = network(reverse=reverse, area=2.0)
    pops = [
        Population("A", 1, area_factor=1.5, target="xB"),
        Population("B", 2, area_factor=2.5, target="xA", pre_movement=3.0),
    ]
    worst = [-np.inf]
    netgen.area_load_monitor(monkeypatch, worst)
    sim = NetworkSimulation(net, pops, counterflow=counterflow, dt=0.1)
    result = sim.run(seed=7)
    assert result.evacuated == 3
    forward = result.link_names.index("A->B")
    assert not result.link_flow[result.times <= 3.0, forward].any()
    netgen.check_conservation(result, net)
    assert worst[0] <= 1e-9
    if counterflow != "independent":
        assert_window_budget(result.link_flow[1:, :2].sum(axis=1), 1.0, sim.dt)


@pytest.mark.parametrize("counterflow", ["bounding", "estimate"])
def test_two_full_nodes_do_not_exchange_without_receiving_space(counterflow):
    # Storage is checked before departures: simultaneous swaps are not allowed.
    net = network(area=1.0)
    pops = [Population("A", 2, target="xB"), Population("B", 2, target="xA")]
    sim = NetworkSimulation(
        net, pops, max_density=2.0, counterflow=counterflow, t_max=5
    )
    result = sim.run(seed=7)
    check_run(sim, result)
    assert result.evacuated == 0
    assert not result.link_flow.any()


@pytest.mark.parametrize("kind", ["door", "opening", "stair"])
@pytest.mark.parametrize(
    "counterflow, passages",
    [("bounding", 2), ("estimate", 3), ("independent", 6)],
)
def test_balanced_first_step_uses_prescribed_total_reduction(
    kind, counterflow, passages
):
    # C = 1/s, dt = 2 s, initial credit = 1 person.
    # Shared: floor(1 + 0.94*2) = 2 or floor(1 + 1*2) = 3.
    # Independent: floor(1 + 1*2) in each direction, hence 6 total.
    sim = NetworkSimulation(
        network(kind),
        populations(DEMANDS["balanced"]),
        counterflow=counterflow,
        dt=2.0,
        t_max=2.0,
    )
    result = sim.run(seed=7)
    assert result.link_flow[1, :2].sum() == passages
    netgen.check_conservation(result, sim.network)
