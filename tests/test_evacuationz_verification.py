# SPDX-License-Identifier: LGPL-3.0-or-later
"""Cases of the EvacuatioNZ verification report v2.11 (Spearpoint, 2016).

Every expected value is a hand calculation in this model's conventions:
the first agent passes a link at once and the last after (N-1)/C, agents
leave at t + dt, and every link costs at least one step. Values read from
figures of the report are never asserted. Sections refer to the report;
page numbers are the printed ones (PDF page minus one).

EvacuatioNZ inputs map as follows: an 'enz_door' is a door with b = 0.15 m
and Fs = 1.33, an untyped connection an opening with b = 0 and Fs = 1.33,
and 'enz_stairs' a stair node whose Fs = k/(4a) follows the steps.
"""

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
)

DT = 0.5
FS = 1.33
FT = 0.3048
IN = 0.0254
A = 0.266  # m², slope of S = k (1 - a D)
K_LEVEL = 84 / 60  # m/s


def free_speed(k):
    return k * (1 - A * 0.54)


def stair_k(riser, tread):
    return 51.8 * math.sqrt(tread / riser) / 60


def stair_fs(k):
    return k / (4 * A)


def assert_invariants(result, net, n, max_density=2.75):
    """No agent lost, no node above max_density, exits on the time grid."""
    safe = [i for i, node in enumerate(net.nodes) if node.kind == "safe"]
    to_safe = [lk.index for lk in net.links if lk.target in safe]
    exited = np.cumsum(result.link_flow[:, to_safe].sum(axis=1))
    assert np.all(result.node_occupancy.sum(axis=1) + exited == n)
    assert result.evacuated == n
    for node in net.nodes:
        if node.kind == "safe":
            continue
        limit = math.floor(max_density * node.area + 1e-9)
        assert result.node_occupancy[:, node.index].max() <= limit
    steps = result.exit_times / DT
    np.testing.assert_allclose(steps, np.round(steps), atol=1e-9)


# §2.1.1-2.1.2, pp. 6-7: one agent walks 40 m at 1.0 m/s along a link
# (§2.1.1) or from a start distance (§2.1.2).


@pytest.mark.parametrize("start, link", [(40.0, 0.0), (0.0, 40.0)])
def test_travel_speed_from_start_distance(start, link):
    net = Network()
    net.add_room("corridor", length=40.0, width=2.0)
    net.add_safe("exit")
    net.connect(
        "corridor",
        "exit",
        width=2.0,
        kind="opening",
        length=link,
        specific_flow=FS,
    )
    pop = Population("corridor", 1, speed=1.0, start_distance=start)
    result = NetworkSimulation(net, [pop], dt=DT).run(seed=1)
    assert result.evacuation_time == pytest.approx(40.0 / 1.0, abs=DT)
    assert_invariants(result, net, 1)


# §2.2, pp. 8-12: door and opening flow of the IMO 4 room (8 m x 5 m).


@pytest.mark.parametrize("n", [1, 10, 100])
@pytest.mark.parametrize(
    "width, kind, layer",
    [
        (1.0, "door", 0.15),
        (2.0, "door", 0.15),
        (3.0, "door", 0.15),
        (1.0, "opening", 0.0),
    ],
)
def test_door_flow_widths(width, kind, layer, n):
    net = Network()
    net.add_room("room", length=8.0, width=5.0)
    net.add_safe("exit")
    net.connect(
        "room", "exit", width=width, kind=kind, length=0.1, specific_flow=FS
    )
    sim = NetworkSimulation(net, [Population("room", n, speed=1.0)], dt=DT)
    result = sim.run(seed=1)
    capacity = FS * (width - 2 * layer)
    hand = (n - 1) / capacity
    assert hand < result.evacuation_time <= hand + DT
    assert_invariants(result, net, n)


# §2.3, pp. 12-13: a crowd from a long room descends a stair of L x w.

STAIR_K = stair_k(0.18, 0.28)


def stair_flow(n, length, width):
    net = Network()
    net.add_room("room", length=200.0, width=5.0)
    net.add_stair("stair", length=length, width=width, riser=0.18, tread=0.28)
    net.add_safe("exit")
    net.connect(
        "room",
        "stair",
        width=5.0,
        kind="opening",
        length=0.01,
        specific_flow=FS,
    )
    net.connect("stair", "exit", width=width, kind="stair", length=length)
    sim = NetworkSimulation(net, [Population("room", n, speed=1.2)], dt=DT)
    return net, sim.run(seed=1)


def stair_hand(n, length, width):
    capacity = stair_fs(STAIR_K) * (width - 0.3)
    return length / free_speed(STAIR_K) + (n - 1) / capacity


# Uncongested: N <= 0.54 L w, so everyone walks at the free stair speed.
@pytest.mark.parametrize(
    "length, width, n",
    [
        (10, 1, 1),
        (200, 1, 1),
        (200, 1, 10),
        (200, 1, 100),
        (200, 5, 1),
        (200, 5, 10),
        (200, 5, 100),
    ],
)
def test_stair_flow_uncongested(length, width, n):
    net, result = stair_flow(n, length, width)
    hand = stair_hand(n, length, width)
    assert hand <= result.evacuation_time <= hand + 2 * DT
    assert_invariants(result, net, n)


# Congested: the stair fills and everyone on it walks at k (1 - a D), so the
# hand value with the free stair speed is only a lower bound.
@pytest.mark.parametrize(
    "length, width, n",
    [(10, 1, 10), (10, 1, 100), (10, 1, 1000), (200, 1, 1000), (200, 5, 1000)],
)
def test_stair_flow_congested_is_bounded(length, width, n):
    net, result = stair_flow(n, length, width)
    assert result.evacuation_time >= stair_hand(n, length, width)
    assert_invariants(result, net, n)


@pytest.mark.parametrize("width", [1, 5])
def test_stair_throughput_is_stair_capacity(width):
    n = 1000
    net, result = stair_flow(n, 200, width)
    assert_invariants(result, net, n)
    exits = result.exit_times
    flow = (n - 1) / (exits.max() - exits.min())
    fs = stair_fs(STAIR_K)
    assert flow / (width - 0.3) == pytest.approx(fs, rel=0.01)


# §2.4, pp. 13-15: Fire Engineering Design Guide, a room over one stair.
# The stair (1.012 x 0.9 = 0.911/s) limits stairs->exit, not the door
# (1.33 x 0.7 = 0.931/s).


def fedg():
    net = Network()
    net.add_room("room", length=10.0, width=10.0)
    net.add_stair("stairs", length=10.0, width=1.2, riser=0.18, tread=0.28)
    net.add_safe("exit")
    net.connect("room", "stairs", width=1.0, length=0.1, specific_flow=FS)
    net.connect("stairs", "exit", width=1.2, kind="stair", length=10.0)
    pop = Population("room", 90, speed=1.2, start_distance=20.0)
    return net, NetworkSimulation(net, [pop], dt=DT).run(seed=1)


def steps(distance, speed):
    return math.ceil(distance / (speed * DT)) * DT


def test_fedg_first_exit():
    net, result = fedg()
    # 90 agents in 100 m² walk 20.1 m at 1.4 (1 - a 0.9), pass the door
    # in the step they arrive, then walk 10 m of stair. At the free stair
    # speed this takes 30.0 s; agents following at 0.931/s raise the stair
    # density above 0.54/m² and slow the first one down.
    room_speed = K_LEVEL * (1 - A * 0.9)
    stair_speed = free_speed(STAIR_K)
    hand = steps(20.1, room_speed) + steps(10.0, stair_speed)
    assert hand <= np.min(result.exit_times) <= hand + 2 * DT
    assert_invariants(result, net, 90)


def test_fedg_last_exit_bound():
    net, result = fedg()
    # After the first exit the stair link passes the other 89 at most at
    # its capacity 1.012 x 0.9 = 0.911/s.
    capacity = stair_fs(STAIR_K) * (1.2 - 0.3)
    bound = np.min(result.exit_times) + 89 / capacity
    assert bound <= result.evacuation_time <= bound + 4 * DT
    assert_invariants(result, net, 90)


# §2.5, pp. 15-17: SFPE nine-storey building. The report gives the top
# floor only. The occupants (300 per floor on floors 2-9) and the 36 in
# door at each stair exit come from the SFPE example it reproduces (SFPE
# Handbook 6th ed., p. 2181). Stand-in for an even use of the two tied
# stairs: one office zone per floor goes to each stair. Landings are
# nodes, so the 4.8 m of landing travel is walked at level speed and
# corridor->landing is 4.8 m shorter below the top floor.

SFPE_STAIR = 12 * FT * math.sqrt(1 + (0.28 / 0.18) ** 2)
LANDING = 4.8
STARTUP_LAG = 1.5  # s; door start-up lag, measured 0.6-1.1 s for dt 0.5-0.1


def test_sfpe_stair_length_from_height():
    height = 12 * FT
    length = height * math.sqrt(1 + (0.28 / 0.18) ** 2)
    assert length == pytest.approx(6.76, abs=0.01)


def sfpe_floor(net, f):
    for r in (1, 2):
        net.add_room(f"Room_{f}.{r}", length=300 * FT, width=10.8)
        net.connect(
            f"Room_{f}.{r}",
            f"Corridor_{f}",
            width=5.79,
            length=14.12,
            bidirectional=False,
            specific_flow=FS,
        )
    for s in "RL":
        net.add_stair(
            f"Stairs_{f}{s}",
            length=SFPE_STAIR,
            width=1.12,
            riser=0.18,
            tread=0.28,
        )
        top = f == 9
        net.connect(
            f"Corridor_{f}",
            f"Landing_{f}{s}",
            width=0.91,
            length=45.5 if top else 45.5 - LANDING,
            bidirectional=False,
            specific_flow=FS,
        )
        net.connect(
            f"Landing_{f}{s}",
            f"Stairs_{f}{s}",
            width=1.12,
            kind="stair",
            length=0.0 if top else LANDING,
            bidirectional=False,
        )
        net.connect(
            f"Stairs_{f}{s}",
            f"Landing_{f - 1}{s}",
            width=1.2,
            kind="opening",
            length=SFPE_STAIR,
            bidirectional=False,
            specific_flow=FS,
        )


def sfpe_building():
    net = Network()
    for s in "RL":
        net.add_safe(f"Exit{s}")
        for f in range(1, 10):
            net.add_room(f"Landing_{f}{s}", length=LANDING, width=1.2)
        net.connect(
            f"Landing_1{s}",
            f"Exit{s}",
            width=0.91,
            length=LANDING,
            bidirectional=False,
            specific_flow=FS,
        )
    for f in range(2, 10):
        net.add_room(f"Corridor_{f}", length=300 * FT, width=8 * FT)
    for f in range(2, 10):
        sfpe_floor(net, f)
    pops = [
        Population(f"Room_{f}.{r}", 150, speed=1.2, target=f"Exit{s}")
        for f in range(2, 10)
        for r, s in ((1, "R"), (2, "L"))
    ]
    return net, NetworkSimulation(net, pops, dt=DT).run(seed=1)


def test_sfpe_nine_storey():
    net, result = sfpe_building()
    # The 36 in exit door (1.33 x 0.61 = 0.811/s) controls, below the
    # stair (1.012 x 0.82 = 0.830/s). Each door passes its 1200 agents in
    # no less than (N-1)/C. Before the door queue forms, the first agents
    # arrive slower than C; this start-up lag is about 1 s whatever dt, so
    # the window is absolute. Valid for start 0 only.
    door = FS * (0.91 - 0.3)
    # The stair links carry the stair capacity, 1.012 x (1.12 - 0.3)
    # per s, and the incline length 12 ft x sqrt(1 + (0.28/0.18)^2).
    links = {lk.name: lk for lk in net.links}
    stair = stair_fs(STAIR_K) * (1.12 - 0.3)
    for f in range(2, 10):
        for s in "RL":
            down = links[f"Landing_{f}{s}->Stairs_{f}{s}"]
            assert down.kind == "stair"
            assert down.capacity == pytest.approx(stair, rel=1e-3)
            run = links[f"Stairs_{f}{s}->Landing_{f - 1}{s}"]
            assert run.length == pytest.approx(SFPE_STAIR)
    for s in "RL":
        flow = result.link_flow[
            :, result.link_names.index(f"Landing_1{s}->Exit{s}")
        ]
        passed = np.cumsum(flow)
        assert passed[-1] == 1200
        first = result.times[np.argmax(passed >= 1)]
        last = result.times[np.argmax(passed >= 1200)]
        assert 1199 / door <= last - first <= 1199 / door + STARTUP_LAG
    # Lower bound for a floor-2 agent starting at the door: 14.12 m of
    # room and 50.3 m of corridor and landings at the free level speed,
    # then one stair at its free speed.
    walk = (14.12 + 40.7 + 2 * LANDING) / free_speed(K_LEVEL)
    hand = walk + SFPE_STAIR / free_speed(STAIR_K)
    assert hand == pytest.approx(61.0, abs=0.1)
    assert np.min(result.exit_times) >= hand
    assert_invariants(result, net, 2400)


# §2.6, pp. 18-20: SFPE Guide on Human Behavior, example 1. Stand-in for
# EvacuatioNZ's least-populated-connection rule: two populations of 150,
# each with its own exit. The 32 in door (0.682/s) limits room->stair.

GUIDE_K = stair_k(7 * IN, 11 * IN)


def guide(start):
    net = Network()
    net.add_room("room", length=200 * FT, width=30 * FT)
    for i in (1, 2):
        net.add_stair(
            f"stair{i}",
            length=50 * FT,
            width=44 * IN,
            riser=7 * IN,
            tread=11 * IN,
        )
        net.add_safe(f"exit{i}")
        net.connect("room", f"stair{i}", width=32 * IN, specific_flow=FS)
        net.connect(
            f"stair{i}",
            f"exit{i}",
            width=32 * IN,
            kind="opening",
            length=50.1 * FT,
            specific_flow=FS,
        )
    speed = 275 * FT / 60
    pops = [
        Population(
            "room", 150, speed=speed, start_distance=start, target=f"exit{i}"
        )
        for i in (1, 2)
    ]
    return net, NetworkSimulation(net, pops, dt=DT).run(seed=1)


@pytest.mark.parametrize("start", [0.0, 200 * FT])
def test_sfpe_guide_example_1(start):
    net, result = guide(start)
    door = FS * (32 * IN - 0.3)
    room_density = 300 / (200 * FT * 30 * FT)
    room_speed = K_LEVEL * (1 - A * max(room_density, 0.54))
    walk = start / min(room_speed, 275 * FT / 60)
    hand = walk + 149 / door + 50.1 * FT / free_speed(GUIDE_K)
    assert hand <= result.evacuation_time <= hand + 2 * DT
    assert_invariants(result, net, 300)


# §3.1, pp. 21-25: distributions of the pre-movement time.


@pytest.mark.parametrize("value", [45.0, 120.0])
def test_fixed_distribution_is_exact(value):
    values = Fixed(value).sample(np.random.default_rng(1), 100)
    assert np.all(values == value)


@pytest.mark.parametrize(
    "dist, mean, std",
    [
        (Uniform(10, 100), 55.0, 90 / math.sqrt(12)),
        (Normal(120, 30), 120.0, 30.0),
        (LogNormal(5, 2), 5.0, 2.0),
    ],
)
def test_distribution_moments(dist, mean, std):
    values = dist.sample(np.random.default_rng(1), 20000)
    assert values.mean() == pytest.approx(mean, rel=0.02)
    assert values.std() == pytest.approx(std, rel=0.05)


def test_uniform_distribution_range():
    values = Uniform(10, 100).sample(np.random.default_rng(1), 20000)
    assert values.min() >= 10 and values.max() <= 100


# §3.2, p. 25: clearance of the IMO 4 room with pre-movement delays.


def room_clearance(pre_movement, start, seed):
    net = Network()
    net.add_room("room", length=8.0, width=5.0)
    net.add_safe("exit")
    net.connect("room", "exit", width=1.0, length=0.1, specific_flow=FS)
    pop = Population(
        "room",
        100,
        speed=1.0,
        pre_movement=pre_movement,
        start_distance=start,
    )
    return net, NetworkSimulation(net, [pop], dt=DT).run(seed=seed)


def test_room_clearance_without_delay():
    net, result = room_clearance(Fixed(0.0), 0.0, seed=1)
    hand = 99 / (FS * 0.7)
    assert hand < result.evacuation_time <= hand + 2 * DT
    assert_invariants(result, net, 100)


@pytest.mark.parametrize("delay", [30.0, 120.0])
def test_room_clearance_fixed_delay_shifts(delay):
    # Fixed draws no random numbers, so each seed gives the same starts.
    for seed in range(20):
        net, base = room_clearance(Fixed(0.0), Uniform(0, 8.0), seed)
        _, late = room_clearance(Fixed(delay), Uniform(0, 8.0), seed)
        assert_invariants(base, net, 100)
        assert_invariants(late, net, 100)
        shift = late.evacuation_time - base.evacuation_time
        assert shift == pytest.approx(delay, abs=1e-9)


def test_room_clearance_dispersed_without_delay():
    hand = 99 / (FS * 0.7)
    for seed in range(20):
        net, result = room_clearance(Fixed(0.0), Uniform(0, 8.0), seed)
        assert hand < result.evacuation_time <= hand + 2 * DT
        assert_invariants(result, net, 100)


@pytest.mark.parametrize(
    "mode, upper",
    [(15, 30), (30, 60), (60, 120)],
)
def test_room_clearance_triangular_bound(mode, upper):
    # Start at the door. The agent with the i-th smallest delay cannot
    # leave before the N-1-i agents after it have passed at C.
    net, result = room_clearance(Triangular(0, mode, upper), 0.0, seed=0)
    tau = np.sort(result.pre_movement_times)
    bound = max(tau[i] + (99 - i) / (FS * 0.7) for i in range(100))
    assert bound <= result.evacuation_time <= bound + 2 * DT
    assert_invariants(result, net, 100)


def test_one_arrival_per_step_respects_capacity():
    # 40 agents released one per step through a 0.931/s door: the last
    # cannot leave before 39/C after the first.
    net = Network()
    net.add_room("room", area=40.0)
    net.add_safe("exit")
    net.connect("room", "exit", width=1.0, specific_flow=FS)
    pops = [
        Population("room", 1, speed=1.0, pre_movement=Fixed(0.5 * i))
        for i in range(40)
    ]
    result = NetworkSimulation(net, pops, dt=DT).run(seed=1)
    assert result.evacuation_time >= 39 / (FS * 0.7)
    assert_invariants(result, net, 40)


# §5.1, pp. 29-33: exit choice. The report gives no node sizes or widths;
# 25 m² nodes and 1 m doors are assumed and only the exit used is checked.


def exit_choice():
    net = Network()
    for name in ("Room_1", "Room_2", "Room_4"):
        net.add_room(name, area=25.0)
    for name in ("Exit_3", "Exit_5", "Exit_6"):
        net.add_safe(name)
    for source, target, length in [
        ("Room_1", "Room_2", 1.0),
        ("Room_2", "Exit_3", 15.0),
        ("Room_2", "Room_4", 4.0),
        ("Room_4", "Exit_6", 2.0),
        ("Room_4", "Exit_5", 1.0),
    ]:
        net.connect(source, target, width=1.0, length=length, specific_flow=FS)
    return net


@pytest.mark.parametrize(
    "target, used", [(None, "Room_4->Exit_5"), ("Exit_6", "Room_4->Exit_6")]
)
def test_exit_choice(target, used):
    net = exit_choice()
    pop = Population(
        "Room_1", 12, speed=1.2, start_distance=Uniform(0, 5.0), target=target
    )
    result = NetworkSimulation(net, [pop], dt=DT).run(seed=1)
    link = result.link_names.index(used)
    assert result.link_flow[:, link].sum() == 12
    assert_invariants(result, net, 12)


# §5.2, pp. 34-35: required connection, not modelled. EvacuatioNZ sends
# everyone through the 5.0 m direct door; this model takes the 0.6 m route
# through Room_2 and Room_3.


def test_required_connection_is_not_modelled():
    net = Network()
    for name in ("Room_1", "Room_2", "Room_3"):
        net.add_room(name, length=2.0, width=2.0)
    net.add_safe("Exit")
    net.connect("Room_1", "Exit", width=0.5, length=5.0, specific_flow=FS)
    for source, target, length in [
        ("Room_1", "Room_2", 0.1),
        ("Room_2", "Room_3", 0.2),
        ("Room_3", "Exit", 0.3),
    ]:
        net.connect(
            source,
            target,
            width=0.5,
            kind="opening",
            length=length,
            specific_flow=FS,
        )
    result = NetworkSimulation(net, [Population("Room_1", 10)], dt=DT).run(1)
    flow = dict(zip(result.link_names, result.link_flow.sum(axis=0)))
    assert flow["Room_3->Exit"] == 10
    assert flow["Room_1->Exit"] == 0
    assert_invariants(result, net, 10)
