# Network Model

The network model in {mod}`jupedsim_network` estimates the required safe
egress time (RSET) of a building from a coarse graph instead of a
continuous geometry. Spaces such as rooms, corridors and stair flights are
**nodes** with an area. Doors, openings and stair entries are **links**
with a flow capacity. Individual agents move through this graph following
the hydraulic relations of the SFPE Handbook [1].

A run of a ten-storey building with 600 agents takes about 0.1 s, so a
scenario can be repeated hundreds of times with sampled pre-movement
times, occupant loads and walking speeds. The model sits between a hand
calculation and a microscopic simulation:

- **Unlike a hand calculation,** the model handles distributions of
  pre-movement time, interacting queues, merging streams and capacity
  limits of intermediate spaces.
- **Unlike a microscopic model,** it knows nothing about positions inside
  a node. The microscopic models of JuPedSim are the tool for checking
  geometry details and the critical percentiles found with the network
  model.

The model follows the same approach as EvacuatioNZ
[2, 3]. It differs in the update scheme
and in how full nodes are handled. See {ref}`network-comparison`
below.

```{figure} _static/network/mechanics.gif
:alt: Agents in two rooms walk to their doors, queue, merge into a corridor and leave through an exit
:width: 100%
:align: center

Two rooms of 40 agents each empty into a corridor of 4 m², which holds at
most 11 agents. The corridor is full most of the time. Its inflow is then
reduced and shared 1 : 3 between the rooms, following the merge weights.
Positions inside a node are drawn for illustration only, since the model
tracks a remaining walking distance per agent.
```

## Usage

```python
from jupedsim_network import LogNormal, Network, NetworkSimulation, Population

net = Network()
net.add_room("office", area=200.0)
net.add_stair("flight", area=10.8, riser=0.18, tread=0.28)
net.add_safe("street")
net.connect("office", "flight", width=0.9, length=25.0)
net.connect("flight", "street", width=1.2, kind="stair", length=9.0)

population = Population(
    "office", 120, speed=1.2, pre_movement=LogNormal(120.0, 60.0)
)
simulation = NetworkSimulation(net, [population], dt=0.5)

result = simulation.run(seed=1)
print(result.evacuation_time)

runs = simulation.run_many(500, seed=1)
print(runs.quantile([0.5, 0.95]))
```

A {class}`~jupedsim_network.SimulationResult` holds the following:

- the exit time and pre-movement time of each agent
- the number of agents in each node at every time step
- the number of agents that passed each link during every time step

A {class}`~jupedsim_network.MonteCarloResult` holds the evacuation time of
every run. Runs that did not finish before `t_max` are marked `nan`.

## Model elements

```{figure} _static/network/schematic.png
:alt: Schematic of nodes connected by directed links
:width: 100%
:align: center

Rooms, corridors and stair flights are nodes, and links connect them.
An agent first walks the link length inside the source node, then joins
the queue at the constriction.
```

### Nodes

A node $n$ has an area $A_n$ and a speed constant $k_n$.

- **Rooms** use the level value $k = 84$ m/min $= 1.40$ m/s.
- **Stair flights** take $k$ from the riser height $R$ and the tread
  depth $T$ [1]:

  $$
  k_\text{stair} = 51.8\,\sqrt{T/R}\ \text{m/min}.
  $$

- **Safe nodes** have an unlimited area. Agents that reach one leave the
  simulation.

A stair is a node with an area, normally its width times the flight
length. Agents on the flight therefore take up space and count towards
its density.

### Links

A link $\ell$ is a directed passage from a source node to a target node.
Its capacity in persons/s is

$$
C_\ell = F_s\,(w_\ell - 2 b_\ell),
$$

where $w_\ell$ is the clear width and $b_\ell$ is the boundary layer on
each side. The defaults are:

| Kind | $F_s$ (persons/s/m) | $b$ (m) |
|------|---------------------|---------|
| `door` | 1.3 | 0.15 |
| `opening` | 1.3 | 0 |
| `stair` | $k/(4a)$ of the adjacent stair node, about 1.01 for 18/28 cm | 0.15 |

Here $a = 0.266$ m² is the slope of the speed–density relation. The value
$k/(4a)$ is the maximum of the specific flow $S(D)\,D$, reached at the
density $1/(2a) \approx 1.88$ m⁻².

A link also has the following attributes:

- **Length $L_\ell$:** the walking distance inside the *source* node up to
  the constriction. `connect(..., bidirectional=True)` creates both
  directions with the same length.
- **Merge weight $m_\ell$:** the relative share of the link when several
  links feed the same full node.

### Agents

A {class}`~jupedsim_network.Population` places agents in a start node.
Each agent $i$ has the following attributes, and every one except the area
factor can be drawn from a distribution:

- a free walking speed $v_i^\text{max}$
- a pre-movement time $t_i^\text{pre}$
- an extra start distance $s_i$
- an area factor $a_i$. A value of 1 stands for an average adult. Larger
  values can represent, for example, wheelchair users.

The available distributions are `Fixed`, `Uniform`, `Normal`, `LogNormal`,
`Triangular` and `Weibull`. Each can be truncated to $[\text{lower},
\text{upper}]$.

### Routes

Each agent follows a fixed route to the nearest safe node, measured as the
sum of link lengths. If a `target` is given, the route leads to that
safe node instead. One shortest-path tree is computed per target before
the run starts.

## Update scheme

Time advances in fixed steps $\Delta t$, 0.5 s by default. Every step
follows the five stages below. All transfers in a step are applied
together at the end. The result therefore doesn't depend on the order in
which agents are stored.

### 1. Density

The density of node $n$ at the start of the step counts the area factor
of each agent in the node, so occupants of different sizes add up
differently:

$$
D_n = \frac{1}{A_n} \sum_{i \in n} a_i .
$$

### 2. Pre-movement

An agent starts walking once $t \ge t_i^\text{pre}$. Its first walking
distance is $s_i + L_\ell$, where $\ell$ is the first link of its route.

### 3. Walking

A walking agent in node $n$ moves at

$$
v_i = \min\!\left(v_i^\text{max},\; k_n\,\bigl(1 - a\,\max(D_n, 0.54)\bigr)\right),
$$

with $v_i$ clipped at zero. Its remaining distance shrinks by
$v_i\,\Delta t$. Once the remaining distance reaches zero, the agent joins
the queue of its link. The arrival time is interpolated within the step,
and the queue is served in order of arrival.

```{figure} _static/network/fundamental_diagram.png
:alt: Speed, specific flow and supply factor plotted against density
:width: 100%
:align: center

(a) SFPE speed–density relation for level ground and for an 18/28 cm
stair. (b) Specific flow, with its peak at 1.88 m⁻². (c) Share of its
inflow capacity that a node accepts. With supply reduction (solid line)
the share falls linearly from the peak-flow density to `max_density`.
The dashed line is a hard capacity limit.
```

### 4. Passing links

**Link budget.** Each link has a budget for the step, made up of a carry
$c_\ell$ from earlier steps and its capacity for this step:

$$
\beta_\ell = c_\ell + C_\ell\,\Delta t .
$$

At most $\lfloor \beta_\ell \rfloor$ agents from the front of the queue
ask to pass.

**What the target node accepts.** A receiving node $n$ that is not safe
accepts agents only up to two limits.

- **Free space** is always enforced:

  $$
  F_n = D_\text{max}\,A_n - \sum_{i\in n} a_i ,
  $$

  where $D_\text{max}$ is `max_density`, 2.75 m⁻² by default.

- **Supply.** With `supply_reduction=True`, a node whose density lies
  above the peak-flow density accepts only part of its inflow capacity:

  $$
  \varphi_n = \operatorname{clip}\!\left(
      \frac{D_\text{max} - D_n}{D_\text{max} - D_\text{peak}},\, 0,\, 1
  \right),
  \qquad
  \alpha_n = \gamma_n + \varphi_n \sum_{\ell \to n} C_\ell\,\Delta t
  \quad (\varphi_n < 1).
  $$

  Here $D_\text{peak} = 1/(2a)$. The node carry $\gamma_n$ keeps the
  fractional part of $\alpha_n$ for the next step, so that low inflow
  rates aren't rounded away.

Candidates pass one at a time while their summed area factors stay within
$\min(F_n, \alpha_n)$.

**Merging.** When several links compete for what a node accepts, the
node serves them in the order of the key

$$
\kappa = \tau_\ell + \frac{r + 1}{m_\ell},
$$

where $r$ is the candidate's place in its own queue in this step. Equal
keys are broken at random. The virtual time $\tau_\ell$ grows by
$q_\ell / m_\ell$ when $q_\ell$ agents pass, and a link with an empty
queue is moved up to the smallest $\tau$ of the active links into the
same node. Over time each link's share approaches $m_\ell / \sum m$.

**Carry update.**

- If agents are still waiting at a link, the carry becomes
  $c_\ell = \min\bigl(\beta_\ell - q_\ell,\ \max(C_\ell\,\Delta t, 1)\bigr)$.
- If no one is waiting, it is reset to $c_\ell = 1$. An idle door
  therefore lets the first agent through at once, and the last of $N$
  agents passes after $(N-1)/C_\ell$, the usual hand-calculation result.

### 5. Commit

Agents that passed a link move to its target node. There they walk the
length of their next link, or they are marked safe with exit time
$t + \Delta t$. Space freed by agents who leave a node becomes available
in the next step.

## Verification

The tests in `tests/test_network.py` check the model against hand
calculations and the IMO MSC.1/Circ.1533 test cases [4]:

| Case | Expected | Tolerance |
|------|----------|-----------|
| IMO 1: 40 m at 1.0 m/s | 40 s | 0.5 s |
| IMO 3: stair speed, 18/28 cm, 10 m | $10 / (k(1-0.266\cdot0.54))$ | 0.25 s ($\Delta t = 0.1$ s) |
| IMO 4: 100 agents, 1 m door, $F_s = 1.33$ | $99/0.931 = 106.3$ s | 1 s |
| Opening, 0.6 m, no boundary layer | $49/0.78 = 62.8$ s | 0.5 s |
| 200 agents at 2 m⁻², 20 m | $20/(1.4\,(1-0.266\cdot2))$ | 0.6 s |
| Merge weights 1 : 3 | flow ratio 3 | 15 % |

Further tests check pre-movement delays, route choice, conservation of
agents, that `max_density` is never exceeded, reproducibility with a
fixed seed, and the means of the distributions.

```{figure} _static/network/door_and_merge.png
:alt: Cumulative door flow against the hand calculation, and the cumulative merge flows
:width: 100%
:align: center

(a) IMO test 4. The model follows the hand calculation $1 + C\,t$ to
within one time step. (b) Two rooms feeding a full corridor with merge
weights 1 : 3. Over 150 s the flows reach 3 : 1. At the start, room a
stalls between 3 s and 17 s while room b catches up on the share it lost
before the corridor filled (see {ref}`network-limitations`).
```

### Sensitivity to `max_density`

In EvacuatioNZ, raising the maximum node density from 2.5 to 3.5 m⁻²
more than doubled the RSET of a 21-storey hotel without pre-movement
delay, from 539 s to 1232 s [5] (Table 5.5, p. 55). With pre-movement
delay the increase was smaller, from 796 s to 1156 s. At densities close to jam density
($1/a \approx 3.76$ m⁻²) a full node lets almost no one move. A hard
capacity limit then lets a node fill up to that density, and the stream
locks up.

The figure below repeats the experiment with this model on a ten-storey
building with one stair, comparing the two settings of `supply_reduction`.
With a hard limit only, the RSET grows sharply above 3 m⁻². With supply
reduction, it stays almost constant. This comparison only shows that
supply reduction removes the effect in this model. The building is not
the one Tsai used, so it says nothing about EvacuatioNZ's own numbers.

```{figure} _static/network/max_density_sweep.png
:alt: RSET against max_density with and without supply reduction
:width: 70%
:align: center

Ten floors of 60 agents each (400 m² per floor, pre-movement U(30, 120) s)
and one stair of 1.2 m with 0.9 m doors, all connected one way. The
line is the median of 30 runs and the band covers 5–95 %.
```

### Monte Carlo

```{figure} _static/network/monte_carlo.png
:alt: Histogram of RSET over 300 runs
:width: 70%
:align: center

The same building with two stairs and half of each floor sent to each
stair. Pre-movement times are LogNormal with mean 120 s and standard
deviation 60 s, truncated at 600 s. The 300 runs take about 30 s
together.
```

```{figure} _static/network/building.gif
:alt: Animation of node densities in a ten-storey building with two stairs
:width: 100%
:align: center

One run of the two-stair building. Floors are shaded by density, and the
stair flights fill to about 2.3 m⁻² while the doors from the floors
compete with the stream from above.
```

(network-comparison)=
## Comparison with EvacuatioNZ

EvacuatioNZ is a closed-source network model by M. Spearpoint. The table
compares its documented behaviour with this implementation. No licensed
copy of EvacuatioNZ was used, so the comparison rests only on its
published guides, its website and Tsai's thesis. Page numbers refer to
the PDF pages of the Exercise guide and to the printed pages of the
thesis.

| Aspect | EvacuatioNZ | `jupedsim_network` |
|--------|-------------|--------------------|
| Speed in a node | SFPE $S = k(1-0.266D)$, $D \ge 0.54$ [2] §2.1 | same |
| Door flow | $F_s = 1.33$ default, boundary layer 0.15 m [2] §2.2, [3] p. 6 | $F_s = 1.3$ default (SFPE), configurable per link |
| Stairs | stair node with an `enz_stairs` connection; $F_s$ from the SFPE table (website) | stair node with area and $k(R,T)$; link flow $k/(4a)$ |
| Node capacity | hard maximum node density, default 2.75 m⁻² [3] p. 6 | hard `max_density` plus a linear supply reduction above 1.88 m⁻² |
| Agent size | one density for all agents. In v1.2 a "local occupant density" was lowered to represent disabled occupants [5] | area factor per agent, counted in density and free space |
| Update order | sequential by default (`enz_sequential`). Random orders are optional [3] p. 6, p. 45 | synchronous, so independent of storage order |
| Queue near the door | "congested node" algorithm shortens the walk of agents who join a queue: 22.5 s with it, 31.5 s without, 30.5 s by hand [3] pp. 18–19 | not modelled. Agents walk the full link length at the node speed |
| Merging | 50 : 50 by default. `<Merge>` weights 1 : 3 gave 2.8 : 1 [3] p. 38 | weights by stride scheduling. 1 : 3 gives about 3 : 1 |
| Counterflow | optional. Its exercise is still marked "To do" [3] p. 46. Half the effective width is discussed in [6] | not modelled. Each direction keeps its full capacity |
| Routes | many exit behaviours (distance, signs, preferred links, least populated, leader, …) with reassessment (website) | shortest distance or a fixed target, no reassessment |
| Pre-movement | seven distribution types with truncation, plus a decision model (website) | six distribution types with truncation |
| Lighting, smoke, groups, node delays | yes (website) | no |
| Verification | IMO tests, FEDG example (179 s), SFPE 9-storey example (1871 s against 1524 s by hand) [2] §2.4–2.5 | IMO tests 1, 3 and 4, plus hand calculations |
| Validation | Jean Talon drill, 827 s against 863 s observed, with the pre-movement spread tuned to the drill [5] p. 88. A simple network of 61 nodes and a detailed one of 496 nodes gave similar RSET [5] pp. 53, 64 | none yet |
| Source | closed. The licence forbids reverse engineering | open (LGPL-3.0) |

(network-limitations)=
## Limitations

- **Ties between equally distant exits are not split.** With two stairs
  at the same distance, every agent takes the stair found first, and the
  second stair stays empty. Until this is fixed, split the populations by
  hand with `target`.

  ```{figure} _static/network/route_tie.png
  :alt: Cumulative evacuation curves showing that a tie sends everyone down one stair
  :width: 70%
  :align: center

  Two equally distant stairs. Nearest-exit routing evacuates as slowly
  as a building with a single stair (702.5 s). Splitting the targets by
  hand cuts the time by 42 % (405.5 s).
  ```

- **Supply counts every incoming link.** The inflow capacity
  $\sum_{\ell \to n} C_\ell$ in the supply factor includes links that
  rarely carry anyone, such as the reverse direction of a bidirectional
  connection. Such a node then accepts more inflow than intended when
  it is nearly full. The building figures use one-way links
  (`bidirectional=False`) for this reason.
- **Routes are static.** They are computed once from link lengths. Agents
  don't react to queues, blocked exits, signs or smoke.
- **Counterflow isn't modelled.** The two directions of a bidirectional
  connection are separate links, each with the full capacity, so a door
  used both ways passes twice its capacity.
- **Nodes are well mixed.** All walkers in a node share one density and
  one speed, so local crowding inside a large room isn't seen. Queued
  agents are taken to stand at the constriction, and a long queue
  doesn't add walking distance. Splitting large spaces into several
  nodes helps.
- **One length per link.** The walking distance to a door doesn't depend
  on where in the room an agent starts, apart from the sampled
  `start_distance`. Both directions of a connection use the same length.
- **Results are quantised by the time step.** Agents leave at the end of
  a step, so exit times and RSET are multiples of $\Delta t$. Stair
  speeds need $\Delta t \approx 0.1$ s to match a hand calculation within
  0.25 s.
- **Merge shares remember the past.** Virtual times accumulate while a
  node is not yet full. When it fills, the link with the lower weight can
  stall until the shares are balanced again, for example room a in the
  merge figure.
- **The supply reduction is a modelling choice.** Its linear form between
  1.88 m⁻² and `max_density` hasn't been calibrated against
  experiments. `max_density` must stay below the jam density of 3.76 m⁻².
- **Behaviour is minimal.** There are no lighting or smoke effects on
  speed, no groups, refuges, phased evacuation or node delays. Mobility
  impairment can be represented only through speed and area factor.
- **Not validated.** The model has been verified against hand
  calculations and IMO component tests. It hasn't been compared with
  evacuation drills, experiments, EvacuatioNZ runs or JuPedSim's
  microscopic models.
- **Output counts heads.** `node_occupancy` counts agents, not area
  factors, so it differs from the density used by the model when area
  factors other than 1 are present.

The figures and animations on this page are produced by
`docs/source/_scripts/network/make_figures.py` and `make_gifs.py`.

## References

1. S. M. V. Gwynne and E. R. Rosenbaum, "Employing the hydraulic model in
   assessing emergency movement", in *SFPE Handbook of Fire Protection
   Engineering*, 5th ed., Springer, 2016.
2. M. J. Spearpoint, *EvacuatioNZ verification*, version 2.11, 2016.
3. M. J. Spearpoint, *Evacuationz Exercise Guide*, June 2022.
4. International Maritime Organization, *Revised guidelines on evacuation
   analysis for new and existing passenger ships*, MSC.1/Circ.1533, 2016.
5. W.-L. Tsai, *Validation of EvacuatioNZ model for high-rise building
   analysis*, Fire Engineering Research Report, University of Canterbury,
   2007.
6. M. Arnott, M. Spearpoint, S. Gwynne and A. Templeton, "Counterflow in
   computational evacuation modelling: the hydraulic model, modelling
   tools and trials", *Fire and Evacuation Modeling Technical Conference
   (FEMTC)*, 2022.
