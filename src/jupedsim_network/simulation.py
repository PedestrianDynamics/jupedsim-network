# SPDX-License-Identifier: LGPL-3.0-or-later
"""Time-stepped agent network model for estimating evacuation times.

Each time step of length ``dt`` is processed synchronously:

1. Node densities are computed from the agents in each node at the start of
   the step, weighted by each agent's area factor.
2. Agents whose pre-movement time has elapsed start walking.
3. Walking agents cover ``min(v_max, k (1 - 0.266 D)) * dt`` towards the
   constriction of their next link; on arrival they join its queue.
4. Each link passes up to ``capacity * dt`` agents from the front of its
   queue, keeping the fractional remainder for the next step; a link that
   has been idle for at least ``1 / capacity`` lets the first arriving agent
   through at once; no link passes more than ``1 + capacity * t`` agents in
   any interval ``t``. Above the peak-flow density a node accepts a share
   of the summed capacity of its incoming links that have a queue in this
   step; the share falls linearly to zero at ``max_density``, which the
   node never exceeds. A node keeps unused supply, whether or not an
   agent was ready to pass, up to one step of inflow, one agent or the
   largest area factor waiting at its links, whichever is largest. When
   several links compete for what a node accepts, it is shared in
   proportion to their merge weights.
5. All transfers are applied at once, so the result does not depend on the
   order in which links or nodes are processed. Agents that join the same
   queue at the same interpolated time are served in the order in which they
   were created, that is, in population order. Individual exit times
   therefore depend on the order of the population list. Aggregate results
   can depend on it too, when tied agents differ in speed, area factor or
   target.

Agents move on to the next link of their route. Where several routes to
safety are equally short (up to floating-point rounding), the agents
taking a decision at that node alternate between the tied links in
creation order: at the start in population order, later in order of
arrival at the link they passed. Which agent takes which link therefore
also depends on population order.

Space freed by agents leaving a node becomes available in the next step.
"""

import warnings
from dataclasses import dataclass, field

import numpy as np

from jupedsim_network import hydraulic
from jupedsim_network.network import SAFE, Network
from jupedsim_network.sampling import Distribution, as_distribution

_WAITING = 0
_WALKING = 1
_QUEUED = 2
_SAFE = 3


@dataclass(frozen=True)
class Population:
    """A group of agents placed in one node.

    Plain numbers are accepted wherever a distribution is expected.

    Attributes:
        node: name of the start node
        count: number of agents, rounded to an integer when sampled
        speed: maximum (free-walking) speed in m/s
        pre_movement: time in s before the agent starts moving
        start_distance: extra distance in m walked in the start node
        area_factor: space taken relative to an average adult; counts
            towards node density and capacity
        target: name of a safe node to head for; ``None`` for the nearest
    """

    node: str
    count: Distribution | float
    speed: Distribution | float = 1.2
    pre_movement: Distribution | float = 0.0
    start_distance: Distribution | float = 0.0
    area_factor: float = 1.0
    target: str | None = None


@dataclass(frozen=True)
class SimulationResult:
    """Outcome of one realisation.

    ``evacuation_time`` is ``nan`` if not all agents reached safety before
    ``t_max``. ``exit_times`` is ``nan`` for agents that did not.
    ``node_occupancy[i, n]`` counts agents in node ``n`` at ``times[i]``;
    ``link_flow[i, l]`` counts agents that passed link ``l`` during the step
    ending at ``times[i]``.
    """

    evacuation_time: float
    exit_times: np.ndarray
    pre_movement_times: np.ndarray
    times: np.ndarray
    node_occupancy: np.ndarray
    link_flow: np.ndarray
    node_names: tuple[str, ...]
    link_names: tuple[str, ...]

    @property
    def evacuated(self) -> int:
        return int(np.isfinite(self.exit_times).sum())


@dataclass(frozen=True)
class MonteCarloResult:
    """Evacuation times of repeated realisations (``nan`` = incomplete).

    An incomplete run is right-censored at ``t_max``: its evacuation time is
    only known to exceed ``t_max``. ``incomplete`` counts these runs.
    """

    evacuation_times: np.ndarray
    agent_counts: np.ndarray
    t_max: float | None = None

    @property
    def complete(self) -> np.ndarray:
        return self.evacuation_times[np.isfinite(self.evacuation_times)]

    @property
    def incomplete(self) -> int:
        return int(self.evacuation_times.size - self.complete.size)

    def quantile(self, q):
        """Linear quantile (numpy default) over all runs.

        Incomplete runs rank above every finished run. A quantile whose
        interpolation involves an incomplete run is only bounded below and
        is returned as ``inf``. Issues a ``RuntimeWarning`` when any run is
        incomplete.
        """
        if self.incomplete == 0:
            return np.quantile(self.complete, q)
        times = self.evacuation_times
        finished = np.isfinite(times)
        sentinel = np.max(times, where=finished, initial=0.0)
        value = np.quantile(np.where(finished, times, sentinel), q)
        upper = np.ceil((times.size - 1) * np.asarray(q))
        warnings.warn(self._censoring_message(), RuntimeWarning, stacklevel=2)
        return np.where(upper >= self.complete.size, np.inf, value)[()]

    def _censoring_message(self) -> str:
        n, m = self.evacuation_times.size, self.incomplete
        when = "" if self.t_max is None else f" before t_max = {self.t_max:g} s"
        head = f"{m} of {n} runs did not finish{when}; "
        if m == n:
            return head + "all quantiles are inf."
        k = n - m - 1
        return (
            head
            + f"quantiles above q = {k}/{n - 1} (about {k / (n - 1):.3f}) are inf."
        )


class NetworkSimulation:
    """Runs the network model for one scenario.

    Arguments:
        network: the node-link graph
        populations: agent groups
        dt: time step in s
        t_max: time in s after which a run stops
        max_density: hard limit of agents per m² in a node
        supply_reduction: reduce link capacity when the target node is
            above the peak-flow density
        split_ties: split agents evenly between equally short routes;
            ``False`` sends all of them along the first route found and
            issues a ``UserWarning`` if a population can reach a tie
    """

    def __init__(
        self,
        network: Network,
        populations: list[Population],
        *,
        dt: float = 0.5,
        t_max: float = 3600.0,
        max_density: float = 2.75,
        supply_reduction: bool = True,
        split_ties: bool = True,
    ) -> None:
        if dt <= 0 or t_max <= 0:
            raise ValueError("dt and t_max must be positive.")
        if not 0 < max_density < hydraulic.JAM_DENSITY:
            raise ValueError(
                f"max_density must be in (0, {hydraulic.JAM_DENSITY:.2f})."
            )
        if not populations:
            raise ValueError("At least one population is required.")
        self.network = network
        self.populations = list(populations)
        self.dt = dt
        self.t_max = t_max
        self.max_density = max_density
        self.supply_reduction = supply_reduction
        self.split_ties = split_ties
        self._routes = _route_tables(network, self.populations)
        self._choices = {t: network._route_choices(t) for t in self._routes}
        for pop in self.populations:
            _check_area_factor(self, pop)
        if not split_ties:
            _warn_unsplit_ties(self)

    def run(self, seed=None, *, record: bool = True) -> SimulationResult:
        """Run one realisation.

        Arguments:
            seed: seed or ``numpy.random.Generator``
            record: keep node occupancy and link flow time series
        """
        rng = np.random.default_rng(seed)
        return _Run(self, rng, record).execute()

    def run_many(self, runs: int, seed=None) -> MonteCarloResult:
        """Run independent realisations with seeds derived from ``seed``."""
        if runs < 1:
            raise ValueError("runs must be at least 1.")
        seeds = np.random.SeedSequence(seed).spawn(runs)
        results = [self.run(s, record=False) for s in seeds]
        return MonteCarloResult(
            evacuation_times=np.array([r.evacuation_time for r in results]),
            agent_counts=np.array([len(r.exit_times) for r in results]),
            t_max=self.t_max,
        )


def _route_tables(network, populations) -> dict:
    tables = {}
    for pop in populations:
        if pop.target not in tables:
            tables[pop.target] = network.route_table(pop.target)
        node = network.node(pop.node)
        if node.kind == SAFE:
            raise ValueError(f"Population starts in safe node '{pop.node}'.")
        if tables[pop.target][node.index] is None:
            raise ValueError(f"No route from '{pop.node}' to safety.")
    return tables


def _check_area_factor(sim, pop) -> None:
    """Reject agents that cannot fit into a node they must enter."""
    nodes = sim.network.nodes
    for u in _route_nodes(sim, pop) - {sim.network.node(pop.node).index}:
        limit = sim.max_density * nodes[u].area
        if pop.area_factor <= limit + 1e-9:
            continue
        raise ValueError(
            f"area_factor {pop.area_factor} of the population in "
            f"'{pop.node}' exceeds max_density * area = {limit:g} of "
            f"'{nodes[u].name}' on its route."
        )


def _route_nodes(sim, pop) -> set[int]:
    """Non-safe nodes agents of ``pop`` can reach, start node included."""
    net = sim.network
    links, table = net.links, sim._routes[pop.target]
    choices = sim._choices[pop.target]
    stack, seen = [net.node(pop.node).index], set()
    while stack:
        u = stack.pop()
        if u in seen or table[u] is None:
            continue
        seen.add(u)
        tied = choices[u] if sim.split_ties else ()
        stack.extend(links[i].target for i in (table[u], *tied))
    return seen


def _warn_unsplit_ties(sim) -> None:
    names = set()
    for pop in sim.populations:
        names |= _reachable_ties(sim, pop)
    if not names:
        return
    warnings.warn(
        f"Routes are tied at {sorted(names)}; with split_ties=False every "
        "agent there takes the first route found.",
        UserWarning,
        stacklevel=3,
    )


def _reachable_ties(sim, pop) -> set[str]:
    """Nodes with tied links that agents of ``pop`` can reach."""
    net = sim.network
    links, table = net.links, sim._routes[pop.target]
    choices = sim._choices[pop.target]
    stack, seen = [net.node(pop.node).index], set()
    while stack:
        u = stack.pop()
        if u in seen or table[u] is None:
            continue
        seen.add(u)
        stack.extend(links[i].target for i in (table[u], *choices[u]))
    return {net.nodes[u].name for u in seen if len(choices[u]) > 1}


@dataclass
class _Agents:
    node: np.ndarray
    link: np.ndarray
    state: np.ndarray
    distance: np.ndarray
    speed: np.ndarray
    pre_movement: np.ndarray
    area: np.ndarray
    route: np.ndarray
    arrival: np.ndarray
    exit_time: np.ndarray = field(init=False)

    def __post_init__(self) -> None:
        self.exit_time = np.full(len(self.node), np.nan)


class _Run:
    def __init__(self, sim: NetworkSimulation, rng, record: bool) -> None:
        net = sim.network
        self.sim = sim
        self.rng = rng
        self.record = record
        self.area = np.array([n.area for n in net.nodes])
        self.safe = np.array([n.kind == SAFE for n in net.nodes])
        self.k = np.array([n.speed_constant for n in net.nodes])
        self.link_source = np.array([lk.source for lk in net.links], dtype=int)
        self.link_target = np.array([lk.target for lk in net.links], dtype=int)
        self.link_length = np.array([lk.length for lk in net.links])
        self.link_rate = np.array([lk.capacity for lk in net.links]) * sim.dt
        self.link_weight = np.array([lk.merge_weight for lk in net.links])
        # A fresh link lets the first agent through without waiting.
        self.carry = np.ones(len(net.links))
        self.node_carry = np.zeros(len(self.area))
        # Served agents per merge weight; keeps merge shares across steps.
        self.virtual_time = np.zeros(len(net.links))
        self.targets = list(sim._routes)
        self.route_matrix = np.array(
            [_as_index_array(sim._routes[t]) for t in self.targets]
        )
        # Tied links per route and node code (route * nodes + node), and
        # the number of agents each has assigned so far.
        self.ties = self._tie_links() if sim.split_ties else {}
        self.tie_codes = np.array(sorted(self.ties), dtype=int)
        self.tie_count: dict[int, int] = {}
        self.agents = self._spawn()
        self.occupancy_series: list[np.ndarray] = []
        self.flow_series: list[np.ndarray] = []
        self.times: list[float] = []

    def _tie_links(self) -> dict[int, np.ndarray]:
        n = len(self.area)
        return {
            route * n + node: np.array(tied, dtype=int)
            for route, t in enumerate(self.targets)
            for node, tied in enumerate(self.sim._choices[t])
            if len(tied) > 1
        }

    def _choose(self, code: int, count: int) -> np.ndarray:
        """Next links of ``count`` agents at a tie, alternating in order."""
        tied = self.ties[code]
        first = self.tie_count.get(code, 0)
        self.tie_count[code] = first + count
        return tied[(first + np.arange(count)) % tied.size]

    def execute(self) -> SimulationResult:
        t = 0.0
        self._record(t, np.zeros(len(self.link_rate), dtype=int))
        while t < self.sim.t_max and (self.agents.state != _SAFE).any():
            flow = self._step(t)
            t = round(t + self.sim.dt, 9)
            self._record(t, flow)
        return self._result()

    def _spawn(self) -> _Agents:
        parts = [self._spawn_population(p) for p in self.sim.populations]
        agents = _Agents(
            *(np.concatenate([p[i] for p in parts]) for i in range(9))
        )
        self._check_capacity(agents)
        return agents

    def _spawn_population(self, pop: Population) -> list[np.ndarray]:
        node = self.sim.network.node(pop.node).index
        count = int(round(as_distribution(pop.count).sample(self.rng, 1)[0]))
        route = self.targets.index(pop.target)
        link = np.full(count, self.route_matrix[route, node], dtype=int)
        code = route * len(self.area) + node
        if code in self.ties:
            link = self._choose(code, count)
        start = as_distribution(pop.start_distance).sample(self.rng, count)
        speed = as_distribution(pop.speed).sample(self.rng, count)
        if (speed <= 0).any():
            raise ValueError("Agent speeds must be positive.")
        return [
            np.full(count, node, dtype=int),
            link,
            np.full(count, _WAITING, dtype=int),
            start + self.link_length[link],
            speed,
            as_distribution(pop.pre_movement).sample(self.rng, count),
            np.full(count, pop.area_factor, dtype=float),
            np.full(count, route, dtype=int),
            np.zeros(count),
        ]

    def _check_capacity(self, agents: _Agents) -> None:
        load = self._load(agents.node, agents.area)
        over = np.flatnonzero(load > self.sim.max_density * self.area + 1e-9)
        if over.size == 0:
            return
        names = [self.sim.network.nodes[i].name for i in over]
        raise ValueError(f"Initial population exceeds max_density in {names}.")

    def _load(self, nodes, weights) -> np.ndarray:
        return np.bincount(nodes, weights=weights, minlength=len(self.area))

    def _step(self, t: float) -> np.ndarray:
        a = self.agents
        inside = a.state != _SAFE
        load = self._load(a.node[inside], a.area[inside])
        density = np.where(self.safe, 0.0, load / self.area)
        start = (a.state == _WAITING) & (a.pre_movement <= t)
        a.state[start] = _WALKING
        self._walk(density, t)
        return self._transfer(load, density, t)

    def _walk(self, density: np.ndarray, t: float) -> None:
        a = self.agents
        walking = np.flatnonzero(a.state == _WALKING)
        congested = hydraulic.speed(
            density[a.node[walking]], self.k[a.node[walking]]
        )
        step = np.minimum(a.speed[walking], congested) * self.sim.dt
        a.distance[walking] -= step
        reached = a.distance[walking] <= 0
        arrived = walking[reached]
        a.state[arrived] = _QUEUED
        # Fraction of the step at which the constriction was reached.
        fraction = 1.0 + a.distance[arrived] / np.maximum(step[reached], 1e-12)
        a.arrival[arrived] = t + np.clip(fraction, 0.0, 1.0) * self.sim.dt

    def _transfer(self, load, density, t) -> np.ndarray:
        a = self.agents
        queued = np.flatnonzero(a.state == _QUEUED)
        queued = queued[np.lexsort((queued, a.arrival[queued], a.link[queued]))]
        budget = self.carry + self.link_rate
        wanted = self._wanted(queued, budget)
        queuing = np.bincount(a.link[queued], minlength=len(budget)) > 0
        # Links whose capacity enters the supply limit of their target.
        supply_links = queuing.copy()
        offered = self._offered(supply_links)
        allowance = self._allowance(density, offered)
        free = self.sim.max_density * self.area - load
        passed = self._admit(wanted, np.minimum(free, allowance))
        flow = np.bincount(a.link[passed], minlength=len(budget))
        self._update_carry(budget, flow)
        head = self._head_area(queued, passed)
        self._update_node_carry(allowance, offered, head, passed)
        self._update_virtual_time(flow, queuing)
        self._move(passed, t)
        return flow

    def _offered(self, links: np.ndarray) -> np.ndarray:
        """Summed per-step rate of the selected links into each node."""
        return np.bincount(
            self.link_target[links],
            weights=self.link_rate[links],
            minlength=len(self.area),
        )

    def _allowance(
        self, density: np.ndarray, offered: np.ndarray
    ) -> np.ndarray:
        """Agent area a node accepts this step beyond the space limit.

        Above the peak-flow density the capacity ``offered`` to a node by
        its incoming links with a queue is reduced linearly to zero at
        ``max_density``.
        """
        allowance = np.full(len(self.area), np.inf)
        peak, limit = hydraulic.PEAK_FLOW_DENSITY, self.sim.max_density
        if not self.sim.supply_reduction or limit <= peak:
            return allowance
        factor = np.clip((limit - density) / (limit - peak), 0.0, 1.0)
        reduced = (factor < 1.0) & ~self.safe
        allowance[reduced] = (
            self.node_carry[reduced] + factor[reduced] * offered[reduced]
        )
        return allowance

    def _head_area(self, queued, passed) -> np.ndarray:
        """Largest area factor at the head of a queue into each node."""
        a = self.agents
        head = np.zeros(len(self.area))
        waiting = queued[~np.isin(queued, passed)]
        if waiting.size == 0:
            return head
        links = a.link[waiting]
        first = np.ones(waiting.size, dtype=bool)
        first[1:] = links[1:] != links[:-1]
        heads = waiting[first]
        np.maximum.at(head, self.link_target[a.link[heads]], a.area[heads])
        return head

    def _update_node_carry(self, allowance, offered, head, passed) -> None:
        a = self.agents
        admitted = self._load(self.link_target[a.link[passed]], a.area[passed])
        # Save at most one step of supply, or enough for the largest head;
        # an unlimited node (infinite allowance) holds the full cap.
        cap = np.maximum(np.maximum(offered, 1.0), head)
        self.node_carry = np.clip(allowance - admitted, 0.0, cap)

    def _wanted(
        self, queued: np.ndarray, budget: np.ndarray
    ) -> list[np.ndarray]:
        links = self.agents.link[queued]
        wanted = []
        for link in np.unique(links):
            members = queued[links == link]
            wanted.append(members[: int(budget[link] + 1e-9)])
        return wanted

    def _admit(self, wanted: list[np.ndarray], free: np.ndarray) -> np.ndarray:
        if not wanted:
            return np.empty(0, dtype=int)
        candidates = np.concatenate(wanted)
        if candidates.size == 0:
            return candidates
        a = self.agents
        target = self.link_target[a.link[candidates]]
        rank = np.concatenate([np.arange(len(w)) for w in wanted])
        # Interleave queues in proportion to merge weight; random tie-break.
        links = a.link[candidates]
        key = self.virtual_time[links] + (rank + 1.0) / self.link_weight[links]
        order = np.lexsort((self.rng.random(candidates.size), key, target))
        candidates, target = candidates[order], target[order]
        return candidates[self._fits(candidates, target, free)]

    def _fits(self, candidates, target, free) -> np.ndarray:
        weights = self.agents.area[candidates]
        fits = np.ones(candidates.size, dtype=bool)
        for node in np.unique(target):
            if self.safe[node]:
                continue
            mask = target == node
            used = np.cumsum(weights[mask])
            fits[mask] = used <= free[node] + 1e-9
        return fits

    def _update_carry(self, budget, flow) -> None:
        """Keep unused budget, at most one agent; refills at rate C."""
        self.carry = np.clip(budget - flow, 0.0, 1.0)

    def _update_virtual_time(self, flow, active) -> None:
        """Advance served links; idle links catch up to avoid banking."""
        self.virtual_time += flow / self.link_weight
        floor = np.full(len(self.area), np.inf)
        np.minimum.at(
            floor, self.link_target[active], self.virtual_time[active]
        )
        catch_up = ~active & np.isfinite(floor[self.link_target])
        self.virtual_time[catch_up] = np.maximum(
            self.virtual_time[catch_up], floor[self.link_target[catch_up]]
        )

    def _move(self, passed: np.ndarray, t: float) -> None:
        a = self.agents
        target = self.link_target[a.link[passed]]
        a.node[passed] = target
        done = passed[self.safe[target]]
        a.state[done] = _SAFE
        a.exit_time[done] = t + self.sim.dt
        onward = passed[~self.safe[target]]
        next_link = self.route_matrix[a.route[onward], a.node[onward]]
        a.link[onward] = next_link
        a.distance[onward] = self.link_length[next_link]
        a.state[onward] = _WALKING
        self._split_ties(onward)

    def _split_ties(self, onward: np.ndarray) -> None:
        """Reassign agents entering a tie, in order of arrival and index."""
        if not self.ties or onward.size == 0:
            return
        a = self.agents
        onward = onward[np.lexsort((onward, a.arrival[onward]))]
        codes = a.route[onward] * len(self.area) + a.node[onward]
        for code in np.intersect1d(codes, self.tie_codes):
            members = onward[codes == code]
            a.link[members] = self._choose(int(code), members.size)
            a.distance[members] = self.link_length[a.link[members]]

    def _record(self, t: float, flow: np.ndarray) -> None:
        if not self.record:
            return
        a = self.agents
        inside = a.state != _SAFE
        self.times.append(t)
        self.occupancy_series.append(
            np.bincount(a.node[inside], minlength=len(self.area))
        )
        self.flow_series.append(flow)

    def _result(self) -> SimulationResult:
        a = self.agents
        complete = np.isfinite(a.exit_time).all()
        net = self.sim.network
        return SimulationResult(
            evacuation_time=float(np.max(a.exit_time, initial=0.0))
            if complete
            else float("nan"),
            exit_times=a.exit_time,
            pre_movement_times=a.pre_movement,
            times=np.array(self.times),
            node_occupancy=np.array(self.occupancy_series, dtype=int),
            link_flow=np.array(self.flow_series, dtype=int),
            node_names=tuple(n.name for n in net.nodes),
            link_names=tuple(lk.name for lk in net.links),
        )


def _as_index_array(table: list[int | None]) -> np.ndarray:
    return np.array([-1 if i is None else i for i in table], dtype=int)
