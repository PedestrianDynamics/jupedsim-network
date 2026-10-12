# SPDX-License-Identifier: LGPL-3.0-or-later
"""Stateless path calculations over supplied edge costs.

Node and Link records remain owned by network.py. Inputs are borrowed for
one calculation; only temporary adjacency lists and algorithm state are built.
This module does not construct costs or depend on hydraulic equations.
Callers supply nonnegative costs indexed by Link.index and target node
indices. Positive infinity denotes a cost outside the floating-point range;
it raises only if a reachable node has no finite route. No graph records or caller-owned collections are modified.
"""

from __future__ import annotations

import heapq
import math
from collections import Counter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jupedsim_network.network import Link, Node

# Relative tolerance, with an absolute floor in the supplied cost's units.
# Approximate equality selects eligible ties; it never defines progress order.
TIE_TOLERANCE = 1e-9


def route_table(
    nodes: tuple[Node, ...],
    links: tuple[Link, ...],
    targets: list[int],
    costs: list[float],
    *,
    metric="distance",
    unit="m",
) -> list[int | None]:
    """Next links at minimum supplied cost, preserving first-found tie order."""
    distance = [math.inf] * len(nodes)
    next_link: list[int | None] = [None] * len(nodes)
    heap = [(0.0, index) for index in targets]
    for _, index in heap:
        distance[index] = 0.0
    incoming = _incoming(nodes, links)
    while heap:
        d, index = heapq.heappop(heap)
        if d > distance[index]:
            continue
        for link in incoming[index]:
            _relax(link, d, distance, next_link, heap, costs[link.index])
    choices = route_choices(
        nodes, links, targets, costs, metric=metric, unit=unit
    )
    return [
        link if not tied or link in tied else tied[0]
        for link, tied in zip(next_link, choices)
    ]


def route_choices(
    nodes: tuple[Node, ...],
    links: tuple[Link, ...],
    targets: list[int],
    costs: list[float],
    *,
    metric="distance",
    unit="m",
) -> list[tuple[int, ...]]:
    """Eligible equal-cost first links in creation order.

    Progress strictly decreases (cost, hops), independently of tie tolerance.
    """
    distance, hops = distances(
        nodes, links, targets, costs, metric=metric, unit=unit
    )
    choices: list[list[int]] = [[] for _ in nodes]
    for link in links:
        if _is_tied(link, distance, hops, costs[link.index]):
            choices[link.source].append(link.index)
    _check_acyclic(choices, links)
    return [tuple(c) for c in choices]


def distances(
    nodes: tuple[Node, ...],
    links: tuple[Link, ...],
    targets: list[int],
    costs: list[float],
    *,
    metric="distance",
    unit="m",
) -> tuple[list[float], list[float]]:
    """Minimum supplied costs and minimum hops on such routes."""
    distance = [math.inf] * len(nodes)
    hops = [math.inf] * len(nodes)
    overflows: list[tuple[Link, float, float]] = []
    heap = [(0.0, 0, index) for index in targets]
    for _, _, index in heap:
        distance[index], hops[index] = 0.0, 0
    incoming = _incoming(nodes, links)
    while heap:
        d, h, index = heapq.heappop(heap)
        if (d, h) > (distance[index], hops[index]):
            continue
        for link in incoming[index]:
            _relax_hops(
                link,
                (d, h),
                distance,
                hops,
                heap,
                overflows,
                costs[link.index],
            )
    # An overflowing candidate is harmless if a finite alternative exists.
    for link, accumulated, cost in overflows:
        if math.isinf(distance[link.source]):
            raise ValueError(
                f"Shortest route {metric} from '{nodes[link.source].name}' "
                f"exceeds the floating-point range at link '{link.name}' "
                f"(index {link.index}): accumulated {metric} {accumulated!r} {unit} "
                f"+ link {'length' if unit == 'm' else 'cost'} {cost!r} {unit} is non-finite."
            )
    return distance, hops


def _incoming(nodes, links) -> list[list[Link]]:
    incoming: list[list[Link]] = [[] for _ in nodes]
    for link in links:
        incoming[link.target].append(link)
    return incoming


def _relax(link, d, distance, next_link, heap, cost) -> None:
    candidate = d + cost
    if candidate >= distance[link.source]:
        return
    distance[link.source] = candidate
    next_link[link.source] = link.index
    heapq.heappush(heap, (candidate, link.source))


def _relax_hops(link, key, distance, hops, heap, overflows, cost) -> None:
    total = key[0] + cost
    # Heap costs are finite; an edge cost or the sum may overflow.
    if not math.isfinite(total):
        overflows.append((link, key[0], cost))
        return
    candidate = (total, key[1] + 1)
    if candidate >= (distance[link.source], hops[link.source]):
        return
    distance[link.source], hops[link.source] = candidate
    heapq.heappush(heap, (*candidate, link.source))


def _is_tied(link, distance, hops, cost) -> bool:
    here, there = distance[link.source], distance[link.target]
    if not math.isfinite(here):
        return False
    tol = TIE_TOLERANCE
    if not math.isclose(there + cost, here, rel_tol=tol, abs_tol=tol):
        return False
    return (there, hops[link.target]) < (here, hops[link.source])


def _check_acyclic(choices, links) -> None:
    """Raise if tied links form a cycle (Kahn's algorithm)."""
    targets = [[links[i].target for i in tied] for tied in choices]
    indegree = Counter(v for vs in targets for v in vs)
    ready = [u for u in range(len(choices)) if indegree[u] == 0]
    removed = 0
    while ready:
        u = ready.pop()
        removed += 1
        indegree.subtract(targets[u])
        ready.extend({v for v in targets[u] if indegree[v] == 0})
    if removed < len(choices):
        raise RuntimeError("Tied routes form a cycle.")
