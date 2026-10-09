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
at most 11 agents. The corridor is full most of the time. Its inflow is
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

{{< cards >}}
  {{< card link="elements" title="Model elements" subtitle="Nodes, links, agents, routes, the hydraulic relations and where each value comes from." >}}
  {{< card link="update-scheme" title="Update scheme" subtitle="The five stages of a time step, with equations." >}}
{{< /cards >}}
