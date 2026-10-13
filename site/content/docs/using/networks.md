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

`Network()` uses the defaults. The coefficients are immutable scalars;
separate networks can use different ones in the same process. Node speeds
and link capacities are resolved when you build the network, and the
simulation and the `"shortest_free_flow_time"` routing cost read
`net.parameters`. Rebuild the network to change a coefficient. A local
`specific_flow` or `boundary_layer` on `connect` takes precedence, and an
explicit zero boundary layer is kept.

| Field | Meaning | Unit | Default | Source |
|---|---|---|---|---|
| `speed_density_slope` | Slope $a$ of the speed–density relation | m²/person | 0.266 | SFPE Eq. 67.3 |
| `level_speed_constant` | Level-walking constant $k$ | m/s | `84 / 60` | SFPE Table 67.2 |
| `door_specific_flow` | Specific flow of doors and openings | persons/(m·s) | 1.3 | SFPE Table 67.5 |
| `stair_speed_coefficient` | Coefficient of $\sqrt{T/R}$ in the stair $k$ | m/min | 51.8 | EvacuatioNZ |
| `door_boundary_layer` | Excluded width per side of a door | m | 0.15 | SFPE Table 67.1 |
| `stair_boundary_layer` | Excluded width per side of a stair link | m | 0.15 | SFPE Table 67.1 |

The coefficients and boundary layers are finite; the four coefficients
are positive and the boundary layers nonnegative. Three quantities are
derived and cannot be set: jam density $1/a$, peak-flow density
$1/(2a)$ and maximum specific flow $k/(4a)$. The slope must keep the
peak-flow density at or above the density floor of 0.54 m⁻², that is
$a \le 0.926$ m²/person. `door_specific_flow` must not exceed $k/(4a)$ of
the level constant, because a door cannot pass more than the
speed–density relation allows; the error names both values. With the
default `door_specific_flow` of 1.3 this bound is reached at a slope
of 0.269, so to raise the slope further lower `door_specific_flow` in
the same step. `NetworkSimulation` (and `check`) requires `max_density`
below the jam density, so the default 2.75 fails for a slope of 0.364
(1/2.75) or more.

The opening boundary layer (0 m) and the density floor 0.54 m⁻² are not
coefficients and cannot be changed. The floor is an applicability bound
of the relation, not a minimum physical density; the speed at zero
density is a hydraulic reference speed, not a free-walking speed.

The defaults come from the sources in the table; see
[Model elements]({{< relref "/docs/model/elements#default-values-and-sources" >}}).
Changed values are study assumptions, not validated ranges, and the
package does not check them against data. Stair riser and tread ranges stay
reference limits, independent of the coefficients.

In a scenario file, give the coefficients that differ from the defaults
under `hydraulic_parameters`; an absent block means all defaults
([Command line]({{< relref "/docs/using/command-line#the-scenario-file" >}})).
Retain the package version and seeds with results; an exported file
records the version in `software_version`.

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
- `routing_policy="shortest_free_flow_time"` sums a reference time per
  link, `link.length / hydraulic.speed(0, source.speed_constant)` in
  seconds, where `source` is the node the link leaves, because a link's
  length is walked in that node. `speed(0, k)` is the SFPE speed at the
  density floor, $k\,(1 - 0.266 \cdot 0.54) = 0.856\,k$ m/s, so the floor
  only fixes the unit of the cost; the policy differs from
  `"shortest_distance"` only through the speed constants $k$ of the
  nodes, 1.4 m/s for rooms and $51.8\sqrt{T/R}/60$ m/s for stairs
  (1.077 m/s for 18/28 cm steps). Stair length is thereby weighted by
  about 1.3 relative to level length, and nothing else changes. A
  `kind="stair"` link that leaves a room is costed at the room's speed;
  only links leaving a stair node use the stair speed. This stair-entry
  rule and the policy itself are engineering choices of this model, not
  taken from SFPE, EvacuatioNZ or Tsai. The reference time excludes
  individual speeds, congestion and queues and is not a prediction of
  travel time ([Limitations]({{< relref "/docs/limitations#routes" >}})).
  Pass the policy to `NetworkSimulation`, `route_table` or
  `route_choices`; scenario files store it under `simulation.routing_policy`.
  One static table per destination is shared across populations.
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
