---
title: Command line
weight: 5
---

The `jupedsim-network` command runs a scenario written as a JSON file
and writes the results to CSV and JSON files. It needs no Python code.
It calls the Python API, so a scenario gives the same results from the
file as from Python, byte for byte.

## Install

```bash
pip install jupedsim-network
```

This installs the `jupedsim-network` command. `python -m jupedsim_network`
runs the same command. The only dependency is still NumPy.

For coloured `--help` text, install the `cli` extra, which adds
`rich-argparse`:

```bash
pip install "jupedsim-network[cli]"
```

Without it, `--help` prints plain text with the same groups. Every
command works either way.

For the [terminal UI]({{< relref "/docs/using/terminal-ui" >}}), which
edits, checks and runs a scenario file in forms, install the `tui`
extra:

```bash
pip install "jupedsim-network[tui]"
```

## First run

Write the scenario of [Getting started]({{< relref "/docs/getting-started" >}})
to `scenario.json`:

```bash
jupedsim-network init
```

```console
Wrote scenario.json (the getting-started scenario).
Next steps:
  1. Check it: jupedsim-network check scenario.json
  2. Run it: jupedsim-network run scenario.json
  3. Edit nodes, connections and populations for your building, then check and run again.
```

Check it:

```bash
jupedsim-network check scenario.json
```

```console
Scenario scenario.json: 3 nodes, 2 links, 1 population.
Nodes:
  0   office           room   200 m²
  1   flight           stair  10.8 m²
  2   street           safe
Links:
  0   office->flight           door     0.78 persons/s
  1   flight->street           stair    0.91 persons/s
Populations:
  0   office           -> street
Trial run, seed 1: evacuation time 323.0 s; 120 of 120 agents safe.
The scenario is valid.
```

**Check:** the last line reads `The scenario is valid.` and the exit
status is 0 (`echo $?` prints `0`).

`check` builds the network and the simulation, lists the nodes with
their area, the links with their capacity and the safe node that each
population's route leads to, and makes one trial run. It writes no
files.

Run it:

```bash
jupedsim-network run scenario.json
```

```console
Scenario scenario.json: 3 nodes, 2 links, 1 population.
Run, seed 1: evacuation time 323.0 s; 120 of 120 agents safe.
Monte Carlo, 500 runs, seed 1: q 0.5 383.25 s, q 0.95 550.05 s; 0 incomplete.
Wrote scenario_results/: summary.json, agents.csv, link_flow.csv, occupancy.csv, runs.csv
```

The 500 runs take 15–20 s on a laptop (Apple M3 Pro).

**Check:** the `Monte Carlo` line ends with `0 incomplete`, and
`scenario_results/` holds five files.

These are the numbers of [Getting started]({{< relref "/docs/getting-started" >}}):
the door passes 0.78 persons/s and the stair link 0.91 persons/s, the
run with seed 1 ends at 323.0 s, and over 500 runs the median is
383.25 s and the 95th percentile 550.05 s. Getting started explains
them.

**Try one change.** Open `scenario.json`, set the `width` of the first
connection from `0.9` to `1.2`, and run `check` again. The `office->flight`
link gets a larger capacity, but the evacuation time of the trial run
stays the same: the pre-movement times set it
([Try one change]({{< relref "/docs/getting-started#try-one-change" >}})).

### The four commands

| Command | What it does |
|---------|--------------|
| `init [PATH] [--example NAME] [--force]` | Writes a packaged scenario to `PATH` (default `scenario.json`). `NAME` is `getting-started` (default) or `office-wing`, the [worked example]({{< relref "/docs/examples/office-wing" >}}). The file is copied unchanged. An existing file is kept unless you pass `--force`. |
| `check SCENARIO.json` | Builds the scenario, lists it and makes one trial run with the seed of `run.seed`. Writes nothing. |
| `run SCENARIO.json [options]` | Makes one run with `run.seed`, then a Monte Carlo set if the file has a `monte_carlo` section or `--runs` is given, and writes the result files. |
| `tui [SCENARIO.json] [--theme NAME]` | Opens the [terminal UI]({{< relref "/docs/using/terminal-ui" >}}); needs the `tui` extra. |

Options of `run`. Each one overrides the matching key of the file.

| Option | Overrides |
|--------|-----------|
| `-o DIR`, `--output DIR` | Result directory; default `<scenario stem>_results/` next to the scenario file |
| `--seed N` | `run.seed` |
| `--runs N` | `monte_carlo.runs` |
| `--mc-seed N` | `monte_carlo.seed` |
| `--quantile Q` | `monte_carlo.quantiles`; repeat it for several quantiles |
| `--no-monte-carlo` | Runs the single realisation only |

`run` writes `summary.json`, `agents.csv`, `link_flow.csv`,
`occupancy.csv` and, with Monte Carlo, `runs.csv` to `DIR`, replacing
files of the same name; without Monte Carlo it removes an earlier
`runs.csv`. Other files stay. An error writes nothing and leaves earlier
results in `DIR` as they were.

{{< callout type="warning" >}}
`check` makes one run with one seed. A scenario that passes can still
fail with another seed, for example when a sampled speed is 0 or a
sampled `count` overfills its start node. `run --runs 1000` can
therefore fail after `check` passed. "Valid" means that the file is
well formed and the API accepts it; it says nothing about whether the
model is valid for your building
([Limitations]({{< relref "/docs/limitations" >}})).
{{< /callout >}}

## The scenario file

This is the file that `init` writes. It describes the same building as
the Python code of
[Getting started]({{< relref "/docs/getting-started#run-a-first-scenario" >}}),
call for call:

```json
{
  "format_version": 1,
  "description": "Getting started: an office of 200 m² with 120 occupants empties through a 0.9 m door into a stair flight, which leads to the street. Pre-movement times are log-normal with a mean of 120 s and a standard deviation of 60 s.",
  "nodes": [
    {
      "name": "office",
      "kind": "room",
      "area": 200.0
    },
    {
      "name": "flight",
      "kind": "stair",
      "area": 10.8,
      "riser": 0.18,
      "tread": 0.28
    },
    {
      "name": "street",
      "kind": "safe"
    }
  ],
  "connections": [
    {
      "source": "office",
      "target": "flight",
      "width": 0.9,
      "length": 25.0,
      "bidirectional": false
    },
    {
      "source": "flight",
      "target": "street",
      "width": 1.2,
      "kind": "stair",
      "length": 9.0,
      "bidirectional": false
    }
  ],
  "populations": [
    {
      "node": "office",
      "count": 120,
      "speed": 1.2,
      "pre_movement": {
        "distribution": "LogNormal",
        "mean": 120.0,
        "std": 60.0
      }
    }
  ],
  "simulation": {
    "dt": 0.5
  },
  "run": {
    "seed": 1
  },
  "monte_carlo": {
    "runs": 500,
    "seed": 1,
    "quantiles": [
      0.5,
      0.95
    ]
  }
}
```

Each section goes to one part of the API:

| Key | Type | Goes to | Arguments on |
|-----|------|---------|--------------|
| `format_version` | integer, required | Must be `1` | |
| `description` | string | Free text, not passed on | |
| `nodes` | array, required | `add_room`, `add_stair` or `add_safe`, chosen by `kind` (`"room"`, `"stair"`, `"safe"`) | [Networks]({{< relref "/docs/using/networks#nodes" >}}) |
| `connections` | array, required | `Network.connect` | [Networks]({{< relref "/docs/using/networks#links" >}}) |
| `populations` | array, required, not empty | `Population` | [Populations]({{< relref "/docs/using/populations" >}}) |
| `simulation` | object | Keyword arguments of `NetworkSimulation` | [Running]({{< relref "/docs/using/running#settings" >}}) |
| `run` | object | `seed` of `run()` | [Running]({{< relref "/docs/using/running#one-run-many-runs" >}}) |
| `monte_carlo` | object | `runs` and `seed` of `run_many()`; `quantiles` for `quantile()` | [Running]({{< relref "/docs/using/running#one-run-many-runs" >}}), [Results]({{< relref "/docs/using/results#many-runs-montecarloresult" >}}) |

The arguments, their defaults and their errors are documented once, on
the pages in the last column. The rules below are those of the file.

### Keys are the argument names of the API

The loader reads the allowed keys from the signatures of the API, so
the file has no names of its own, and every value is passed on
unchanged. Two names differ from what you might guess: a population
starts in `node`, and a stair takes `riser` and `tread` in m.

Three names are not shared between the file and the API:

- `record` of `run()` is not in the file: `run` always records
  ([What the command line adds](#what-the-command-line-adds)).
- `progress` of `run_many()` is not in the file.
- `quantiles` is in the file only. It is not an argument of
  `run_many()`; it feeds `MonteCarloResult.quantile()`.

A key you leave out takes the API default. The loader adds no defaults
of its own. An unknown key is an error that lists the valid keys, so a
typo cannot fall back to a default without notice. Here `typo.json` is
a copy of `scenario.json` with `max_density` misspelt as `max_densty`:

```bash
jupedsim-network check typo.json
```

```console
jupedsim-network check: error: typo.json: simulation: unknown key 'max_densty'; valid keys: counterflow, dt, max_density, routing_policy, split_ties, supply_reduction, t_max
```

### Watch for these

- **Connections are two-way unless you say otherwise.** As in Python,
  `bidirectional` defaults to `true`: a connection without
  `"bidirectional": false` also creates the reverse link, and the two
  directions share one door under `counterflow`. The packaged scenarios
  set `false` on every connection
  ([One-way and two-way links]({{< relref "/docs/using/networks#one-way-and-two-way-links" >}})).
- **Order matters.** The API is called in array order. Node and link
  indices, the agent order and the rule that a route tie goes to the
  first link created all follow from it. Swapping two tied connections
  or two populations can change the result
  ([Routes]({{< relref "/docs/using/networks#routes" >}})).
- **Two keys are called `length`.** On a node, `length` × `width` only
  sets the area. On a connection, `length` is the distance walked in the
  source node, along the incline on a stair
  ([Length]({{< relref "/docs/using/networks#length" >}})).

### Distributions

`count`, `speed`, `pre_movement` and `start_distance` take a plain
number or a distribution object such as
`{"distribution": "LogNormal", "mean": 120.0, "std": 60.0}`.

- `distribution` is one of `Fixed`, `Uniform`, `Normal`, `LogNormal`,
  `Triangular` and `Weibull`.
- The other keys are the arguments of that class, plus `lower` and
  `upper` ([Distributions]({{< relref "/docs/using/populations#distributions" >}})).
- `area_factor` takes a plain number only.
- `"lower": null` is not the same as leaving `lower` out. Left out,
  the distribution keeps its default truncation at 0. `null` removes the
  lower bound. `lower` is the only key where `null` and a missing key
  differ.

### What the loader checks

- The structure: required and unknown keys, JSON types, duplicate keys,
  UTF-8 text, at most 64 levels of nesting, and finite numbers (`NaN`,
  `Infinity` and `1e999` are rejected).
- `monte_carlo.runs` is at least 1, and every quantile lies in [0, 1].
- Each distribution object is sampled once, with its own random
  generator, so the check does not change the results.

Every other check is done by the API, with the API's message. The
message starts with the JSON path of the entry
([Errors](#errors)).

Warnings, such as a stair outside the SFPE range or route ties with
`split_ties: false`, are printed to stderr as `warning: <path>: …` and
stored under `warnings` in `summary.json`. They never change the exit
status, so read every one.

### What the command line adds

Three behaviours belong to the command line and are not in the API:

- **Quantiles.** If neither the file nor `--quantile` gives quantiles,
  `run` reports 0.5 and 0.95.
- **Drawn seeds.** With `"seed": null`, or no seed, `check` and `run`
  draw a seed, print it as `seed <N> (drawn)` and store it in
  `summary.json` with `"seed_drawn": true`. In Python, `seed=None` uses
  a fresh seed that is never recorded.
- **Time series.** `run` always records occupancy and link flow. This
  does not touch the random numbers, so the results are the same.

`"runs": 0` in the file is an error, even when `--runs` is given.

### Input checks

The file and Python reject the same inputs with the same message, at
the JSON path of the entry; the list is on
[Limitations]({{< relref "/docs/limitations#input-checks" >}})
([issue #53](https://github.com/PedestrianDynamics/jupedsim-network/issues/53)).
For example, `riser` and `tread` in mm (`180` and `280`), a negative
plain `pre_movement`, `start_distance`, `speed` or `count`,
`area_factor` 0 or negative, a negative `boundary_layer`, a room with
`area` together with `length` or `width`, and a `dt` below 1e-6 s are
errors. A `Fixed`
value outside its bounds and a distribution with `lower` above `upper`
are rejected when the file is loaded. `max_density` at or below
1.88 m⁻² turns supply reduction off with a warning
([Limitations]({{< relref "/docs/limitations#movement-and-capacity" >}})).

## Result files

`run` writes these files to the result directory:

| File | Content |
|------|---------|
| `summary.json` | Inputs, seeds, evacuation time, quantiles, links and warnings (below) |
| `agents.csv` | One row per agent, in population order: sampled pre-movement time and exit time |
| `link_flow.csv` | Per step, the agents that passed each link |
| `occupancy.csv` | Per step, the agents in each node |
| `runs.csv` | Monte Carlo only: one row per run, with its evacuation time and number of agents |

All files are UTF-8 with `\n` line endings. Times are in s from the
start of the run, which is also the origin of `pre_movement`. A missing
value is an empty field in a CSV file and `null` in JSON.
`summary.json` repeats every unit in its `units` block.

The CSV headers of the getting-started run:

```csv
agent,pre_movement_sampled,exit_time
```

```csv
time,0:office->flight,1:flight->street
```

```csv
time,office,flight
```

```csv
run,evacuation_time,agents
```

- **`agents.csv`.** `exit_time` is empty for an agent still inside at
  `t_max`. The file has no population column, because a run does not
  record the population of an agent and `count` can be sampled; agents
  are in the order of the populations.
- **`link_flow.csv`** counts agents (heads) per step, in the step
  `(time − dt, time]`. It is not a flow rate: divide by `dt` for
  persons/s. Row 0 is time 0 and all zeros. Columns are headed
  `index:name`, because a custom name or two links between the same
  nodes can repeat a link name. The `links` list in `summary.json` maps
  each index to its source and target.
- **`occupancy.csv`** counts agents (heads) in each node at `time`, not
  the area-weighted load that `max_density` limits
  ([Limitations]({{< relref "/docs/limitations#output" >}})). Safe nodes
  are left out.
- **`runs.csv`.** `evacuation_time` is empty for an incomplete run.
  `agents` varies when `count` is a distribution.

{{< details title="Times in the files" closed="true" >}}

- The `time` column starts at 0, before the first step. Its last value
  can exceed `t_max` by less than `dt`. The values are those of the
  API's `times`, which the step loop rounds to 9 decimals.
- `exit_time` is the end of the step in which the agent reached safety,
  an upper bound to within `dt`. It equals the `time` value of that step
  in `link_flow.csv` and `occupancy.csv`, so the files join exactly. The
  value is the API's `exit_times`, written unchanged so that the files
  match Python.
- Monte Carlo quantiles in `summary.json` are interpolated between runs
  and are not step times.
- `pre_movement_sampled` is the sampled time. The agent starts walking
  at the first step that starts at or after it.
- The files keep every value at full precision. The terminal rounds
  times to 0.01 s and prints the shortest form, so a value in the
  terminal can differ in the last digits from the one in the files.
  Capacities are rounded too: `0.78` in the terminal is
  `0.7800000000000001` in `summary.json`. An
  unfinished quantile prints as `> t_max`. An unfinished run prints
  `not finished by t_max; <k> of <n> agents safe.`

{{< /details >}}

{{< details title="Fields of summary.json" closed="true" >}}

- `format_version` (1) and `jupedsim_network`, the package version.
- `scenario`: `path` as given on the command line, and `sha256` of the
  file's bytes.
- `units`: the unit and time base of every column.
- `dt` and `t_max`.
- `run`: `seed`, `seed_drawn`, `evacuation_time` (`null` if an agent was
  still inside at `t_max`), `agents` and `evacuated`.
- `monte_carlo`, or `null` without Monte Carlo: `runs`, `seed`,
  `seed_drawn`, `incomplete`, and `quantiles` as a list of `q` and
  `value`. `value` is `null` where the quantile is only known to exceed
  `t_max` (`inf` in Python).
- `links`: index, name, source, target, kind and capacity in persons/s
  of every link, reverse links included.
- `warnings`.

{{< /details >}}

## Seeds and reproducibility

`run.seed` and `monte_carlo.seed` are separate seeds. They give the same
results as `run(seed)` and `run_many(runs, seed)` in Python, byte for
byte. `--seed` overrides the first and `--mc-seed` the second.

To replay a run with a drawn seed, pass the printed value in place of
`N`, for example `--seed 1234`:

```console
jupedsim-network run scenario.json --seed N
```

`--mc-seed` replays a whole Monte Carlo set. The command line cannot
replay one run of a set. Use Python for that: row *i* of `runs.csv` is
the run with seed `numpy.random.SeedSequence(seed).spawn(runs)[i]`
([Replay a critical run]({{< relref "/docs/using/running#replay-a-critical-run" >}})).

A result is fixed by four things: the scenario file (its `sha256` is in
`summary.json`), the seeds, the jupedsim-network version (also in
`summary.json`) and the major version of NumPy. Keep `summary.json`
with the results.

- **A file means "these inputs under this version's defaults".**
  `format_version` versions the layout of the file, not the model
  defaults. A key left out takes the default of the installed version,
  which can change between versions.
- **NumPy 1 and NumPy 2 differ slightly.** `summary.json`,
  `link_flow.csv`, `occupancy.csv` and `runs.csv` are the same.
  `agents.csv` differs in the last digits of a few sampled pre-movement
  times.

## Exit status

| Code | Meaning |
|------|---------|
| 0 | `run`: every run finished. `check`: the scenario is valid and the trial run finished. `init`: the file was written. |
| 2 | `run`: the single run or at least one Monte Carlo run did not finish by `t_max`. All result files are written. `check`: the scenario is valid, but the trial run did not finish by `t_max`. |
| 1 | An error, including a wrong option. An error message and no traceback. Nothing is written, and earlier results in `DIR` stay as they were. |
| 130 | Interrupted with Ctrl-C. The message `jupedsim-network: interrupted` and no traceback. Nothing is written, except when the interrupt falls while the finished files are moved into `DIR`; then `DIR` can hold a mix of new and earlier files. |

Code 2 is not an error: the results are written, and the quantiles that
depend on unfinished runs read `> t_max`
([t_max and incomplete runs]({{< relref "/docs/using/running#t_max-and-incomplete-runs" >}})).
A shell script with `set -e` that expects unfinished runs must accept 2:

```bash
jupedsim-network run scenario.json || [ $? -eq 2 ]
```

A wrong option also gives 1, unlike the usual 2 of Python's
`argparse`, so that 2 always means an unfinished run.

## From Python

Five names of `jupedsim_network.scenario` move a scenario between
Python and the file. They are importable from `jupedsim_network`. To
write the [Getting started]({{< relref "/docs/getting-started" >}})
simulation to a file and run it from there:

```python
from jupedsim_network import Scenario, load_scenario, save_scenario

scenario = Scenario.from_simulation(
    simulation,
    seed=1,
    monte_carlo={"runs": 500, "seed": 1, "quantiles": [0.5, 0.95]},
)
save_scenario(scenario, "office.json")

loaded = load_scenario("office.json")
result = loaded.simulation.run(seed=loaded.run_seed)
```

`result` is the same as `simulation.run(seed=1)`, byte for byte.
`jupedsim-network run office.json` gives the same numbers as the
packaged file.

- **`Scenario.from_simulation(simulation, *, seed=None, monte_carlo=None, description=None)`**
  writes the arguments that the network, the populations and the
  simulation were built with, in the order they were created.
  - An argument equal to its API default is left out.
  - Derived values, such as capacities, are never written.
  - `seed=None` leaves out the `run` section, and `monte_carlo` takes a
    dict as above.
  - What the format cannot express raises `ScenarioError` with its
    path: a `Distribution` subclass of your own or a node name that is
    not a string. Nothing is dropped without notice.
- **`save_scenario(scenario, path)`** writes UTF-8 JSON indented by two
  spaces, in key order, and adds no defaults. `scenario` is a
  `Scenario`, a scenario dict, which is checked and built first, or a
  `NetworkSimulation`, which is written without a `run` or
  `monte_carlo` section. A file written by `save_scenario` is written
  again byte for byte by `save_scenario(load_scenario(path), path2)`.
- **`load_scenario(path)`** reads, checks and builds a scenario and
  returns a `Scenario`. It raises `ScenarioError` for an invalid
  scenario and `OSError` for a file it cannot read.
- **`scenario_from_dict(data, source=None)`** checks and builds a
  scenario held in memory. The terminal UI checks every edit with it.
  - `data` is what `json.load` returns: dicts, lists, strings, finite
    numbers, booleans and `None`. A tuple is rejected.
  - The checks and messages are those of `load_scenario`, except the
    checks of the JSON text itself (UTF-8, duplicate keys).
  - It returns a `Scenario` whose `data` is a copy of `data`.
  - `source` is stored as `Scenario.source`.
  - It raises `ScenarioError`.
- **`Scenario`** is a frozen dataclass with
  - `data`, the document in file order, as a plain dict: changing it
    does not change `simulation`, and `save_scenario` writes it without
    checking it again
    ([issue #47](https://github.com/PedestrianDynamics/jupedsim-network/issues/47)).
    To edit a scenario, change a dict of your own and pass it to
    `scenario_from_dict` or `save_scenario`, which checks a dict first;
  - `simulation`, the `NetworkSimulation` built at load;
  - `warnings`, a tuple of messages that start with their path;
  - `source`, the path of the file, or `None`;
  - the properties `run_seed` and `monte_carlo`;
  - `build()`, which builds a fresh simulation and returns it with its
    warnings;
  - `to_dict()`.
- **`ScenarioError`** is a `ValueError` with `path` (such as
  `"connections[1].width"`) and `message`. `str()` gives
  `"<path>: <message>"`.

An exported file is shorter than the packaged one. Exported from the
Getting started simulation, it has no `"speed": 1.2`, an empty
`"simulation": {}` (0.5 s is the default `dt`) and the stair keys in
the order of the signature. Both files build the same simulation, but
the exported one lists only what differs from the defaults of the
installed version.

## Errors

A scenario error ends the command with one line on stderr: the file,
the JSON path of the entry and the message.

```console
jupedsim-network check: error: typo.json: simulation: unknown key 'max_densty'; valid keys: counterflow, dt, max_density, routing_policy, split_ties, supply_reduction, t_max
jupedsim-network check: error: speed0.json: populations[0]: Agent speeds must be positive.
jupedsim-network check: error: ln0.json: populations[0].pre_movement: cannot sample LogNormal(lower=0.0, upper=None, mean=0, std=60.0): float division by zero
jupedsim-network check: error: policy.json: simulation.routing_policy: routing_policy must be one of 'shortest_distance', 'shortest_free_flow_time'; got 'fastest'.
```

The first and the last are found while the file is loaded. The second
comes from the trial run, so `check` prints the scenario listing first.
A wrong option prints the `usage:` line before the error.

- After the path comes the API's own message. The tables on
  [Networks]({{< relref "/docs/using/networks#errors" >}}) and
  [Running]({{< relref "/docs/using/running#errors" >}}) list them with
  their causes.
- Populations are counted from 0: `populations[0]` on the command line
  is `population 0` in Python.
- `Initial population exceeds max_density in [...]` concerns all
  populations together and has the path `run`.
- A file that is not UTF-8 gives
  `not UTF-8 text: byte 0xNN at position P; save the file as UTF-8`.
  Save it again as UTF-8.

## Next steps

- [Terminal UI]({{< relref "/docs/using/terminal-ui" >}}): edit, check
  and run the same file in forms.
- [Networks]({{< relref "/docs/using/networks" >}}) and
  [Populations]({{< relref "/docs/using/populations" >}}): the keys of
  `nodes`, `connections` and `populations`, with their defaults.
- [Running]({{< relref "/docs/using/running" >}}): choosing `dt`,
  `max_density` and `t_max`.
- [Limitations]({{< relref "/docs/limitations" >}}): read before you use
  a result.
