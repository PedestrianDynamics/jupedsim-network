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


def two_doors_two_groups(first_area_factor):
    net = Network()
    net.add_room("room", area=100.0)
    net.add_safe("s1")
    net.add_safe("s2")
    net.connect("room", "s1", width=1.0)
    net.connect("room", "s2", width=1.0)
    factors = [first_area_factor, 3 - first_area_factor]
    pops = [Population("room", 20, area_factor=f) for f in factors]
    return NetworkSimulation(net, pops).run(seed=1)


@pytest.mark.parametrize("first, last_exit", [(1, 21.0), (2, 43.0)])
def test_simultaneous_arrivals_are_served_in_population_order(first, last_exit):
    # Route tie: only one door is used, C dt = 0.455. Agent k passes in the
    # first step m with 1 + 0.455 m >= k: k = 20 at 21.0 s, k = 40 at 43.0 s.
    result = two_doors_two_groups(first)
    group = slice(0, 20) if first == 1 else slice(20, 40)
    assert result.exit_times[group].max() == last_exit
    assert result.evacuation_time == 43.0


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
