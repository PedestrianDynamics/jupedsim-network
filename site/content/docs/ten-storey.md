---
title: Case study
linkTitle: Case study
weight: 5
---

A ten-storey building with two stairs, sampled 300 times. The building
is invented to show the workflow; the result is not a design value for
any real building. All numbers come from the current version and the scripts
in `scripts/figures/`.

## The building

- Ten floors of 400 m² with 60 agents each.
- Two stairs, A and B. Each floor has a 0.9 m door to each stair, 25 m
  from the floor's occupants. Each flight is 1.2 m wide, with 18/28 cm
  steps, an area of 1.2 × 9.0 m² and a stair link of 9 m. The 9 m are
  entered as the walking distance along the incline, as SFPE measures
  stair distances ([issue #5](https://github.com/PedestrianDynamics/jupedsim-network/issues/5)).
- All links are one way (`bidirectional=False`).
- Half of each floor is sent to each stair with `target`. Nearest-exit
  routing would split the two tied stairs in the same way
  ([Networks]({{< relref "/docs/using/networks#routes" >}})), but with
  random pre-movement times the two set-ups send different agents to
  each stair, so the sampled results below would change, although the
  model is the same.

The network and populations are built by `building()` and
`building_populations()` in `scripts/figures/scenarios.py`. One run
takes about 0.1 s on a laptop (Apple M3 Pro).

## Monte Carlo

![Histogram of the evacuation time over 300 runs](/images/network/monte_carlo.png)

Pre-movement times are log-normal with mean 120 s and standard deviation
60 s, truncated at 600 s, and are sampled anew in each of the 300 runs
(seed 11). The median evacuation time is 529 s and the 95th percentile
647 s. All 300 runs finished; the fastest took 419.5 s and the slowest
717.0 s. The 300 runs take about 30 s on the same laptop.

## One run

![Animation of node densities in a ten-storey building with two stairs](/images/network/building.gif)

One run (seed 1, pre-movement U(30, 120) s). Floors are shaded by
density, and the doors from the floors compete with the stream from
above. The densest flight reaches 2.69 m⁻². That is above the peak-flow
density of 1.88 m⁻², in the range where the model's supply reduction
acts, and above the 1.9 m⁻² that SFPE says should not be assumed in
design {{< cite 1 "p. 2175" >}}
([Model elements]({{< relref "/docs/model/elements#choices-of-this-model" >}})).
