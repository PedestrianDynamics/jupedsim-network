# SPDX-License-Identifier: LGPL-3.0-or-later
"""Build routing costs from resolved network records and hydraulic relations.

Cost construction is separate from the shortest-path implementation.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from jupedsim_network import hydraulic

if TYPE_CHECKING:
    from jupedsim_network.network import Link, Node

ROUTING_POLICIES = ("shortest_distance", "shortest_free_flow_time")


def check_routing_policy(routing_policy) -> None:
    if routing_policy in ROUTING_POLICIES:
        return
    valid = ", ".join(repr(p) for p in ROUTING_POLICIES)
    raise ValueError(
        f"routing_policy must be one of {valid}; got {routing_policy!r}."
    )


def edge_costs(nodes, links, routing_policy) -> list[float]:
    check_routing_policy(routing_policy)
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
    reference_speed = float(hydraulic.speed(0, source.speed_constant))
    # Infinity records an unrepresentable cost; routing raises only when
    # no finite route exists, after considering all alternatives.
    return link.length / reference_speed


def overflow_error(error, routing_policy) -> ValueError:
    """The public message for a routing cost overflow, with metric and unit."""
    metric, unit, what = (
        ("distance", "m", "length")
        if routing_policy == "shortest_distance"
        else ("cost", "s", "cost")
    )
    return ValueError(
        f"Shortest route {metric} from '{error.node}' exceeds the "
        f"floating-point range at link '{error.link}' (index {error.index}): "
        f"accumulated {metric} {error.accumulated!r} {unit} "
        f"+ link {what} {error.cost!r} {unit} is non-finite."
    )
