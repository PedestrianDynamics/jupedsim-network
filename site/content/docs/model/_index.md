---
title: Model
weight: 3
aliases:
  - /docs/network-model/
---

The network model estimates evacuation times from a coarse graph instead
of a continuous geometry. Spaces such as rooms, corridors and stair
flights are **nodes** with an area. Doors, openings and stair entries
are **links** with a flow capacity. Individual agents move through this
graph by relations adapted from the SFPE hydraulic model {{< cite 1 "" >}}.

![Agents in two rooms walk to their doors, queue, merge into a corridor and leave through an exit](/images/network/mechanics.gif)

Two rooms of 40 agents each empty into a corridor of 4 m², which holds
at most 11 agents. The corridor is close to its limit most of the time. Its inflow is
then reduced and shared 1 : 3 between the rooms, following the merge
weights. Positions inside a node are drawn for illustration only, since
the model tracks a remaining walking distance per agent.

## Where it sits

- **Compared with a hand calculation,** the model automates the
  second-order hydraulic calculation {{< cite 1 "pp. 2177–2178" >}} and
  samples pre-movement times, occupant loads and walking speeds. A run
  of a ten-storey building with 600 agents takes about 0.1 s, so a
  scenario can be repeated hundreds of times.
- **Compared with a microscopic model,** it knows nothing about
  positions inside a node. We recommend checking geometry details and
  the critical cases found with the network model with the microscopic
  models of [JuPedSim](https://www.jupedsim.org). SFPE also suggests
  using several models together {{< cite 1 "p. 2185" >}}.

The model follows the approach of EvacuatioNZ {{< cite 2 "" 3 "" >}}. It
differs in several algorithms, most importantly the update scheme,
full-node handling and the walking distance of queued agents
([Comparison with EvacuatioNZ]({{< relref "/docs/evacuationz" >}})).

### Network models

A building can be represented as a network of spaces and connections
with flow capacities {{< cite 14 "p. 8" >}}. This coarse network is an
established method of egress modelling
{{< cite 16 "§2.2, p. 745" 17 "p. 70" 7 "manuscript p. 3" >}}. This
model simulates individual agents forward in time along routes fixed
before the run, so its results are estimates for those routes. It does
not search for the fastest routing.

{{< details title="Network flow optimisation, network simulation and this model" closed="true" >}}

**Network flow optimisation (EVACNET).** Nodes have static capacities,
the maximum number of people in a location. Arcs have flow capacities
in people per time period and travel times
{{< cite 14 "p. 13" >}}. A linear program over a time-expanded network
finds the routing that minimises the evacuation time, with perfect
knowledge of all time periods {{< cite 14 "pp. 3, 15, 93–94, 97" >}}. In optimisation models such as
EVACNET4, occupants therefore do not necessarily take their shortest
route {{< cite 17 "p. 78" >}}. The model counts people and does not identify
individuals {{< cite 14 "p. 20" >}}. Capacities and travel times do not
depend on crowding {{< cite 14 "pp. 94–95" >}}. The authors present the
result as a benchmark of how fast the building can be evacuated if
people follow the model's pattern {{< cite 14 "p. 8" >}}.

**Network simulation with a speed–density law (EXIT89).** Individual
occupants, all with the same properties, move forward in time from node
to node. Their walking speed is set by the density of the node they
cross {{< cite 15 "pp. 815, 818, 820–821" >}}, from the relations of
Predtechenskii and Milinskii with emergency speeds by default
{{< cite 15 "pp. 819–820" >}}. Queues form only through the lower
walking speed at high density {{< cite 15 "p. 822" >}}. Occupants take
the shortest route on each floor; when smoke blocks a node, the routes
on that floor are recomputed {{< cite 15 "pp. 817–819, 822" >}}.

**This model.** Each time step updates all individual agents at once,
with no optimisation. The node capacity of EVACNET corresponds to
`max_density` times the node area (agents of area factor 1), and its arc flow capacity to the link
capacity $C_\ell = F_s\,(w_\ell - 2 b_\ell)$
([links]({{< relref "/docs/model/elements#links" >}})). Walking speeds
and, by default, the inflow into a node depend on the node density. The
movement relations are adapted from SFPE {{< cite 1 "" >}}, while EXIT89 uses those of
Predtechenskii and Milinskii {{< cite 15 "p. 819" >}}. Routes are fixed
before the run: the shortest walking distance to the nearest safe node or to a
given target. In the
code: the module docstring of `jupedsim_network.simulation`,
`NetworkSimulation.run`, `Network.route_table` and
`hydraulic.SPEED_DENSITY_SLOPE`.

{{< /details >}}

{{< cards >}}
  {{< card link="elements" title="Model elements" subtitle="Nodes, links, agents, routes, the hydraulic relations and where each value comes from." >}}
  {{< card link="update-scheme" title="Update scheme" subtitle="The five stages of a time step, with equations." >}}
{{< /cards >}}
