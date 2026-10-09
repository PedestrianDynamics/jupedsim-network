# SPDX-License-Identifier: LGPL-3.0-or-later
import math

import numpy as np
import pytest

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
