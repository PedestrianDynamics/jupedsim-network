# SPDX-License-Identifier: LGPL-3.0-or-later
"""Directed graph with resolved physical properties for the network model.

The builder resolves hydraulic defaults into node speeds and link capacities.
Routing minimizes static link costs, either lengths or hydraulic
reference travel times (the ``routing_policy``). Flow sharing and agent
movement belong to the simulation. Reverse links identify directions of one
physical connection.
"""

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

# Route costs agreeing to this fraction, or this absolute amount if larger,
# are tied: metres for distance routing, seconds for reference-time routing.
TIE_TOLERANCE = 1e-9

ROUTING_POLICIES = ("shortest_distance", "shortest_free_flow_time")


@dataclass(frozen=True)
class Node:
    """A space agents occupy: a room, a stair flight or a safe place.

    ``speed_constant`` is the k of the SFPE speed-density relation used for
    walking inside the node. ``area`` is the supplied occupancy area in m²,
    used for both density and storage; no gross-to-usable area conversion is
    performed. Safe nodes have infinite area.
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
    unidirectional flow in persons/s. Paired reverse links represent one
    physical connection; the simulation's counterflow policy determines
    their combined flow, rather than summing their capacities unconditionally.
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
        # Arguments of each add_* and connect call as given, in call
        # order, so that a scenario file can be written without loss.
        self._inputs: list[tuple[str, dict]] = []

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
        """Add a level space, given by ``area`` or ``length`` and ``width``.

        Arguments:
            name: unique name of the node
            area: floor area in m²; give it, or both ``length`` and
                ``width``, not both
            length: length in m; with ``width``, the area is
                ``length * width``
            width: width in m; see ``length``
        """
        node = self._add(name, ROOM, _area(area, length, width), None)
        self._record("room", name=name, area=area, length=length, width=width)
        return node

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

        Arguments:
            name: unique name of the node
            riser: riser height in m, below 1 m; with ``tread`` it sets
                the walking speed on the flight
            tread: tread depth in m, below 1 m
            area: area of the flight in m², which holds the agents on
                it; give it, or both ``length`` and ``width``, not both.
            length: length of the flight in m along the incline, like the
                stair link, without landings; with ``width``, the area is
                ``length * width``
            width: width of the flight in m; see ``length``
        """
        k = hydraulic.stair_speed_constant(riser, tread)
        _warn_outside_sfpe_range(name, riser, tread)
        node = self._add(name, STAIR, _area(area, length, width), k)
        self._record(
            "stair",
            name=name,
            riser=riser,
            tread=tread,
            area=area,
            length=length,
            width=width,
        )
        return node

    def add_safe(self, name: str) -> Node:
        """Add a place of safety with unlimited capacity.

        An agent that reaches a safe node counts as safe: its exit time is
        recorded and it leaves the model. A safe node can be the outside
        or a protected area such as a refuge.

        Arguments:
            name: unique name of the node
        """
        node = self._add(name, SAFE, math.inf, hydraulic.LEVEL_SPEED_CONSTANT)
        self._record("safe", name=name)
        return node

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
            source: name of the node the link starts in
            target: name of the node the link leads to
            width: clear width in m
            kind: ``"door"``, ``"opening"`` or ``"stair"``
            length: distance in m walked inside the source node to reach
                the constriction; used in both directions. On a ``stair``
                link, the distance along the incline (line of travel),
                including landings, not the horizontal run.
            specific_flow: persons/s/m effective width, must be positive.
                Defaults to 1.3 for doors and openings, and to the maximum
                flow of the adjacent stair node for stairs. If both nodes
                are stairs, the source node sets the capacity in both
                directions; give an explicit value to override this rule.
            boundary_layer: per side in m, at least 0. Defaults to 0.15
                for doors and stairs and 0 for openings.
            merge_weight: relative share when several links feed a full node
            bidirectional: also create the link from target to source;
                the two links share one door (``counterflow`` of
                ``NetworkSimulation``). No link leaves a safe node, so a
                safe target gets no reverse link.
            name: name of the link from ``source`` to ``target``; ``None``
                or empty gives ``"source->target"``. The reverse link is
                always named ``"target->source"``.

        Returns:
            The created links.
        """
        src, dst = self.node(source), self.node(target)
        _validate_connection(src, dst, width, kind, length, merge_weight)
        capacity = _connection_capacity(
            src, dst, width, kind, specific_flow, boundary_layer
        )
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
        self._record(
            "connect",
            source=source,
            target=target,
            width=width,
            kind=kind,
            length=length,
            specific_flow=specific_flow,
            boundary_layer=boundary_layer,
            merge_weight=merge_weight,
            bidirectional=bidirectional,
            name=name,
        )
        return tuple(links)

    def _record(self, call: str, **arguments) -> None:
        self._inputs.append((call, arguments))

    def route_table(
        self,
        target: str | None = None,
        *,
        routing_policy: str = "shortest_distance",
    ) -> list[int | None]:
        """Next link per node on the minimum-cost route to safety.

        Raises ``ValueError`` if a reachable node's minimum cost
        exceeds the floating-point range.

        Arguments:
            target: name of one safe node; ``None`` minimizes cost to any safe node
            routing_policy: "shortest_distance" sums link lengths in m;
                "shortest_free_flow_time" sums length divided by the source
                node's ``hydraulic.speed(0, k)`` in seconds. This hydraulic
                reference time includes the density floor, but excludes
                personal speed limits, congestion and queues. It does not
                predict actual travel time.

        Of several equally short routes the first link found is kept if it
        makes progress (closer to safety, or as close over fewer links),
        else the first such link in creation order; ``NetworkSimulation``
        splits such ties between their links. Raises ``RuntimeError`` if
        tied routes form a cycle, which the progress rule excludes.

        Returns:
            For each node index the index of the link to take, or ``None``
            for safe nodes and nodes without a route.
        """
        costs = _routing_costs(self, routing_policy)
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
                self._relax(
                    link, d, distance, next_link, heap, costs[link.index]
                )
        choices = self._route_choices(
            target, routing_policy=routing_policy, costs=costs
        )
        return [
            link if not tied or link in tied else tied[0]
            for link, tied in zip(next_link, choices)
        ]

    def route_choices(
        self,
        target: str | None = None,
        *,
        routing_policy: str = "shortest_distance",
    ) -> list[tuple[int, ...]]:
        """Tied next links per node: the first links of all shortest routes.

        Where several routes to safety are equally short, within
        ``TIE_TOLERANCE``, and each first link makes progress (see
        :meth:`route_table`), a node has more than one link here.
        ``NetworkSimulation`` with ``split_ties=True`` (the default)
        alternates its agents at such a node between all of these links;
        with ``split_ties=False`` every agent takes the one link of
        :meth:`route_table`, which is one of them.
        The tolerance handles numerical equality, not behavioral route
        equivalence; alternation is an algorithmic policy, not an empirical
        route-choice law.
        Progress requires a strictly smaller computed cost, or fewer
        links at exactly the same computed cost, without a tolerance.

        Arguments:
            target: name of one safe node; ``None`` minimizes cost to any safe node
            routing_policy: "shortest_distance" sums link lengths in m;
                "shortest_free_flow_time" sums length divided by the source
                node's ``hydraulic.speed(0, k)`` in seconds. This hydraulic
                reference time includes the density floor, but excludes
                personal speed limits, congestion and queues. It does not
                predict actual travel time.

        Returns:
            For each node index the tied link indices in creation order;
            one link where the route is unique, and empty for safe nodes
            and nodes without a route.

        Raises:
            ValueError: a reachable node's minimum cost exceeds the
                floating-point range
            RuntimeError: tied routes form a cycle, which the progress
                rule excludes
        """
        return self._route_choices(target, routing_policy=routing_policy)

    def _relax(self, link, d, distance, next_link, heap, cost) -> None:
        candidate = d + cost
        if candidate >= distance[link.source]:
            return
        distance[link.source] = candidate
        next_link[link.source] = link.index
        heapq.heappush(heap, (candidate, link.source))

    def _route_choices(
        self,
        target: str | None = None,
        *,
        routing_policy: str = "shortest_distance",
        costs=None,
    ) -> list[tuple[int, ...]]:
        """Tied next links per node: the first links of all shortest routes.

        A link u -> v is tied for u if d(v) + edge cost equals d(u) within
        ``TIE_TOLERANCE`` and the link makes progress: v is closer to
        safety, or at exactly the same computed cost over fewer links.
        This strict lexicographic ordering excludes cycles independently
        of the tolerance used to identify equal route lengths.

        Returns:
            For each node index the tied link indices in creation order;
            empty for safe nodes and nodes without a route.
        """
        costs = _routing_costs(self, routing_policy) if costs is None else costs
        distance, hops = self._distances(
            target, routing_policy=routing_policy, costs=costs
        )
        choices: list[list[int]] = [[] for _ in self._nodes]
        for link in self._links:
            if _is_tied(link, distance, hops, costs[link.index]):
                choices[link.source].append(link.index)
        _check_acyclic(choices, self._links)
        return [tuple(c) for c in choices]

    def _distances(
        self, target, *, routing_policy: str = "shortest_distance", costs=None
    ) -> tuple[list[float], list[float]]:
        """Minimum selected cost to safety and fewest links on such a route."""
        costs = _routing_costs(self, routing_policy) if costs is None else costs
        metric, unit = (
            ("distance", "m")
            if routing_policy == "shortest_distance"
            else ("cost", "s")
        )
        distance = [math.inf] * len(self._nodes)
        hops = [math.inf] * len(self._nodes)
        overflows: list[tuple[Link, float, float]] = []
        heap = [(0.0, 0, n.index) for n in self._targets(target)]
        for _, _, index in heap:
            distance[index], hops[index] = 0.0, 0
        incoming = self._incoming()
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
                    f"Shortest route {metric} from '{self._nodes[link.source].name}' "
                    f"exceeds the floating-point range at link '{link.name}' "
                    f"(index {link.index}): accumulated {metric} {accumulated!r} {unit} "
                    f"+ link {'length' if unit == 'm' else 'cost'} {cost!r} {unit} is non-finite."
                )
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
        if speed_constant is None:
            speed_constant = hydraulic.LEVEL_SPEED_CONSTANT
        if not 0 < speed_constant < math.inf:
            raise ValueError("speed_constant must be finite and positive.")
        node = Node(
            name=name,
            index=len(self._nodes),
            kind=kind,
            area=area,
            speed_constant=speed_constant,
        )
        self._nodes.append(node)
        self._by_name[name] = node
        return node


def check_routing_policy(routing_policy) -> None:
    if routing_policy in ROUTING_POLICIES:
        return
    valid = ", ".join(repr(p) for p in ROUTING_POLICIES)
    raise ValueError(
        f"routing_policy must be one of {valid}; got {routing_policy!r}."
    )


def _routing_costs(network, routing_policy) -> list[float]:
    check_routing_policy(routing_policy)
    nodes = network.nodes
    return [
        _edge_cost(link, nodes[link.source], routing_policy)
        for link in network.links
    ]


def _edge_cost(link: Link, source: Node, routing_policy: str) -> float:
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


def _area(area, length, width) -> float:
    if area is not None and (length is not None or width is not None):
        raise ValueError("Give either area or length and width, not both.")
    if area is None and (length is None or width is None):
        raise ValueError("Give either area or both length and width.")
    given = (
        {"area": area}
        if area is not None
        else {"length": length, "width": width}
    )
    for name, value in given.items():
        if not 0 < value < math.inf:
            raise ValueError(f"Node area must be positive, got {name} {value}.")
    resolved = float(area if area is not None else length * width)
    if not 0 < resolved < math.inf:
        raise ValueError("Computed node area must be finite and positive.")
    return resolved


def _validate_connection(src, dst, width, kind, length, merge_weight) -> None:
    if kind not in _BOUNDARY_LAYERS:
        raise ValueError(f"Unknown connection kind '{kind}'.")
    if src is dst:
        raise ValueError("A connection needs two different nodes.")
    if src.kind == SAFE and dst.kind == SAFE:
        raise ValueError("Cannot connect two safe nodes.")
    checks = (
        ("width", width, 0 < width < math.inf),
        ("length", length, 0 <= length < math.inf),
        ("merge_weight", merge_weight, 0 < merge_weight < math.inf),
    )
    for name, value, valid in checks:
        if valid:
            continue
        raise ValueError(
            "Width and merge weight must be positive, length non-negative, "
            f"all finite; got {name} {value}."
        )


def _connection_capacity(
    src, dst, width, kind, specific_flow, boundary_layer
) -> float:
    """Resolve hydraulic assumptions into unidirectional capacity (persons/s)."""
    fs = specific_flow
    if fs is None:
        fs = _default_specific_flow(kind, src, dst)
    if not 0 < fs < math.inf:
        raise ValueError(f"specific_flow must be positive, got {fs}.")
    layer = _BOUNDARY_LAYERS[kind] if boundary_layer is None else boundary_layer
    if not 0 <= layer < math.inf:
        raise ValueError(f"boundary_layer: must be >= 0 m, got {layer}.")
    capacity = fs * hydraulic.effective_width(width, layer)
    if capacity <= 0:
        raise ValueError(f"Connection {src.name}-{dst.name} has no capacity.")
    if not math.isfinite(capacity):
        raise ValueError("Connection capacity must be finite.")
    return capacity


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
