# SPDX-License-Identifier: LGPL-3.0-or-later
"""Build routing costs from resolved network records and hydraulic relations.

Cost construction is separate from the shortest-path implementation.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from jupedsim_network import hydraulic

if TYPE_CHECKING:
    from jupedsim_network.network import Link, Node

ROUTING_POLICIES = ("shortest_distance", "shortest_free_flow_time")


def edge_costs(nodes, links, routing_policy) -> list[float]:
    if routing_policy not in ROUTING_POLICIES:
        raise ValueError(f"Unknown routing policy: {routing_policy!r}.")
    return [
        edge_cost(link, nodes[link.source], routing_policy) for link in links
    ]


def edge_cost(link: Link, source: Node, routing_policy: str) -> float:
    """Distance (m) or hydraulic reference travel time (s), independent of routing.

    Reference time uses the source node's density-floor hydraulic speed.
    It excludes personal speed limits, congestion and queues and is not a
    prediction of actual travel time.
    """
    if routing_policy == "shortest_distance":
        return link.length
    if routing_policy != "shortest_free_flow_time":
        raise ValueError(f"Unknown routing policy: {routing_policy!r}.")
    reference_speed = float(hydraulic.speed(0, source.speed_constant))
    if not math.isfinite(reference_speed) or reference_speed <= 0:
        raise ValueError(
            f"Node '{source.name}' must have a finite positive reference speed."
        )
    # Infinity records an unrepresentable cost; routing raises only when
    # no finite route exists, after considering all alternatives.
    return link.length / reference_speed


def units(routing_policy):
    """Diagnostic label and unit for the selected cost."""
    return (
        ("distance", "m")
        if routing_policy == "shortest_distance"
        else ("cost", "s")
    )
