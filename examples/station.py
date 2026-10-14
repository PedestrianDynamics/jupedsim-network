# SPDX-License-Identifier: LGPL-3.0-or-later
"""Worked example: The Station nightclub as a coarse-network benchmark.

Run from the repository root::

    python examples/station.py

The network and the occupants are those of Spearpoint's EvacuatioNZ study
of NIST Scenario #1. The page ``site/content/docs/examples/station.md``
quotes this script and its output; ``tests/test_examples.py`` checks that
they agree.
"""

import math

import numpy as np

from jupedsim_network import (
    Network,
    NetworkSimulation,
    Population,
    Uniform,
)

# Spaces: name -> (length, width) in m, read from Fig. 1(b) of Spearpoint.
ROOMS = {
    "dart": (7.2, 5.4),
    "kitchen": (7.2, 2.2),
    "bar": (8.5, 7.6),
    "dance": (13.2, 7.8),
    "entrance": (2.0, 4.6),
    "sunroom": (10.9, 4.6),
    "hallway": (4.8, 8.2),
    "platform": (12.2, 2.2),
    "stage": (5.2, 3.6),
    "stageside": (2.4, 3.6),
}
SAFE = ("front", "side", "kitchen_exit", "platform_exit")

# Occupants of each space (Table 1 of Spearpoint), 420 in all.
OCCUPANTS = {
    "dart": 39,
    "kitchen": 3,
    "bar": 31,
    "dance": 237,
    "sunroom": 76,
    "hallway": 12,
    "platform": 18,
    "stage": 4,
}

# Links in the direction of egress: (source, target, clear width in m,
# connection length in m walked inside the source). The widths are the
# door widths before the boundary layer is taken off.
LINKS = [
    ("dart", "kitchen", 0.6, 3.7),
    ("dart", "dance", 2.5, 10.4),
    ("kitchen", "dance", 0.91, 10.4),
    ("kitchen", "kitchen_exit", 0.91, 3.6),
    ("bar", "side", 0.91, 3.8),
    ("bar", "dance", 1.2, 11.6),
    ("bar", "entrance", 0.91, 5.2),
    ("dance", "entrance", 0.91, 9.6),
    ("sunroom", "dance", 9.2, 6.1),
    ("entrance", "front", 1.83, 2.3),
    ("hallway", "dance", 1.6, 8.0),
    ("platform", "dance", 1.4, 10.0),
    ("stage", "stageside", 1.4, 3.8),
    ("dance", "stageside", 2.4, 8.9),
    ("stageside", "platform_exit", 0.91, 1.8),
]
# The stage side is walked back to the dance floor only by the stage
# occupants who head for the front entrance.
STAGESIDE_LINK = ("stageside", "dance", 2.4, 8.9)

# Exits assigned to the occupants of each space (Table 5 of Spearpoint).
TABLE_5 = {
    "dart": {"front": 39},
    "sunroom": {"front": 38, "platform_exit": 38},
    "dance": {"front": 118, "platform_exit": 119},
    "bar": {"front": 11, "side": 20},
    "platform": {"front": 6, "platform_exit": 12},
    "hallway": {"platform_exit": 12},
    "stage": {"platform_exit": 4},
    "kitchen": {"kitchen_exit": 3},
}
PREFERRED_SHARE = 0.6

SPEED = 1.2
SPECIFIC_FLOW = 1.33


def build_network(
    boundary_layer=0.15,
    stageside_link=False,
    specific_flow=SPECIFIC_FLOW,
    dance_entrance_factor=1.0,
    parameters=None,
):
    """The nightclub; every link is a one-way door."""
    net = Network(parameters=parameters)
    for name, (length, width) in ROOMS.items():
        net.add_room(name, length=length, width=width)
    for name in SAFE:
        net.add_safe(name)
    links = LINKS + [STAGESIDE_LINK] * stageside_link
    for source, target, width, length in links:
        if (source, target) == ("dance", "entrance"):
            length *= dance_entrance_factor
        net.connect(
            source,
            target,
            kind="door",
            width=width,
            length=length,
            specific_flow=specific_flow,
            boundary_layer=boundary_layer,
            bidirectional=False,
        )
    return net


def exits(case, node):
    """(target, agents) of the occupants of ``node``; ``None`` is nearest."""
    count = OCCUPANTS[node]
    if case == "nearest":
        return [(None, count)]
    if case == "table5":
        return list(TABLE_5[node].items())
    front = round(PREFERRED_SHARE * count)
    return [("front", front), (None, count - front)]


def populations(case="nearest", random_start=False):
    """Everyone moves at t = 0. ``case`` is ``"nearest"``, ``"preferred"``
    (60 % of each space head for the front door) or ``"table5"``."""
    pops = []
    for node in OCCUPANTS:
        start = Uniform(0.0, math.hypot(*ROOMS[node])) if random_start else 0.0
        for target, count in exits(case, node):
            pops.append(
                Population(
                    node,
                    count,
                    speed=SPEED,
                    start_distance=start,
                    target=target,
                )
            )
    return pops


def simulation(
    case="nearest",
    random_start=False,
    dt=0.5,
    max_density=2.75,
    supply_reduction=True,
    routing_policy="shortest_distance",
    **network_options,
):
    """The case on a network; ``network_options`` go to ``build_network``."""
    network_options.setdefault("stageside_link", case == "preferred")
    return NetworkSimulation(
        build_network(**network_options),
        populations(case, random_start),
        dt=dt,
        t_max=1800.0,
        max_density=max_density,
        supply_reduction=supply_reduction,
        routing_policy=routing_policy,
    )


def exit_links(result):
    """Names of the links into the four exits, in the order of ``SAFE``."""
    return [name for name in result.link_names if name.split("->")[1] in SAFE]


def exit_counts(result):
    """Agents through the platform, side, kitchen and front exits."""
    order = ("platform_exit", "side", "kitchen_exit", "front")
    flow = {
        name.split("->")[1]: result.link_flow[:, result.link_names.index(name)]
        for name in exit_links(result)
    }
    return [int(flow[exit].sum()) for exit in order]


def agents_inside(result, time):
    """Agents in the building at ``time``."""
    row = np.isclose(result.times, time)
    return int(result.node_occupancy[row].sum())


def passage_time(result, link, number=1):
    """Time of the ``number``-th passage through ``link``."""
    flow = result.link_flow[:, result.link_names.index(link)]
    passed = np.cumsum(flow)
    return float(result.times[np.argmax(passed >= number)])


def report_network(net):
    for link in net.links:
        print(f"{link.name:26s} {link.capacity:.3f} persons/s")
    routes = net.route_table()
    for name in OCCUPANTS:
        link = net.links[routes[net.node(name).index]]
        print(f"{name} leaves through {link.name}")


def report_run(label, result):
    platform, side, kitchen, front = exit_counts(result)
    print(
        f"{label}: {result.evacuation_time:.1f} s; platform {platform}, "
        f"side {side}, kitchen {kitchen}, front {front}; "
        f"{agents_inside(result, 90.0)} inside at 90 s"
    )


def main():
    net = build_network()
    report_network(net)
    print()

    report_run("S0", simulation().run(seed=1))
    report_run("S0s", simulation(supply_reduction=False).run(seed=1))
    report_run("S1", simulation(boundary_layer=0.0).run(seed=1))
    report_run("S3", simulation("preferred").run(seed=1))
    report_run("S3n", simulation("preferred", boundary_layer=0.0).run(seed=1))
    report_run("S2", simulation("table5", boundary_layer=0.0).run(seed=1))
    report_run("S2b", simulation("table5").run(seed=1))
    print()

    result = simulation().run(seed=1)
    door = "stageside->platform_exit"
    for number in (1, 5):
        print(
            f"passage {number} through the platform door: "
            f"{passage_time(result, door, number):.1f} s"
        )
    for dt in (0.1, 0.5, 1.0):
        print(f"dt {dt}: {simulation(dt=dt).run(seed=1).evacuation_time:.1f} s")


if __name__ == "__main__":
    main()
