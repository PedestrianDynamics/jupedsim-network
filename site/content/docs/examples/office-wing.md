---
title: Office wing
weight: 1
---

A two-storey office wing with a training room, one stair and two exits.
You turn the floor plan into a network, run it once and 100 times, find
where the queue forms, and test one change to the building. The script
is [`examples/office_wing.py`](https://github.com/PedestrianDynamics/jupedsim-network/blob/main/examples/office_wing.py);
read [Getting started]({{< relref "/docs/getting-started" >}}) first.

{{< callout type="info" >}}
The building and its occupants are invented to show the workflow. Every
number on this page comes from running the script with the current
version.
The result is not a design value
([Limits of this example](#limits-of-this-example)).
{{< /callout >}}

## The building

![Floor plans of the upper and ground floor of the office wing, with the network drawn on top: nodes at the centre of each room, corridor half and the stair, arrows through each door labelled with its clear width in metres](/images/network/office_plan.png)

[Open the plan at full size](../../../images/network/office_plan.png).

- **Wing.** Both floors are 36 m long. Rooms are 7 m deep and lie south
  of a 2 m corridor.
- **Upper floor.** Two offices of 9 × 7 m (U1, U2) and a training room
  of 18 × 7 m (TR). The only way down is the stair at the east end of
  the corridor, through a 0.9 m door.
- **Ground floor.** Four offices of 9 × 7 m (G1 to G4). The corridor
  ends in the main door (1.8 m, double door) at the west and the side
  door (0.9 m) at the east. The stair lands next to the side door.
- **Stair.** Two flights of 1.2 m with a half landing, 175 mm risers and
  280 mm treads, 3.5 m storey height.
- **Doors.** Every office door and the training-room door is 0.9 m wide.

In the drawing, circles are room nodes, the square is the stair node and
the triangles are the safe nodes outside the two exits. Each room shows
its number of occupants. Blue arrows are
door links, thick green arrows exit doors, and the dashed orange arrow
is the stair link. The
dotted orange line joins the two halves of the one stair node.

## From plan to network

Each space becomes a node with its floor area. Each door becomes a link
with its clear width and the distance walked to it. The corridor of each
floor is split at the middle into a west and an east half (W, E, dashed
line in the drawing). With one corridor node, every agent in it would
walk the same distance to the same exit; with two, the ground-floor
offices at the west use the main door and those at the east the side
door.

### Nodes

| Node | Kind | Area (m²) | Measured as |
|------|------|-----------|-------------|
| G1–G4, U1, U2 | room | 63 | office, 9 × 7 m |
| TR | room | 126 | training room, 18 × 7 m |
| GW, GE, UW, UE | room | 36 | corridor half, 18 × 2 m |
| stair | stair | 8.9 | 2.4 × 3.72 m: two flights side by side, run plus half landing |
| main, side | safe | ∞ | outside |

### Links

All links are one way, in the walking direction.

| From → to | Kind | Width (m) | Length (m) |
|-----------|------|-----------|------------|
| office → corridor | door | 0.9 | 3.5 |
| TR → UE | door | 0.9 | 3.5 |
| GW → GE, GE → GW | door | 2.0 | 9.0 |
| UW → UE | door | 2.0 | 9.0 |
| GW → main | door | 1.8 | 9.0 |
| GE → side | door | 0.9 | 9.0 |
| UE → stair | door | 0.9 | 7.0 |
| stair → GE | stair | 1.2 | 8.3 |

- **Width.** The clear width of the door, the corridor width at the
  split between two corridor halves, and the flight width for the stair.
- **Length.** The distance walked inside the source node, from its
  centre to the door: half the room depth from an office or TR, half the
  length of a corridor half to the split or to the corridor end, and
  from the centre of UE to the stair door. The stair link takes the length along
  the incline (below).

GW → GE and GE → GW together are the ground-floor corridor, which agents
could walk in either direction. The corridor split has no door. It is
entered as a door so that the 0.15 m boundary layer along each corridor
wall applies; `kind="opening"` has none. No agent crosses the split in
this example ([One run](#one-run)), so the choice does not change the
results.

**Stair length.** This model applies the SFPE stair speed along the line
of travel, so the stair link takes the walking distance along the
incline ([issue #5](https://github.com/PedestrianDynamics/jupedsim-network/issues/5)).
Each flight has 9 treads of 280 mm, a horizontal run of 2.52 m. Along
the incline that is $2.52\,\sqrt{1 + (0.175/0.28)^2} = 2.97$ m. Two
flights and about 2.4 m across the half landing, where SFPE applies the
stair speed as well {{< cite 1 "p. 2175" >}}, give 8.3 m. Risers of
175 mm and treads of 280 mm are inside the range for which SFPE supports
the stair speed law {{< cite 1 "p. 2175" >}}.

{{< details title="The same numbers in the script" closed="true" >}}

The script starts with its imports:

```python
import math

import numpy as np

from jupedsim_network import Network, NetworkSimulation, Population, Uniform
```

```python
# Stair between the floors: 20 risers of 175 mm over a storey height of
# 3.5 m, in two flights of 10 risers (9 treads of 280 mm) and a half
# landing. Each flight is 1.2 m wide.
RISER, TREAD = 0.175, 0.28
FLIGHT_WIDTH = 1.2
FLIGHT_GOING = 9 * TREAD  # horizontal run of one flight, m
LANDING_DEPTH = 1.2
INCLINE = math.sqrt(1.0 + (RISER / TREAD) ** 2)
# Two flights along the incline plus the walk across the half landing.
STAIR_LENGTH = round(2 * FLIGHT_GOING * INCLINE + 2 * FLIGHT_WIDTH, 1)
# Two flights side by side, plus the half landing.
STAIR_AREA = round(2 * FLIGHT_WIDTH * (FLIGHT_GOING + LANDING_DEPTH), 1)

# Level spaces: name -> (length, width) in m. G = ground floor,
# U = upper floor; W and E are the west and east halves of a corridor.
ROOMS = {
    "G1": (9.0, 7.0),
    "G2": (9.0, 7.0),
    "G3": (9.0, 7.0),
    "G4": (9.0, 7.0),
    "GW": (18.0, 2.0),
    "GE": (18.0, 2.0),
    "U1": (9.0, 7.0),
    "U2": (9.0, 7.0),
    "TR": (18.0, 7.0),
    "UW": (18.0, 2.0),
    "UE": (18.0, 2.0),
}

# Links: (source, target, kind, clear width in m, length in m walked
# inside the source from its centre to the constriction).
LINKS = [
    ("G1", "GW", "door", 0.9, 3.5),
    ("G2", "GW", "door", 0.9, 3.5),
    ("G3", "GE", "door", 0.9, 3.5),
    ("G4", "GE", "door", 0.9, 3.5),
    ("GW", "GE", "door", 2.0, 9.0),
    ("GE", "GW", "door", 2.0, 9.0),
    ("GW", "main", "door", 1.8, 9.0),
    ("GE", "side", "door", 0.9, 9.0),
    ("U1", "UW", "door", 0.9, 3.5),
    ("U2", "UW", "door", 0.9, 3.5),
    ("TR", "UE", "door", 0.9, 3.5),
    ("UW", "UE", "door", 2.0, 9.0),
    ("UE", "stair", "door", 0.9, 7.0),
    ("stair", "GE", "stair", FLIGHT_WIDTH, STAIR_LENGTH),
]
```

{{< /details >}}

`build_network` turns the two tables into a `Network`. Its argument
`side_door` is used in the [what-if](#what-if-the-side-door-were-wider):

```python
def build_network(side_door=0.9):
    """The office wing; ``side_door`` is the clear width of the side door."""
    net = Network()
    for name, (length, width) in ROOMS.items():
        net.add_room(name, length=length, width=width)
    net.add_stair("stair", riser=RISER, tread=TREAD, area=STAIR_AREA)
    net.add_safe("main")
    net.add_safe("side")
    for source, target, kind, width, length in LINKS:
        if (source, target) == ("GE", "side"):
            width = side_door
        net.connect(
            source,
            target,
            kind=kind,
            width=width,
            length=length,
            bidirectional=False,
        )
    return net
```

## Occupants and settings

```python
SPEED = Uniform(0.8, 1.2)
OFFICE_START = Uniform(30.0, 90.0)
TRAINING_START = Uniform(20.0, 40.0)


def populations():
    """Six people per office, 60 in the training room."""
    offices = [
        Population(room, 6, speed=SPEED, pre_movement=OFFICE_START)
        for room in ("G1", "G2", "G3", "G4", "U1", "U2")
    ]
    training = Population("TR", 60, speed=SPEED, pre_movement=TRAINING_START)
    return offices + [training]
```

These inputs are assumptions of this example. None of them is taken from
a code or a data set.

- **Counts.** Six people per office, about 10.5 m² each, and 60 seats
  in the training room, about 2.1 m² each: 96 people in all. The
  training room makes this wing more crowded than a plain office floor.
- **Pre-movement.** Office occupants start between 30 and 90 s. The
  training group starts earlier and closer together, between 20 and
  40 s, because the session is stopped for everyone at once.
- **Speeds.** Free walking speeds between 0.8 and 1.2 m/s. Speeds above
  1.2 m/s would change nothing on level ground
  ([Populations]({{< relref "/docs/using/populations#speeds-above-12-ms-have-no-effect-on-level-ground" >}})).

Counts are fixed. Speeds and pre-movement times are sampled anew for
every agent in every run.

```python
RUNS = 100


def simulation(side_door=0.9, dt=0.1):
    return NetworkSimulation(
        build_network(side_door),
        populations(),
        dt=dt,
        t_max=900.0,
        max_density=2.75,
    )
```

- **`dt=0.1`.** An agent from the upper floor passes four or five
  links, and every link costs at least one time step. Stair speeds need a step of about 0.1 s
  to match a hand calculation
  ([Limitations]({{< relref "/docs/limitations#numerics" >}})).
- **`t_max=900.0`.** Far above the expected evacuation time of a few
  minutes. The output counts the runs that did not finish, so a too
  small `t_max` would show.
- **`max_density=2.75`.** The default. In the run with seed 1 no node
  gets near it (see [One run](#one-run)).

## Run it

Clone the repository, install the package from the clone and run the
script from the repository root. It takes up to a minute on a laptop,
most of it for the 400 Monte Carlo runs.

```
git clone https://github.com/PedestrianDynamics/jupedsim-network.git
cd jupedsim-network
pip install .
python examples/office_wing.py
```

`pip install .` installs the model from the same checkout as the script.
Releases before 0.2.0 predate the link capacity fix
([issue #18](https://github.com/PedestrianDynamics/jupedsim-network/issues/18))
and prints other numbers.

The script runs these steps:

```python
def main():
    net = build_network()
    report_network(net)
    print()

    sim = simulation()
    result = sim.run(seed=1)
    report_run(result, net)
    print()

    runs = sim.run_many(RUNS, seed=1)
    report_monte_carlo(runs, result)
    print()

    report_what_if()


if __name__ == "__main__":
    main()
```

{{< details title="The report functions" closed="true" >}}

They only read the network and the results.

```python
def exit_of(net, name):
    """Safe node that the route from ``name`` leads to."""
    routes = net.route_table()
    node = net.node(name)
    while routes[node.index] is not None:
        node = net.nodes[net.links[routes[node.index]].target]
    return node.name


def agents_through(result, link):
    """Agents that passed ``link`` during the run."""
    return int(result.link_flow[:, result.link_names.index(link)].sum())


def peak(result, node):
    """Largest number of agents in ``node`` at any time."""
    return int(result.node_occupancy[:, result.node_names.index(node)].max())


def passage_times(result, link):
    """Times of the first and the last passage through ``link``."""
    flow = result.link_flow[:, result.link_names.index(link)]
    times = result.times[flow > 0]
    return times[0], times[-1]


def quantiles(runs):
    q = runs.quantile([0.5, 0.95])
    return f"median {q[0]:.1f} s, 95th percentile {q[1]:.1f} s"


def report_network(net):
    print(f"stair: length {STAIR_LENGTH} m, area {STAIR_AREA} m²")
    for link in net.links:
        print(f"{link.name:10s} {link.capacity:.2f} persons/s")
    for room in ("G1", "G2", "G3", "G4", "U1", "U2", "TR"):
        print(f"{room} leaves by the {exit_of(net, room)} door")


def report_run(result, net):
    print(f"evacuation time: {result.evacuation_time:.1f} s")
    print(f"agents safe: {result.evacuated} of {len(result.exit_times)}")
    print(f"main door: {agents_through(result, 'GW->main')} agents")
    print(f"side door: {agents_through(result, 'GE->side')} agents")
    for link in ("TR->UE", "UE->stair", "GE->side", "GW->main"):
        first, last = passage_times(result, link)
        print(f"{link}: first agent at {first:.1f} s, last at {last:.1f} s")
    for node in ("UE", "stair", "GE"):
        most = peak(result, node)
        density = most / net.node(node).area
        print(f"peak in {node}: {most} agents, {density:.2f} per m²")
    between = agents_through(result, "GW->GE") + agents_through(
        result, "GE->GW"
    )
    print(f"agents between the corridor halves: {between}")
    # Agents are stored in population order: the training room comes last.
    print(f"last agent from TR out: {result.exit_times[-60:].max():.1f} s")


def report_monte_carlo(runs, result):
    print(quantiles(runs))
    print(f"incomplete runs: {runs.incomplete} of {runs.evacuation_times.size}")
    fastest, slowest = runs.complete.min(), runs.complete.max()
    print(f"fastest {fastest:.1f} s, slowest {slowest:.1f} s")
    share = (runs.complete < result.evacuation_time).mean()
    print(f"seed 1 is slower than {share:.0%} of the runs")


def report_what_if():
    print("side door  seed 1    median   95th pct  peak in GE")
    starts = []
    for width in (0.9, 1.2, 1.8):
        sim = simulation(side_door=width)
        one = sim.run(seed=1)
        q = sim.run_many(RUNS, seed=1).quantile([0.5, 0.95])
        print(
            f"{width} m      {one.evacuation_time:.1f} s  {q[0]:.1f} s  "
            f"{q[1]:.1f} s   {peak(one, 'GE')}"
        )
        starts.append(one.pre_movement_times)
    same = all(np.array_equal(starts[0], s) for s in starts)
    print(f"same pre-movement times in every variant: {same}")
```

{{< /details >}}

### Check the network

The first lines of the output show the stair, the capacity of every
link and the exit each room's route leads to:

```text
stair: length 8.3 m, area 8.9 m²
G1->GW     0.78 persons/s
G2->GW     0.78 persons/s
G3->GE     0.78 persons/s
G4->GE     0.78 persons/s
GW->GE     2.21 persons/s
GE->GW     2.21 persons/s
GW->main   1.95 persons/s
GE->side   0.78 persons/s
U1->UW     0.78 persons/s
U2->UW     0.78 persons/s
TR->UE     0.78 persons/s
UW->UE     2.21 persons/s
UE->stair  0.78 persons/s
stair->GE  0.92 persons/s
G1 leaves by the main door
G2 leaves by the main door
G3 leaves by the side door
G4 leaves by the side door
U1 leaves by the side door
U2 leaves by the side door
TR leaves by the side door
```

**Check:** a 0.9 m door passes $1.3 \times (0.9 - 2 \times 0.15) = 0.78$
persons/s and the 1.8 m main door 1.95 persons/s
([Model elements]({{< relref "/docs/model/elements" >}})). The stair
link passes 0.92 persons/s, the maximum stair flow for these steps times
the effective width of 0.9 m.

Routes follow the shortest walking distance. From GE the side door is
9 m away and the main door 18 m, so the routes are not tied
([issue #7](https://github.com/PedestrianDynamics/jupedsim-network/issues/7)).
Everyone upstairs comes down the stair into GE and therefore leaves by
the side door.

## One run

```text
evacuation time: 156.5 s
agents safe: 96 of 96
main door: 12 agents
side door: 84 agents
TR->UE: first agent at 24.0 s, last at 99.6 s
UE->stair: first agent at 31.2 s, last at 123.3 s
GE->side: first agent at 48.6 s, last at 156.5 s
GW->main: first agent at 42.4 s, last at 102.0 s
peak in UE: 19 agents, 0.53 per m²
peak in stair: 9 agents, 1.01 per m²
peak in GE: 19 agents, 0.53 per m²
agents between the corridor halves: 0
last agent from TR out: 156.5 s
```

**Check:** all 96 agents are safe. If fewer were, `evacuation_time`
would be `nan`; raise `t_max`.

![Cumulative number of agents safe over time: all agents, through the side door and through the main door for a 0.9 m side door, and all agents for a 1.2 m side door](/images/network/office_evacuated.png)

[Open the chart at full size](../../../images/network/office_evacuated.png).

The side door takes 84 of the 96 agents. After a few gaps in the first
seconds, its curve rises in a straight line at its capacity of 0.78
persons/s until the end. Its first agent passes at 48.6 s and its last at
156.5 s, 107.9 s later. A door that never runs empty passes 84 agents in
$(84 - 1)/0.78 = 106.4$ s in this model, where the first agent passes an
idle door at once; SFPE's $N/C$ gives 107.7 s
([Limitations]({{< relref "/docs/limitations#numerics" >}})). The main
door, 1.8 m wide, takes the 12 people from G1 and G2 and is idle after
102.0 s.

![Number of agents over time in the training room, the upper corridor east, the stair and the ground corridor east](/images/network/office_occupancy.png)

[Open the chart at full size](../../../images/network/office_occupancy.png).

Everyone upstairs passes three 0.9 m doors in a row, each with a
capacity of 0.78 persons/s. A queue forms at each of them, and the
three queues overlap in time:

1. **At the training-room door.** The 60 people of TR start between
   20 and 40 s. The door passes the first at 24.0 s and the last at
   99.6 s, 75.6 s later. That is $(60 - 1)/0.78 = 75.6$ s: the door
   runs at capacity from the first agent to the last.
2. **At the stair door.** UE receives the 60 people from TR and the 12
   from U1 and U2, more than the stair door lets through. UE holds up
   to 19 agents. The stair door passes its 72 agents from 31.2 to
   123.3 s, 92.1 s, close to $(72 - 1)/0.78 = 91.0$ s.
3. **At the side door.** GE receives the 72 agents from the stair and
   the 12 from G3 and G4. GE holds up to 19 agents.

The stair itself holds no lasting queue. Its link passes 0.92 persons/s,
more than the 0.78 persons/s the stair door admits, and it holds at most
9 agents.

In this run the densities stay low. The highest, 1.01 per m² on the
stair, is below the 1.88 per m² at which the model starts to reduce
inflow, so `max_density` and the supply reduction play no part
([update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}})).
No agent walks between the corridor halves, so the two-way corridor
links carry no counterflow.

## 100 runs

```text
median 155.1 s, 95th percentile 158.3 s
incomplete runs: 0 of 100
fastest 150.2 s, slowest 159.3 s
seed 1 is slower than 75% of the runs
```

- All 100 runs finished, so the quantiles are finite and `t_max` is
  large enough.
- Half of the runs end within 155.1 s and 95&nbsp;% within 158.3 s.
- The runs differ by at most 9.1 s, from 150.2 to 159.3 s. The three
  queues set the pace, and they change little when the sampled speeds
  and pre-movement times change.
- The run with seed 1 is one sample. It happens to be slower than
  75&nbsp;% of the runs.

The spread comes only from the sampled speeds and pre-movement times
([Limitations]({{< relref "/docs/limitations#monte-carlo" >}})).

## What if the side door were wider?

The side door limits the last agents, so widen it. The script runs the
same seeds with a side door of 0.9, 1.2 and 1.8 m and changes nothing
else:

```text
side door  seed 1    median   95th pct  peak in GE
0.9 m      156.5 s  155.1 s  158.3 s   19
1.2 m      143.9 s  143.3 s  144.9 s   13
1.8 m      143.9 s  143.2 s  144.9 s   13
same pre-movement times in every variant: True
```

With seed 1, every variant samples the same pre-movement times (last
line), so the differences in that run come from the door alone. The
`peak in GE` column is also from the run with seed 1.

- **From 0.9 to 1.2 m** the median falls by 11.8 s, from 155.1 to
  143.3 s, and the peak in GE from 19 to 13 agents. The side door must
  pass 84 agents, 12 more than come down the stair. At 0.78 persons/s it
  could not keep up; at 1.2 m it passes $1.3 \times 0.9 = 1.17$
  persons/s, more than the 0.78 persons/s that the stair door lets
  down.
- **From 1.2 to 1.8 m** the median changes by 0.1 s and the run with
  seed 1 stays at 143.9 s. The side door no longer limits. The upper
  floor drains at the pace of the stair door, which passes all 72
  people from upstairs at its capacity (see [One run](#one-run)). A
  wider side door cannot help; the door to widen next is the stair door.

In the model, the main door stays almost unused in every variant.
Routes use distance only, so nobody from upstairs walks the extra 9 m to
the main door. To test a different exit choice, send part of the upper
floor to the main door with `target="main"` ([Networks]({{< relref "/docs/using/networks#routes" >}})).

## Limits of this example

The [Limitations]({{< relref "/docs/limitations" >}}) page lists every
known limitation of the model. The ones that matter here:

- **Verified, not validated.** The model is checked against hand
  calculations and adapted IMO tests, not against drills or experiments.
  It is not intended for design or regulatory use
  ([Limitations]({{< relref "/docs/limitations#status" >}})).
- **Inputs are assumed.** The occupant counts, pre-movement times and
  speeds above are chosen for the example, not taken from data.
- **Routes are static.** Agents take the shortest route and never
  switch exits when the side door queues
  ([Limitations]({{< relref "/docs/limitations#routes" >}})).
- **Nodes are well mixed and have one length per link.** Every agent in
  a room walks the same 3.5 m to its door, whether it sits by the door
  or in a far corner. Agents coming off the stair land about 1 m from
  the side door but still walk the 9 m of GE. Splitting the corridor
  into halves reduces this error; it does not remove it
  ([Limitations]({{< relref "/docs/limitations#movement-and-capacity" >}})).
- **Stair length is a convention.** The 8.3 m along the incline would
  be 7.4 m as horizontal run plus landing
  ([issue #5](https://github.com/PedestrianDynamics/jupedsim-network/issues/5)).
- **Doors are open and have no leaves.** The door capacities assume
  doors held open ([Limitations]({{< relref "/docs/limitations#movement-and-capacity" >}})).
- **No counterflow and no supply reduction in the run with seed 1.**
  The corridor links carry no agent, and no node exceeds 1.88 per m².
  The `counterflow` setting therefore does not affect that run.

## Next steps

- Change one input in `examples/office_wing.py`, for example the
  width of the stair door, and run it again.
- [Networks]({{< relref "/docs/using/networks" >}}): all options of
  rooms, stairs and links.
- [Results]({{< relref "/docs/using/results" >}}): what else a run
  returns and how to report it.
- [Case study]({{< relref "/docs/ten-storey" >}}): a ten-storey building
  with two stairs.
