---
title: Getting started
weight: 1
---

Install `jupedsim_network`, build a three-node network, and compute the
evacuation time once and over 500 sampled runs. Each step shows the
output you should see.

## Install

You need Python 3.10 or later. The only dependency is NumPy 1.26 or
later. Install it from PyPI:

```
pip install jupedsim-network
```

**Check:** `python -c "import jupedsim_network"` returns without an
error.

## Run a first scenario

An office of 200 m² with 120 occupants empties through a 0.9 m door
into a stair flight, which leads to the street. Pre-movement times are
log-normal with a mean of 120 s and a standard deviation of 60 s.

```python
from jupedsim_network import LogNormal, Network, NetworkSimulation, Population

net = Network()
net.add_room("office", area=200.0)
net.add_stair("flight", area=10.8, riser=0.18, tread=0.28)
net.add_safe("street")
net.connect("office", "flight", width=0.9, length=25.0, bidirectional=False)
net.connect(
    "flight", "street", width=1.2, kind="stair", length=9.0, bidirectional=False
)

population = Population(
    "office", 120, speed=1.2, pre_movement=LogNormal(120.0, 60.0)
)
simulation = NetworkSimulation(net, [population], dt=0.5)

result = simulation.run(seed=1)
print(result.evacuation_time)

runs = simulation.run_many(500, seed=1)
print(runs.quantile([0.5, 0.95]))
```

Output:

```
323.0
[383.25 550.05]
```

The 500 runs take about 15 s on a laptop (Apple M3 Pro).

- `323.0` is the `evacuation_time` of the run with seed 1: the time in
  seconds at which the last agent reached the street, pre-movement
  included.
- `[383.25 550.05]` are the median and the 95th percentile of the
  evacuation time over 500 runs, each with newly sampled pre-movement
  times.

`bidirectional=False` creates each link in the walking direction only.
The default creates the reverse link as well; the two directions then
share one door
([Networks]({{< relref "/docs/using/networks#one-way-and-two-way-links" >}})).

## Check that every run finished

A run that still has agents inside at `t_max` (3600 s by default)
returns `nan`: its evacuation time is only known to exceed `t_max`.
`quantile` ranks such runs above every finished run and returns `inf`
for a quantile that depends on one of them. It issues a
`RuntimeWarning` whenever any run is incomplete. Count the incomplete
runs before you report a quantile:

```python
print(result.evacuated, "of", len(result.exit_times), "agents are safe")
print(runs.incomplete, "incomplete runs")
```

Output:

```
120 of 120 agents are safe
0 incomplete runs
```

If the count is not zero, raise `t_max` and run again
([Running]({{< relref "/docs/using/running#t_max-and-incomplete-runs" >}})).

## Try one change

Does a wider door help? First look at the latest start:

```python
print(round(result.pre_movement_times.max(), 1))

for width in (0.9, 1.2):
    test = Network()
    test.add_room("office", area=200.0)
    test.add_stair("flight", area=10.8, riser=0.18, tread=0.28)
    test.add_safe("street")
    test.connect(
        "office", "flight", width=width, length=25.0, bidirectional=False
    )
    test.connect(
        "flight",
        "street",
        width=1.2,
        kind="stair",
        length=9.0,
        bidirectional=False,
    )
    at_once = Population("office", 120, speed=1.2)
    print(width, NetworkSimulation(test, [at_once]).run(seed=1).evacuation_time)
```

Output:

```
291.9
0.9 184.0
1.2 162.5
```

In the first run the last agent starts at 291.9 s and leaves at 323.0 s.
The pre-movement times set the evacuation time, and a wider door changes
nothing. When everyone starts at once, the door decides: the 0.9 m door
passes 0.78 persons/s, and widening it to 1.2 m cuts the time from
184.0 s to 162.5 s. The stair link, at 0.91 persons/s, is then the
narrowest point.

## What happened

Each agent waits for its pre-movement time, walks 25 m to the door at a
speed that falls with the density of the office, queues, and passes the
door at most at the door's capacity. On the flight it walks 9 m along
the incline at stair
speed and leaves through the stair link. The
[model description]({{< relref "/docs/model" >}}) explains each step.

## If something goes wrong

| Message or symptom | Cause | Fix |
|--------------------|-------|-----|
| `ValueError: Initial population exceeds max_density in [...]`, raised by `run()` | More agents (weighted by area factor) than `max_density` × area in a start node | Enlarge the node, split the population, or check `count` |
| `ValueError: No route from '...' to safety.`, raised by `NetworkSimulation(...)` | No chain of links from the start node to a safe node, or to the `target` | Add the missing `connect` call; check the link direction |
| `ValueError: Agent speeds must be positive.` | A speed distribution produced 0, or a negative value with `lower=None` | Set `lower` above 0 on the speed distribution ([Populations]({{< relref "/docs/using/populations#distributions" >}})) |
| `evacuation_time` is `nan` | Some agents were still inside at `t_max` | Raise `t_max`, or look for a node that cannot empty |
| `RuntimeWarning: ... runs did not finish before t_max ...`; `quantile` returns `inf` | Some runs were still running at `t_max` | Raise `t_max` until `runs.incomplete` is 0 |

All error messages are listed in
[Networks]({{< relref "/docs/using/networks#errors" >}}) and
[Running]({{< relref "/docs/using/running#errors" >}}).

## Next steps

- [Office wing]({{< relref "/docs/examples/office-wing" >}}): a worked
  example with two floors, a stair and two exits, from floor plan to
  bottleneck.
- [Networks]({{< relref "/docs/using/networks" >}}): rooms, stairs and links
  for your own building.
- [Running]({{< relref "/docs/using/running" >}}): choosing the time step and
  `max_density`, and replaying a critical run.
- [Limitations]({{< relref "/docs/limitations" >}}): read before you use a
  result.
