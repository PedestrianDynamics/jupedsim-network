"""Scenarios shared by the figure and animation scripts.

The runs behind the figures are computed here, with NumPy only, so that
``tests/test_docs_numbers.py`` checks the numbers the pages quote from
them without matplotlib.
"""

import warnings

import numpy as np

from jupedsim_network import (
    HydraulicParameters,
    LogNormal,
    Network,
    NetworkSimulation,
    Population,
    Uniform,
)
from jupedsim_network.hydraulic import stair_speed_constant
from jupedsim_network.simulation import _SAFE, _Run

#: max_density values of the density sweep, in 1/m².
DENSITY_LIMITS = np.array([2.0, 2.25, 2.5, 2.75, 3.0, 3.25, 3.5, 3.7])

#: Values of the hydraulic sweep, one coefficient changed at a time. The
#: slope stays at or below the bound 0.269 set by door_specific_flow = 1.3
#: and above 0.182, where 1/(2a) would exceed max_density = 2.75.
HYDRAULIC_SWEEP = {
    "stair_speed_coefficient": np.array([40.0, 45.0, 51.8, 55.0, 60.0, 65.0]),
    "speed_density_slope": np.array([0.19, 0.21, 0.23, 0.25, 0.266]),
    "door_specific_flow": np.array([0.7, 0.9, 1.1, 1.3]),
}


def building(
    floors=10, stairs=("A", "B"), lengths=None, area=400.0, parameters=None
):
    """Floors stacked above ground, each with a door to every stair.

    The flight node ``A3`` holds agents walking from floor 3 down to
    floor 2; ``A1`` discharges to the safe node ``exitA``.
    """
    lengths = lengths or {s: 25.0 for s in stairs}
    net = Network(parameters=parameters)
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
            length=9.0,  # along the incline
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


def door_run():
    """IMO test 4 geometry: 100 agents through a 1 m door, Fs = 1.33."""
    net = Network()
    net.add_room("room", area=40.0)
    net.add_safe("exit")
    net.connect("room", "exit", width=1.0, specific_flow=1.33)
    return NetworkSimulation(net, [Population("room", 100, speed=1.0)]).run(1)


def merge_run():
    """Two rooms of 300 agents merge 1 : 3 into a full corridor."""
    pops = [Population("a", 300), Population("b", 300)]
    return NetworkSimulation(merge_corridor(), pops, t_max=150.0).run(seed=2)


def density_sweep_runs(max_density, supply_reduction, runs=30):
    """Evacuation times of the one-stair building, seed 1."""
    sim = NetworkSimulation(
        building(stairs=("A",)),
        building_populations(),
        max_density=max_density,
        supply_reduction=supply_reduction,
    )
    return sim.run_many(runs, seed=1).evacuation_times


def rset_quantiles(max_density, supply_reduction, runs):
    times = density_sweep_runs(max_density, supply_reduction, runs)
    return np.quantile(times, [0.05, 0.5, 0.95])


def hydraulic_sweep_runs(name, value, runs=30):
    """Evacuation times of the one-stair building with one coefficient changed."""
    parameters = HydraulicParameters(**{name: float(value)})
    sim = NetworkSimulation(
        building(stairs=("A",), parameters=parameters), building_populations()
    )
    return sim.run_many(runs, seed=1).evacuation_times


def stair_capacity_bound(name, value):
    """Lower bound on the evacuation time set by the stair flow, in s.

    600 agents pass the 1.2 m stair (0.9 m effective) at its maximum specific
    flow k/(4a) after the earliest pre-movement time of 30 s.
    """
    p = HydraulicParameters(**{name: float(value)})
    k = stair_speed_constant(0.18, 0.28, parameters=p)
    width = 1.2 - 2 * p.stair_boundary_layer
    return 30.0 + 600.0 / (width * k / (4 * p.speed_density_slope))


def route_tie_runs():
    """Seed 1 of the ten-storey building: ties split, not split, one stair."""
    cases = {
        "split": (building(), True),
        "first": (building(), False),
        "one": (building(stairs=("A",)), True),
    }
    runs = {}
    for key, (net, split) in cases.items():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sim = NetworkSimulation(
                net, building_populations(), split_ties=split
            )
        runs[key] = sim.run(seed=1)
    return runs


def monte_carlo_runs(runs=300):
    """The case study: log-normal pre-movement, half of each floor per stair."""
    pre = LogNormal(120.0, 60.0, upper=600.0)
    pops = building_populations(pre=pre, split="AB")
    return NetworkSimulation(building(), pops).run_many(runs, seed=11)


def mechanics_simulation():
    """Two rooms of 40 agents empty into a 4 m² corridor (mechanics.gif)."""
    pops = [
        Population(
            r, 40, pre_movement=Uniform(0, 8), start_distance=Uniform(1, 12)
        )
        for r in "ab"
    ]
    return NetworkSimulation(merge_corridor(), pops)


def building_run(floors=10):
    """One run of the case-study building, seed 1 (building.gif)."""
    net = building(floors=floors)
    pops = building_populations(floors=floors, split="AB")
    return net, NetworkSimulation(net, pops).run(seed=1)


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
