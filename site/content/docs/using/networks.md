---
title: Networks
weight: 1
---

A `Network` holds the spaces of a building as nodes and the passages
between them as directed links. This page shows how to build one and
which defaults you get. The values behind the defaults and their
sources are in [Model elements]({{< relref "/docs/model/elements" >}}).

## Hydraulic configuration

```python
from jupedsim_network import HydraulicParameters, Network

parameters = HydraulicParameters(
    speed_density_slope=0.25, door_specific_flow=1.2
)
net = Network(parameters=parameters)
```

`Network()` retains the default configuration. Configuration fields are immutable
scalars; separate networks can use different configurations in the same process.
Node speeds and link capacities are resolved during construction. Simulation and
hydraulic reference-time routing use `net.parameters`, without a separate
simulation override. Rebuild the network to change the configuration.

Every numerical result must be traceable to the network geometry, immutable
hydraulic configuration, explicit local overrides and documented model
implementation. Retain simulation settings and random seeds with results.

Local `specific_flow` and `boundary_layer` overrides take precedence over
configuration-derived values; omitted configuration fields use library defaults.
Only `None` selects a connection default: an explicit zero boundary layer is
retained. Geometry, including widths, lengths, areas and stair steps, remains
in the original construction inputs, alongside the resolved graph records.

| Configuration field | Meaning | Unit | Default |
|---|---|---|---|
| `speed_density_slope` | Empirical speed–density slope | m²/person | 0.266 |
| `min_density` | Density floor used in the speed calculation | persons/m² | 0.54 |
| `level_speed_constant` | Level-walking coefficient, not reference speed | m/s | `84 / 60` |
| `door_specific_flow` | Prescribed specific flow for doors and openings | persons/(m·s) | 1.3 |
| `stair_speed_coefficient` | EvacuatioNZ coefficient multiplying `sqrt(tread/riser)` | m/min | 51.8 |
| `door_boundary_layer` | Excluded width per side | m | 0.15 |
| `opening_boundary_layer` | Excluded width per side | m | 0.0 |
| `stair_boundary_layer` | Excluded width per side | m | 0.15 |

Coefficients must be finite and positive; boundary layers must be finite and
nonnegative. The density floor must satisfy `0 <= min_density < jam_density`,
and the slope must yield a representable finite jam density. Simulation still
requires `max_density` below that jam density; an incompatible value raises an
error, including when the default `max_density=2.75` is too high.
`min_density` is **not** a minimum physical pedestrian density. The speed at
zero density is a hydraulic reference speed, not an empirical individual
free-walking speed.

Jam density (`1/a`), peak-flow density (`max(min_density, 1/(2*a))`) and maximum
specific flow are derived quantities. When the density floor exceeds `1/(2*a)`,
the maximum is at the floor and uses `k * min_density * (1 - a * min_density)`;
otherwise it is `k/(4*a)`. These are the extrema of the existing piecewise speed
relation, not additional configurable coefficients. Stair applicability ranges
remain reference limits in `hydraulic.py`, independent of the parameter set.

## Nodes

```python
net.add_room(
    name,
    *,
    area=None,
    length=None,
    width=None,
)
net.add_stair(
    name,
    *,
    riser,
    tread,
    area=None,
    length=None,
    width=None,
)
net.add_safe(name)
```

- **Rooms** are level spaces: rooms, corridors, lobbies. Give the floor
  area in m², or `length` and `width` in m.
- **Stair flights** take the riser height and tread depth in m, which set
  their walking speed. Their area holds the agents on the flight.
- **Safe nodes** have unlimited area. An agent that reaches a safe node
  counts as safe: its exit time is recorded and it leaves the model. A
  safe node can be the outside or a protected area such as a refuge.
  Either way it has unlimited capacity and no onward movement
  ([Behaviour]({{< relref "/docs/limitations#behaviour" >}}),
  [Movement and capacity]({{< relref "/docs/limitations#movement-and-capacity" >}})).

Names must be unique and areas positive.

### Stairs

Model each flight as one stair node, with an area of about its width
times the length of the flight. Connect the flight to the space below
with a `kind="stair"` link. SFPE applies stair speed to landings as well
{{< cite 1 "p. 2175" >}}. EvacuatioNZ models landings as separate nodes
{{< cite 3 "p. 20" >}}.

The stair speed grows with $\sqrt{T/R}$ (tread over riser). SFPE
supports this only for risers of 165–191 mm and treads of 254–330 mm
{{< cite 1 "Table 67.2, p. 2174; p. 2175" >}}. Other step sizes are an
extrapolation. `add_stair` takes riser and tread in m, each below 1 m,
computes the speed as usual, and issues a `UserWarning` when either lies
outside this range. For a riser of 0.20 m:

```text
UserWarning: Stair 'flight': riser 200.0 mm and tread 280.0 mm lie outside the SFPE range (risers 165-191 mm, treads 254-330 mm, SFPE Handbook Table 67.2); the speed constant k = 51.8 sqrt(T/R) m/min is extrapolated.
```

## Links

```python
net.connect(
    source,
    target,
    *,
    width,
    kind="door",
    length=0.0,
    specific_flow=None,
    boundary_layer=None,
    merge_weight=1.0,
    bidirectional=True,
    name=None,
)
```

`connect` returns the links it created.

| Argument | Meaning |
|----------|---------|
| `width` | Clear width in m. The capacity is $F_s\,(w - 2b)$ persons/s. |
| `kind` | `"door"`, `"opening"` or `"stair"` (see below). |
| `length` | Walking distance in m inside the *source* node to the constriction. |
| `specific_flow` | $F_s$ in persons/s per m of effective width; `None` uses the default of the kind. |
| `boundary_layer` | $b$ in m per side; `None` uses the default of the kind. |
| `merge_weight` | Relative share of this link when several links feed one full node. |
| `bidirectional` | Also create the link from `target` to `source`; the two links share one door ([Counterflow]({{< relref "/docs/model/counterflow" >}})). No link is created out of a safe node ([One-way and two-way links](#one-way-and-two-way-links)). |
| `name` | Name of the forward link; the default is `"source->target"`. |

### Kinds

- **`door`**: doors, archways and other openings in a wall.
- **`opening`**: a passage without a boundary layer. Following
  EvacuatioNZ, it stands for theatre seat rows and stadium benches
  {{< cite 3 "p. 14" >}}. Use `door` for an architectural opening or an
  archway {{< cite 1 "Table 67.1" >}}.
- **`stair`**: the exit of a stair flight. At least one of the two nodes
  must be a stair. The default specific flow comes from that stair node;
  if both nodes are stairs, it comes from the source node. Both directions
  share that resolved capacity. A stair–level connection uses the stair's flow
  in either construction direction. Door and opening kinds retain prescribed
  doorway flow even when adjacent to stairs; explicit `specific_flow` wins.

A connection without capacity, for example a width no larger than
$2b$, raises a `ValueError`, and so does a `specific_flow` of 0, a negative
value or NaN. To close a passage, leave the connection out.

### Length

`length` is walked inside the source node before the agent queues at
the constriction. Both directions of a two-way connection use the same
length, so a door in the middle of a long corridor needs one-way links
or separate nodes.

This model applies SFPE stair speeds along the line of travel
{{< cite 1 "p. 2175" >}}, so on a stair link enter the distance along the
incline, as SFPE does in its Example 67.1 {{< cite 1 "p. 2178" >}}.
For 18/28 cm steps the
incline is $\sqrt{1 + (R/T)^2} = 1.19$ times the horizontal run, so
entering the horizontal run makes the walk about 16 % too short.

### One-way and two-way links

`bidirectional=True` is the default. It creates a second link from
`target` to `source`, named `"target->source"` whatever `name` says. No
link is created out of a safe node, so `connect("street", "office",
bidirectional=False)` with a safe `"street"` creates no link and does
not raise. The two links of one two-way `connect` share one door: they
keep one carry, and while both directions have a queue they pass a
total $g\,C$ split between them
([Counterflow]({{< relref "/docs/model/counterflow" >}})).
`counterflow="independent"` restores the full capacity each way. Two
one-way `connect` calls between the same nodes make two separate doors.
A reverse link that nobody
queues at does not change how much a nearly full node accepts
([update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}})).

For a pure egress network, where everyone walks towards the exits, use
`bidirectional=False`. The building scenarios and the Getting started
example do.

## Routes

By default, every agent follows a fixed route to the nearest safe node,
measured as the sum of link lengths (Dijkstra's algorithm, in
`network.Network.route_table`). With `target`, a population heads for
that safe node instead. One route table is computed per target before
the run starts and is never updated.

- `routing_policy="shortest_distance"` is the default and sums link lengths
  in metres. Speeds and queues play no part.
- `routing_policy="shortest_free_flow_time"` minimizes **hydraulic reference
  travel time**, not predicted actual travel time. Each link costs
  `link.length / hydraulic.speed(0, source.speed_constant, parameters=net.parameters)` seconds because
  its length is walked in the source node. The reference speed is
  `k * (1 - a * min_density)` m/s (`k * (1 - 0.266 * 0.54)` by default);
  it is not the coefficient `k` itself. Individual speed limits, congestion,
  and queueing delays are excluded. This does not minimize total evacuation
  time. Pass the policy to `NetworkSimulation`, `route_table`, or
  `route_choices`; scenario files store it under `simulation.routing_policy`.
  One static table per destination is shared across populations. Explicit
  population targets still select the destination; speeds do not select tables.
- Equally short routes are split. A node where several links start a
  minimum-cost route is a tie; selected costs count as equal if they agree
  to within 10⁻⁹ of their cost (at least 10⁻⁹ m or 10⁻⁹ s), that is, up to
  floating-point rounding. Agents deciding at a tie alternate between the
  tied links in the order the links were created: at the start in
  population order, later in the order they reached the link they just
  passed. With two tied links, half the agents take each, the first
  link getting one more if their number is odd. Ties are split wherever
  they occur along a route, and with `target` within the routes to that
  safe node. No random numbers are drawn.
- A link is on a route only if it strictly decreases the computed cost
  to safety, or decreases the hop count at exactly equal cost. This strict
  lexicographic ordering is independent of approximate equality. A
  zero-length detour is therefore never taken, and agents cannot walk
  in circles.
- With `NetworkSimulation(..., split_ties=False)`, every agent at a node
  takes the one link that `route_table` returns: the link found first,
  if the rule above allows it; otherwise the first allowed link in the
  order the links were created (only at a node where zero-length links
  tie). The simulation issues a `UserWarning` naming the tied nodes
  the populations can reach
  ([Limitations]({{< relref "/docs/limitations#routes" >}}),
  [issue #7](https://github.com/PedestrianDynamics/jupedsim-network/issues/7)).
- `Network.route_choices(target=None)` returns, for each node index,
  the tied first links of all shortest routes, in creation order: one
  link where the route is unique, and none for safe nodes and nodes
  without a route. `split_ties=True` alternates agents between these
  links; the one link of `route_table` is one of them. It raises
  `RuntimeError` if tied routes form a cycle, which the progress
  rule (a link must bring agents closer) excludes.
- `start_distance` of a population is added to the walk but not to the
  route distance.

## Errors

| Error | When |
|-------|------|
| `Node '...' already exists.` | A name is used twice. |
| `Give either area or both length and width.` / `Node area must be positive, got ...` | Missing area, or an `area`, `length` or `width` that is not positive or not finite. |
| `Give either area or length and width, not both.` | `area` together with `length` or `width`. |
| `Unknown connection kind '...'.` | `kind` is not door, opening or stair. |
| `A stair connection needs an adjacent stair node.` | `kind="stair"` between two non-stair nodes. |
| `Cannot connect two safe nodes.` | Both nodes are safe. |
| `Width and merge weight must be positive, length non-negative, all finite; got ...` | Invalid or non-finite numbers. |
| `boundary_layer: must be >= 0 m, got ...` | A negative or non-finite `boundary_layer`. |
| `A connection needs two different nodes.` | `source` and `target` are the same node. |
| `Connection ...-... has no capacity.` | Effective width is zero. |
| `specific_flow must be positive, got ...` | `specific_flow` is 0, negative, NaN or infinite. |
| `Unknown node '...'.` | `connect` or `node()` names a node that does not exist. |
| `Riser and tread must be positive, got ...` | `add_stair` with a riser or tread of 0 or less, or NaN. |
| `riser and tread are in m and must be below 1 m; got ...` | `add_stair` with a riser or tread of 1 m or more, such as values in mm. |

Errors raised when the simulation is created or run are listed in
[Running]({{< relref "/docs/using/running#errors" >}}).
