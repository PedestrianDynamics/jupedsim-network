---
title: Networks
weight: 1
---

A `Network` holds the spaces of a building as nodes and the passages
between them as directed links. This page shows how to build one and
which defaults you get. The values behind the defaults and their
sources are in [Model elements]({{< relref "/docs/model/elements" >}}).

## Nodes

```python
net.add_room(name, *, area=None, length=None, width=None)
net.add_stair(name, *, riser, tread, area=None, length=None, width=None)
net.add_safe(name)
```

- **Rooms** are level spaces: rooms, corridors, lobbies. Give the floor
  area in m², or `length` and `width` in m.
- **Stair flights** take the riser height and tread depth in m, which set
  their walking speed. Their area holds the agents on the flight.
- **Safe nodes** have unlimited area. An agent that reaches one has left
  the building.

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
extrapolation. `add_stair` accepts any positive riser and tread, computes
the speed as usual, and issues a `UserWarning` when either lies outside
this range. For a riser of 0.20 m:

```
UserWarning: Stair 'flight': riser 200.0 mm and tread 280.0 mm lie outside the SFPE range (risers 165-191 mm, treads 254-330 mm, SFPE Handbook Table 67.2); the speed constant k = 51.8 sqrt(T/R) m/min is extrapolated.
```

## Links

```python
net.connect(
    source, target, *, width, kind="door", length=0.0,
    specific_flow=None, boundary_layer=None, merge_weight=1.0,
    bidirectional=True, name=None,
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
| `bidirectional` | Also create the link from `target` to `source`. |
| `name` | Name of the forward link; the default is `"source->target"`. |

### Kinds

- **`door`**: doors, archways and other openings in a wall.
- **`opening`**: a passage without a boundary layer. Following
  EvacuatioNZ, it stands for theatre seat rows and stadium benches
  {{< cite 3 "p. 14" >}}. Use `door` for an architectural opening or an
  archway {{< cite 1 "Table 67.1" >}}.
- **`stair`**: the exit of a stair flight. At least one of the two nodes
  must be a stair. The default specific flow comes from that stair node;
  if both nodes are stairs, it comes from the source node.

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
not raise. The reverse link has two side effects:

- it adds its capacity to the inflow capacity of the source node, which
  sets how much a nearly full node accepts
  ([update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}}));
- a door used in both directions passes its full capacity each way,
  since counterflow is not modelled.

For a pure egress network, where everyone walks towards the exits, use
`bidirectional=False`. The building scenarios and the Getting started
example do.

## Routes

Every agent follows a fixed route to the nearest safe node, measured as
the sum of link lengths (Dijkstra's algorithm, in
`network.Network.route_table`). With `target`, a population heads for
that safe node instead. One route table is computed per target before
the run starts and is never updated.

- Routes use distance only. Walking speed, stairs and queues play no
  part.
- Equal distances are not split. Zero-length links make ties likely,
  and every agent then takes the route found first
  ([Limitations]({{< relref "/docs/limitations#routes" >}}),
  [issue #7](https://github.com/PedestrianDynamics/jupedsim-network/issues/7)).
- `start_distance` of a population is added to the walk but not to the
  route distance.

## Errors

| Error | When |
|-------|------|
| `Node '...' already exists.` | A name is used twice. |
| `Give either area or both length and width.` / `Node area must be positive.` | Missing or non-positive area. |
| `Unknown connection kind '...'.` | `kind` is not door, opening or stair. |
| `A stair connection needs an adjacent stair node.` | `kind="stair"` between two non-stair nodes. |
| `Cannot connect two safe nodes.` | Both nodes are safe. |
| `Width and merge weight must be positive, length non-negative.` | Invalid numbers. |
| `A connection needs two different nodes.` | `source` and `target` are the same node. |
| `Connection ...-... has no capacity.` | Effective width is zero. |
| `specific_flow must be positive, got ...` | `specific_flow` is 0, negative or NaN. |
| `Unknown node '...'.` | `connect` or `node()` names a node that does not exist. |
| `Riser and tread must be positive.` | `add_stair` with a riser or tread of 0 or less. |

Errors raised when the simulation is created or run are listed in
[Running]({{< relref "/docs/using/running#errors" >}}).
