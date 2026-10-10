# SPDX-License-Identifier: LGPL-3.0-or-later
import math
import warnings

import numpy as np
import pytest

from jupedsim_network import (
    Fixed,
    LogNormal,
    MonteCarloResult,
    Network,
    NetworkSimulation,
    Normal,
    Population,
    Triangular,
    Uniform,
    Weibull,
    hydraulic,
)


def single_room(area=100.0, width=1.0, kind="door", length=0.0, **kwargs):
    net = Network()
    net.add_room("room", area=area)
    net.add_safe("exit")
    net.connect("room", "exit", width=width, kind=kind, length=length, **kwargs)
    return net


def test_free_walking_speed_imo_test_1():
    # IMO MSC.1/Circ.1533 test 1: 40 m at 1.0 m/s takes 40 s.
    net = single_room(width=2.0, kind="opening", length=40.0)
    sim = NetworkSimulation(net, [Population("room", 1, speed=1.0)])
    assert sim.run(seed=1).evacuation_time == pytest.approx(40.0, abs=0.5)


def test_door_flow_imo_test_4():
    # 100 agents through a 1.0 m door at 1.33 p/s/m (We = 0.7 m). The first
    # agent passes at once, the last after 99 headways: 99 / 0.931 = 106.3 s.
    net = single_room(area=40.0, specific_flow=1.33)
    sim = NetworkSimulation(net, [Population("room", 100, speed=1.0)])
    expected = 99 / (1.33 * 0.7)
    assert sim.run(seed=1).evacuation_time == pytest.approx(expected, abs=1.0)


def test_opening_has_no_boundary_layer():
    # 50 agents through a 0.6 m opening at 1.3 p/s/m: 49 / 0.78 = 62.8 s.
    net = single_room(width=0.6, kind="opening")
    sim = NetworkSimulation(net, [Population("room", 50)])
    assert sim.run(seed=1).evacuation_time == pytest.approx(49 / 0.78, abs=0.5)


def test_stair_speed_imo_test_3():
    # k = 51.8 sqrt(280/180) m/min, S = k (1 - 0.266 * 0.54): 10 m in 10.9 s.
    net = Network()
    net.add_room("room", area=20.0)
    net.add_stair("flight", area=20.0, riser=0.18, tread=0.28)
    net.add_safe("exit")
    net.connect("room", "flight", width=2.0, kind="stair")
    net.connect("flight", "exit", width=2.0, kind="stair", length=10.0)
    pop = Population("room", 1, speed=2.0)
    sim = NetworkSimulation(net, [pop], dt=0.1)
    k = hydraulic.stair_speed_constant(0.18, 0.28)
    expected = 10.0 / (k * (1 - 0.266 * 0.54))
    assert sim.run(seed=1).evacuation_time == pytest.approx(expected, abs=0.25)


def test_congested_walking_speed():
    # 200 agents in 100 m² (2 /m²) walk 20 m at 84 (1 - 0.266 * 2) m/min.
    net = single_room(width=1000.0, kind="opening", length=20.0)
    sim = NetworkSimulation(net, [Population("room", 200, speed=1.2)])
    expected = 20.0 / (84.0 / 60.0 * (1 - 0.266 * 2.0))
    assert sim.run(seed=1).evacuation_time == pytest.approx(expected, abs=0.6)


def test_pre_movement_delays_start():
    net = single_room(width=2.0, kind="opening", length=10.0)
    pop = Population("room", 1, speed=1.0, pre_movement=30.0)
    result = NetworkSimulation(net, [pop]).run(seed=1)
    assert result.evacuation_time == pytest.approx(40.0, abs=0.5)
    assert result.pre_movement_times[0] == 30.0


def test_shortest_route_is_chosen():
    net = Network()
    net.add_room("room", area=50.0)
    net.add_safe("near")
    net.add_safe("far")
    net.connect("room", "near", width=1.0, length=5.0)
    net.connect("room", "far", width=1.0, length=50.0)
    result = NetworkSimulation(net, [Population("room", 10)]).run(seed=1)
    near = result.link_names.index("room->near")
    assert result.link_flow[:, near].sum() == 10


def test_target_overrides_nearest_exit():
    net = Network()
    net.add_room("room", area=50.0)
    net.add_safe("near")
    net.add_safe("far")
    net.connect("room", "near", width=1.0, length=5.0)
    net.connect("room", "far", width=1.0, length=50.0)
    pop = Population("room", 10, target="far")
    result = NetworkSimulation(net, [pop]).run(seed=1)
    far = result.link_names.index("room->far")
    assert result.link_flow[:, far].sum() == 10


def corridor_with_rooms(merge_weights=(1.0, 1.0)):
    net = Network()
    net.add_room("a", area=200.0)
    net.add_room("b", area=200.0)
    net.add_room("corridor", area=4.0)
    net.add_safe("exit")
    for name, weight in zip(("a", "b"), merge_weights):
        net.connect(name, "corridor", width=2.0, merge_weight=weight)
    net.connect("corridor", "exit", width=1.0, length=2.0)
    return net


def test_node_never_exceeds_max_density():
    net = corridor_with_rooms()
    pops = [Population("a", 300), Population("b", 300)]
    sim = NetworkSimulation(net, pops, t_max=200.0)
    result = sim.run(seed=3)
    corridor = result.node_names.index("corridor")
    assert result.node_occupancy[:, corridor].max() <= 2.75 * 4.0


def test_agents_are_conserved():
    net = corridor_with_rooms()
    pops = [Population("a", 120), Population("b", 80)]
    result = NetworkSimulation(net, pops).run(seed=5)
    total = result.node_occupancy.sum(axis=1)
    exited = np.concatenate([[0], np.cumsum(result.link_flow[1:, -1])])
    assert np.all(total + exited == 200)
    assert result.evacuated == 200


def test_merge_weights_split_flow():
    net = corridor_with_rooms(merge_weights=(1.0, 3.0))
    pops = [Population("a", 300), Population("b", 300)]
    result = NetworkSimulation(net, pops, t_max=150.0).run(seed=2)
    a = result.link_names.index("a->corridor")
    b = result.link_names.index("b->corridor")
    ratio = result.link_flow[:, b].sum() / result.link_flow[:, a].sum()
    assert ratio == pytest.approx(3.0, rel=0.15)


def fed_corridor(feeders):
    """Corridor C (40 m²) fed by one-way openings, out through a 1 m door."""
    net = Network()
    net.add_room("C", area=40.0)
    net.add_safe("exit")
    for name, area, width in feeders:
        net.add_room(name, area=area)
        net.connect(name, "C", width=width, kind="opening", bidirectional=False)
    net.connect("C", "exit", width=1.0, bidirectional=False)
    return net


def assert_supply_from_queued_links(result):
    # Only R -> C (2.6/s) has a queue; the door passes 0.91/s, so the
    # steady density is 2.75 - (2.75 - 1/(2a)) * 0.91 / 2.6 = 2.4454 m⁻²,
    # i.e. 97.82 agents in C. Counting every incoming link gives 105.94.
    corridor = result.node_names.index("C")
    occupancy = result.node_occupancy[:, corridor]
    window = (result.times >= 200.0) & (result.times <= 400.0)
    assert occupancy[window].mean() == pytest.approx(97.82, abs=1.0)
    assert occupancy.max() < 99


def test_supply_ignores_unused_reverse_link():
    net = fed_corridor([("R", 1000.0, 2.0)])
    net.add_room("D", area=40.0)
    net.add_safe("exit2")
    net.connect("C", "D", width=4.0, kind="opening", length=50.0)
    net.connect("D", "exit2", width=1.0, length=1.0, bidirectional=False)
    sim = NetworkSimulation(net, [Population("R", 600)], t_max=900.0)
    result = sim.run(seed=1)
    assert_supply_from_queued_links(result)
    # Filling is unchanged until C passes the peak-flow density.
    occupancy = result.node_occupancy[:, result.node_names.index("C")]
    assert result.times[np.argmax(occupancy >= 76)] == 45.0
    # Door-limited: (1 + ceil(599 / (0.91 * 0.5))) * 0.5 s.
    assert result.evacuated == 600
    assert result.evacuation_time == 659.0


def test_supply_ignores_idle_feeder():
    net = fed_corridor([("R", 1000.0, 2.0), ("R2", 100.0, 4.0)])
    pops = [Population("R", 600), Population("R2", 1)]
    result = NetworkSimulation(net, pops, t_max=900.0).run(seed=1)
    assert_supply_from_queued_links(result)
    # Door-limited: (1 + ceil(600 / (0.91 * 0.5))) * 0.5 s.
    assert result.evacuated == 601
    assert result.evacuation_time == 660.0


def room_swap(count, area_factor, side_door):
    """Rooms A and B (20 m²) swap occupants through a 1 m door."""
    net = Network()
    for name in ("A", "B"):
        net.add_room(name, area=20.0)
    net.add_safe("exitA")
    net.add_safe("exitB")
    net.connect("A", "B", width=1.0, length=2.0)
    if side_door:
        net.add_room("S", area=20.0)
        net.connect("A", "S", width=2.0, length=2.0)
    net.connect("A", "exitA", width=1.0, length=50.0, bidirectional=False)
    net.connect("B", "exitB", width=1.0, length=50.0, bidirectional=False)
    pops = [
        Population("A", count, area_factor=area_factor, target="exitB"),
        Population("B", count, area_factor=area_factor, target="exitA"),
    ]
    return NetworkSimulation(net, pops, t_max=900.0).run(seed=1)


def door_passages(result, link):
    column = result.link_flow[:, result.link_names.index(link)]
    assert column.max() == 1
    return list(result.times[column == 1])


@pytest.mark.parametrize(
    (
        "count",
        "area_factor",
        "side_door",
        "first_exit",
        "total",
        "first",
        "gap",
    ),
    [
        # phi * C * dt = 0.392 per step; the 2nd area saved after 6 steps.
        (20, 2.0, True, 82.5, 127.5, 6.0, 3.5),
        # phi * C * dt = 0.418 per step; 1.5 saved after 4 steps.
        (26, 1.5, False, 79.0, 122.0, 4.5, 2.5),
    ],
    ids=["side_door_af2", "no_side_door_af1_5"],
)
def test_supply_carry_admits_large_agent_swap(
    count, area_factor, side_door, first_exit, total, first, gap
):
    # A capped at max(C * dt, 1) stalls: alpha <= 1 + phi * C * dt < a.
    result = room_swap(count, area_factor, side_door)
    expected = [first + gap * k for k in range(count)]
    assert door_passages(result, "A->B") == expected
    assert door_passages(result, "B->A") == expected
    assert np.nanmin(result.exit_times) == first_exit
    assert result.evacuated == 2 * count
    assert result.evacuation_time == total


def test_same_seed_gives_same_result():
    net = corridor_with_rooms()
    pops = [Population("a", 50, pre_movement=Uniform(0, 60))]
    sim = NetworkSimulation(net, pops)
    assert sim.run(seed=7).evacuation_time == sim.run(seed=7).evacuation_time


def test_monte_carlo_samples_vary():
    net = single_room()
    pop = Population("room", 50, pre_movement=Normal(60, 20))
    mc = NetworkSimulation(net, [pop]).run_many(20, seed=1)
    assert mc.evacuation_times.shape == (20,)
    assert np.isfinite(mc.evacuation_times).all()
    assert mc.evacuation_times.std() > 0
    assert mc.quantile(0.5) == pytest.approx(np.median(mc.complete))


def censored_fixture(**kwargs):
    times = np.array([10, 20, 30, 40, 50, 60, 70, 80, np.nan, np.nan])
    return MonteCarloResult(times, np.ones(10, dtype=int), **kwargs)


def test_quantile_ranks_unfinished_runs_last():
    mc = censored_fixture()
    with pytest.warns(RuntimeWarning, match="2 of 10"):
        q = mc.quantile([0.5, 0.75, 7 / 9, 0.9])
    np.testing.assert_array_equal(q, [55.0, 77.5, 80.0, np.inf])


@pytest.mark.parametrize(
    "q, expected",
    [
        (0.0, 10.0),
        (0.5, 55.0),
        (0.7, 73.0),
        (0.75, 77.5),
        (7 / 9, 80.0),
        (0.78, np.inf),
        (0.9, np.inf),
        (0.95, np.inf),
        (1.0, np.inf),
    ],
)
def test_quantile_values_with_unfinished_runs(q, expected):
    mc = censored_fixture()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        value = mc.quantile(q)
    assert np.ndim(value) == 0
    assert value == expected


def test_quantile_warning_names_counts_and_t_max():
    mc = censored_fixture(t_max=100.0)
    assert mc.incomplete == 2
    np.testing.assert_array_equal(mc.complete, np.arange(10, 90, 10))
    with pytest.warns(RuntimeWarning, match="2 of 10") as record:
        mc.quantile(0.1)
    assert "100" in str(record[0].message)
    with pytest.warns(RuntimeWarning) as record:
        censored_fixture().quantile(0.1)
    assert "t_max" not in str(record[0].message)


def test_quantile_warning_states_exact_boundary():
    # 7/9 = 0.7778 prints as 0.778; a rounded boundary hides that
    # q = 0.7779 is already inf.
    mc = censored_fixture()
    with pytest.warns(RuntimeWarning, match="above q = 7/9 ") as record:
        assert mc.quantile(0.7779) == np.inf
    assert "0.778" in str(record[0].message)


def test_quantile_unchanged_when_all_runs_finish():
    times = np.array([12.5, 3.0, 7.5, 40.0, 18.0, 25.5, 9.0])
    mc = MonteCarloResult(times, np.ones(7, dtype=int))
    qs = np.linspace(0, 1, 101)
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert mc.quantile(0.37) == np.quantile(times, 0.37)
        np.testing.assert_array_equal(mc.quantile(qs), np.quantile(times, qs))
    assert mc.incomplete == 0


def test_quantile_all_runs_unfinished_is_inf():
    mc = MonteCarloResult(np.full(4, np.nan), np.ones(4, dtype=int))
    with pytest.warns(RuntimeWarning, match="4 of 4"):
        q = mc.quantile([0, 0.5, 1])
    np.testing.assert_array_equal(q, [np.inf, np.inf, np.inf])


def test_quantile_single_unfinished_run_is_inf():
    mc = MonteCarloResult(np.array([np.nan]), np.ones(1, dtype=int))
    with pytest.warns(RuntimeWarning, match="1 of 1"):
        assert mc.quantile(0.5) == np.inf


def test_run_many_ranks_unfinished_runs_last():
    net = single_room()
    pop = Population("room", 5, pre_movement=Uniform(0, 40))
    sim = NetworkSimulation(net, [pop], t_max=35.0)
    mc = sim.run_many(20, seed=3)
    assert mc.t_max == sim.t_max
    assert 0 < mc.incomplete < 20
    with pytest.warns(RuntimeWarning, match=f"{mc.incomplete} of 20"):
        assert mc.quantile(1.0) == np.inf


def test_incomplete_run_reports_nan():
    net = single_room(length=1000.0)
    pop = Population("room", 1, speed=1.0)
    result = NetworkSimulation(net, [pop], t_max=10.0).run(seed=1)
    assert math.isnan(result.evacuation_time)
    assert result.evacuated == 0


def test_overfull_start_node_is_rejected():
    net = single_room(area=10.0)
    sim = NetworkSimulation(net, [Population("room", 40)])
    with pytest.raises(ValueError, match="max_density"):
        sim.run(seed=1)


def test_agent_larger_than_node_on_route_is_rejected():
    # max_density * area of C = 2.75 * 0.7 = 1.925 < 2: never fits.
    net = Network()
    net.add_room("R", area=100.0)
    net.add_room("C", area=0.7)
    net.add_safe("exit")
    net.connect("R", "C", width=1.0)
    net.connect("C", "exit", width=1.0)
    with pytest.raises(ValueError, match=r"area_factor 2\.0 .* 1\.925 .*'C'"):
        NetworkSimulation(net, [Population("R", 3, area_factor=2.0)])
    NetworkSimulation(net, [Population("R", 3, area_factor=1.9)])


def test_population_without_route_is_rejected():
    net = Network()
    net.add_room("island", area=10.0)
    net.add_room("room", area=10.0)
    net.add_safe("exit")
    net.connect("room", "exit", width=1.0)
    with pytest.raises(ValueError, match="No route"):
        NetworkSimulation(net, [Population("island", 1)])


def test_stair_connection_needs_stair_node():
    net = Network()
    net.add_room("room", area=10.0)
    net.add_safe("exit")
    with pytest.raises(ValueError, match="stair node"):
        net.connect("room", "exit", width=1.0, kind="stair")


def test_stair_specific_flow_follows_geometry():
    k = hydraulic.stair_speed_constant(0.178, 0.279)
    # SFPE: riser/tread 7/11 in gives k = 1.08 m/s and Fsm = 1.01 p/s/m.
    assert k == pytest.approx(1.08, abs=0.01)
    assert hydraulic.max_specific_flow(k) == pytest.approx(1.01, abs=0.01)


@pytest.mark.parametrize("value", [0, 0.0, -1.0, math.nan])
def test_non_positive_specific_flow_is_rejected(value):
    net = Network()
    net.add_room("room", area=10.0)
    net.add_safe("exit")
    with pytest.raises(ValueError, match="specific_flow"):
        net.connect("room", "exit", width=1.0, specific_flow=value)
    assert len(net.links) == 0


def test_default_specific_flow_is_used_when_none():
    net = single_room(specific_flow=None)
    # 1.3 p/s/m over 1 m - 2 * 0.15 m.
    assert net.links[0].capacity == pytest.approx(0.91, abs=1e-12)


def one_door_two_groups(first_area_factor):
    net = single_room()
    factors = [first_area_factor, 3 - first_area_factor]
    pops = [Population("room", 20, area_factor=f) for f in factors]
    return NetworkSimulation(net, pops).run(seed=1)


@pytest.mark.parametrize("first, last_exit", [(1, 21.0), (2, 43.0)])
def test_simultaneous_arrivals_are_served_in_population_order(first, last_exit):
    # One door, C dt = 0.455. Agent k passes in the first step m with
    # 1 + 0.455 m >= k: k = 20 at 21.0 s, k = 40 at 43.0 s.
    result = one_door_two_groups(first)
    group = slice(0, 20) if first == 1 else slice(20, 40)
    assert result.exit_times[group].max() == last_exit
    assert result.evacuation_time == 43.0


# Route ties (issue #7). A 1 m door passes C dt = 0.91 x 0.5 = 0.455 agents
# per step; the n-th agent of a full queue leaves at the end of step
# ceil((n - 1)/0.455): n = 10 -> 20, n = 11 -> 22, n = 20 -> 42.


def two_doors(length=0.0):
    net = Network()
    net.add_room("room", area=100.0)
    net.add_safe("s1")
    net.add_safe("s2")
    net.connect("room", "s1", width=1.0, length=length)
    net.connect("room", "s2", width=1.0, length=length)
    return net


def flows(result):
    return dict(zip(result.link_names, result.link_flow.sum(axis=0).tolist()))


@pytest.mark.parametrize(
    "n, split, last_exit", [(20, (10, 10), 10.0), (21, (11, 10), 11.0)]
)
def test_tie_at_start_node_is_split(n, split, last_exit):
    # Main sends all agents through s1: 21.0 s for 20, 22.0 s for 21.
    result = NetworkSimulation(two_doors(), [Population("room", n)]).run(1)
    assert (flows(result)["room->s1"], flows(result)["room->s2"]) == split
    assert result.evacuation_time == last_exit


def test_tie_with_walking_is_split():
    # 5 m at 1.199 m/s are reached in the step starting at 4.0 s; then
    # 10 per door: 4.0 + 20 x 0.5 = 14.0 s (main: 4.0 + 42 x 0.5 = 25.0 s).
    net = two_doors(length=5.0)
    result = NetworkSimulation(net, [Population("room", 20)]).run(1)
    assert (flows(result)["room->s1"], flows(result)["room->s2"]) == (10, 10)
    assert result.evacuation_time == 14.0


def test_tie_at_intermediate_node_is_split():
    # The 40 m opening passes all 20 into the hall at 0.5 s; its 5 m are
    # reached in the step starting at 4.5 s: 4.5 + 20 x 0.5 = 14.5 s
    # (main: 4.5 + 42 x 0.5 = 25.5 s).
    net = Network()
    net.add_room("room", area=100.0)
    net.add_room("hall", area=100.0)
    net.add_safe("s1")
    net.add_safe("s2")
    net.connect("room", "hall", width=40.0, kind="opening", bidirectional=False)
    for exit_ in ("s1", "s2"):
        net.connect("hall", exit_, width=1.0, length=5.0, bidirectional=False)
    result = NetworkSimulation(net, [Population("room", 20)]).run(1)
    assert (flows(result)["hall->s1"], flows(result)["hall->s2"]) == (10, 10)
    assert result.evacuation_time == 14.5


def test_tie_is_taken_in_order_of_arrival():
    # Both agents enter the hall in the first step: a (listed first) after
    # 0.25 / 0.6 = 0.42 s, b after 0.1 / 1.2 = 0.08 s. b arrived first and
    # takes hall->s1, so s1 passes the fast agent (5 m in 4.2 s) and s2 the
    # slow one (5 m in 8.3 s).
    net = Network()
    for room in ("a", "b", "hall"):
        net.add_room(room, area=100.0)
    net.add_safe("s1")
    net.add_safe("s2")
    net.connect("a", "hall", width=2.0, length=0.25, bidirectional=False)
    net.connect("b", "hall", width=2.0, length=0.1, bidirectional=False)
    for exit_ in ("s1", "s2"):
        net.connect("hall", exit_, width=1.0, length=5.0, bidirectional=False)
    pops = [Population("a", 1, speed=0.6), Population("b", 1, speed=1.2)]
    result = NetworkSimulation(net, pops).run(1)
    passed = dict(zip(result.link_names, result.link_flow.T))
    first_s1 = np.flatnonzero(passed["hall->s1"])[0]
    first_s2 = np.flatnonzero(passed["hall->s2"])[0]
    assert first_s1 < first_s2


def test_odd_tie_split_is_reproducible():
    # 21 agents end the alternation on s1; a tie counter kept across runs
    # would start the second run on s2.
    pop = Population("room", 21, pre_movement=Uniform(0, 30))
    sim = NetworkSimulation(two_doors(), [pop])
    first, again = sim.run(3), sim.run(3)
    fresh = NetworkSimulation(two_doors(), [pop]).run(3)
    for other in (again, fresh):
        np.testing.assert_array_equal(first.link_flow, other.link_flow)
        np.testing.assert_array_equal(first.exit_times, other.exit_times)
    assert (flows(first)["room->s1"], flows(first)["room->s2"]) == (11, 10)


def two_stair_building(stairs=("A", "B")):
    """Ten floors of 400 m², a 0.9 m door 25 m away to each stair."""
    net = Network()
    for s in stairs:
        net.add_safe(f"exit{s}")
    for f in range(1, 11):
        net.add_room(f"F{f}", area=400.0)
    cells = [(f, s) for f in range(1, 11) for s in stairs]
    for f, s in cells:
        net.add_stair(f"{s}{f}", riser=0.18, tread=0.28, area=1.2 * 9.0)
    for f, s in cells:
        below = f"{s}{f - 1}" if f > 1 else f"exit{s}"
        net.connect(
            f"F{f}", f"{s}{f}", width=0.9, length=25.0, bidirectional=False
        )
        net.connect(
            f"{s}{f}",
            below,
            width=1.2,
            kind="stair",
            length=9.0,
            bidirectional=False,
        )
    return net


@pytest.mark.parametrize("pre, evacuation", [(60.0, 422.5), (0.0, 362.5)])
def test_split_ties_match_split_by_hand(pre, evacuation):
    # Main sends all 600 agents down stair A: 752.0 s and 692.0 s.
    net = two_stair_building()
    plain = [Population(f"F{f}", 60, pre_movement=pre) for f in range(1, 11)]
    by_hand = [
        Population(f"F{f}", 30, pre_movement=pre, target=f"exit{s}")
        for f in range(1, 11)
        for s in "AB"
    ]
    split = NetworkSimulation(net, plain).run(1)
    hand = NetworkSimulation(net, by_hand).run(1)
    np.testing.assert_array_equal(
        np.sort(split.exit_times), np.sort(hand.exit_times)
    )
    np.testing.assert_array_equal(split.node_occupancy, hand.node_occupancy)
    np.testing.assert_array_equal(split.link_flow, hand.link_flow)
    assert split.evacuation_time == evacuation
    flow = flows(split)
    for f in range(1, 11):
        assert flow[f"F{f}->A{f}"] == flow[f"F{f}->B{f}"] == 30
    assert flow["A1->exitA"] == flow["B1->exitB"] == 300


def test_unsplit_ties_keep_first_route_and_warn():
    with pytest.warns(UserWarning, match=r"tied at \['room'\]"):
        sim = NetworkSimulation(
            two_doors(), [Population("room", 20)], split_ties=False
        )
    result = sim.run(1)
    assert (flows(result)["room->s1"], flows(result)["room->s2"]) == (20, 0)
    assert result.evacuation_time == 21.0


def test_unsplit_routes_without_ties_are_silent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        NetworkSimulation(
            single_room(), [Population("room", 20)], split_ties=False
        )


def test_tied_zero_length_links_do_not_cycle():
    # a <-> b has zero length and both are 1 m from safety: each agent
    # leaves through its own 1 m door.
    net = Network()
    net.add_room("a", area=50.0)
    net.add_room("b", area=50.0)
    net.add_safe("s")
    net.connect("a", "b", width=1.0)
    net.connect("a", "s", width=1.0, length=1.0)
    net.connect("b", "s", width=1.0, length=1.0)
    pops = [Population("a", 10), Population("b", 10)]
    result = NetworkSimulation(net, pops).run(1)
    flow = flows(result)
    assert flow["a->b"] == flow["b->a"] == 0
    assert flow["a->s"] == flow["b->s"] == 10
    assert result.evacuation_time == 10.5


def test_zero_length_detour_is_not_a_tie():
    net = Network()
    net.add_room("c", area=50.0)
    net.add_room("a", area=50.0)
    net.add_safe("s")
    net.connect("c", "a", width=1.0, bidirectional=False)
    net.connect("a", "s", width=1.0, length=1.0)
    (direct,) = net.connect("c", "s", width=1.0, length=1.0)
    assert net._route_choices()[net.node("c").index] == (direct.index,)


@pytest.mark.parametrize("delta, tied", [(0.0, True), (1e-6, False)])
def test_ties_within_rounding_only(delta, tied):
    # 0.1 + 0.2 differs from 0.3 in floating point but is a tie.
    net = Network()
    net.add_room("room", area=50.0)
    net.add_room("hall", area=50.0)
    net.add_safe("s")
    net.connect("room", "hall", width=1.0, length=0.1, bidirectional=False)
    net.connect("hall", "s", width=1.0, length=0.2)
    net.connect("room", "s", width=1.0, length=0.3 + delta)
    choices = net._route_choices()[net.node("room").index]
    assert (len(choices) == 2) is tied


def test_split_ties_draw_no_random_numbers():
    pop = Population("room", 40, pre_movement=Uniform(0, 30))
    sim = NetworkSimulation(two_doors(), [pop])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        unsplit = NetworkSimulation(two_doors(), [pop], split_ties=False)
    first, again = sim.run(3), sim.run(3)
    np.testing.assert_array_equal(first.exit_times, again.exit_times)
    np.testing.assert_array_equal(
        first.pre_movement_times, unsplit.run(3).pre_movement_times
    )


@pytest.mark.parametrize(
    "dist, mean",
    [
        (Uniform(0, 100), 50.0),
        (Normal(100, 10), 100.0),
        (LogNormal(100, 30), 100.0),
        (Triangular(0, 50, 100), 50.0),
        (Weibull(233, 3), 233 * math.gamma(1 + 1 / 3)),
        (Fixed(5.0), 5.0),
    ],
)
def test_distribution_means(dist, mean):
    values = dist.sample(np.random.default_rng(1), 20000)
    assert values.mean() == pytest.approx(mean, rel=0.02)
    assert values.min() >= 0.0


def test_distribution_truncation():
    dist = Normal(0, 10, lower=-5.0, upper=5.0)
    values = dist.sample(np.random.default_rng(1), 1000)
    assert values.min() >= -5.0 and values.max() <= 5.0


def assert_link_capacity(result, net, dt):
    """No link passes more than 1 + C w dt agents in any w steps."""
    flow = result.link_flow[1:].astype(float)
    cum = np.vstack([np.zeros(flow.shape[1]), np.cumsum(flow, axis=0)])
    capacity = np.array([lk.capacity for lk in net.links])
    for w in range(1, len(flow) + 1):
        passed = (cum[w:] - cum[:-w]).max(axis=0)
        assert np.all(passed <= 1.0 + capacity * w * dt + 1e-9), w


def released_one_by_one(gap, count, area=40.0):
    net = single_room(area=area, specific_flow=1.33)
    pops = [
        Population("room", 1, speed=1.0, pre_movement=Fixed(gap * i))
        for i in range(count)
    ]
    return net, NetworkSimulation(net, pops).run(seed=1)


def test_one_arrival_per_step_keeps_link_capacity():
    # 40 agents released one per step through a 0.931/s door: the last
    # cannot leave before 39/C after the first (#18).
    net, result = released_one_by_one(0.5, 40)
    assert result.evacuation_time >= 39 / (1.33 * 0.7)
    assert_link_capacity(result, net, 0.5)


def test_emptied_queue_keeps_stair_capacity():
    # Getting started with a 1.2 m door: the door feeds the stair faster
    # than it drains, its queue empties between arrivals (#18).
    net = Network()
    net.add_room("office", area=200.0)
    net.add_stair("flight", area=10.8, riser=0.18, tread=0.28)
    net.add_safe("street")
    net.connect("office", "flight", width=1.2, length=25.0, bidirectional=False)
    net.connect(
        "flight",
        "street",
        width=1.2,
        kind="stair",
        length=9.0,
        bidirectional=False,
    )
    result = NetworkSimulation(net, [Population("office", 120, speed=1.2)]).run(
        seed=1
    )
    assert_link_capacity(result, net, 0.5)
    stair = net.links[1].capacity
    assert (
        result.evacuation_time >= np.min(result.exit_times) + 119 / stair - 0.5
    )


def test_blocked_wide_link_banks_at_most_one_agent():
    # hall->lobby passes 2.03 agents per step but is held back by the
    # small lobby; unused capacity must not be banked beyond one agent.
    net = Network()
    net.add_room("hall", area=200.0)
    net.add_room("lobby", area=3.0)
    net.add_safe("exit")
    net.connect(
        "hall",
        "lobby",
        width=3.0,
        kind="opening",
        length=1.0,
        bidirectional=False,
    )
    net.connect(
        "lobby",
        "exit",
        width=2.8,
        kind="opening",
        length=0.5,
        bidirectional=False,
    )
    pops = [
        Population("hall", 1, speed=1.2, pre_movement=Fixed(0.1 * i))
        for i in range(80)
    ]
    result = NetworkSimulation(net, pops, dt=0.5).run(seed=1)
    assert_link_capacity(result, net, 0.5)
    assert result.evacuated == 80


def test_link_regains_capacity_at_rate_c():
    # 1 / C = 1.07 s: the second agent, 0.5 s behind, waits for the credit.
    _, result = released_one_by_one(0.5, 2)
    np.testing.assert_allclose(np.sort(result.exit_times), [0.5, 1.5])


def test_link_idle_for_one_headway_passes_at_once():
    _, result = released_one_by_one(1.5, 2)
    np.testing.assert_allclose(np.sort(result.exit_times), [0.5, 2.0])


def test_fresh_link_passes_first_agent_at_once():
    net = single_room()
    result = NetworkSimulation(net, [Population("room", 1)]).run(seed=1)
    assert result.evacuation_time == pytest.approx(0.5)


def test_full_queue_keeps_n_minus_one_headways():
    # IMO 4: 100 agents at once, 99 / 0.931 = 106.3 s, one step of slack.
    net = single_room(area=40.0, specific_flow=1.33)
    result = NetworkSimulation(net, [Population("room", 100, speed=1.0)]).run(
        seed=1
    )
    headways = 99 / (1.33 * 0.7)
    assert result.evacuation_time == pytest.approx(106.5)
    assert headways < result.evacuation_time <= headways + 0.5
    assert_link_capacity(result, net, 0.5)


def test_dispersed_arrivals_converge_with_dt():
    # 100 agents with pre-movement U(0, 50) through a 0.9 m door (#18).
    net = single_room(area=400.0, width=0.9, length=5.0)
    pop = Population("room", 100, speed=1.0, pre_movement=Uniform(0, 50))
    times = []
    for dt in (0.5, 0.1, 0.05):
        result = NetworkSimulation(net, [pop], dt=dt).run(seed=3)
        assert_link_capacity(result, net, dt)
        times.append(result.evacuation_time)
    assert max(times) - min(times) <= 1.0


@pytest.mark.parametrize("riser, tread", [(0.20, 0.28), (0.18, 0.24)])
def test_stair_outside_sfpe_range_warns(riser, tread):
    net = Network()
    with pytest.warns(UserWarning, match="SFPE range") as record:
        net.add_stair("flight", area=10.0, riser=riser, tread=tread)
    assert record[0].filename == __file__
    assert net.node("flight").speed_constant == pytest.approx(
        hydraulic.stair_speed_constant(riser, tread)
    )


@pytest.mark.parametrize(
    "riser, tread", [(0.1651, 0.254), (0.1905, 0.3302), (0.18, 0.28)]
)
def test_stair_inside_sfpe_range_is_silent(riser, tread):
    net = Network()
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        net.add_stair("flight", area=10.0, riser=riser, tread=tread)


def network_with_island():
    net = single_room(area=10.0)
    net.add_room("island", area=10.0)
    return net


@pytest.mark.parametrize("target", [None, "exit"])
def test_second_population_without_route_is_rejected(target):
    populations = [
        Population("room", 1, target=target),
        Population("island", 1, target=target),
    ]
    with pytest.raises(ValueError, match="No route from 'island'"):
        NetworkSimulation(network_with_island(), populations)


@pytest.mark.parametrize("target", [None, "exit"])
def test_second_population_in_safe_node_is_rejected(target):
    populations = [
        Population("room", 1, target=target),
        Population("exit", 1, target=target),
    ]
    with pytest.raises(ValueError, match="starts in safe node 'exit'"):
        NetworkSimulation(single_room(), populations)


@pytest.mark.parametrize("target", [None, "exit"])
def test_second_population_in_unknown_node_is_rejected(target):
    populations = [
        Population("room", 1, target=target),
        Population("nowhere", 1, target=target),
    ]
    with pytest.raises(ValueError, match="Unknown node .nowhere."):
        NetworkSimulation(single_room(), populations)
