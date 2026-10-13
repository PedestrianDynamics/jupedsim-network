# SPDX-License-Identifier: LGPL-3.0-or-later
"""The route tree of a network (design §9); imports no Textual.

There are no coordinates, so the network is shown as the routes the model
takes: each safe node is a root, and a node's children are the nodes
whose route leads through it. :func:`build` calls the package (on the
engine thread); :func:`lines` only formats what it returned.

With ``split_ties`` (the default) the model alternates agents between
tied links (:meth:`Network.route_choices`), so the tree marks such a node
and names every tied link; none of them is listed as off-route. Without
it the model takes the first link (:meth:`Network.route_table`) and the
tree shows that route only.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Link:
    index: int
    name: str
    kind: str
    capacity: float


@dataclass(frozen=True)
class Tree:
    """One route tree: towards ``target``, or the nearest safe node."""

    target: str | None
    roots: tuple[int, ...]
    children: dict[int, tuple[int, ...]]
    via: dict[int, int]
    ties: dict[int, tuple[int, ...]]
    no_route: tuple[int, ...]


@dataclass(frozen=True)
class Routes:
    """The trees of a simulation and the facts the lines need."""

    nodes: tuple[tuple[str, str, str], ...]  # name, kind, area text
    links: tuple[Link, ...]
    trees: tuple[Tree, ...]
    off_route: tuple[int, ...]
    routing_policy: str = "shortest_distance"


def build(sim) -> Routes:
    """The route trees of ``sim``, one per distinct population target."""
    from jupedsim_network.network import SAFE

    net = sim.network
    targets = tuple(dict.fromkeys(pop.target for pop in sim.populations))
    trees = tuple(
        _tree(net, t, sim.split_ties, SAFE, sim.routing_policy)
        for t in targets or (None,)
    )
    used = {link for tree in trees for link in _used(tree)}
    nodes = tuple(
        (n.name, n.kind, "" if n.kind == SAFE else f"{n.area:g} m²")
        for n in net.nodes
    )
    links = tuple(
        Link(link.index, link.name, link.kind, float(link.capacity))
        for link in net.links
    )
    off = tuple(link.index for link in net.links if link.index not in used)
    return Routes(nodes, links, trees, off, sim.routing_policy)


def _used(tree: Tree) -> set[int]:
    return set(tree.via.values()) | {i for t in tree.ties.values() for i in t}


def _tree(net, target, split: bool, safe: str, routing_policy: str) -> Tree:
    table = net.route_table(target, routing_policy=routing_policy)
    choices = net.route_choices(target, routing_policy=routing_policy)
    children: dict[int, list[int]] = {}
    via = {}
    for node, link in enumerate(table):
        if link is None:
            continue
        via[node] = link
        children.setdefault(net.links[link].target, []).append(node)
    ties = {
        node: tuple(tied)
        for node, tied in enumerate(choices)
        if split and len(tied) > 1
    }
    roots = tuple(
        n.index
        for n in net.nodes
        if n.kind == safe and (target is None or n.name == target)
    )
    no_route = tuple(
        n.index for n in net.nodes if n.kind != safe and table[n.index] is None
    )
    return Tree(
        target,
        roots,
        {k: tuple(v) for k, v in children.items()},
        via,
        ties,
        no_route,
    )


def lines(routes: Routes, labels: dict[str, str] | None = None) -> list[str]:
    """The tree as text; ``labels`` adds text after a node, by name."""
    labels = labels or {}
    out: list[str] = []
    if routes.routing_policy != "shortest_distance":
        out.append(f"Routing policy: {routes.routing_policy}")
    for tree in routes.trees:
        if len(routes.trees) > 1 or tree.target is not None:
            where = tree.target or "the nearest safe node"
            out.append(f"Routes to {where}:")
        for root in tree.roots:
            out.append(_node_text(routes, root, labels))
            _walk(routes, tree, root, "", labels, out)
        if tree.no_route:
            names = ", ".join(routes.nodes[i][0] for i in tree.no_route)
            out.append(f"no route to safety: {names}")
    if routes.off_route:
        names = ", ".join(_link_name(routes.links[i]) for i in routes.off_route)
        out.append(f"not on a route: {names}")
    return out


def _walk(routes, tree, node, prefix, labels, out) -> None:
    kids = tree.children.get(node, ())
    for n, child in enumerate(kids):
        last = n == len(kids) - 1
        branch, more = ("└─", "   ") if last else ("├─", "│  ")
        out.append(f"{prefix}{branch}◀ {_via(routes, tree.via[child])}")
        out.append(f"{prefix}{more}{_node_text(routes, child, labels)}")
        tied = tree.ties.get(child)
        if tied:
            names = ", ".join(_link_name(routes.links[i]) for i in tied)
            out.append(f"{prefix}{more}  ties: split between {names}")
        _walk(routes, tree, child, prefix + more, labels, out)


def _node_text(routes: Routes, index: int, labels: dict[str, str]) -> str:
    name, kind, area = routes.nodes[index]
    text = "  ".join(part for part in (name, kind, area) if part)
    label = labels.get(name)
    return f"{text}   {label}" if label else text


def _via(routes: Routes, index: int) -> str:
    link = routes.links[index]
    return (
        f"{_link_name(link)}, {link.kind}, capacity "
        f"{link.capacity:.2f} persons/s"
    )


def _link_name(link: Link) -> str:
    return f"L{link.index} {link.name}"
