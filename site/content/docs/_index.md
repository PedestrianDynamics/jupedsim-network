---
title: Documentation
cascade:
  type: docs
  math: true
---

`jupedsim_network` estimates how long the occupants of a building need to
reach safety. Rooms, corridors and stair flights are nodes with an area.
Doors, openings and stair entries are links with a flow capacity. Agents
move through this graph by relations adapted from the SFPE hydraulic
model. A run of a ten-storey building with 600 agents takes about 0.1 s,
so a scenario can be sampled hundreds of times.

{{< callout type="warning" >}}
Version 0.2.0, a prototype. The model is verified against hand
calculations and adapted IMO component tests. It is not validated against drills
or experiments, and it is not intended for regulatory or design use. See
[Limitations]({{< relref "/docs/limitations" >}}).
{{< /callout >}}

**New here.** Install the package, run a first scenario, then work
through a complete example:

{{< cards >}}
  {{< card link="getting-started" title="Getting started" subtitle="Install, run one building, and check the result." >}}
  {{< card link="examples/office-wing" title="Worked example" subtitle="An office wing from floor plan to bottleneck and one design change." >}}
{{< /cards >}}

**Building your own scenario.** Describe the building, the occupants and
the run, and read the results:

{{< cards >}}
  {{< card link="using/networks" title="Networks" subtitle="Rooms, stairs, safe places and the links between them." >}}
  {{< card link="using/populations" title="Populations" subtitle="Agents, their inputs and the sampling distributions." >}}
  {{< card link="using/running" title="Running" subtitle="Seeds, Monte Carlo, time step, max_density and t_max." >}}
  {{< card link="using/results" title="Results" subtitle="What a run returns and how to report it." >}}
{{< /cards >}}

**Checking the model.** How it works, how it is tested, and where it
stops:

{{< cards >}}
  {{< card link="model" title="Model" subtitle="Nodes, links, agents, routes and the update scheme." >}}
  {{< card link="verification" title="Verification" subtitle="Hand calculations, IMO tests and max_density sensitivity." >}}
  {{< card link="ten-storey" title="Case study" subtitle="A ten-storey building with two stairs." >}}
  {{< card link="limitations" title="Limitations" subtitle="Everything the model does not do, or does in a simple way." >}}
  {{< card link="evacuationz" title="Comparison with EvacuatioNZ" subtitle="Where this model follows EvacuatioNZ and where it differs." >}}
  {{< card link="references" title="References" subtitle="Sources cited on these pages." >}}
{{< /cards >}}

The `evacuation_time` of a run is the pre-movement time plus the
movement time of the simulated occupants. Detection and alarm times are
not modelled unless they are added to the pre-movement time, so the
output is an RSET only under that condition.
