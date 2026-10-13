# SPDX-License-Identifier: LGPL-3.0-or-later
"""Random networks for the property tests, and the invariant checks.

``specs()`` draws a plain spec (nodes, connections, populations and
simulation keywords) that hypothesis can shrink and print; ``build()``
turns it into a network and populations. Every spec is valid by
construction: every node reaches a safe node, start nodes hold at most
0.9 of ``max_density``, and a ``target`` is used only if the start node
reaches it.

The checks take a ``SimulationResult`` and assert what the model
guarantees exactly; the only slack is the float slack the code itself
uses, named at each check.
"""

import math
import warnings

import numpy as np
from hypothesis import strategies as st

from jupedsim_network import (
    LogNormal,
    Network,
    NetworkSimulation,
    Population,
    Triangular,
    Uniform,
)
from jupedsim_network import simulation as simulation_module
from jupedsim_network.routing import TIE_TOLERANCE

COUNTERFLOW = ("independent", "estimate", "bounding")
AREAS = (4.0, 10.0, 20.0, 40.0, 100.0)
WIDTHS = (0.6, 0.8, 1.0, 1.2, 2.0, 4.0)
LENGTHS = (0.0, 0.0, 1.0, 2.0, 3.0, 10.0, 0.1, 0.2, 0.3)
MERGE_WEIGHTS = (0.5, 1.0, 1.0, 2.0)

# Limits of the PR profile and of the scheduled job (``wide``).
_LIMITS = {
    False: dict(
        rooms=(2, 6),
        stairs=(0, 1),
        safes=(1, 2),
        extra=1,
        pops=(1, 3),
        agents=200,
        area_factors=((1.0,), (1.5,)),
        speeds=("fixed", "uniform"),
        pres=("zero", "uniform"),
        dts=(0.5, 0.25),
        max_densities=(2.0, 2.75, 3.5),
        t_max=1800.0,
    ),
    True: dict(
        rooms=(2, 10),
        stairs=(0, 2),
        safes=(1, 3),
        extra=2,
        pops=(1, 5),
        agents=600,
        area_factors=((1.0,), (1.5,), (1.0, 1.5, 2.0)),
        speeds=("fixed", "uniform", "triangular"),
        pres=("zero", "uniform", "lognormal"),
        dts=(0.5, 0.25, 0.1),
        max_densities=(1.5, 2.0, 2.75, 3.5),
        t_max=3600.0,
    ),
}


@st.composite
def specs(draw, wide=False, targets=None):
    """A random scenario as a plain dict.

    Arguments:
        wide: use the limits of the scheduled job
        targets: ``False`` gives every population ``target=None``,
            ``True`` lets populations draw a reachable safe node,
            ``None`` draws the mode
    """
    lim = _LIMITS[wide]
    spec = dict(
        seed=draw(st.integers(0, 2**16)),
        dt=draw(st.sampled_from(lim["dts"])),
        max_density=draw(st.sampled_from(lim["max_densities"])),
        supply_reduction=draw(st.booleans()),
        split_ties=draw(st.booleans()),
        t_max=lim["t_max"],
    )
    if targets is None:
        targets = draw(st.booleans())
    # Counterflow needs two safe nodes that agents head for.
    spec.update(draw(_graphs(lim, min_safes=2 if targets else 1)))
    spec["populations"] = draw(_populations(spec, lim, targets))
    return spec


@st.composite
def graphs(draw, wide=False):
    """Nodes and connections only, for route-table properties."""
    return draw(_graphs(_LIMITS[wide]))


@st.composite
def _graphs(draw, lim, min_safes=1):
    n_rooms = draw(st.integers(*lim["rooms"]))
    n_stairs = draw(st.integers(*lim["stairs"]))
    n_safe = draw(st.integers(max(min_safes, lim["safes"][0]), lim["safes"][1]))
    rooms = [[f"r{i}", draw(st.sampled_from(AREAS))] for i in range(n_rooms)]
    stairs = [
        [
            f"t{i}",
            draw(st.sampled_from(AREAS)),
            draw(st.sampled_from((0.17, 0.18, 0.19))),
            draw(st.sampled_from((0.28, 0.3, 0.33))),
        ]
        for i in range(n_stairs)
    ]
    safes = [f"s{i}" for i in range(n_safe)]
    inside = draw(st.permutations([r[0] for r in rooms + stairs]))
    edges = []
    # Tree towards safety: the first node links to a safe node, each later
    # node to a safe node or to an earlier node, so every node reaches one.
    for i, node in enumerate(inside):
        options = safes + [n for n in inside[:i] if _joinable(node, n)]
        if i == 0 or not options:
            options = safes
        edges.append((node, draw(st.sampled_from(options))))
    if min_safes > 1 and len(inside) > 1:
        # The last node also leads to another exit than the first node,
        # so routes to the two exits run through the graph both ways.
        other = [s for s in safes if s != edges[0][1]]
        edges.append((inside[-1], draw(st.sampled_from(other))))
    extra = draw(st.integers(0, lim["extra"] * len(inside)))
    for _ in range(extra):
        a = draw(st.sampled_from(inside))
        b = draw(st.sampled_from(inside + safes))
        if a == b or not _joinable(a, b):
            continue
        if (a, b) in edges or (b, a) in edges:
            continue
        edges.append((a, b))
    connections = [draw(_connection(a, b, safes)) for a, b in edges]
    return dict(
        rooms=rooms, stairs=stairs, safes=safes, connections=connections
    )


def _joinable(a, b) -> bool:
    """Stair-stair links are avoided: their capacity depends on direction."""
    return not (a.startswith("t") and b.startswith("t"))


@st.composite
def _connection(draw, a, b, safes):
    stair = a.startswith("t") or b.startswith("t")
    kind = "stair" if stair else draw(st.sampled_from(("door", "opening")))
    return dict(
        source=a,
        target=b,
        width=draw(st.sampled_from(WIDTHS)),
        kind=kind,
        length=draw(st.sampled_from(LENGTHS)),
        bidirectional=b not in safes and draw(st.integers(0, 9)) < 7,
        merge_weight=draw(st.sampled_from(MERGE_WEIGHTS)),
    )


@st.composite
def _populations(draw, spec, lim, targets):
    net = build_network(spec)
    area = {n.name: n.area for n in net.nodes}
    room = dict(
        free={n: 0.9 * spec["max_density"] * area[n] for n in _inside(spec)},
        left=lim["agents"],
        factors=draw(st.sampled_from(lim["area_factors"])),
    )
    starts = []
    crossings = _crossings(net, spec) if targets else []
    if crossings:
        # Two groups that walk one two-way connection in opposite directions.
        u, s_u, v, s_v = draw(st.sampled_from(crossings))
        starts += [(u, s_u), (v, s_v)]
    lo, hi = lim["pops"]
    for _ in range(
        draw(st.integers(max(lo - len(starts), 0), hi - len(starts)))
    ):
        node = draw(st.sampled_from(sorted(room["free"])))
        starts.append((node, draw(_target(net, node, spec["safes"], targets))))
    pops = [draw(_population(lim, room, n, t)) for n, t in starts]
    pops = [p for p in pops if p is not None]
    if not pops:
        # Every start node is at least 4 m² and max_density at least 1.5.
        node = _inside(spec)[0]
        pops.append(dict(node=node, count=1, area_factor=1.0, target=None))
    return pops


@st.composite
def _population(draw, lim, room, node, target):
    """One population in ``node``, within the space and agents left."""
    af = draw(st.sampled_from(room["factors"]))
    most = min(int(room["free"][node] / af), room["left"])
    if most < 1:
        return None
    # Often as many as fit, so that nodes fill up.
    count = draw(st.one_of(st.just(most), st.integers(1, most)))
    room["free"][node] -= count * af
    room["left"] -= count
    return dict(
        node=node,
        count=count,
        speed=draw(st.sampled_from(lim["speeds"])),
        pre_movement=draw(st.sampled_from(lim["pres"])),
        start_distance=draw(st.sampled_from(("zero", "uniform"))),
        area_factor=af,
        target=target,
    )


def _crossings(net, spec):
    """(u, safe, v, safe) where routes cross one two-way connection u-v."""
    tables = {s: net.route_table(s) for s in spec["safes"]}
    found = []
    for i, j in pairs(spec, net):
        u, v = net.links[i].source, net.links[i].target
        to_u = [s for s, t in tables.items() if t[v] == j]
        to_v = [s for s, t in tables.items() if t[u] == i]
        names = net.nodes[u].name, net.nodes[v].name
        found += [(names[0], a, names[1], b) for a in to_v for b in to_u]
    return found


@st.composite
def _target(draw, net, node, safes, targets):
    """None, or a safe node that ``node`` reaches; often the farthest one.

    Agents sent to their farthest exit cross the others, so two-way
    connections see counterflow.
    """
    if not targets:
        return None
    u = net.node(node).index
    reach = {s: oracle_distances(net, s)[0][u] for s in safes}
    reach = {s: d for s, d in reach.items() if math.isfinite(d)}
    far = max(reach, key=reach.get)
    return draw(st.sampled_from([far, far, None, *sorted(reach)]))


def _inside(spec):
    return [r[0] for r in spec["rooms"]] + [s[0] for s in spec["stairs"]]


_SPEED = {
    "fixed": 1.2,
    "uniform": Uniform(0.6, 1.4),
    "triangular": Triangular(0.6, 1.0, 1.4),
}
_PRE = {
    "zero": 0.0,
    "uniform": Uniform(0.0, 30.0),
    "lognormal": LogNormal(20.0, 10.0, upper=120.0),
}
_START = {"zero": 0.0, "uniform": Uniform(0.0, 10.0)}


def build_network(spec, one_way=False) -> Network:
    """The network of ``spec``.

    With ``one_way``, every two-way connection is replaced by two one-way
    connections, source to target and back, at the same place in the
    order: the same links, without the shared door.
    """
    net = Network()
    for name, area in spec["rooms"]:
        net.add_room(name, area=area)
    for name, area, riser, tread in spec["stairs"]:
        net.add_stair(name, area=area, riser=riser, tread=tread)
    for name in spec["safes"]:
        net.add_safe(name)
    for c in spec["connections"]:
        kw = {k: c[k] for k in ("width", "kind", "length", "merge_weight")}
        if one_way and c["bidirectional"]:
            net.connect(c["source"], c["target"], bidirectional=False, **kw)
            net.connect(c["target"], c["source"], bidirectional=False, **kw)
            continue
        net.connect(
            c["source"], c["target"], bidirectional=c["bidirectional"], **kw
        )
    return net


def build_populations(spec) -> list[Population]:
    return [
        Population(
            p["node"],
            p["count"],
            speed=_SPEED[p.get("speed", "fixed")],
            pre_movement=_PRE[p.get("pre_movement", "zero")],
            start_distance=_START[p.get("start_distance", "zero")],
            area_factor=p["area_factor"],
            target=p["target"],
        )
        for p in spec["populations"]
    ]


def simulation(spec, counterflow, net=None) -> NetworkSimulation:
    """The simulation of ``spec``; the split_ties warning is silenced."""
    net = net or build_network(spec)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        return NetworkSimulation(
            net,
            build_populations(spec),
            dt=spec["dt"],
            t_max=spec["t_max"],
            max_density=spec["max_density"],
            supply_reduction=spec["supply_reduction"],
            split_ties=spec["split_ties"],
            counterflow=counterflow,
        )


def same_result(r1, r2) -> bool:
    return (
        np.array_equal(r1.exit_times, r2.exit_times, equal_nan=True)
        and np.array_equal(r1.pre_movement_times, r2.pre_movement_times)
        and np.array_equal(r1.times, r2.times)
        and np.array_equal(r1.node_occupancy, r2.node_occupancy)
        and np.array_equal(r1.link_flow, r2.link_flow)
    )


def pairs(spec, net) -> list[tuple[int, int]]:
    """Link indices of each two-way connection of ``spec``.

    Taken from the spec and the link names, not from the network, so a
    network that loses its pairs is still checked as a pair.
    """
    index = {lk.name: lk.index for lk in net.links}
    return [
        (
            index[f"{c['source']}->{c['target']}"],
            index[f"{c['target']}->{c['source']}"],
        )
        for c in spec["connections"]
        if c["bidirectional"]
    ]


def two_way_flow(result, pairs) -> bool:
    """Whether some pair passed agents in both directions in the run."""
    used = result.link_flow.sum(axis=0) > 0
    return any(used[i] and used[j] for i, j in pairs)


# Invariants of one run ------------------------------------------------------


def check_conservation(result, net):
    """P1: no agent is lost or created (exact; 1e-9 s for rounded times)."""
    occ, flow = result.node_occupancy, result.link_flow
    n = result.exit_times.size
    out = np.array(
        [np.sum(result.exit_times <= t + 1e-9) for t in result.times]
    )
    assert np.array_equal(occ.sum(axis=1) + out, np.full(occ.shape[0], n)), (
        "P1: heads inside plus agents out differ from the agent count"
    )
    source = np.array([lk.source for lk in net.links], dtype=int)
    target = np.array([lk.target for lk in net.links], dtype=int)
    safe = np.array([nd.kind == "safe" for nd in net.nodes])
    k = len(net.nodes)
    inflow = np.zeros((flow.shape[0], k), dtype=int)
    outflow = np.zeros((flow.shape[0], k), dtype=int)
    for i in range(len(net.links)):
        inflow[:, target[i]] += flow[:, i]
        outflow[:, source[i]] += flow[:, i]
    change = np.diff(occ, axis=0)
    balance = (inflow - outflow)[1:]
    assert np.array_equal(change[:, ~safe], balance[:, ~safe]), (
        "P1: occupancy change differs from inflow - outflow"
    )
    assert not occ[:, safe].any(), "P1: a safe node holds agents"
    assert inflow[:, safe].sum() == result.evacuated, (
        "P1: flow into safe nodes differs from evacuated"
    )
    assert np.isnan(result.exit_times).sum() == occ[-1].sum(), (
        "P1: nan exit times differ from agents left inside"
    )


def max_window_excess(flow, rate) -> np.ndarray:
    """Largest ``passages - rate * steps`` over all step windows, per column.

    O(K): the excess of window (i, j] is X_j - X_i with
    X_j = cumsum(flow)_j - rate * j, maximised against the running
    minimum of X over i < j.
    """
    flow = np.asarray(flow, dtype=float)
    cs = np.vstack([np.zeros(flow.shape[1]), np.cumsum(flow, axis=0)])
    x = cs - np.outer(np.arange(cs.shape[0]), rate)
    lowest = np.minimum.accumulate(x, axis=0)
    return (x[1:] - lowest[:-1]).max(axis=0, initial=-np.inf)


def check_link_bound(result, net, dt):
    """P2: no link passes more than 1 + C t agents in any interval t.

    Slack 1e-9 agents per step: the code floors ``budget + 1e-9``.
    """
    flow = result.link_flow[1:]
    if not flow.size:
        return
    rate = np.array([lk.capacity for lk in net.links]) * dt
    excess = max_window_excess(flow, rate)
    slack = 1.0 + 1e-9 * flow.shape[0]
    worst = int(np.argmax(excess))
    assert excess[worst] <= slack, (
        f"P2: link {net.links[worst].name} passes {excess[worst]:.6f} agents "
        "beyond C t"
    )


def check_pair_bound(result, net, dt, pairs):
    """P3: both links of a pair together pass at most 1 + C t agents.

    Under "bounding" and "estimate" only; same slack as P2.
    """
    flow = result.link_flow[1:]
    if not pairs or not flow.size:
        return
    joint = np.stack([flow[:, i] + flow[:, j] for i, j in pairs], axis=1)
    rate = np.array([net.links[i].capacity for i, _ in pairs]) * dt
    excess = max_window_excess(joint, rate)
    slack = 1.0 + 1e-9 * flow.shape[0]
    worst = int(np.argmax(excess))
    assert excess[worst] <= slack, (
        f"P3: pair {net.links[pairs[worst][0]].name} passes "
        f"{excess[worst]:.6f} agents beyond C t"
    )


def check_density(result, net, max_density, area_factor):
    """P4a: max_density is never exceeded, with one area factor per run.

    Slack 1e-9 agents (area units), as in ``_fits``.
    """
    area = np.array([nd.area for nd in net.nodes])
    inside = np.isfinite(area)
    load = area_factor * result.node_occupancy[:, inside]
    over = load - max_density * area[inside]
    assert over.max(initial=-np.inf) <= 1e-9, (
        f"P4: a node exceeds max_density by {over.max():.6f}"
    )


def check_exit_times(result, sim):
    """P10: exit times lie on the dt grid, after the pre-movement time."""
    dt, t_max = sim.dt, sim.t_max
    out = result.exit_times
    done = np.isfinite(out)
    steps = out[done] / dt
    assert np.allclose(steps, np.round(steps), rtol=0, atol=1e-6), (
        "P10: an exit time is not a multiple of dt"
    )
    early = out[done] < result.pre_movement_times[done] + dt - 1e-9
    assert not early.any(), "P10: an agent left before pre-movement + dt"
    if done.all():
        assert result.evacuation_time == np.max(out, initial=0.0), (
            "P10: evacuation_time is not the last exit time"
        )
        return
    assert math.isnan(result.evacuation_time), "P10: unfinished run is not nan"
    assert result.evacuated < out.size, "P10: unfinished run evacuated all"
    assert result.times[-1] >= t_max - 1e-9, "P10: run stopped before t_max"


def area_load_monitor(mp, worst):
    """P4b: track the area-weighted load after every step.

    Coupled to the private ``_Run``: wraps ``_Run._step`` through the
    pytest ``MonkeyPatch`` ``mp`` and reads the agents' node, state and
    area factor, as ``scripts/figures`` does (decision D5). Records the
    largest ``load - max_density * area`` of a non-safe node in
    ``worst[0]``; the code allows 1e-9.
    """
    step = simulation_module._Run._step

    def wrapped(self, t):
        flow = step(self, t)
        a = self.agents
        inside = a.state != simulation_module._SAFE
        load = self._load(a.node[inside], a.area[inside])
        over = np.where(
            self.safe, -np.inf, load - self.sim.max_density * self.area
        )
        worst[0] = max(worst[0], float(over.max(initial=-np.inf)))
        return flow

    mp.setattr(simulation_module._Run, "_step", wrapped)


def area_factor_of(spec) -> float:
    """The one area factor of every population (PR profile)."""
    factors = {p["area_factor"] for p in spec["populations"]}
    assert len(factors) == 1, f"mixed area factors {factors}"
    return factors.pop()


# Route-table oracle ---------------------------------------------------------


def oracle_distances(net, target):
    """Shortest distance and fewest links to safety, computed afresh.

    Distances by Bellman-Ford; hops by a Dijkstra on (distance, hops) with
    exact float comparison, as ``routing.distances`` defines them.
    """
    n = len(net.nodes)
    goals = [
        nd.index
        for nd in net.nodes
        if nd.kind == "safe" and (target is None or nd.name == target)
    ]
    dist = [math.inf] * n
    for g in goals:
        dist[g] = 0.0
    for _ in range(n):
        for lk in net.links:
            dist[lk.source] = min(dist[lk.source], dist[lk.target] + lk.length)
    hops = [math.inf] * n
    for g in goals:
        hops[g] = 0
    for _ in range(n):
        for lk in net.links:
            hops[lk.source] = _fewest_hops(lk, dist, hops)
    return dist, hops


def _fewest_hops(link, dist, hops):
    """Hops of ``link.source``, lowered if ``link`` gives (d, h) smaller."""
    key = (dist[link.target] + link.length, hops[link.target] + 1)
    if key < (dist[link.source], hops[link.source]):
        return key[1]
    return hops[link.source]


def tied(link, dist, hops) -> bool:
    """The tie rule of ``routing.route_choices``, as documented."""
    here, there = dist[link.source], dist[link.target]
    if not math.isfinite(here):
        return False
    tol = TIE_TOLERANCE
    if not math.isclose(there + link.length, here, rel_tol=tol, abs_tol=tol):
        return False
    return (there, hops[link.target]) < (here, hops[link.source])


def tied_distance(link, dist) -> bool:
    """``link`` starts a shortest route of its source, up to rounding."""
    tol = TIE_TOLERANCE
    there, here = dist[link.target] + link.length, dist[link.source]
    return math.isclose(there, here, rel_tol=tol, abs_tol=tol)
