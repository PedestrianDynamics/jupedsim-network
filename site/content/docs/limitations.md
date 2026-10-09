---
title: Limitations
weight: 6
---

This page lists every known limitation of version 0.1.0. Read it before
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
  Nearest-exit routing and equal merge weights are optimistic defaults
  in the sense of Gwynne et al., who argue for bounding defaults on
  route use, flow, pre-evacuation time and speed {{< cite 11 "" >}}.
- **Prototype.** The interface may change between versions.

## Routes

- **Ties between equally distant exits are not split.** With two stairs
  at the same distance, every agent takes the stair found first, and the
  second stair stays empty. Split the populations by hand with `target`.

  ![Cumulative evacuation curves showing that a tie sends everyone down one stair](/images/network/route_tie.png)

  The ten-storey building of the [case study]({{< relref "/docs/ten-storey" >}})
  with pre-movement U(30, 120) s, seed 1. Nearest-exit routing evacuates
  as slowly as a building with a single stair (702.5 s). Splitting the
  targets by hand cuts the time by 42 % (405.5 s).

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
  254–330 mm {{< cite 1 "p. 2175" >}}. The code accepts other values
  without a warning.
- **Densities above 1.9 m⁻².** SFPE states that such densities should
  not be assumed in engineering designs {{< cite 1 "p. 2175" >}}. The
  model allows nodes up to `max_density`, 2.75 m⁻² by default, and its
  behaviour between 1.88 m⁻² and `max_density` is its own choice.
- **The supply reduction is a modelling choice.** Its linear form
  between 1.88 m⁻² and `max_density` has not been calibrated against
  experiments. It is off when `max_density` ≤ 1.88 m⁻².
  `max_density` must stay below the jam density of 3.76 m⁻².
- **Supply counts every incoming link.** The inflow capacity in the
  supply factor includes links that rarely carry anyone, such as the
  reverse direction of a two-way connection. A nearly full node then
  accepts more inflow than intended. Two-way links are the default
  (`bidirectional=True`); use `bidirectional=False` for egress networks
  ([Networks]({{< relref "/docs/using/networks#one-way-and-two-way-links" >}})).
- **Counterflow isn't modelled.** The two directions of a two-way
  connection are separate links, each with the full capacity, so a door
  used both ways passes twice its capacity. In trials, the flow per
  direction under counterflow was about 13–20 % above half the
  one-way flow {{< cite 6 "pp. 6, 10–11" >}}, so the model overpredicts
  it by about 1.7 times (our estimate from these trials).
- **Doors are open and the data are old.** $F_s = 1.3$ persons/s/m
  assumes doors held open; for doors that are not, SFPE suggests
  50 persons/min per door leaf. SFPE also notes that the door data are
  several decades old, come from non-emergency movement and drills, and
  should not be assumed to be conservative {{< cite 1 "p. 2176" >}}.
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
  one speed, so local crowding inside a large room isn't seen. Queued
  agents are taken to stand at the constriction, and a long queue
  doesn't add walking distance. Splitting large spaces into several
  nodes helps.
- **One length per link.** The walking distance to a door doesn't
  depend on where in the room an agent starts, apart from the sampled
  `start_distance`. Both directions of a connection use the same
  length.
- **The area factor is not calibrated.** It scales an agent's
  contribution to density. It is not the Predtechenskii–Milinskii
  method that SFPE describes for mixed body sizes
  {{< cite 1 "pp. 2185–2187" >}}.

## Numerics

- **Results are quantised by the time step.** Agents leave at the end of
  a step, so exit times are multiples of $\Delta t$. Every link costs at
  least one step: six zero-length links in a row take 3.0 s at
  $\Delta t = 0.5$ s. Stair speeds need $\Delta t \approx 0.1$ s to
  match a hand calculation within 0.25 s.
- **Passage time is one headway shorter than SFPE.** An idle link lets
  the first agent through at once, so $N$ agents need $(N-1)/C$ instead
  of the SFPE $N/C$ {{< cite 1 "Eq. 67.9, p. 2177" >}}
  ([Verification]({{< relref "/docs/verification#passage-time-n1c-and-nc" >}})).
- **Simultaneous arrivals are served in population order.** Agents that
  reach the same queue in the same step at the same interpolated time
  pass in the order of the populations, not at random. Individual exit
  times can therefore depend on the order of the population list. In a
  test with 20 agents of area factor 1 and 20 of area factor 2 in one
  room, the evacuation time is 43.0 s in both orders, but the last
  agent of the area-factor-1 group leaves at 21.0 s when that group is
  listed first and at 43.0 s when it is listed second.

## Monte Carlo

<!-- quantile: update after fix/quantile-censored -->
- **Incomplete runs.** A run that still has agents inside at `t_max`
  (3600 s by default) returns `nan`; its evacuation time is only known
  to exceed `t_max`. In version 0.1.0, `quantile` uses completed runs
  only. Count incomplete runs before reporting a quantile
  ([Running]({{< relref "/docs/using/running#t_max-and-incomplete-runs" >}})).
- **Quantiles describe the inputs.** They reflect the spread of the
  sampled inputs, not the uncertainty of the model itself.

## Behaviour

- **Behaviour is minimal.** There are no lighting or smoke effects on
  speed, no groups, refuges, phased evacuation or node delays. Mobility
  impairment can be represented only through speed and area factor.
- **Detection and alarm are not modelled.** They count only if added
  to `pre_movement`.

## Output

- **`node_occupancy` counts heads.** It counts agents, not area factors,
  so it differs from the density the model uses when area factors other
  than 1 are present.
