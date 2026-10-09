"""Scenarios shared by the figure and animation scripts."""

import numpy as np

from jupedsim_network import Network, Population, Uniform
from jupedsim_network.simulation import _SAFE, _Run


def building(floors=10, stairs=("A", "B"), lengths=None, area=400.0):
    """Floors stacked above ground, each with a door to every stair.

    The flight node ``A3`` holds agents walking from floor 3 down to
    floor 2; ``A1`` discharges to the safe node ``exitA``.
    """
    lengths = lengths or {s: 25.0 for s in stairs}
    net = Network()
    for s in stairs:
        net.add_safe(f"exit{s}")
    for f in range(1, floors + 1):
        net.add_room(f"F{f}", area=area)
    cells = [(f, s) for f in range(1, floors + 1) for s in stairs]
    for f, s in cells:
        net.add_stair(f"{s}{f}", riser=0.18, tread=0.28, area=1.2 * 9.0)
    for f, s in cells:
        below = f"{s}{f - 1}" if f > 1 else f"exit{s}"
        net.connect(
            f"F{f}",
            f"{s}{f}",
            width=0.9,
            length=lengths[s],
            bidirectional=False,
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


def building_populations(
    floors=10, per_floor=60, pre=Uniform(30, 120), split=None
):
    """One population per floor, or one per floor and stair if ``split``."""
    if split is None:
        return [
            Population(f"F{f}", per_floor, pre_movement=pre)
            for f in range(1, floors + 1)
        ]
    share = per_floor // len(split)
    return [
        Population(f"F{f}", share, pre_movement=pre, target=f"exit{s}")
        for f in range(1, floors + 1)
        for s in split
    ]


def merge_corridor(weights=(1.0, 3.0)):
    net = Network()
    net.add_room("a", area=200.0)
    net.add_room("b", area=200.0)
    net.add_room("corridor", area=4.0)
    net.add_safe("exit")
    for name, w in zip(("a", "b"), weights):
        net.connect(name, "corridor", width=2.0, merge_weight=w)
    net.connect("corridor", "exit", width=1.0, length=2.0)
    return net


def trace(sim, seed):
    """Run ``sim`` and keep every agent's state at each step.

    Uses the private ``_Run`` because the public result only records node
    occupancy and link flow, not per-agent states.
    """
    run = _Run(sim, np.random.default_rng(seed), True)
    a = run.agents
    frames, t = [], 0.0

    def snapshot():
        frames.append(
            dict(
                t=t,
                node=a.node.copy(),
                link=a.link.copy(),
                state=a.state.copy(),
                distance=a.distance.copy(),
                arrival=a.arrival.copy(),
            )
        )

    while t < sim.t_max and (a.state != _SAFE).any():
        snapshot()
        run._step(t)
        t = round(t + sim.dt, 9)
    snapshot()
    return run, frames
