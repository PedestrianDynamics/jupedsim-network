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
    network,
    populations,
    *,
    dt=0.5,
    t_max=3600.0,
    max_density=2.75,
    supply_reduction=True,
    split_ties=True,
    counterflow="bounding",
    routing_policy="shortest_distance",
)
```

| Setting | Default | Meaning |
|---------|---------|---------|
| `dt` | 0.5 s | Time step, at least 1e-6 s |
| `t_max` | 3600 s | A run stops here, finished or not; must be finite |
| `max_density` | 2.75 m⁻² | Hard limit of agents (weighted by area factor) per m² in a node; must lie in (0, 3.76) |
| `supply_reduction` | `True` | Reduce what a node accepts above the peak-flow density of 1.88 m⁻² |
| `split_ties` | `True` | Alternate agents between equally short routes; `False` takes the route found first and warns ([Networks]({{< relref "/docs/using/networks#routes" >}})). Neither setting bounds the result ([Limitations]({{< relref "/docs/limitations#defaults-compared-with-bounding-defaults" >}})) |
| `counterflow` | `"bounding"` | How the two links of a two-way connection share one door. `"bounding"` (low end of the walkway data; stairs: Tofiło et al.'s 75 %) and `"estimate"` (centre of the data): the pair keeps one carry at all times; while both directions have a queue they pass together $g\,C$, $g$ between 0.75 and 1.0, split by queue share with at least 17 % of passages per direction. `"independent"`: two separate links, each with full capacity and its own carry, as before this setting ([Counterflow]({{< relref "/docs/model/counterflow" >}})) |
| `routing_policy` | `"shortest_distance"` | Link cost of the fixed routes. `"shortest_distance"`: sum of link lengths in m. `"shortest_free_flow_time"`: sum of `length / speed(0, k)` in s, with `speed(0, k) = 0.856 k` the hydraulic speed of the node the link leaves at the density floor (0.54 m⁻²); a static reference time, not a prediction of travel time ([Networks]({{< relref "/docs/using/networks#routes" >}}), [Limitations]({{< relref "/docs/limitations#routes" >}})) |

Routes are computed when the simulation is created, so a population
without a route raises `ValueError` here, before any run.

## One run, many runs

```python
result = simulation.run(seed=1)  # one realisation
runs = simulation.run_many(500, seed=1)  # 500 independent realisations
```

- `seed` of `run` may be an integer, a `numpy.random.SeedSequence`, a
  `numpy.random.Generator` or `None`, which uses fresh entropy that is
  not recorded. `seed` of `run_many` may be an integer, a sequence of
  integers or `None`. For both, an integer gives the same result
  every time; for `run`, so does a `SeedSequence`. A `Generator` is advanced by the run, so pass a
  new one each time.
- `run(..., record=False)` skips the time series of node occupancy and
  link flow. `run_many` uses it.
- In a scenario file, the `run` and `monte_carlo` sections hold these
  seeds, and `--seed` and `--mc-seed` override them
  ([Command line]({{< relref "/docs/using/command-line#seeds-and-reproducibility" >}})).
- `run_many(runs, seed)` derives one seed per run with
  `numpy.random.SeedSequence(seed).spawn(runs)`. Run *i* of
  `run_many(500, seed=1)` is therefore not `run(seed=i)`. The first *k*
  runs do not depend on `runs`: `run_many(100, seed=1)` gives the first
  100 runs of `run_many(500, seed=1)`.
- `run_many(runs, seed=None, *, progress=None)` calls
  `progress(done, runs)` after each run, on the calling thread, with
  `done` counting from 1 and both arguments Python integers. There is
  no call with 0, and the last call comes before the result is built.
  `progress` does not change the results; keep it quick. An exception
  it raises ends `run_many`, propagates unchanged and discards the runs
  done so far, so there is no partial result. A call ended this way
  cannot be resumed; with `seed=None` its seeds are lost.

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

```text
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

```text
1.0 323.0
0.5 323.0
0.25 323.0
0.1 322.6
```

Here the result changes by 0.4 s between 1.0 s and 0.1 s. Cases set by
door queues on level ground behave like this. Two kinds of case are known
to need a smaller step. The first is walking on short stair flights: the
stair-speed test needs $\Delta t = 0.1$ s to match the hand
calculation within 0.25 s
([Verification]({{< relref "/docs/verification" >}})). The second is a
node held at `max_density` whose agents walk out on a link longer than
the node. There a coarse step is slightly slow, by up to about one step
for each walk through the node
([Limitations]({{< relref "/docs/limitations#numerics" >}})). Counterflow,
and supply reduction at a `max_density` of 3.5 m⁻², can still give a
result that is too short. When $\Delta t$ is halved, the result can
therefore move either way.

The rule this model recommends: choose $\Delta t$ small compared with
the shortest walk through a node, and halve it once to check. If the
result changes by more than one or two steps, in either direction, the
step is too coarse.

## Choosing max_density

`max_density` is the most a node can hold, in agents per m² weighted by
area factor. A node never exceeds it.

- The default of 2.75 m⁻² is the default maximum node density of
  EvacuatioNZ {{< cite 3 "p. 3" >}}. It "has been found to give
  suitable results in previous work" {{< cite 10 "p. 111" >}}, namely
  {{< cite 7 "" >}}; see also {{< cite 8 "p. 165" >}}.
- SFPE states that densities above 1.9 m⁻² should not be assumed in
  engineering designs {{< cite 1 "p. 2175" >}}. Everything between the
  peak-flow density of 1.88 m⁻² and `max_density`, including the supply
  reduction, is a choice of this model.
- The value must lie below the jam density $1/a = 3.76$ m⁻².
- With `supply_reduction=True`, a node above 1.88 m⁻² accepts less and
  less inflow as it fills
  ([update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}})).
  For `max_density` ≤ 1.88 m⁻² the reduction has no range to act on and
  is switched off with a `UserWarning`; only the hard limit remains.
- With `supply_reduction=False`, results become very sensitive to
  `max_density` above about 3 m⁻²
  ([Verification]({{< relref "/docs/verification#sensitivity-to-max_density" >}})).

## t_max and incomplete runs

A run stops at `t_max`, 3600 s by default. A run that still has agents
inside at that time is incomplete: its `evacuation_time` is `nan`, and
its true evacuation time is only known to exceed `t_max`. The exit time
of every agent still inside is `nan` as well.

`MonteCarloResult.quantile` ranks incomplete runs above every finished
run. A quantile that depends on an incomplete run is only bounded from
below and is returned as `inf`; a quantile that does not is exact.
`quantile` issues a `RuntimeWarning` whenever any run is incomplete.
`MonteCarloResult.complete` lists the finished runs only. With all runs finished, `quantile` is NumPy's default (linear)
quantile of the evacuation times.

The Getting started scenario with `t_max` cut to 500 s:

```python
short = NetworkSimulation(net, [population], t_max=500.0)
cut = short.run_many(500, seed=1)
print(cut.incomplete)
print(cut.quantile([0.5, 0.95]))
```

Output:

```text
59
[383.25    inf]
```

The warning reads:

```text
RuntimeWarning: 59 of 500 runs did not finish before t_max = 500 s; quantiles above q = 440/499 (about 0.882) are inf.
```

The median is the same as with the default `t_max`. The 95th
percentile needs some of the 59 unfinished runs, so it is `inf`. Raise
`t_max` until `runs.incomplete` is 0. A run whose nodes lock up stays
`nan` whatever `t_max` is
([Limitations]({{< relref "/docs/limitations#movement-and-capacity" >}})).

Runs close to the default `t_max` are realistic: in the
[max_density sweep]({{< relref "/docs/verification#sensitivity-to-max_density" >}})
with a hard limit of 3.7 m⁻², the slowest of 30 runs takes 3102 s.

## Errors

| Error | When |
|-------|------|
| `dt and t_max must be positive and finite, got ...` | `dt` or `t_max` is 0, negative, NaN or infinite. |
| `dt must be at least 1e-6 s, got ...` | `dt` is below 1e-6 s. |
| `max_density must be in (0, 3.76).` | `max_density` is 0 or negative, or at least the jam density. |
| `area_factor: must be positive, got ...` | `Population` with an `area_factor` of 0 or less, or not finite. |
| `count: Fixed value ... lies outside [lower, upper] = [0.0, None].` | A plain negative `count`; likewise `speed`, `pre_movement` and `start_distance`. |
| `Fixed value ... lies outside [lower, upper] = [...]` | A `Fixed` value outside its bounds. |
| `lower ... is greater than upper ...` | A distribution with `lower` above `upper`. |
| `... must be finite, got ...` / `... must be a finite number or None, got ...` | A distribution parameter, a plain `count`, `speed`, `pre_movement` or `start_distance`, or a `lower` or `upper` bound that is NaN or infinite. |
| `Weibull alpha and beta must be positive, got ...` / `std must be >= 0, got ...` | A Weibull scale or shape of 0 or less; a negative `LogNormal` `std`. |
| `start_distance: must have lower >= 0, got lower=...` | A `start_distance` distribution with `lower=None` or a negative `lower`. |
| `At least one population is required.` | The population list is empty. |
| `Unknown node '...'.` | A population or `target` names a node that does not exist. |
| `Target '...' is not a safe node.` | `target` names a room or stair. |
| `The network has no safe node.` | No `add_safe` call. |
| `Population starts in safe node '...'.` | The start node of a population is safe. |
| `No route from '...' to safety.` | No chain of links from the start node to a safe node, or to the `target`. |
| `area_factor ... of the population in '...' exceeds max_density * area = ... of '...' on its route.` | An agent of the population would not fit into a node it may enter, even when that node is empty. With `split_ties=True` every tied route counts, so a run is rejected even if alternation might have kept the population off that node. |
| `runs must be at least 1.` | Raised by `run_many()` with fewer than one run. |
| `Initial population exceeds max_density in [...]` | Raised by `run()`: too many agents (weighted by area factor) in a start node. |
| `population i: Agent speeds must be positive.` | Raised by `run()`: population *i* (0-based) has a speed of 0, or a speed distribution produced 0 or, with `lower=None`, a negative value. |

The last three are raised by `run_many()` or `run()`, the others when
the `NetworkSimulation`, the `Population` or the distribution is
created. `max_density` at or below the peak-flow density 1.88 m⁻² with
`supply_reduction=True` issues a `UserWarning`: supply reduction has no
effect.

Every value or arithmetic error raised while the agents of a population are created names
that population as `population i:` (0-based) and keeps the original
message. It is a `ValueError`, with the original exception as
`__cause__`. For example, `LogNormal(0.0, 60.0)` as pre-movement gives
`population 0: float division by zero`.
