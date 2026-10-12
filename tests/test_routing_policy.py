# SPDX-License-Identifier: LGPL-3.0-or-later
import math

import numpy as np
import pytest

from jupedsim_network import (
    Network,
    NetworkSimulation,
    Population,
    load_scenario,
    save_scenario,
)
from jupedsim_network.network import _edge_cost
from jupedsim_network.tui import netview

TIME = "shortest_free_flow_time"
LEVEL_SPEED = 1.4 * (1 - 0.266 * 0.54)
STAIR_SPEED = (51.8 * math.sqrt(0.28 / 0.18) / 60) * (1 - 0.266 * 0.54)


def alternatives(stair_length=30, level_length=35):
    net = Network()
    net.add_room("start", area=100)
    net.add_stair("stair", area=100, riser=0.18, tread=0.28)
    net.add_room("hall", area=100)
    net.add_safe("exit")
    for a, b, length in [
        ("start", "stair", 0),
        ("start", "hall", 0),
        ("stair", "exit", stair_length),
        ("hall", "exit", level_length),
    ]:
        net.connect(a, b, width=1, length=length, bidirectional=False)
    return net


def test_analytical_level_and_stair_costs():
    net = alternatives()
    distance, _ = net._distances(None, routing_policy=TIME)
    assert distance[1] == pytest.approx(30 / STAIR_SPEED)
    assert distance[2] == pytest.approx(35 / LEVEL_SPEED)
    assert distance[0] == pytest.approx(35 / LEVEL_SPEED)
    assert net.route_table()[0] == 0
    assert net.route_table(routing_policy=TIME)[0] == 1


def test_cost_uses_source_node_even_for_stair_entry():
    net = alternatives()
    entry = net.connect(
        "start", "stair", width=1, length=12, kind="stair", bidirectional=False
    )[0]
    assert _edge_cost(entry, net.node("start"), TIME) == pytest.approx(
        12 / LEVEL_SPEED
    )


@pytest.mark.parametrize("seconds", [0.0, 10.0])
def test_equal_time_alternatives_with_different_lengths(seconds):
    net = alternatives(seconds * STAIR_SPEED, seconds * LEVEL_SPEED)
    assert net.route_choices(routing_policy=TIME)[0] == (0, 1)
    costs, hops = net._distances(None, routing_policy=TIME)
    assert costs[0] == pytest.approx(seconds)
    for link in net.links:
        if link.index in net.route_choices(routing_policy=TIME)[link.source]:
            assert (costs[link.target], hops[link.target]) < (
                costs[link.source],
                hops[link.source],
            )


def test_zero_length_cycle_has_progress_under_time_policy():
    net = alternatives()
    net.connect("start", "hall", width=1, bidirectional=True)
    choices = net.route_choices(routing_policy=TIME)
    # hall must exit, never return to start, despite their equal costs.
    assert choices[2] == (3,)
    assert set(choices[0]) == {1, 4}


def test_equal_distance_is_not_equal_reference_time():
    net = alternatives(30, 30)
    assert net.route_choices()[0] == (0, 1)
    assert net.route_choices(routing_policy=TIME)[0] == (1,)


def test_simulation_shares_static_routes_and_preserves_scenario_policy(
    tmp_path,
):
    net = alternatives()
    pops = [
        Population("start", 1, speed=0.2),
        Population("start", 1, speed=2.0),
    ]
    sim = NetworkSimulation(net, pops, routing_policy=TIME)
    assert list(sim._routes) == [None]
    assert sim._routes[None][0] == 1
    result = sim.run(seed=1)
    assert result.link_flow[:, 0].sum() == 0
    assert result.link_flow[:, 1].sum() == 2
    assert result.evacuated == 2
    assert sim._routes[None][0] == 1
    assert netview.build(sim).trees[0].via[0] == 1
    path = tmp_path / "scenario.json"
    save_scenario(sim, path)
    loaded = load_scenario(path)
    assert loaded.data["simulation"]["routing_policy"] == TIME
    assert loaded.simulation.routing_policy == TIME
    np.testing.assert_array_equal(
        loaded.simulation.run(seed=1).exit_times, result.exit_times
    )


def test_default_distance_policy_preserves_results_and_export(tmp_path):
    net = alternatives()
    pops = [Population("start", 2)]
    default = NetworkSimulation(net, pops)
    explicit = NetworkSimulation(net, pops, routing_policy="shortest_distance")
    np.testing.assert_array_equal(
        default.run(seed=1).exit_times, explicit.run(seed=1).exit_times
    )
    path = tmp_path / "scenario.json"
    save_scenario(default, path)
    assert "routing_policy" not in load_scenario(path).data["simulation"]


@pytest.mark.parametrize("method", ["route_table", "route_choices"])
def test_unknown_routing_policy_is_rejected(method):
    with pytest.raises(ValueError, match="Unknown routing policy"):
        getattr(alternatives(), method)(routing_policy="fastest")


def test_overflowing_time_detour_preserves_finite_route():
    net = alternatives(1e308, 1)
    net.connect("start", "stair", width=1, length=1e308, bidirectional=False)
    # The overflowing candidate does not invalidate the finite hall route.
    assert net.route_table(routing_policy=TIME)[0] == 1


@pytest.mark.parametrize("method", ["route_table", "route_choices"])
def test_accumulated_reference_time_overflow_has_units(method):
    net = Network()
    net.add_room("A", area=10)
    net.add_room("B", area=10)
    net.add_safe("exit")
    net.connect("A", "B", width=1, length=1.7e308, bidirectional=False)
    net.connect("B", "exit", width=1, length=1.7e308, bidirectional=False)
    with pytest.raises(
        ValueError, match=r"link 'A->B'.*accumulated cost .* s .*link cost .* s"
    ):
        getattr(net, method)(routing_policy=TIME)


@pytest.mark.parametrize("delta, tied", [(0.5e-9, True), (2e-9, False)])
def test_time_tolerance_is_in_seconds(delta, tied):
    net = Network()
    net.add_room("A", area=10)
    net.add_safe("exit")
    net.connect("A", "exit", width=1, length=0.001 * LEVEL_SPEED)
    net.connect("A", "exit", width=1, length=(0.001 + delta) * LEVEL_SPEED)
    assert net.route_choices(routing_policy=TIME)[0] == (
        (0, 1) if tied else (0,)
    )
