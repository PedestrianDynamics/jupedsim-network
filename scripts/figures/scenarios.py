"""Scenarios shared by the figure and animation scripts.

The runs behind the figures are computed here, with NumPy only, so that
``tests/test_docs_numbers.py`` checks the numbers the pages quote from
them without matplotlib.
"""

import functools
import sys
import warnings
from pathlib import Path

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

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples"))
import station  # noqa: E402

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


# The Station nightclub (examples/station.py) --------------------------------

#: Cases of the baseline table: label -> keyword arguments of
#: ``station.simulation``.
STATION_CASES = {
    "S0": {},
    "S0 dt 0.1": {"dt": 0.1},
    "S0 dt 1.0": {"dt": 1.0},
    "S0s": {"supply_reduction": False},
    "S1": {"boundary_layer": 0.0},
    "S1 dt 0.1": {"boundary_layer": 0.0, "dt": 0.1},
    "S1s": {"boundary_layer": 0.0, "supply_reduction": False},
    "S2": {"case": "table5", "boundary_layer": 0.0},
    "S2b": {"case": "table5"},
    "S3": {"case": "preferred"},
    "S3 dt 0.1": {"case": "preferred", "dt": 0.1},
    "S3n": {"case": "preferred", "boundary_layer": 0.0},
}

#: Factors of the length of dance->entrance in the S4a sweep. 0.875 is the
#: exact tie: 0.875 * 9.6 + 2.3 = 8.9 + 1.8.
STATION_FACTORS = np.unique(np.append(np.arange(80, 121) / 100, 0.875))
#: Specific flows (persons/s/m) and boundary layers (m) of the S4b grid.
STATION_FLOWS = (1.21, 1.25, 1.30, 1.33)
STATION_LAYERS = (0.0, 0.05, 0.10, 0.15)
#: max_density values (1/m²) of the S4c sweep. The dance floor starts at
#: 2.30 per m², so smaller limits are rejected.
STATION_DENSITIES = (2.5, 2.75, 3.0, 3.25, 3.5)


@functools.cache
def station_runs():
    """Seed 1 of every case in ``STATION_CASES``."""
    return {
        label: station.simulation(**options).run(seed=1)
        for label, options in STATION_CASES.items()
    }


@functools.cache
def station_start_spread(seeds=100):
    """Evacuation times and exit counts of S0 with random start distances.

    The start distance is Uniform(0, R) with R the diagonal of the start
    node; run ``i`` uses child ``i`` of ``SeedSequence(1)``.
    """
    sim = station.simulation(random_start=True)
    runs = [sim.run(child) for child in np.random.SeedSequence(1).spawn(seeds)]
    times = np.array([r.evacuation_time for r in runs])
    splits = np.array([station.exit_counts(r) for r in runs])
    return times, splits


@functools.cache
def station_length_sweep():
    """S0 with the length of dance->entrance scaled by each factor.

    Returns the evacuation times (one row per routing policy, shortest
    distance first) and the front-door counts of the first row.
    """
    policies = ("shortest_distance", "shortest_free_flow_time")
    times = np.empty((2, STATION_FACTORS.size))
    front = np.empty(STATION_FACTORS.size, dtype=int)
    for j, f in enumerate(STATION_FACTORS):
        for i, policy in enumerate(policies):
            sim = station.simulation(
                routing_policy=policy, dance_entrance_factor=float(f)
            )
            result = sim.run(seed=1)
            times[i, j] = result.evacuation_time
            if i == 0:
                front[j] = station.exit_counts(result)[3]
    return times, front


@functools.cache
def station_door_sweep():
    """S0 for each specific flow and boundary layer of the door grid.

    Returns evacuation times, the capacity of the 0.91 m door and the time
    of the fifth passage through the platform door, each of shape
    (flows, layers).
    """
    shape = (len(STATION_FLOWS), len(STATION_LAYERS))
    times, capacity, fifth = np.empty(shape), np.empty(shape), np.empty(shape)
    for i, flow in enumerate(STATION_FLOWS):
        for j, layer in enumerate(STATION_LAYERS):
            sim = station.simulation(specific_flow=flow, boundary_layer=layer)
            result = sim.run(seed=1)
            times[i, j] = result.evacuation_time
            capacity[i, j] = flow * (0.91 - 2 * layer)
            fifth[i, j] = station.passage_time(
                result, "stageside->platform_exit", 5
            )
    return times, capacity, fifth


@functools.cache
def station_density_sweep():
    """Evacuation times and fifth platform passages per ``max_density``.

    Rows: supply reduction on, off.
    """
    shape = (2, len(STATION_DENSITIES))
    times, fifth = np.empty(shape), np.empty(shape)
    for i, supply in enumerate((True, False)):
        for j, limit in enumerate(STATION_DENSITIES):
            sim = station.simulation(max_density=limit, supply_reduction=supply)
            result = sim.run(seed=1)
            times[i, j] = result.evacuation_time
            fifth[i, j] = station.passage_time(
                result, "stageside->platform_exit", 5
            )
    return times, fifth
