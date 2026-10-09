# SPDX-License-Identifier: LGPL-3.0-or-later
"""Coarse network egress model for fast evacuation-time estimates.

Spaces are nodes with an area, doors and stair entries are links with a
flow capacity, and individual agents move through them by relations adapted
from the SFPE hydraulic relations. A run takes milliseconds, so scenarios can
be sampled many times with :meth:`NetworkSimulation.run_many`.
"""

from jupedsim_network.network import Link, Network, Node
from jupedsim_network.sampling import (
    Distribution,
    Fixed,
    LogNormal,
    Normal,
    Triangular,
    Uniform,
    Weibull,
)
from jupedsim_network.simulation import (
    MonteCarloResult,
    NetworkSimulation,
    Population,
    SimulationResult,
)

__all__ = [
    "Distribution",
    "Fixed",
    "Link",
    "LogNormal",
    "MonteCarloResult",
    "Network",
    "NetworkSimulation",
    "Node",
    "Normal",
    "Population",
    "SimulationResult",
    "Triangular",
    "Uniform",
    "Weibull",
]
