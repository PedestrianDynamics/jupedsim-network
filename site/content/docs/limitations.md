---
title: Limitations
weight: 6
description: Known limitations of the jupedsim-network model and how its defaults compare with the bounding defaults of Gwynne et al.
---

This page lists every known limitation of version 0.2.0. Read it before
using a result. SFPE asks that model results be presented with a
description of the model's limitations, including its level of
validation {{< cite 1 "p. 2171" >}}.

## Status

- **Not validated.** The model is verified against hand calculations
  and adapted IMO component tests
  ([Verification]({{< relref "/docs/verification" >}})). It has not been
  compared with evacuation drills, experiments, EvacuatioNZ runs or
  JuPedSim's microscopic models. It is not intended for regulatory or
  design use.
- **Optimistic by construction.** SFPE notes that the hydraulic model
  tends to give an optimistic estimate {{< cite 1 "p. 2165" >}}.
  Gwynne et al. name five elements an egress model must address:
  pre-evacuation time, travel speed, route usage, route availability
  and flow constraints {{< cite 11 "p. 339" >}}. They write that model
  defaults "often represent optimistic and even unrealistic evacuation
  conditions or occupant behaviour (e.g. immediate response and optimal
  use of routes available)" {{< cite 11 "p. 336" >}}, and propose
  bounding defaults instead: values from the literature that lengthen
  the evacuation time {{< cite 11 "pp. 335, 342" >}}. The
  [table below](#defaults-compared-with-bounding-defaults) compares
  them with the defaults of this model.
- **SFPE relations applied to a network.** Shestopal and Grubits write
  that the analytical approach of Nelson and MacLennan, in the SFPE
  Handbook, "is not intended to be extrapolated to complex network of
  exit routes" {{< cite 19 "p. 625" >}}. This model applies those SFPE relations on
  a network of nodes and links. The effect of this has not been tested.
- **Prototype.** The interface may change between versions.

### Defaults compared with bounding defaults

No default of this model is a bounding default in the sense of Gwynne
et al. They give their values as "the first iteration of values that
might then be modified", and their approach gives "relative
conservatism (within the application of each model)"
{{< cite 11 "p. 343" >}}. The paper does not test the values in a
simulation.

| Element | Direction | Default here | Bounding default of Gwynne et al. |
|---------|-----------|--------------|-----------------------------------|
| Pre-evacuation time | Optimistic | `pre_movement=0.0` s for every agent | 1800 s, all agents at once {{< cite 11 "p. 345" >}} |
| Travel speed | Design value | `speed=1.2` m/s; level speed capped at 1.199 m/s | 0.3 m/s {{< cite 11 "p. 346" >}} |
| Route availability and usage | Optimistic (availability); not established (usage) | Every safe node can be used; shortest distance to the nearest one | All agents to the narrowest, most remote final exit {{< cite 11 "pp. 346–347; Table II, p. 349" >}} |
| Ties between routes | Not established (see Ties below) | `split_ties=True`: agents alternate between tied links | "all agents are randomly assigned to one of those final exits" {{< cite 11 "p. 347" >}} |
| Door flow | Design value; disputed | $F_s = 1.3$ persons/s/m of effective width, $b = 0.15$ m per side | 0.67 persons/s per single-leaf door of regulated minimum width, not scaled with width {{< cite 11 "p. 348" >}} |
| Merge weights | Not established | 1 for every link | None proposed |
| `max_density`, supply reduction | Not established | 2.75 m⁻², on | None proposed |

- **Pre-movement.** Zero pre-evacuation time is the paper's example of
  an optimistic default {{< cite 11 "p. 342" >}}. A pre-movement time
  $T$ common to all agents adds $T$ to the evacuation time, because the
  agents start together and queue the same way. This holds exactly when
  $T$ is a multiple of $\Delta t$ and the run ends before `t_max`.
  Detection and alarm count only if added to `pre_movement`
  ([Behaviour](#behaviour)).
- **Travel speed.** 1.2 m/s is "a frequently used design value"
  {{< cite 11 "p. 345" >}}.
- **Route availability and usage.** Gwynne et al. give one bound for
  both elements. Taking all routes and exits as available "may produce
  optimistic results"; as a first step they discount the widest final
  exit, then refine this to the narrowest, most remote one
  {{< cite 11 "pp. 346–347" >}}. Whether nearest exit and shortest
  path are conservative depends on the scenario
  {{< cite 11 "p. 341" >}}. To test a blocked exit, build the network
  without that safe node and compare the results.
- **Ties.** The paper's tie rule applies to final exits of the same
  minimum width and the same maximum travel distance; it does not cover
  ties at intermediate nodes {{< cite 11 "p. 347" >}}. In the
  ten-storey case, splitting ties is faster than `split_ties=False`
  (407.5 s against 725.5 s, see [Routes](#routes)). With tied links of
  different widths, alternation can be slower, because it splits agents
  by count, not by capacity. Neither setting bounds the result.
- **Door flow.** 1.3 persons/s/m is the SFPE design value
  {{< cite 1 "Table 67.5, p. 2176" >}}. Gwynne et al. and SFPE differ
  on whether the door data are conservative; see "Doors are open and
  the data are old" under [Movement and capacity](#movement-and-capacity).
- **Merge weights.** Gwynne et al. propose no bound; SFPE calls equal
  shares not conservative {{< cite 1 "p. 2178" >}}.
- **`max_density` and supply reduction.** Gwynne et al. propose no
  bound. [Verification]({{< relref "/docs/verification#sensitivity-to-max_density" >}})
  shows how the results depend on `max_density`.

## Routes

- **Ties are split by count, not by capacity.** Where two routes are
  equally short, agents alternate between them, so each tied link gets
  the same number of agents whatever its width
  ([Networks]({{< relref "/docs/using/networks#routes" >}}),
  [issue #7](https://github.com/PedestrianDynamics/jupedsim-network/issues/7)).
  Routes that differ by more than floating-point rounding (10⁻⁹ of their
  length) are not tied, however small the difference. With
  `split_ties=False` every agent takes the route found first.

  ![Cumulative evacuation curves with ties split, with split_ties=False and with one stair](/images/network/route_tie.png)

  The ten-storey building of the [case study]({{< relref "/docs/ten-storey" >}})
  with pre-movement U(30, 120) s, seed 1. With ties split, 300 agents
  take each stair and the building is clear after 407.5 s. With
  `split_ties=False` all 600 take one stair and evacuate as slowly as a
  building with a single stair (725.5 s); splitting the tie cuts the
  time by 44 %.

- **Routes are static and use distance only.** They are computed once
  from link lengths. Agents don't react to queues, blocked exits, signs
  or smoke, and walking speed (level or stair) plays no part.

## Movement and capacity

- **Free speed is capped.** Because the density is taken as at least
  0.54 m⁻², no agent walks faster than 1.199 m/s on level ground or
  0.922 m/s on an 18/28 cm stair, whatever its `speed`
  ([Populations]({{< relref "/docs/using/populations#speeds-above-12-ms-have-no-effect-on-level-ground" >}})).
- **Stair speed outside the SFPE range is extrapolated.** The
  $\sqrt{T/R}$ law is supported for risers of 165–191 mm and treads of
  254–330 mm {{< cite 1 "p. 2175" >}}. `add_stair` warns for other
  values but still computes the speed
  ([Networks]({{< relref "/docs/using/networks#stairs" >}})).
- **Stair length is taken along the incline.** Stair links take the
  walking distance along the line of travel, as SFPE does in its
  Example 67.1 {{< cite 1 "p. 2178" >}}. Entering the horizontal run
  makes the walk about 16 % too short for 18/28 cm steps
  ([Networks]({{< relref "/docs/using/networks#length" >}})).
- **Densities above 1.9 m⁻².** SFPE states that such densities should
  not be assumed in engineering designs {{< cite 1 "p. 2175" >}}. The
  model allows nodes up to `max_density`, 2.75 m⁻² by default, and its
  behaviour between 1.88 m⁻² and `max_density` is its own choice.
- **The supply reduction is a modelling choice.** Its linear form
  between 1.88 m⁻² and `max_density` has not been calibrated against
  experiments. It is off when `max_density` ≤ 1.88 m⁻².
  `max_density` must stay below the jam density of 3.76 m⁻².
- **Supply depends on which links have a queue.** Above 1.88 m⁻² a node
  accepts a share of the summed capacity of its incoming links that have
  a queue in this step. At the same density, a node fed through one
  queued link therefore accepts less than one fed through two
  ([update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}})).
- **Counterflow isn't modelled.** The two directions of a two-way
  connection are separate links, each with the full capacity, so a door
  used both ways passes twice its capacity. In trials, the flow per
  direction under counterflow was about 13–20 % above half the
  one-way flow {{< cite 6 "pp. 6, 10–11" >}}, so the model overpredicts
  it by about 1.7 times (our estimate from these trials)
  ([issue #8](https://github.com/PedestrianDynamics/jupedsim-network/issues/8)).
  When every link has a positive length, default routing (no `target`)
  sends no agents both ways along a link, because every shortest route
  moves closer to a safe node, or as close over fewer links.
  Counterflow then arises only when populations have different
  `target`s.
- **Doors are open and the data are old.** $F_s = 1.3$ persons/s/m
  assumes doors held open; for doors that are not, SFPE suggests
  50 persons/min per door leaf. SFPE also notes that the door data are
  several decades old, come from non-emergency movement and drills, and
  should not be assumed to be conservative {{< cite 1 "p. 2176" >}}.
  Gwynne et al. call 1.3 persons/s/m "possibly already conservative"
  {{< cite 11 "p. 348" >}}; the question is open. With the boundary
  layers, $1.3\,(w - 0.3)$ equals their bound of 0.67 persons/s at a
  clear width $w$ of about 0.82 m; wider doors pass more.
  There are no door leaves or closers in the model.
- **Equal merge weights are not conservative.** SFPE says merge shares
  cannot be predetermined and recommends, conservatively, that the route
  of interest is dominated {{< cite 1 "p. 2178" >}}. The default weight
  is 1 for every link.
- **Merge shares remember the past.** Virtual times accumulate while a
  node is not yet full. When it fills, the link with the lower weight
  can stall until the shares are balanced again, for example room a in
  the [merge figure]({{< relref "/docs/verification#door-flow-and-merging" >}}).
- **Nodes are well mixed.** All walkers in a node share one density and
  one speed, so local crowding inside a large room isn't seen.
  Positions inside a node are not represented, so overtaking and local
  conflicts are not modelled {{< cite 16 "§2.2, p. 745" >}}. Queued
  agents are taken to stand at the constriction, and a long queue
  doesn't add walking distance. Splitting large spaces into several
  nodes helps.
- **One length per link.** The walking distance to a door doesn't
  depend on where in the room an agent starts, apart from the sampled
  `start_distance`. Both directions of a connection use the same
  length.
- **A link longer than its node limits the node's flow.** An agent
  walks a link's length $L$ inside the source node, at that node's
  speed $S(D) = k(1 - aD)$ ($k$ the node's speed constant,
  $a = 0.266$ m²). A node of length $\ell$ and width $w$ at density $D$
  then passes on average at most $D\,w\,\ell\,S(D)/L$ agents per
  second. This is largest at $D = 1/(2a)$, where it equals
  $k\,w\,\ell/(4aL)$: the node's peak specific flow $k/(4a)$ times
  $w\ell/L$. For $L > \ell$ the node passes less than $k w/(4a)$,
  whatever the door widths. Putting landing travel on a stair link
  makes $L$ longer than the stair node. In the SFPE nine-storey
  building this lowers the exit flow from 0.811 to about 0.65
  persons/s and raises the evacuation time from 1548.5 s to 1915.0 s
  ([Verification]({{< relref "/docs/verification#evacuationz-verification-cases" >}})).
  Model landings as their own nodes.
- **The area factor is not calibrated.** It scales an agent's
  contribution to density. It is not the Predtechenskii–Milinskii
  method that SFPE describes for mixed body sizes
  {{< cite 1 "pp. 2185–2187" >}}.
- **Full nodes can lock up.** No node ever exceeds `max_density`, so an
  agent enters only if its area factor fits into the free space. When
  every node on a cycle is too full to take the next agent waiting for
  it, the run never finishes: two 20 m² rooms holding 55 agents each
  ($2.75 \times 20$) and swapping occupants through one door stay full
  for good. The evacuation time is `nan`, and a larger `t_max` doesn't
  help. With mixed area factors a lock can also come from the queue
  order: a node serves the heads of its queues in turn, so a smaller
  agent that would fit waits behind a larger one that does not. An
  agent whose area factor exceeds `max_density` × area of a node on its
  route would never fit; `NetworkSimulation` rejects it with a
  `ValueError`
  ([Running]({{< relref "/docs/using/running#errors" >}})).

## Numerics

- **Results are quantised by the time step.** Agents leave at the end of
  a step, so exit times are multiples of $\Delta t$. Every link costs at
  least one step: six zero-length links in a row take 3.0 s at
  $\Delta t = 0.5$ s. Stair speeds need $\Delta t \approx 0.1$ s to
  match a hand calculation within 0.25 s.
- **Passage time is one headway shorter than SFPE.** A link idle for at
  least $1/C_\ell$ lets the first agent through at once, so $N$ agents need $(N-1)/C$ instead
  of the SFPE $N/C$ {{< cite 1 "Eq. 67.9, p. 2177" >}}
  ([Verification]({{< relref "/docs/verification#passage-time-n1c-and-nc" >}})).
- **Simultaneous arrivals are served in population order.** Agents that
  reach the same queue in the same step at the same interpolated time
  pass in the order of the populations, not at random. This order is
  kept by design ([issue #1](https://github.com/PedestrianDynamics/jupedsim-network/issues/1)).
  Individual exit times, and aggregate results when the tied agents
  differ in speed, area factor or target, can therefore depend on the
  order of the population list. In a small test, a 100 m² room with one 1 m door
  of zero length to a safe node holds 20 agents of area factor 1 and
  20 of area factor 2. The evacuation time is 43.0 s in both orders,
  but the last agent of the area-factor-1 group leaves at 21.0 s when
  that group is listed first and at 43.0 s when it is listed second.
  At a route tie, the population order also decides which agents take
  which of the tied links.

## Monte Carlo

- **Incomplete runs make high quantiles infinite.** A run that still
  has agents inside at `t_max` (3600 s by default) returns `nan`; its
  evacuation time is only known to exceed `t_max`. `quantile` ranks such
  runs above every finished run and returns `inf` for every quantile
  that depends on one of them. It warns whenever any run is incomplete.
  Raise `t_max` until `runs.incomplete` is 0
  ([Running]({{< relref "/docs/using/running#t_max-and-incomplete-runs" >}})).
- **Quantiles describe the inputs.** They reflect the spread of the
  sampled inputs, not the uncertainty of the model itself.

## Behaviour

- **Behaviour is minimal.** There are no lighting or smoke effects on
  speed, no groups, refuges, phased evacuation or node delays. Mobility
  impairment can be represented only through speed and area factor.
- **Detection and alarm are not modelled.** They count only if added
  to `pre_movement`
  ([defaults](#defaults-compared-with-bounding-defaults)).

## Output

- **`node_occupancy` counts heads.** It counts agents, not area factors,
  so it differs from the density the model uses when area factors other
  than 1 are present.
