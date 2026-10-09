# SPDX-License-Identifier: LGPL-3.0-or-later
"""Worked example: evacuation of a two-storey office wing.

Run from the repository root::

    python examples/office_wing.py

The page ``site/content/docs/examples/office-wing.md`` quotes this script
and its output; ``tests/test_examples.py`` checks that they agree.
"""

import math

import numpy as np

from jupedsim_network import Network, NetworkSimulation, Population, Uniform

# Stair between the floors: 20 risers of 175 mm over a storey height of
# 3.5 m, in two flights of 10 risers (9 treads of 280 mm) and a half
# landing. Each flight is 1.2 m wide.
RISER, TREAD = 0.175, 0.28
FLIGHT_WIDTH = 1.2
FLIGHT_GOING = 9 * TREAD  # horizontal run of one flight, m
LANDING_DEPTH = 1.2
INCLINE = math.sqrt(1.0 + (RISER / TREAD) ** 2)
# Two flights along the incline plus the walk across the half landing.
STAIR_LENGTH = round(2 * FLIGHT_GOING * INCLINE + 2 * FLIGHT_WIDTH, 1)
# Two flights side by side, plus the half landing.
STAIR_AREA = round(2 * FLIGHT_WIDTH * (FLIGHT_GOING + LANDING_DEPTH), 1)

# Level spaces: name -> (length, width) in m. G = ground floor,
# U = upper floor; W and E are the west and east halves of a corridor.
ROOMS = {
    "G1": (9.0, 7.0),
    "G2": (9.0, 7.0),
    "G3": (9.0, 7.0),
    "G4": (9.0, 7.0),
    "GW": (18.0, 2.0),
    "GE": (18.0, 2.0),
    "U1": (9.0, 7.0),
    "U2": (9.0, 7.0),
    "TR": (18.0, 7.0),
    "UW": (18.0, 2.0),
    "UE": (18.0, 2.0),
}

# Links: (source, target, kind, clear width in m, length in m walked
# inside the source from its centre to the constriction).
LINKS = [
    ("G1", "GW", "door", 0.9, 3.5),
    ("G2", "GW", "door", 0.9, 3.5),
    ("G3", "GE", "door", 0.9, 3.5),
    ("G4", "GE", "door", 0.9, 3.5),
    ("GW", "GE", "door", 2.0, 9.0),
    ("GE", "GW", "door", 2.0, 9.0),
    ("GW", "main", "door", 1.8, 9.0),
    ("GE", "side", "door", 0.9, 9.0),
    ("U1", "UW", "door", 0.9, 3.5),
    ("U2", "UW", "door", 0.9, 3.5),
    ("TR", "UE", "door", 0.9, 3.5),
    ("UW", "UE", "door", 2.0, 9.0),
    ("UE", "stair", "door", 0.9, 7.0),
    ("stair", "GE", "stair", FLIGHT_WIDTH, STAIR_LENGTH),
]


def build_network(side_door=0.9):
    """The office wing; ``side_door`` is the clear width of the side door."""
    net = Network()
    for name, (length, width) in ROOMS.items():
        net.add_room(name, length=length, width=width)
    net.add_stair("stair", riser=RISER, tread=TREAD, area=STAIR_AREA)
    net.add_safe("main")
    net.add_safe("side")
    for source, target, kind, width, length in LINKS:
        if (source, target) == ("GE", "side"):
            width = side_door
        net.connect(
            source,
            target,
            kind=kind,
            width=width,
            length=length,
            bidirectional=False,
        )
    return net


SPEED = Uniform(0.8, 1.2)
OFFICE_START = Uniform(30.0, 90.0)
TRAINING_START = Uniform(20.0, 40.0)


def populations():
    """Six people per office, 60 in the training room."""
    offices = [
        Population(room, 6, speed=SPEED, pre_movement=OFFICE_START)
        for room in ("G1", "G2", "G3", "G4", "U1", "U2")
    ]
    training = Population("TR", 60, speed=SPEED, pre_movement=TRAINING_START)
    return offices + [training]


RUNS = 100


def simulation(side_door=0.9, dt=0.1):
    return NetworkSimulation(
        build_network(side_door),
        populations(),
        dt=dt,
        t_max=900.0,
        max_density=2.75,
    )


def exit_of(net, name):
    """Safe node that the route from ``name`` leads to."""
    routes = net.route_table()
    node = net.node(name)
    while routes[node.index] is not None:
        node = net.nodes[net.links[routes[node.index]].target]
    return node.name


def agents_through(result, link):
    """Agents that passed ``link`` during the run."""
    return int(result.link_flow[:, result.link_names.index(link)].sum())


def peak(result, node):
    """Largest number of agents in ``node`` at any time."""
    return int(result.node_occupancy[:, result.node_names.index(node)].max())


def passage_times(result, link):
    """Times of the first and the last passage through ``link``."""
    flow = result.link_flow[:, result.link_names.index(link)]
    times = result.times[flow > 0]
    return times[0], times[-1]


def quantiles(runs):
    q = runs.quantile([0.5, 0.95])
    return f"median {q[0]:.1f} s, 95th percentile {q[1]:.1f} s"


def report_network(net):
    print(f"stair: length {STAIR_LENGTH} m, area {STAIR_AREA} m²")
    for link in net.links:
        print(f"{link.name:10s} {link.capacity:.2f} persons/s")
    for room in ("G1", "G2", "G3", "G4", "U1", "U2", "TR"):
        print(f"{room} leaves by the {exit_of(net, room)} door")


def report_run(result, net):
    print(f"evacuation time: {result.evacuation_time:.1f} s")
    print(f"agents safe: {result.evacuated} of {len(result.exit_times)}")
    print(f"main door: {agents_through(result, 'GW->main')} agents")
    print(f"side door: {agents_through(result, 'GE->side')} agents")
    for link in ("TR->UE", "UE->stair", "GE->side", "GW->main"):
        first, last = passage_times(result, link)
        print(f"{link}: first agent at {first:.1f} s, last at {last:.1f} s")
    for node in ("UE", "stair", "GE"):
        most = peak(result, node)
        density = most / net.node(node).area
        print(f"peak in {node}: {most} agents, {density:.2f} per m²")
    between = agents_through(result, "GW->GE") + agents_through(
        result, "GE->GW"
    )
    print(f"agents between the corridor halves: {between}")
    # Agents are stored in population order: the training room comes last.
    print(f"last agent from TR out: {result.exit_times[-60:].max():.1f} s")


def report_monte_carlo(runs, result):
    print(quantiles(runs))
    print(f"incomplete runs: {runs.incomplete} of {runs.evacuation_times.size}")
    fastest, slowest = runs.complete.min(), runs.complete.max()
    print(f"fastest {fastest:.1f} s, slowest {slowest:.1f} s")
    share = (runs.complete < result.evacuation_time).mean()
    print(f"seed 1 is slower than {share:.0%} of the runs")


def report_what_if():
    print("side door  seed 1    median   95th pct  peak in GE")
    starts = []
    for width in (0.9, 1.2, 1.8):
        sim = simulation(side_door=width)
        one = sim.run(seed=1)
        q = sim.run_many(RUNS, seed=1).quantile([0.5, 0.95])
        print(
            f"{width} m      {one.evacuation_time:.1f} s  {q[0]:.1f} s  "
            f"{q[1]:.1f} s   {peak(one, 'GE')}"
        )
        starts.append(one.pre_movement_times)
    same = all(np.array_equal(starts[0], s) for s in starts)
    print(f"same pre-movement times in every variant: {same}")


def main():
    net = build_network()
    report_network(net)
    print()

    sim = simulation()
    result = sim.run(seed=1)
    report_run(result, net)
    print()

    runs = sim.run_many(RUNS, seed=1)
    report_monte_carlo(runs, result)
    print()

    report_what_if()


if __name__ == "__main__":
    main()
