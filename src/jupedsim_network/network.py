# SPDX-License-Identifier: LGPL-3.0-or-later
"""Graph of spaces (nodes) and constrictions (links) for the network model."""

import heapq
import math
import warnings
from collections import Counter
from dataclasses import dataclass

from jupedsim_network import hydraulic

ROOM = "room"
STAIR = "stair"
SAFE = "safe"

DOOR = "door"
OPENING = "opening"

_BOUNDARY_LAYERS = {DOOR: 0.15, OPENING: 0.0, STAIR: 0.15}

# Route distances agreeing to this fraction of their length, or to this
# many m if larger, are tied: equal up to floating-point rounding.
TIE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Node:
    """A space agents occupy: a room, a stair flight or a safe place.

    ``speed_constant`` is the k of the SFPE speed-density relation used for
    walking inside the node. Safe nodes have infinite area.
    """

    name: str
    index: int
    kind: str
    area: float
    speed_constant: float


@dataclass(frozen=True)
class Link:
    """Directed passage from ``source`` to ``target`` node.

    ``length`` is walked inside the source node before the constriction is
    reached, along the incline on stair links. ``capacity`` is the maximum
    flow in persons/s.
    """

    name: str
    index: int
    source: int
    target: int
    kind: str
    length: float
    capacity: float
    merge_weight: float


class Network:
    """Builder for the node-link graph.

    Example:
        .. code:: python

            net = Network()
            net.add_room("office", area=200.0)
            net.add_stair("flight", area=8.0, riser=0.18, tread=0.28)
            net.add_safe("street")
            net.connect("office", "flight", width=1.2, kind="stair", length=15.0)
            net.connect("flight", "street", width=1.2, kind="stair", length=8.0)
    """

    def __init__(self) -> None:
        self._nodes: list[Node] = []
        self._links: list[Link] = []
        self._by_name: dict[str, Node] = {}
        # Reverse link of each link of a two-way connection (shared door).
        self._reverse: dict[int, int] = {}

    @property
    def nodes(self) -> tuple[Node, ...]:
        return tuple(self._nodes)

    @property
    def links(self) -> tuple[Link, ...]:
        return tuple(self._links)

    def node(self, name: str) -> Node:
        if name not in self._by_name:
            raise ValueError(f"Unknown node '{name}'.")
        return self._by_name[name]

    def add_room(
        self,
        name: str,
        *,
        area: float | None = None,
        length: float | None = None,
        width: float | None = None,
    ) -> Node:
        """Add a level space, given by ``area`` or ``length`` and ``width``."""
        return self._add(name, ROOM, _area(area, length, width), None)

    def add_stair(
        self,
        name: str,
        *,
        riser: float,
        tread: float,
        area: float | None = None,
        length: float | None = None,
        width: float | None = None,
    ) -> Node:
        """Add a stair flight; its area holds the agents on the flight.

        Stair links from this node take their ``length`` along the incline.
        A ``UserWarning`` is issued if ``riser`` lies outside 165-191 mm or
        ``tread`` outside 254-330 mm, the range of SFPE Handbook Table 67.2
        (6th ed., pp. 2174-2175); the speed constant is then extrapolated.
        """
        k = hydraulic.stair_speed_constant(riser, tread)
        _warn_outside_sfpe_range(name, riser, tread)
        return self._add(name, STAIR, _area(area, length, width), k)

    def add_safe(self, name: str) -> Node:
        """Add a place of safety with unlimited capacity."""
        return self._add(name, SAFE, math.inf, hydraulic.LEVEL_SPEED_CONSTANT)

    def connect(
        self,
        source: str,
        target: str,
        *,
        width: float,
        kind: str = DOOR,
        length: float = 0.0,
        specific_flow: float | None = None,
        boundary_layer: float | None = None,
        merge_weight: float = 1.0,
        bidirectional: bool = True,
        name: str | None = None,
    ) -> tuple[Link, ...]:
        """Connect two nodes through a door, opening or stair entry.

        Arguments:
            width: clear width in m
            kind: ``"door"``, ``"opening"`` or ``"stair"``
            length: distance in m walked inside the source node to reach
                the constriction; used in both directions. On a ``stair``
                link, the distance along the incline (line of travel),
                including landings, not the horizontal run.
            specific_flow: persons/s/m effective width, must be positive.
                Defaults to 1.3 for doors and openings, and to the maximum
                flow of the adjacent stair node for stairs.
            boundary_layer: per side in m. Defaults to 0.15 for doors and
                stairs and 0 for openings.
            merge_weight: relative share when several links feed a full node
            bidirectional: also create the link from target to source;
                the two links share one door (``counterflow`` of
                ``NetworkSimulation``)

        Returns:
            The created links.
        """
        src, dst = self.node(source), self.node(target)
        _validate_connection(src, dst, width, kind, length, merge_weight)
        fs = specific_flow
        if fs is None:
            fs = _default_specific_flow(kind, src, dst)
        if not fs > 0:
            raise ValueError(f"specific_flow must be positive, got {fs}.")
        layer = (
            _BOUNDARY_LAYERS[kind] if boundary_layer is None else boundary_layer
        )
        capacity = fs * hydraulic.effective_width(width, layer)
        if capacity <= 0:
            raise ValueError(f"Connection {source}-{target} has no capacity.")
        label = name or f"{source}->{target}"
        pairs = [(src, dst)] + ([(dst, src)] if bidirectional else [])
        links = []
        for a, b in pairs:
            if a.kind == SAFE:
                continue
            link = Link(
                name=label if a is src else f"{target}->{source}",
                index=len(self._links),
                source=a.index,
                target=b.index,
                kind=kind,
                length=length,
                capacity=capacity,
                merge_weight=merge_weight,
            )
            self._links.append(link)
            links.append(link)
        if len(links) == 2:
            self._reverse[links[0].index] = links[1].index
            self._reverse[links[1].index] = links[0].index
        return tuple(links)

    def route_table(self, target: str | None = None) -> list[int | None]:
        """Next link per node on the shortest walking distance to safety.

        Arguments:
            target: name of one safe node; ``None`` uses the nearest one

        Of several equally short routes the first link found is kept if it
        makes progress (closer to safety, or as close over fewer links),
        else the first such link in creation order; ``NetworkSimulation``
        splits such ties between their links. Raises ``RuntimeError`` if
        tied routes form a cycle, which the progress rule excludes.

        Returns:
            For each node index the index of the link to take, or ``None``
            for safe nodes and nodes without a route.
        """
        distance = [math.inf] * len(self._nodes)
        next_link: list[int | None] = [None] * len(self._nodes)
        heap = [(0.0, n.index) for n in self._targets(target)]
        for _, index in heap:
            distance[index] = 0.0
        incoming = self._incoming()
        while heap:
            d, index = heapq.heappop(heap)
            if d > distance[index]:
                continue
            for link in incoming[index]:
                self._relax(link, d, distance, next_link, heap)
        choices = self._route_choices(target)
        return [
            link if not tied or link in tied else tied[0]
            for link, tied in zip(next_link, choices)
        ]

    def _relax(self, link, d, distance, next_link, heap) -> None:
        candidate = d + link.length
        if candidate >= distance[link.source]:
            return
        distance[link.source] = candidate
        next_link[link.source] = link.index
        heapq.heappush(heap, (candidate, link.source))

    def _route_choices(
        self, target: str | None = None
    ) -> list[tuple[int, ...]]:
        """Tied next links per node: the first links of all shortest routes.

        A link u -> v is tied for u if d(v) + length equals d(u) within
        ``TIE_TOLERANCE`` and the link makes progress: v is closer to
        safety, or as close over fewer links. A zero-length detour is thus
        not a tie, and tied links cannot form a cycle.

        Returns:
            For each node index the tied link indices in creation order;
            empty for safe nodes and nodes without a route.
        """
        distance, hops = self._distances(target)
        choices: list[list[int]] = [[] for _ in self._nodes]
        for link in self._links:
            if _is_tied(link, distance, hops):
                choices[link.source].append(link.index)
        _check_acyclic(choices, self._links)
        return [tuple(c) for c in choices]

    def _distances(self, target) -> tuple[list[float], list[float]]:
        """Shortest distance to safety and the fewest links on such a route."""
        distance = [math.inf] * len(self._nodes)
        hops = [math.inf] * len(self._nodes)
        heap = [(0.0, 0, n.index) for n in self._targets(target)]
        for _, _, index in heap:
            distance[index], hops[index] = 0.0, 0
        incoming = self._incoming()
        while heap:
            d, h, index = heapq.heappop(heap)
            if (d, h) > (distance[index], hops[index]):
                continue
            for link in incoming[index]:
                _relax_hops(link, (d, h), distance, hops, heap)
        return distance, hops

    def _incoming(self) -> list[list[Link]]:
        incoming: list[list[Link]] = [[] for _ in self._nodes]
        for link in self._links:
            incoming[link.target].append(link)
        return incoming

    def _targets(self, target: str | None) -> list[Node]:
        if target is not None:
            node = self.node(target)
            if node.kind != SAFE:
                raise ValueError(f"Target '{target}' is not a safe node.")
            return [node]
        safe = [n for n in self._nodes if n.kind == SAFE]
        if not safe:
            raise ValueError("The network has no safe node.")
        return safe

    def _add(self, name, kind, area, speed_constant) -> Node:
        if name in self._by_name:
            raise ValueError(f"Node '{name}' already exists.")
        node = Node(
            name=name,
            index=len(self._nodes),
            kind=kind,
            area=area,
            speed_constant=speed_constant or hydraulic.LEVEL_SPEED_CONSTANT,
        )
        self._nodes.append(node)
        self._by_name[name] = node
        return node


def _relax_hops(link, key, distance, hops, heap) -> None:
    candidate = (key[0] + link.length, key[1] + 1)
    if candidate >= (distance[link.source], hops[link.source]):
        return
    distance[link.source], hops[link.source] = candidate
    heapq.heappush(heap, (*candidate, link.source))


def _is_tied(link, distance, hops) -> bool:
    here, there = distance[link.source], distance[link.target]
    if not math.isfinite(here):
        return False
    tol = TIE_TOLERANCE
    if not math.isclose(there + link.length, here, rel_tol=tol, abs_tol=tol):
        return False
    closer = there < here - tol * max(1.0, here)
    return closer or hops[link.target] < hops[link.source]


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


def _area(area, length, width) -> float:
    if area is None and (length is None or width is None):
        raise ValueError("Give either area or both length and width.")
    value = area if area is not None else length * width
    if value <= 0:
        raise ValueError("Node area must be positive.")
    return float(value)


def _validate_connection(src, dst, width, kind, length, merge_weight) -> None:
    if kind not in _BOUNDARY_LAYERS:
        raise ValueError(f"Unknown connection kind '{kind}'.")
    if src is dst:
        raise ValueError("A connection needs two different nodes.")
    if src.kind == SAFE and dst.kind == SAFE:
        raise ValueError("Cannot connect two safe nodes.")
    if width <= 0 or length < 0 or merge_weight <= 0:
        raise ValueError(
            "Width and merge weight must be positive, length non-negative."
        )


def _default_specific_flow(kind, src, dst) -> float:
    if kind != STAIR:
        return hydraulic.DOOR_SPECIFIC_FLOW
    stairs = [n for n in (src, dst) if n.kind == STAIR]
    if not stairs:
        raise ValueError("A stair connection needs an adjacent stair node.")
    return hydraulic.max_specific_flow(stairs[0].speed_constant)


def _warn_outside_sfpe_range(name, riser, tread) -> None:
    risers, treads = hydraulic.STAIR_RISER_RANGE, hydraulic.STAIR_TREAD_RANGE
    if _within(riser, risers) and _within(tread, treads):
        return
    warnings.warn(
        f"Stair '{name}': riser {riser * 1000:.1f} mm and tread "
        f"{tread * 1000:.1f} mm lie outside the SFPE range (risers 165-191 mm, "
        "treads 254-330 mm, SFPE Handbook Table 67.2); the speed constant "
        "k = 51.8 sqrt(T/R) m/min is extrapolated.",
        UserWarning,
        stacklevel=3,
    )


def _within(value, bounds) -> bool:
    return bounds[0] - 1e-9 <= value <= bounds[1] + 1e-9
