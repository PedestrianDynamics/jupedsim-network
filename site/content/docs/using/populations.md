---
title: Populations
weight: 2
---

A `Population` places a group of agents in one start node. Each input
except the area factor can be a fixed number or a distribution, and is
sampled anew in every run.

## Population

```python
Population(
    node,
    count,
    speed=1.2,
    pre_movement=0.0,
    start_distance=0.0,
    area_factor=1.0,
    target=None,
)
```

| Field | Meaning | Unit |
|-------|---------|------|
| `node` | Name of the start node | |
| `count` | Number of agents. A distribution is sampled once per run and rounded. | persons |
| `speed` | Free walking speed $v_i^\text{max}$, sampled per agent; must be positive | m/s |
| `pre_movement` | Time before the agent starts walking, sampled per agent | s |
| `start_distance` | Extra distance walked in the start node, sampled per agent | m |
| `area_factor` | Space the agent takes relative to an average adult; one fixed number for the population | |
| `target` | Name of a safe node to head for; `None` for the nearest | |

Plain numbers are accepted for every distribution argument.

### Speeds above 1.2 m/s have no effect on level ground

The walking speed is the smaller of $v_i^\text{max}$ and the congested
speed of the node, and the density in that formula is never taken below
0.54 m⁻² ([Model elements]({{< relref "/docs/model/elements#walking-speed" >}})).
No agent therefore walks faster than

- 1.199 m/s on level ground, and
- 0.922 m/s on an 18/28 cm stair,

whatever `speed` says. A 40 m walk at `speed=1.5` takes 33.5 s, which
is 40 m at 1.199 m/s. The default `speed=1.2` sits at this ceiling, so
sampled speeds above 1.2 m/s change nothing on level ground.

### Area factor

`area_factor` scales the agent's contribution to node density and to
the free space of a node. A value of 2 counts the agent as two average
adults, for example for a wheelchair user. The factor is a choice of
this model and is not calibrated
([Model elements]({{< relref "/docs/model/elements#agents" >}})).
Above 1.88 m⁻² an agent with a large area factor waits until the node
has saved supply for its whole area
([update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}})).

## Distributions

```python
Fixed(value)
Uniform(minimum, maximum)
Normal(mean, std)
LogNormal(mean, std)
Triangular(minimum, mode, maximum)
Weibull(alpha, beta)
```

Each takes the keyword arguments `lower=0.0` and `upper=None`.

- **Every distribution is truncated at 0 by default.** `Normal(10, 20)`
  never returns a negative value. Pass `lower=None` to allow them.
- Values outside `[lower, upper]` are drawn again, up to 100 times.
  Values still outside are then clipped to the bounds.
- `LogNormal(mean, std)` takes the mean and standard deviation of the
  variable itself, not of its logarithm.
- `Weibull(alpha, beta)` takes the scale `alpha` and the shape `beta`.

Truncation shifts the mean:

```python
import numpy as np
from jupedsim_network import Normal

rng = np.random.default_rng(1)
print(round(Normal(10.0, 20.0).sample(rng, 100_000).mean(), 2))
print(round(Normal(10.0, 20.0, lower=None).sample(rng, 100_000).mean(), 2))
```

Output:

```
20.12
9.93
```

Truncated at 0, `Normal(10, 20)` has a mean of about 20, not 10.

## Start nodes that are too full

If the agents of all populations in a node, weighted by their area
factors, exceed `max_density` times its area, `run()` raises
`ValueError: Initial population exceeds max_density in [...]`. The check
happens at `run()`, not when the population is created, because `count`
may be sampled.

## Related

- [Running]({{< relref "/docs/using/running" >}}): how sampled inputs are seeded.
- [Limitations]({{< relref "/docs/limitations#behaviour" >}}): behaviour the
  inputs cannot represent.
