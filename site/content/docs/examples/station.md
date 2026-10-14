---
title: The Station nightclub
weight: 2
---

A published network model of a real building, rebuilt here and run
against the results that its author reports for EvacuatioNZ. The
building is the Station nightclub, the case is NIST's Scenario #1 (the
design-load evacuation, not the night of the fire), and the network
comes from Spearpoint's study {{< cite 8 "Fig. 1(b), p. 167; Table 1, p. 160" >}}. The
script is
[`examples/station.py`](https://github.com/PedestrianDynamics/jupedsim-network/blob/main/examples/station.py);
read [Getting started]({{< relref "/docs/getting-started" >}}) and the
[office wing]({{< relref "/docs/examples/office-wing" >}}) first.

{{< callout type="info" >}}
This is model-to-model agreement on a published network. It is not
validation against the incident, a drill or an experiment; Spearpoint
states the same for EvacuatioNZ (p. 180) {{< cite 8 "p. 180" >}}.
Every number on this page comes from running the script and the
sweeps in `scripts/figures/scenarios.py` with the current version.
The dimensions are read from a figure of the paper
([Limits of this study](#limits-of-this-study)).
{{< /callout >}}

## The building and Scenario #1

The nightclub has ten spaces and four exits: the front, platform, side
and kitchen exit doors. At the design load of Table 1 it holds 420
people {{< cite 8 "Table 1, p. 160" >}}. EvacuatioNZ v2.3 evacuates them
in 493 s when every occupant takes the nearest exit
{{< cite 8 "p. 166" >}}. NIST's Simulex and buildingEXODUS models give
188 s and 202 s when the occupants use the exits that NIST assigned
{{< cite 38 "§6.6, Table 6-2" >}}, {{< cite 8 "Table 3, p. 162" >}}.
This page builds the network of Spearpoint's study, runs the cases of
that study and compares each result with its published value or with a
hand calculation. The page names every difference.

![The Station network: ten spaces and four exits, with the routes of the baseline case in blue and the routes to the front door of the 60/40 case in orange](/images/network/station_network.png)

[Open the network at full size](../../../images/network/station_network.png).

The drawing is a schematic. Circles are spaces with their number of
occupants, the empty circles are the exits, and every arrow is one link
in the direction of egress.

## The network

### Nodes

Every space is a room node with its length and width from the figure of
the paper (Fig. 1(b), p. 167). The occupants are those of Spearpoint's
Table 1 {{< cite 8 "Table 1, p. 160" >}}. NIST gives no list per room;
its simulations place the same 420 people by density
{{< cite 39 "pp. L-1–L-2, L-5" >}} {{< cite 38 "§6.6, p. 6-25" >}}, and
Spearpoint's counts of each space are the only per-room listing. The area
and the initial density are derived from these inputs.

| Node | Size (m) | Area (m²) | Occupants | Initial density (m⁻²) |
|------|----------|-----------|-----------|-----------------------|
| dart | 7.2 × 5.4 | 38.9 | 39 | 1.00 |
| kitchen | 7.2 × 2.2 | 15.8 | 3 | 0.19 |
| bar | 8.5 × 7.6 | 64.6 | 31 | 0.48 |
| dance | 13.2 × 7.8 | 103.0 | 237 | 2.30 |
| entrance | 2.0 × 4.6 | 9.2 | 0 | 0.00 |
| sunroom | 10.9 × 4.6 | 50.1 | 76 | 1.52 |
| hallway | 4.8 × 8.2 | 39.4 | 12 | 0.30 |
| platform | 12.2 × 2.2 | 26.8 | 18 | 0.67 |
| stage | 5.2 × 3.6 | 18.7 | 4 | 0.21 |
| stageside | 2.4 × 3.6 | 8.6 | 0 | 0.00 |

The dance floor starts at 2.30 m⁻², above the 1.88 m⁻² where the supply
reduction begins and below the default `max_density` of 2.75 m⁻². The
model refuses a limit below 2.302 m⁻² for this start.
Both values come from the model, not from the paper: 1.88 m⁻² is
$1/(2a)$ with $a$ = 0.266 m², and 2.302 m⁻² is the `max_density` check of
`NetworkSimulation`
([Limitations]({{< relref "/docs/limitations" >}})).

### Links

Every link is a one-way door (`kind="door"`) in the direction that the
route tables use, with `specific_flow=1.33`. Widths and lengths are
inputs read from Fig. 1(b) {{< cite 8 "p. 167" >}}. Spearpoint applies
the boundary layer of 0.15 m to all constrictions
{{< cite 8 "p. 169" >}}; here it is applied to every link by reading that
statement, including the 9.2 m opening to the sunroom and the 2.5 m
opening of the dart room. Spearpoint's lengths run from centre to centre
{{< cite 8 "p. 166" >}}; this model walks the length inside the source
node.

| From → to | Width (m) | Length (m) | Capacity (persons/s) |
|-----------|-----------|------------|----------------------|
| dart → kitchen | 0.6 | 3.7 | 0.399 |
| dart → dance | 2.5 | 10.4 | 2.926 |
| kitchen → dance | 0.91 | 10.4 | 0.811 |
| kitchen → kitchen_exit | 0.91 | 3.6 | 0.811 |
| bar → side | 0.91 | 3.8 | 0.811 |
| bar → dance | 1.2 | 11.6 | 1.197 |
| bar → entrance | 0.91 | 5.2 | 0.811 |
| dance → entrance | 0.91 | 9.6 | 0.811 |
| sunroom → dance | 9.2 | 6.1 | 11.837 |
| entrance → front | 1.83 | 2.3 | 2.035 |
| hallway → dance | 1.6 | 8.0 | 1.729 |
| platform → dance | 1.4 | 10.0 | 1.463 |
| stage → stageside | 1.4 | 3.8 | 1.463 |
| dance → stageside | 2.4 | 8.9 | 2.793 |
| stageside → platform_exit | 0.91 | 1.8 | 0.811 |

The capacity is $C = F_s\,(w - 2b)$ with $F_s = 1.33$ persons/s/m and
$b = 0.15$ m on each side {{< cite 8 "p. 169" >}}; the 0.30 m of
Spearpoint is both sides. The model computes the capacities in the table
(`Link.capacity`). A 0.91 m door passes 0.811 persons/s. The links into the exits are
dart → kitchen → kitchen_exit, bar → side, entrance → front and
stageside → platform_exit.

{{< details title="The tables and the builder in the script" closed="true" >}}

The script starts with its imports:

```python
import math

import numpy as np

from jupedsim_network import (
    Network,
    NetworkSimulation,
    Population,
    Uniform,
)
```

```python
# Spaces: name -> (length, width) in m, read from Fig. 1(b) of Spearpoint.
ROOMS = {
    "dart": (7.2, 5.4),
    "kitchen": (7.2, 2.2),
    "bar": (8.5, 7.6),
    "dance": (13.2, 7.8),
    "entrance": (2.0, 4.6),
    "sunroom": (10.9, 4.6),
    "hallway": (4.8, 8.2),
    "platform": (12.2, 2.2),
    "stage": (5.2, 3.6),
    "stageside": (2.4, 3.6),
}
SAFE = ("front", "side", "kitchen_exit", "platform_exit")
```

```python
# Occupants of each space (Table 1 of Spearpoint), 420 in all.
OCCUPANTS = {
    "dart": 39,
    "kitchen": 3,
    "bar": 31,
    "dance": 237,
    "sunroom": 76,
    "hallway": 12,
    "platform": 18,
    "stage": 4,
}
```

```python
# Links in the direction of egress: (source, target, clear width in m,
# connection length in m walked inside the source). The widths are the
# door widths before the boundary layer is taken off.
LINKS = [
    ("dart", "kitchen", 0.6, 3.7),
    ("dart", "dance", 2.5, 10.4),
    ("kitchen", "dance", 0.91, 10.4),
    ("kitchen", "kitchen_exit", 0.91, 3.6),
    ("bar", "side", 0.91, 3.8),
    ("bar", "dance", 1.2, 11.6),
    ("bar", "entrance", 0.91, 5.2),
    ("dance", "entrance", 0.91, 9.6),
    ("sunroom", "dance", 9.2, 6.1),
    ("entrance", "front", 1.83, 2.3),
    ("hallway", "dance", 1.6, 8.0),
    ("platform", "dance", 1.4, 10.0),
    ("stage", "stageside", 1.4, 3.8),
    ("dance", "stageside", 2.4, 8.9),
    ("stageside", "platform_exit", 0.91, 1.8),
]
# The stage side is walked back to the dance floor only by the stage
# occupants who head for the front entrance.
STAGESIDE_LINK = ("stageside", "dance", 2.4, 8.9)
```

```python
# Exits assigned to the occupants of each space (Table 5 of Spearpoint).
TABLE_5 = {
    "dart": {"front": 39},
    "sunroom": {"front": 38, "platform_exit": 38},
    "dance": {"front": 118, "platform_exit": 119},
    "bar": {"front": 11, "side": 20},
    "platform": {"front": 6, "platform_exit": 12},
    "hallway": {"platform_exit": 12},
    "stage": {"platform_exit": 4},
    "kitchen": {"kitchen_exit": 3},
}
PREFERRED_SHARE = 0.6

SPEED = 1.2
SPECIFIC_FLOW = 1.33
```

`build_network` turns the tables into a `Network`. Its arguments are
the ones that the cases below change: the boundary layer, the extra
link of the 60/40 case, the specific flow, and a factor on the length of
`dance->entrance` for the [tie](#a-tie-in-the-connection-length).

```python
def build_network(
    boundary_layer=0.15,
    stageside_link=False,
    specific_flow=SPECIFIC_FLOW,
    dance_entrance_factor=1.0,
    parameters=None,
):
    """The nightclub; every link is a one-way door."""
    net = Network(parameters=parameters)
    for name, (length, width) in ROOMS.items():
        net.add_room(name, length=length, width=width)
    for name in SAFE:
        net.add_safe(name)
    links = LINKS + [STAGESIDE_LINK] * stageside_link
    for source, target, width, length in links:
        if (source, target) == ("dance", "entrance"):
            length *= dance_entrance_factor
        net.connect(
            source,
            target,
            kind="door",
            width=width,
            length=length,
            specific_flow=specific_flow,
            boundary_layer=boundary_layer,
            bidirectional=False,
        )
    return net
```

{{< /details >}}

### Routes

Each space leaves by the nearest exit. By hand: the dart room goes to
the kitchen door (3.7 + 3.6 = 7.3 m against 21.1 m by the dance floor),
the main bar to its side door (3.8 m against 7.5 m through the entrance),
the kitchen to the kitchen door, and every other space to the platform
door. From the dance floor the platform door is 8.9 + 1.8 = 10.7 m away
and the front door 9.6 + 2.3 = 11.9 m {{< cite 8 "p. 168" >}}. The split is 347 through the
platform door, 31 through the side door, 42 through the kitchen door and
none through the front door, the split that EvacuatioNZ v2.3 reports
{{< cite 8 "p. 166" >}}. The model's route table gives the same
([Run it](#run-it)).

## Settings mapped from Spearpoint

Spearpoint's settings are on pp. 164–166 {{< cite 8 "pp. 164–166" >}}, and
his door flow of 1.33 persons/s/m is on p. 169.

| Spearpoint (EvacuatioNZ v2.3) | This model | Kind of decision |
|-------------------------------|------------|------------------|
| time step 1 s | `dt=0.5`, repeated at 0.1 and 1.0 | engineering choice |
| speed 1.2 m/s, $S = k(1 - 0.266\,D)$ | `speed=1.2`, level $k$ = 1.4 m/s, floor $D$ = 0.54 m⁻² | same relation |
| door flow 1.33 persons/s/m | `specific_flow=1.33` on each link | engineering choice (below) |
| boundary layer 0.15 m on every constriction | `kind="door"`, `boundary_layer=0.15` everywhere | literature {{< cite 8 "p. 169" >}} |
| "widened by 0.30 m, no boundary layer" | `boundary_layer=0.0`, widths unchanged | identity |
| node limit 2.75 m⁻², hard | `max_density=2.75`, supply reduction on (S0) and off (S0s) | model difference, reported |
| connection length between nodes; random start | length walked in the source; start distance 0 | engineering convention |
| exit by minimum distance, ties random | shortest distance, ties alternated | matters only at an exact tie |
| exits prescribed by room and preferred route (60 %) | `target` with fixed counts | approximation |
| sequential update, $N/C$ per door | synchronous steps, $(N - 1)/C$, exit at $t + \Delta t$ | model difference, up to 1/C per door |
| no counterflow | no two-way pair in the network | identity |

`HydraulicParameters(door_specific_flow=1.33)` is rejected, because
1.33 persons/s/m is above the maximum flow k/(4a) = 1.316 persons/s/m
that the model allows for a door. The flow is therefore set on each link,
which skips that check
([issue #83](https://github.com/PedestrianDynamics/jupedsim-network/issues/83)).
For buildingEXODUS, NIST sets a flow of 1.22 persons/s/m on two 0.5 m
nodes for every 36 in door, "in order to equate to the default of 1.33
occ/m/s" on 0.91 m, and no boundary layer; the main door is 2 m wide at
1.2 persons/s/m {{< cite 39 "p. L-1" >}}. That is 1.22 persons/s per
door, which is 1.33 × 0.91 to within rounding. For Simulex, NIST gives
the widths and no flow {{< cite 39 "p. L-5" >}}.

## Occupants and settings

Three assignments of the occupants to exits are used, selected by `case`.
`"nearest"` sends everyone to the nearest exit, the baseline.
`"table5"` sends each space to the exits that Spearpoint lists in his
Table 5 {{< cite 8 "p. 170" >}}. `"preferred"` is the 60/40 case
{{< cite 8 "p. 171" >}}: 60 % of each space, rounded to whole agents with
`round`, go to the front door, and the others take the nearest exit.
That gives 252 of the 420 to the front door, 60.0 %.

The 60/40 case sends some occupants of the stage to the front door, which
they reach only by walking back to the dance floor. It therefore adds the
link stageside → dance, in the one direction. The link lies on no
shortest route, and no other case has it.

```python
def exits(case, node):
    """(target, agents) of the occupants of ``node``; ``None`` is nearest."""
    count = OCCUPANTS[node]
    if case == "nearest":
        return [(None, count)]
    if case == "table5":
        return list(TABLE_5[node].items())
    front = round(PREFERRED_SHARE * count)
    return [("front", front), (None, count - front)]


def populations(case="nearest", random_start=False):
    """Everyone moves at t = 0. ``case`` is ``"nearest"``, ``"preferred"``
    (60 % of each space head for the front door) or ``"table5"``."""
    pops = []
    for node in OCCUPANTS:
        start = Uniform(0.0, math.hypot(*ROOMS[node])) if random_start else 0.0
        for target, count in exits(case, node):
            pops.append(
                Population(
                    node,
                    count,
                    speed=SPEED,
                    start_distance=start,
                    target=target,
                )
            )
    return pops
```

```python
def simulation(
    case="nearest",
    random_start=False,
    dt=0.5,
    max_density=2.75,
    supply_reduction=True,
    routing_policy="shortest_distance",
    **network_options,
):
    """The case on a network; ``network_options`` go to ``build_network``."""
    network_options.setdefault("stageside_link", case == "preferred")
    return NetworkSimulation(
        build_network(**network_options),
        populations(case, random_start),
        dt=dt,
        t_max=1800.0,
        max_density=max_density,
        supply_reduction=supply_reduction,
        routing_policy=routing_policy,
    )
```

- **Start.** Everyone starts at once with no pre-movement time and walks
  at 1.2 m/s (Spearpoint's first phase). The start distance is 0, so the
  walk to a door is the link length.
- **`t_max=1800.0`** is far above every result below.
- **`max_density=2.75`** is the default and the limit of EvacuatioNZ {{< cite 8 "pp. 164–166" >}}.

## Run it

Clone the repository, install the package from the clone and run the
script from the repository root. It takes a few seconds.

```
git clone https://github.com/PedestrianDynamics/jupedsim-network.git
cd jupedsim-network
pip install .
python examples/station.py
```

The script runs these steps:

```python
def main():
    net = build_network()
    report_network(net)
    print()

    report_run("S0", simulation().run(seed=1))
    report_run("S0s", simulation(supply_reduction=False).run(seed=1))
    report_run("S1", simulation(boundary_layer=0.0).run(seed=1))
    report_run("S3", simulation("preferred").run(seed=1))
    report_run("S3n", simulation("preferred", boundary_layer=0.0).run(seed=1))
    report_run("S2", simulation("table5", boundary_layer=0.0).run(seed=1))
    report_run("S2b", simulation("table5").run(seed=1))
    print()

    result = simulation().run(seed=1)
    door = "stageside->platform_exit"
    for number in (1, 5):
        print(
            f"passage {number} through the platform door: "
            f"{passage_time(result, door, number):.1f} s"
        )
    for dt in (0.1, 0.5, 1.0):
        print(f"dt {dt}: {simulation(dt=dt).run(seed=1).evacuation_time:.1f} s")


if __name__ == "__main__":
    main()
```

{{< details title="The report functions" closed="true" >}}

They only read the network and the results.

```python
def exit_links(result):
    """Names of the links into the four exits, in the order of ``SAFE``."""
    return [name for name in result.link_names if name.split("->")[1] in SAFE]


def exit_counts(result):
    """Agents through the platform, side, kitchen and front exits."""
    order = ("platform_exit", "side", "kitchen_exit", "front")
    flow = {
        name.split("->")[1]: result.link_flow[:, result.link_names.index(name)]
        for name in exit_links(result)
    }
    return [int(flow[exit].sum()) for exit in order]


def agents_inside(result, time):
    """Agents in the building at ``time``."""
    row = np.isclose(result.times, time)
    return int(result.node_occupancy[row].sum())


def passage_time(result, link, number=1):
    """Time of the ``number``-th passage through ``link``."""
    flow = result.link_flow[:, result.link_names.index(link)]
    passed = np.cumsum(flow)
    return float(result.times[np.argmax(passed >= number)])
```

```python
def report_network(net):
    for link in net.links:
        print(f"{link.name:26s} {link.capacity:.3f} persons/s")
    routes = net.route_table()
    for name in OCCUPANTS:
        link = net.links[routes[net.node(name).index]]
        print(f"{name} leaves through {link.name}")


def report_run(label, result):
    platform, side, kitchen, front = exit_counts(result)
    print(
        f"{label}: {result.evacuation_time:.1f} s; platform {platform}, "
        f"side {side}, kitchen {kitchen}, front {front}; "
        f"{agents_inside(result, 90.0)} inside at 90 s"
    )
```

{{< /details >}}

The first part of the output is the capacity of every link and the exit
of every space from the route table:

```text
dart->kitchen              0.399 persons/s
dart->dance                2.926 persons/s
kitchen->dance             0.811 persons/s
kitchen->kitchen_exit      0.811 persons/s
bar->side                  0.811 persons/s
bar->dance                 1.197 persons/s
bar->entrance              0.811 persons/s
dance->entrance            0.811 persons/s
sunroom->dance             11.837 persons/s
entrance->front            2.035 persons/s
hallway->dance             1.729 persons/s
platform->dance            1.463 persons/s
stage->stageside           1.463 persons/s
dance->stageside           2.793 persons/s
stageside->platform_exit   0.811 persons/s
dart leaves through dart->kitchen
kitchen leaves through kitchen->kitchen_exit
bar leaves through bar->side
dance leaves through dance->stageside
sunroom leaves through sunroom->dance
hallway leaves through hallway->dance
platform leaves through platform->dance
stage leaves through stage->stageside
```

The second part is one line per case: the evacuation time, the agents
through each exit and the agents still inside at 90 s.

```text
S0: 442.0 s; platform 347, side 31, kitchen 42, front 0; 291 inside at 90 s
S0s: 443.5 s; platform 347, side 31, kitchen 42, front 0; 292 inside at 90 s
S1: 303.0 s; platform 347, side 31, kitchen 42, front 0; 258 inside at 90 s
S3: 308.0 s; platform 139, side 12, kitchen 17, front 252; 257 inside at 90 s
S3n: 214.0 s; platform 139, side 12, kitchen 17, front 252; 202 inside at 90 s
S2: 187.5 s; platform 185, side 20, kitchen 3, front 212; 214 inside at 90 s
S2b: 269.0 s; platform 185, side 20, kitchen 3, front 212; 269 inside at 90 s
```

The last part is the time of the first and of the fifth passage through
the platform door and the baseline at three time steps:

```text
passage 1 through the platform door: 5.5 s
passage 5 through the platform door: 20.5 s
dt 0.1: 441.3 s
dt 0.5: 442.0 s
dt 1.0: 442.0 s
```

## Baseline: S0

Case S0 sends everyone to the nearest exit, with the boundary layer and the
supply reduction on, at `dt=0.5`. The model evacuates the 420 people in
442.0 s: 347 through the platform door, 31 through the side door, 42
through the kitchen door and none through the front door. 291 are still
inside at 90 s.

![Agents safe over time for S0, S0s, S1 and S3n, with the published EvacuatioNZ end points of S0, S1 and S3n and the 90 s counts of S0 and S3n](/images/network/station_exits.png)

### How the result arises

The evacuation time is a door-flow calculation: in every case it is the
first arrival at the controlling 0.91 m door plus (N − 1)/C. Here the
controlling door is the platform door, with $C$ = 0.8113 persons/s.

- **Other doors.** The side door has passed its 31 agents after 40.0 s
  and the kitchen door its 42 after 102.5 s, limited by the 0.6 m door of
  the dart room (0.399 persons/s).
- **First arrival.** The four occupants of the stage pass the platform
  door first, from 5.5 s. The fifth passage is the first agent of the
  dance floor, at 20.5 s. By hand, the first agent walks 8.9 m at
  $S(D)$ for $D$ between 2.30 and 2.75 m⁻², then 1.8 m in the stage side:
  between 17.9 s and 25.2 s.
- **Then the door is busy.** The door passes at most $1 + C\,t$ agents in
  any interval $t$, and it does not idle. The other 342 agents take
  342/0.8113 = 421.5 s, so $T = t_5 + 342/C$ = 20.5 + 421.5 = 442.0 s, the
  model's value.
- **Hand value of the paper.** Spearpoint's hand calculation is
  $N/C$ = 347/0.811 = 428 s {{< cite 8 "p. 169" >}}. The model's 442.0 s
  lies 14 s above it, less than the 20.5 s of the first arrival. This
  model reproduces the route split of EvacuatioNZ v2.3 exactly and
  Spearpoint's hand calculation within the first arrival time.
- **Inside at 90 s.** By 90 s the platform door has passed the first
  four and then 0.811 persons/s from 20.5 s, the dart door
  0.399 persons/s from 14.0 s (the kitchen door follows 3 s later, the
  walk of 3.6 m), and the side door all 31. That leaves 290.5 inside, to
  within 8 agents (one per door, and a spread of 4 s in the arrival).
  The model has 291 and EvacuatioNZ 291 {{< cite 8 "p. 166" >}}.

### The gap to EvacuatioNZ

EvacuatioNZ v2.3 gives 493 s, 51 s more than the model (−10 % for the
model). Spearpoint's own hand value is 428 s {{< cite 8 "p. 169" >}}, so v2.3 lies 65 s above its
hand value and this model 14 s. The difference to EvacuatioNZ v2.3
(493 s against 442 s) is a difference between the two models; its cause
in v2.3 is not published.

The paper describes the hand value as lower than the EvacuatioNZ result
"when the modeling also includes some additional travel time through the
front entrance" {{< cite 8 "p. 169" >}}, although no agent uses the front
door in this baseline. It does not name door start-up, the node limit or
the time step as causes. The differences between the models that the
[settings table](#settings-mapped-from-spearpoint) lists do not account
for 51 s:

- **Supply reduction** changes the result by 1.5 s (S0s below).
- **The time step** moves it by at most 0.7 s (S0 at three steps below).
- **The passage convention**, $(N - 1)/C$ against $N/C$ and one step for
  the exit, is at most 1.2 s per door.

### Variants of S0

| Variant | Change | Time (s) | Difference to S0 (s) |
|---------|--------|----------|----------------------|
| S0s | `supply_reduction=False` | 443.5 | +1.5 |
| S0, `dt=0.1` | time step 0.1 s | 441.3 | −0.7 |
| S0, `dt=1.0` | time step 1.0 s | 442.0 | 0.0 |

Supply reduction changes the result by 1.5 s here, because it acts only
while the dance floor is above 1.88 m⁻² and delays the first arrival. The
split is 347, 31, 42 and 0 at every time step.

**S0r: random start distances.** Spearpoint starts each agent at a random
distance from the door {{< cite 8 "p. 166" >}}. S0r draws the start distance from
$U(0, R)$, with $R$ the diagonal of the start node, in 100 runs with
seeds from `SeedSequence(1).spawn`. The one-sided range is a choice of
this study: the limits $L \pm R$ of the paper, with $L$ the connection
length, have a negative lower end for all eight occupied nodes. All 100 runs give the split 347, 31, 42 and 0, and
times from 441.5 s to 442.5 s: a start spread of up to 15 m is absorbed
in the queue at the door. The paper lists the random start as a
sensitivity that it did not test {{< cite 8 "p. 178" >}}.

## Without boundary layer: S1

S1 removes the boundary layer on every link (`boundary_layer=0.0`),
which is the same capacity as widening every constriction by 0.30 m
{{< cite 8 "p. 169" >}}. A 0.91 m door then passes
$C$ = 1.33 × 0.91 = 1.210 persons/s. The model evacuates in 303.0 s with
the same split, and 258 inside at 90 s.

By hand, $t_5 + 342/C$ = 20.5 + 282.6 = 303.1 s. EvacuatioNZ v2.3 gives
345 s {{< cite 8 "p. 169" >}} (the model is −12 % below). By the same
formula, 347/1.210 = 287 s (the model is +6 % above); this is arithmetic
of this study, because the paper gives no hand value for this case. The
difference is of the same kind as in S0: this model equals the hand bound
plus $t_5$; the paper does not explain the excess of EvacuatioNZ v2.3 over
its own hand value. S1s, without supply reduction,
takes 304.5 s, and S1 at `dt=0.1` takes 302.4 s.

## Prescribed exits: S2 and S2b

S2 sends each space to the exits of Spearpoint's Table 5
{{< cite 8 "p. 170" >}}: 212 to the front door, 185 to the platform door,
20 to the side door and 3 to the kitchen door. Spearpoint chose the
assignment of the dance floor and the sunroom (half and half) and set
the main bar and the back platform so that the totals match NIST's, and
says that the assignment "has required some judgment". S2 has no boundary
layer, S2b has the boundary layer of 0.15 m.

At the front door the controlling link is dance → entrance (0.91 m),
which 201 agents of the dance floor, the sunroom, the dart room and the
back platform pass; the 11 of the main bar use bar → entrance.

| Case | Time (s) | $t_5$ (s) | $t_5 + (201 - 5)/C$ + walk (s) | Published (s) |
|------|----------|-----------|--------------------------------|---------------|
| S2 | 187.5 | 23.5 | 187.4 | 195 {{< cite 8 "p. 170" >}}; NIST 188 and 202; hand 177 {{< cite 8 "p. 169" >}} |
| S2b | 269.0 | 25.0 | 268.5 | 272 ± 2 {{< cite 8 "p. 170" >}}; hand 261 {{< cite 8 "p. 170" >}} |

The walk is 2.3 m from the entrance to the front door at 1.2 m/s, 1.9 s.
S2 is −4 % from the published 195 s and S2b −1 %, 1 s below the published
mean minus one standard deviation (272 ± 2 s, mean and standard deviation
{{< cite 8 "p. 170" >}}). NIST's 188 s and 202 s are from
{{< cite 38 "§6.6, Table 6-2" >}}. At 90 s NIST has 166 (Simulex) and 208
(buildingEXODUS) agents inside {{< cite 8 "Table 3, p. 162" >}}; S2 has
214.

## Preferred exit: S3

S3 is the 60/40 case of Spearpoint {{< cite 8 "p. 171" >}} as an
approximation: a fixed count per space, 60 % to the front door and the
rest to the nearest exit. The paper does not state whether the
boundary layer was on. The paper applies the boundary layer reduction to
the incident scenario "so as to match Proulx", the SFPE Handbook chapter
{{< cite 8 "p. 174" >}}, and its conclusions credit "door flows without a
boundary layer" {{< cite 8 "p. 179" >}}. The boundary layer of the 60/40
case is therefore inferred to be off. The comparison is the run without
boundary layer, S3n, and S3 has the boundary layer on.

The split is 252 through the front door, 139 through the platform door,
17 through the kitchen door and 12 through the side door: 60.0 %,
33.1 %, 4.0 % and 2.9 %. In 428 runs EvacuatioNZ reports 67 ± 3 %
through the front door, 23 ± 3 % through the platform door, 6 ± 2 %
through the kitchen door and 3 ± 2 % through the side door
{{< cite 8 "p. 171" >}}. A fixed split of 60 % per space cannot give a
front-door share above 60 %, because for every occupied space the
nearest exit is the platform, the side or the kitchen door. The preferred
route of EvacuatioNZ therefore acts differently from a per-room split of
the destinations. How v2.3 draws the preferred route is not described.

The controlling link is dance → entrance, which 233 agents pass.

| Case | Time (s) | Inside at 90 s | Published |
|------|----------|----------------|-----------|
| S3 | 308.0 | 257 | – |
| S3n | 214.0 | 202 | 201 ± 8 s, about 163 inside at 90 s |

The published 201 ± 8 s is the mean and one standard deviation of 428
runs {{< cite 8 "p. 171" >}}. S3n is +6 % above the published 201 s: 13 s
above the mean and 5 s above the mean plus one standard deviation, so the
results differ. S3n has 202 agents inside at 90 s where the paper has
about 163.

## Sensitivity

### A tie in the connection length

Static shortest-distance routing is discontinuous in one link length.
The sweep scales the length of dance → entrance by a factor $f$, in 42
values: 0.80 to 1.20 in steps of 0.01 and the tie at 0.875. The dance
floor takes the front door if $9.6 f + 2.3 < 8.9 + 1.8$, that is for
$f < 0.875$, and the platform door above. Spearpoint notes that slightly
different distances between nodes would give a shorter path to the front
entrance and change the outcome significantly {{< cite 8 "p. 168" >}}. In
this study the flip is at 8.4 m, which is $0.875 \times 9.6$ m; the paper
gives no such value.

- **Below the tie.** 343 agents leave through the front door (those of
  the dance floor, the sunroom, the back hallway and the back platform)
  and the time does not decrease as $f$ grows.
- **Above the tie.** None leaves through the front door, and the
  time is 442.0 s from $f$ = 0.88.
- **At the tie.** The flip is at the exact tie $f$ = 0.875. $0.875 \times 9.6 + 2.3 = 8.9 + 1.8$ exactly, so the
  agents alternate: 172 go to the front door and 175 to the platform door.
  Static shortest-distance routing is discontinuous in one link length; at
  the tie the alternation rule gives the shortest time of the sweep,
  230.0 s.

The two routing policies, shortest distance and shortest free-flow time,
give the same time in all 42 values, because there are no stairs.

![Evacuation time and agents through the front door against the factor on the length of dance->entrance](/images/network/station_length.png)

### Door flow and boundary layer

The platform door controls the time, so $T = t_5 + 342/C$ with
$C = F_s\,(0.91 - 2b)$. The grid varies the specific flow of every link and
the boundary layer (S4b); the entries are evacuation times in s.

| $F_s$ (persons/s/m) | $b$ = 0 | $b$ = 0.05 | $b$ = 0.10 | $b$ = 0.15 |
|---------------------|---------|------------|------------|------------|
| 1.21 | 331.0 | 369.0 | 418.5 | 483.5 |
| 1.25 | 321.0 | 358.0 | 405.5 | 469.0 |
| 1.3 | 309.5 | 345.0 | 391.0 | 451.5 |
| 1.33 | 303.0 | 337.5 | 382.5 | 442.0 |

In all 16 cases $T$ lies between 0.46 s and 0.02 s below $t_5 + 342/C$,
within one step. The base case, $F_s$ = 1.33 and $b$ = 0.15, is S0.

![Evacuation time against the boundary layer for four specific flows, with the bound t₅ + 342/C](/images/network/station_doors.png)

### Node density limit

`max_density` from 2.5 to 3.5 m⁻²; smaller limits are rejected, because
the dance floor starts at 2.30 m⁻². The entries are evacuation times in s.

| `max_density` (m⁻²) | supply reduction on | supply reduction off |
|---------------------|---------------------|----------------------|
| 2.5 | 441.0 | 441.5 |
| 2.75 | 442.0 | 443.5 |
| 3.0 | 443.0 | 446.0 |
| 3.25 | 444.0 | 451.0 |
| 3.5 | 445.0 | 453.0 |

A higher limit lets the dance floor fill beyond 2.75 m⁻², and the walk to
the platform door is slower: the fifth passage is later (19.5 s at 2.5 m⁻²,
23.5 s at 3.5 m⁻² with supply reduction, 31.5 s without), and the door flow
afterwards is the same. With the supply reduction on the time is never
longer than without it, and the two differ by 8.0 s at most.

![Evacuation time against max_density, with and without the supply reduction](/images/network/station_density.png)

## Comparison with the published values

Differences are reported in bands, a convention of this study: up to 5 %
the result agrees, from 5 % to 15 % it differs and gives the reason where
one is known, and above 15 % it differs. The tests do not assert the
published values.

| Case | This model | Published | Difference | Band |
|------|------------|-----------|------------|------|
| S0 | 442.0 s | 493 s {{< cite 8 "p. 166" >}} | −10 % | differs; the paper does not explain the excess of v2.3 over its own hand value |
| S0, inside at 90 s | 291 | 291 {{< cite 8 "p. 166" >}} | 0 % | agrees |
| S1 | 303.0 s | 345 s {{< cite 8 "p. 169" >}} | −12 % | differs; the paper does not explain the excess of v2.3 over its own hand value |
| S2 | 187.5 s | 195 s {{< cite 8 "p. 170" >}} | −4 % | agrees |
| S2b | 269.0 s | 272 ± 2 s {{< cite 8 "p. 170" >}} | −1 % | agrees |
| S3n | 214.0 s | 201 ± 8 s {{< cite 8 "p. 171" >}} | +6 % | differs; boundary layer of the case inferred, and the fixed 60 % split cannot give the published 67 % front share |
| S3 | 308.0 s | 201 ± 8 s {{< cite 8 "p. 171" >}} | +53 % | differs |

The split of S0 and the split of S2 are exact. The 67 % of the paper
for the front door of S3 is not reproduced.

## Limits of this study

- **Model against model.** This is model-to-model agreement on a
  published network. It is not validation against the incident, a drill
  or an experiment; Spearpoint states the same for EvacuatioNZ (p. 180).
- **Dimensions.** The sizes and widths are read from Fig. 1(b), a raster
  figure. A misread digit would move a capacity or the dance-floor
  density, and no test would notice. The length of dance → entrance is
  12.5 % from the tie of the routes, so a misread there would flip the
  whole split.
- **One building.** One storey, level walking only, everyone moving at
  $t = 0$, flow controlled by doors. The result scales as 1/$C$ of one
  0.91 m door. Nothing here tests stairs, merge weights, counterflow or
  pre-movement time.
- **Supply reduction.** The dance floor starts above 1.88 m⁻², inside the
  range of the supply ramp, which is not calibrated
  ([Limitations]({{< relref "/docs/limitations" >}})). S0s shows that its
  effect is 1.5 s here.
- **Specific flow.** The flow is set on each link, which skips the check
  against k/(4a) (issue #83).
- **Link lengths.** The length is walked in the source node at the
  density of that node. Splitting each length between the source and the
  target would give the same routes and slightly different speeds.
- **One-way links.** Every connection is used in one direction, so the
  counterflow and reverse-link supply limitations stay out of the
  comparison. Spearpoint does not state whether EvacuatioNZ allowed
  reverse movement.
- **Exit assignment.** Table 5 is a matter of judgement of the author,
  and the 60/40 case is a fixed split, not a draw per agent. The boundary
  layer of the 60/40 case is inferred
  {{< cite 8 "pp. 174, 179" >}}.
- **Static exit choice.** The 40 % take the nearest exit, as in the paper
  {{< cite 8 "p. 171" >}}, and no agent re-chooses.
- **Agreement not claimed.** Agreement with the published 60/40 result
  is not claimed, nor correctness of the exit choice, nor
  generalisation.

## Next steps

- **Scenario #2\*.** Spearpoint lets 5.5 % of the 397 agents of the front
  door and platform group opt for the platform door, 22 agents
  {{< cite 8 "p. 172" >}}, and reports 326 ± 4 s over 81 runs
  {{< cite 8 "p. 172" >}}. The paper does not state which spaces supply
  them, so the case is not built. NIST's own rule moves the 39 occupants
  who would have left by the platform door within 30 s
  {{< cite 39 "p. L-5" >}} {{< cite 38 "p. 6-25" >}}.
- **The incident.** The scenario of the night of the fire has other
  occupants and a different exit use; it is a separate study.
- **Kitchen door.** NIST closes the kitchen door to occupants who are not
  in the kitchen: in buildingEXODUS after 5 s {{< cite 39 "p. L-1" >}}, in
  Simulex only the kitchen starters use it {{< cite 39 "p. L-5" >}}.
  Spearpoint sends 42. A variant without the link dart → kitchen would
  isolate that difference; the dart room would then walk 21.1 m to the
  platform door.
- **Per-agent exit choice.** A random exit per agent would be a feature
  request; the model has none.
