# SPDX-License-Identifier: LGPL-3.0-or-later
"""Graph of spaces (nodes) and constrictions (links) for the network model."""

import heapq
import math
from dataclasses import dataclass

from jupedsim_network import hydraulic

ROOM = "room"
STAIR = "stair"
SAFE = "safe"

DOOR = "door"
OPENING = "opening"

_BOUNDARY_LAYERS = {DOOR: 0.15, OPENING: 0.0, STAIR: 0.15}


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
    reached. ``capacity`` is the maximum flow in persons/s.
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
        """Add a stair flight; its area holds the agents on the flight."""
        k = hydraulic.stair_speed_constant(riser, tread)
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
                the constriction; used in both directions
            specific_flow: persons/s/m effective width. Defaults to 1.3 for
                doors and openings, and to the maximum flow of the adjacent
                stair node for stairs.
            boundary_layer: per side in m. Defaults to 0.15 for doors and
                stairs and 0 for openings.
            merge_weight: relative share when several links feed a full node
            bidirectional: also create the link from target to source

        Returns:
            The created links.
        """
        src, dst = self.node(source), self.node(target)
        _validate_connection(src, dst, width, kind, length, merge_weight)
        fs = specific_flow or _default_specific_flow(kind, src, dst)
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
        return tuple(links)

    def route_table(self, target: str | None = None) -> list[int | None]:
        """Next link per node on the shortest walking distance to safety.

        Arguments:
            target: name of one safe node; ``None`` uses the nearest one

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
        return next_link

    def _relax(self, link, d, distance, next_link, heap) -> None:
        candidate = d + link.length
        if candidate >= distance[link.source]:
            return
        distance[link.source] = candidate
        next_link[link.source] = link.index
        heapq.heappush(heap, (candidate, link.source))

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
