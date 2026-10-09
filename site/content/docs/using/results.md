---
title: Results
weight: 4
---

`run()` returns a `SimulationResult`, and `run_many()` returns a
`MonteCarloResult`. This page lists what each holds and how to report
it.

## One run: SimulationResult

| Field | Content |
|-------|---------|
| `evacuation_time` | Exit time of the last agent, in s, pre-movement included; `nan` if any agent is still inside at `t_max` |
| `exit_times` | Exit time per agent; `nan` for agents that did not reach safety |
| `pre_movement_times` | Sampled pre-movement time per agent |
| `times` | Time at the end of each step, starting with 0 |
| `node_occupancy[i, n]` | Number of agents in node `n` at `times[i]` |
| `link_flow[i, l]` | Number of agents that passed link `l` during the step ending at `times[i]`; row 0 is zero |
| `node_names`, `link_names` | Column labels of the two arrays |
| `evacuated` | Number of agents that reached safety |

An agent's exit time is the end of the step in which it passed its last
link, so exit times are multiples of `dt`.

`node_occupancy` counts heads. The density the model uses counts area
factors, so with area factors other than 1 the two differ.

With the [Getting started]({{< relref "/docs/getting-started" >}}) scenario:

```python
flight = result.node_names.index("flight")
door = result.link_names.index("office->flight")
print(result.node_occupancy[:, flight].max())
print(result.link_flow[:, door].sum())
print(result.times[1] - result.times[0], result.times[-1])
```

Output:

```
10
120
0.5 323.0
```

At most 10 agents are on the flight at once, all 120 pass the door,
and the run ends at 323.0 s in steps of 0.5 s.

## Many runs: MonteCarloResult

| Field | Content |
|-------|---------|
| `evacuation_times` | One evacuation time per run; `nan` for an incomplete run |
| `agent_counts` | Number of agents per run; varies when `count` is a distribution |
| `complete` | The evacuation times of the completed runs |
| `quantile(q)` | Quantile(s) of the evacuation time |

<!-- quantile: update after fix/quantile-censored -->
An incomplete run has agents inside at `t_max`, so its evacuation time
is only known to exceed `t_max`. In version 0.1.0 `quantile` is taken
over completed runs only
([t_max and incomplete runs]({{< relref "/docs/using/running#t_max-and-incomplete-runs" >}})).

## Reporting

- **State what the time includes.** `evacuation_time` is pre-movement
  plus movement of the simulated occupants. Detection and alarm times
  are included only if you added them to `pre_movement`. Call it an
  RSET only with that qualification.
- **Quantiles are conditional on the inputs.** The 95th percentile
  describes the spread caused by the input distributions you chose, not
  the uncertainty of the model.
- **Report the number of runs and of incomplete runs.** A high quantile
  of a few hundred runs has its own sampling error. Repeat the set with
  another seed; if the quantile moves by more than you can accept, use
  more runs.
- **Mention the limitations** that apply to your case
  ([Limitations]({{< relref "/docs/limitations" >}})). SFPE asks that results
  be presented with a description of the model limitations, including
  the level of validation {{< cite 1 "p. 2171" >}}.
