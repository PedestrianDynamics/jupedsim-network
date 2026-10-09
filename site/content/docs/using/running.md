---
title: Running
weight: 3
---

A `NetworkSimulation` combines a network with its populations and the
run settings. This page covers seeds and Monte Carlo runs, and how to
choose the time step, `max_density` and `t_max`. The examples continue
the [Getting started]({{< relref "/docs/getting-started" >}}) scenario.

## Settings

```python
NetworkSimulation(
    network, populations, *, dt=0.5, t_max=3600.0, max_density=2.75,
    supply_reduction=True,
)
```

| Setting | Default | Meaning |
|---------|---------|---------|
| `dt` | 0.5 s | Time step |
| `t_max` | 3600 s | A run stops here, finished or not |
| `max_density` | 2.75 m⁻² | Hard limit of agents (weighted by area factor) per m² in a node; must lie in (0, 3.76) |
| `supply_reduction` | `True` | Reduce what a node accepts above the peak-flow density of 1.88 m⁻² |

Routes are computed when the simulation is created, so a population
without a route raises `ValueError` here, before any run.

## One run, many runs

```python
result = simulation.run(seed=1)          # one realisation
runs = simulation.run_many(500, seed=1)  # 500 independent realisations
```

- `seed` may be an integer, a `numpy.random.SeedSequence` or a
  `numpy.random.Generator`. The same seed gives the same result.
- `run(..., record=False)` skips the time series of node occupancy and
  link flow. `run_many` uses it.
- `run_many(runs, seed)` derives one seed per run with
  `numpy.random.SeedSequence(seed).spawn(runs)`. Run *i* of
  `run_many(500, seed=1)` is therefore not `run(seed=i)`.

### Replay a critical run

To inspect the slowest run of a Monte Carlo set with its full time
series, rebuild its seed:

```python
import numpy as np

runs = simulation.run_many(500, seed=1)
worst = int(np.nanargmax(runs.evacuation_times))
replay = simulation.run(np.random.SeedSequence(1).spawn(500)[worst])
print(worst, runs.evacuation_times[worst], replay.evacuation_time)
```

Output:

```
426 1015.5 1015.5
```

`replay` is a full `SimulationResult` of run 426
([Results]({{< relref "/docs/using/results" >}})).

## Choosing the time step

Agents leave at the end of a step, so evacuation times are multiples of
$\Delta t$. Every link also costs at least one step: an agent that
passes a link walks again only in the next step. Six zero-length links
in a row take 3.0 s at $\Delta t = 0.5$ s.

Check your case by repeating it with a smaller step:

```python
for dt in (1.0, 0.5, 0.25, 0.1):
    sim = NetworkSimulation(net, [population], dt=dt)
    print(dt, sim.run(seed=1).evacuation_time)
```

Output:

```
1.0 323.0
0.5 323.0
0.25 323.0
0.1 322.6
```

Here the result changes by 0.4 s between 1.0 s and 0.1 s. Cases set by
door queues on level ground behave like this. Walking times on short
stair flights do not: the stair-speed test needs $\Delta t = 0.1$ s to
match the hand calculation within 0.25 s
([Verification]({{< relref "/docs/verification" >}})). Choose $\Delta t$ small
compared with the shortest walk through a node, and halve it once to
check.

## Choosing max_density

`max_density` is the most a node can hold, in agents per m² weighted by
area factor. A node never exceeds it.

- The default of 2.75 m⁻² is the default maximum node density of
  EvacuatioNZ {{< cite 3 "p. 3" >}}, where it was chosen because it gave
  suitable results in earlier work {{< cite 8 "p. 165" 10 "p. 111" >}},
  citing {{< cite 7 "" >}}.
- SFPE states that densities above 1.9 m⁻² should not be assumed in
  engineering designs {{< cite 1 "p. 2175" >}}. Everything between the
  peak-flow density of 1.88 m⁻² and `max_density`, including the supply
  reduction, is a choice of this model.
- The value must lie below the jam density $1/a = 3.76$ m⁻².
- With `supply_reduction=True`, a node above 1.88 m⁻² accepts less and
  less inflow as it fills
  ([update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}})).
  For `max_density` ≤ 1.88 m⁻² the reduction has no range to act on and
  is switched off; only the hard limit remains.
- With `supply_reduction=False`, results become very sensitive to
  `max_density` above about 3 m⁻²
  ([Verification]({{< relref "/docs/verification#sensitivity-to-max_density" >}})).

## t_max and incomplete runs

A run stops at `t_max`, 3600 s by default. A run that still has agents
inside at that time is incomplete: its `evacuation_time` is `nan`, and
its true evacuation time is only known to exceed `t_max`. The exit time
of every agent still inside is `nan` as well.

<!-- quantile: update after fix/quantile-censored -->
{{< callout type="warning" >}}
In version 0.1.0, `MonteCarloResult.quantile` and
`MonteCarloResult.complete` use completed runs only. If some runs are
incomplete, a high quantile is lower than it should be. Count the
incomplete runs with `np.isnan(runs.evacuation_times).sum()` and raise
`t_max` until the count is zero.
{{< /callout >}}

Runs close to the default `t_max` are realistic: in the
[max_density sweep]({{< relref "/docs/verification#sensitivity-to-max_density" >}})
with a hard limit of 3.7 m⁻², the slowest of 30 runs takes 2959 s.
