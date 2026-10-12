# SPDX-License-Identifier: LGPL-3.0-or-later
"""Routing verification against exhaustive simple paths, independent of Dijkstra.

Exact invariants use integer/dyadic lengths. Tolerance tests are separate:
locally near-equal alternatives need not be mathematically shortest paths.
"""

import itertools
import math
from fractions import Fraction

import pytest

from jupedsim_network import Network, routing
from jupedsim_network.routing import _check_acyclic


def build(edges, rooms=("A", "B", "C"), safes=("s",)):
    net = Network()
    for name in rooms:
        net.add_room(name, area=10.0)
    for name in safes:
        net.add_safe(name)
    for source, target, length in edges:
        net.connect(
            source, target, width=1.0, length=length, bidirectional=False
        )
    return net


def simple_paths(net, node, targets, seen=frozenset()):
    """Enumerate simple paths in the input graph; do not use routing helpers."""
    if node in targets:
        return [()]
    paths = []
    for link in net.links:
        if link.source != node or link.target in seen | {node}:
            continue
        tails = simple_paths(net, link.target, targets, seen | {node})
        paths.extend((link.index, *tail) for tail in tails)
    return paths


def path_length(net, path):
    # Exact arithmetic on the supplied binary floats, including huge lengths.
    return sum((Fraction(net.links[i].length) for i in path), Fraction(0))


def reference(net, targets):
    paths = [simple_paths(net, node.index, targets) for node in net.nodes]
    best = [
        min((path_length(net, p), len(p)) for p in routes) if routes else None
        for routes in paths
    ]
    return paths, best


def permitted_paths(net, choices, node, targets, seen=frozenset()):
    """Explore every choice sequence; a cycle or non-safe dead end fails."""
    assert node not in seen, "Permitted choices contain a cycle"
    if node in targets:
        assert not choices[node]
        return [()]
    assert choices[node], "Permitted choices end before safety"
    paths = []
    for index in choices[node]:
        link = net.links[index]
        assert link.source == node
        tails = permitted_paths(
            net, choices, link.target, targets, seen | {node}
        )
        paths.extend((index, *tail) for tail in tails)
    return paths


def verify_node(net, node, targets, routes, best, choices, table):
    if best is None or node in targets:
        assert choices[node] == ()
        assert table[node] is None
        return
    assert table[node] in choices[node]
    shortest = [p for p in routes if path_length(net, p) == best[0]]
    first = {p[0] for p in shortest}
    assert set(choices[node]) <= first
    # Strictly positive first edges on exact shortest paths make progress.
    positive = {i for i in first if net.links[i].length > 0}
    assert positive <= set(choices[node])
    paths = permitted_paths(net, choices, node, targets)
    assert all(path_length(net, p) == best[0] for p in paths)
    assert all(len(p) < len(net.nodes) for p in paths)


def verify_exact(net, target=None):
    targets = {
        n.index
        for n in net.nodes
        if n.kind == "safe" and (target is None or n.name == target)
    }
    paths, best = reference(net, targets)
    distance, hops = routing.distances(
        net.nodes,
        net.links,
        sorted(targets),
        [link.length for link in net.links],
    )
    choices, table = net.route_choices(target), net.route_table(target)
    assert choices == net.route_choices(target)
    assert table == net.route_table(target)
    _check_acyclic(choices, net.links)
    for link in net.links:
        if link.index in choices[link.source]:
            assert (distance[link.target], hops[link.target]) < (
                distance[link.source],
                hops[link.source],
            )
    for node, optimum in enumerate(best):
        expected = (math.inf, math.inf) if optimum is None else optimum
        assert (distance[node], hops[node]) == expected
        verify_node(net, node, targets, paths[node], optimum, choices, table)


CASES = {
    "unique": [("A", "B", 2), ("B", "s", 3), ("A", "s", 6)],
    "diamond": [("A", "B", 5), ("A", "C", 5), ("B", "s", 5), ("C", "s", 5)],
    "zero_chain": [("A", "B", 0), ("B", "C", 0), ("C", "s", 0)],
    "zero_cycle": [("A", "B", 0), ("B", "A", 0), ("A", "s", 1), ("B", "s", 1)],
    "positive_cycle": [
        ("A", "B", 1),
        ("B", "C", 1),
        ("C", "A", 1),
        ("C", "s", 1),
    ],
    "unreachable_cycle": [("A", "s", 1), ("B", "C", 0), ("C", "B", 0)],
    "parallel": [("A", "s", 2), ("A", "s", 2), ("A", "s", 3)],
    "no_edges": [],
}


@pytest.mark.parametrize("edges", CASES.values(), ids=CASES)
def test_small_network_invariants(edges):
    verify_exact(build(edges))


def test_diamond_identifies_both_ten_metre_routes():
    net = build(CASES["diamond"])
    assert net.route_choices()[0] == (0, 1)
    assert (
        routing.distances(
            net.nodes, net.links, [3], [link.length for link in net.links]
        )[0][0]
        == 10
    )


def test_zero_length_detours_are_intentionally_excluded():
    net = build(CASES["zero_cycle"])
    assert net.route_choices() == [(2,), (3,), (), ()]
    # A->B->s is also exactly shortest, but does not reduce distance or hops.
    paths = simple_paths(net, 0, {3})
    assert (0, 3) in paths
    assert path_length(net, (0, 3)) == 1


@pytest.mark.parametrize("target", [None, "s", "t"])
def test_multiple_safe_destinations(target):
    net = build(
        [("A", "B", 1), ("A", "C", 1), ("B", "s", 1), ("C", "t", 1)],
        safes=("s", "t"),
    )
    verify_exact(net, target)
    expected = {None: (0, 1), "s": (0,), "t": (1,)}
    assert net.route_choices(target)[0] == expected[target]


@pytest.mark.parametrize("length", [0, 1, 0.125])
def test_all_three_room_directed_topologies(length):
    edges = [(a, b, length) for a in "ABC" for b in "ABCs" if a != b]
    for present in itertools.product((False, True), repeat=len(edges)):
        verify_exact(
            build([edge for edge, keep in zip(edges, present) if keep])
        )


@pytest.mark.parametrize("scale", [1e-6, 1.0, 1e6])
@pytest.mark.parametrize("factor, accepted", [(0.5, True), (2.0, False)])
def test_tolerance_is_local_numerical_equality(scale, factor, accepted):
    delta = factor * 1e-9 * max(1.0, scale)
    net = build([("A", "s", scale), ("A", "s", scale + delta)])
    assert net.route_choices()[0] == ((0, 1) if accepted else (0,))
    assert net.route_table()[0] == 0
    assert path_length(net, (1,)) > path_length(net, (0,))


def test_floating_point_rounding_is_a_tie():
    net = build([("A", "B", 0.1), ("B", "s", 0.2), ("A", "s", 0.3)])
    assert net.route_choices()[0] == (0, 2)


def test_tie_order_is_creation_order_and_repeatable():
    edges = CASES["diamond"]
    for ordered in (edges, list(reversed(edges))):
        net = build(ordered)
        choices = net.route_choices()[0]
        assert choices == tuple(sorted(choices))
        names = {net.links[i].name for i in choices}
        assert names == {"A->B", "A->C"}
        verify_exact(net)


def test_cycle_guard_rejects_cycles_and_accepts_parallel_edges():
    net = build([("A", "B", 0), ("B", "A", 0), ("A", "B", 0)])
    with pytest.raises(RuntimeError, match="cycle"):
        _check_acyclic([(0,), (1,), (), ()], net.links)
    _check_acyclic([(0, 2), (), (), ()], net.links)


@pytest.mark.parametrize("method", ["route_choices", "route_table"])
def test_tolerance_cycle_has_usable_routes(method):
    net = build(
        [
            ("A", "s", 1 + 1.5e-9),
            ("B", "Y", 0.75e-9),
            ("C", "X", 0),
            ("X", "Y", 0),
            ("Y", "s", 1),
            ("A", "C", 1.5e-9),
            ("B", "A", 0),
            ("C", "B", 0),
        ],
        rooms=("A", "B", "C", "X", "Y"),
    )
    assert all(simple_paths(net, n.index, {5}) for n in net.nodes)
    result = getattr(net, method)()
    choices = (
        result
        if method == "route_choices"
        else [() if link is None else (link,) for link in result]
    )
    for node in net.nodes:
        permitted_paths(net, choices, node.index, {5})


@pytest.mark.parametrize("method", ["route_choices", "route_table"])
def test_reachable_route_with_overflowing_distance(method):
    net = build([("A", "B", 1e308), ("B", "s", 1e308)], rooms=("A", "B"))
    paths = simple_paths(net, 0, {2})
    assert paths == [(0, 1)]
    assert path_length(net, paths[0]) > Fraction(1e308)
    with pytest.raises(
        ValueError,
        match="Shortest route distance from 'A'.*floating-point range",
    ) as error:
        getattr(net, method)()
    assert "link 'A->B' (index 0)" in str(error.value)
    assert "accumulated distance 1e+308 m + link length 1e+308 m" in str(
        error.value
    )


@pytest.mark.parametrize("method", ["route_choices", "route_table"])
@pytest.mark.parametrize("alternative", [1.0, 1.5e308])
@pytest.mark.parametrize("via_room", [False, True])
def test_overflowing_detour_does_not_hide_finite_shortest_route(
    method, alternative, via_room
):
    detour = [("A", "B", 1e308), ("B", "s", 1e308)]
    finite = (
        [("A", "C", 0), ("C", "s", alternative)]
        if via_room
        else [("A", "s", alternative)]
    )
    # With C at 1.5e308, B's overflowing candidate is explored before the
    # finite alternative to A is discovered through C.
    net = build(detour + finite)
    result = getattr(net, method)()[0]
    assert result == ((2,) if method == "route_choices" else 2)


def test_progress_uses_exact_distance_before_hop_count():
    net = build(
        [("A", "B", 5e-10), ("B", "s", 1), ("A", "s", 1 + 5e-10), ("B", "A", 0)]
    )
    # A and B each have a one-hop shortest route. A->B still reduces distance;
    # B->A must be excluded even though its route length is within tolerance.
    assert net.route_choices()[0] == (0, 2)
    assert net.route_choices()[1] == (1,)
