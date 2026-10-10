---
title: Model elements
weight: 1
---

![Schematic of nodes connected by directed links](/images/network/schematic.png)

Rooms, corridors and stair flights are nodes, and directed links connect
them. An agent walks the length of its next link inside its current
node, then queues at the constriction and passes it when the link and
the receiving node allow. How to build a network is in
[Networks]({{< relref "/docs/using/networks" >}}); this page gives the
relations and the source of each value.

## Nodes

A node $n$ has an area $A_n$ and a speed constant $k_n$.

- **Rooms** use the level value $k = 84$ m/min $= 1.40$ m/s
  {{< cite 1 "Table 67.2, p. 2174" >}}.
- **Stair flights** take $k$ from the riser height $R$ and the tread
  depth $T$:

  $$
  k_\text{stair} = 51.8\,\sqrt{T/R}\ \text{m/min},
  $$

  the closed form used by EvacuatioNZ {{< cite 2 "§2.1.3, Eq. 2.1" 3 "p. 17" >}},
  which takes it from the New Zealand Fire Engineering Design Guide
  {{< cite 18 "p. 223" >}}. It
  reproduces the SFPE stair constants of Table 67.2
  {{< cite 1 "p. 2174" >}} to within about 1 % (our comparison). SFPE supports the
  $\sqrt{T/R}$ dependence only for risers of 165–191 mm and treads of
  254–330 mm {{< cite 1 "p. 2175" >}}. For 18/28 cm steps,
  $k_\text{stair} = 1.077$ m/s.
- **Safe nodes** have an unlimited area. Agents that reach one leave the
  simulation.

A stair is a node with an area, normally its width times the flight
length. Agents on the flight take up space and count towards its
density.

## Walking speed

The SFPE speed–density relation {{< cite 1 "Eq. 67.3, p. 2174" >}} is

$$
S = k\,(1 - a D), \qquad a = 0.266\ \text{m}^2\text{ per person},
$$

valid for densities from 0.54 to 3.8 m⁻². Below 0.54 m⁻² people walk at
their own pace {{< cite 1 "p. 2174" >}}. The model takes the density as
at least 0.54 m⁻², so the congested speed never exceeds
$k\,(1 - 0.266 \cdot 0.54)$:

- 1.199 m/s on level ground, which matches the unimpeded speed of
  1.19 m/s in SFPE Table 67.4 {{< cite 1 "p. 2175" >}};
- 0.922 m/s on an 18/28 cm stair.

Each agent walks at the smaller of its own free speed $v_i^\text{max}$
and this congested speed
([update scheme]({{< relref "/docs/model/update-scheme#3-walking" >}})). Free speeds
above the ceiling have no effect.

## Links

A link $\ell$ is a directed passage from a source node to a target node.
Its capacity in persons/s is

$$
C_\ell = F_s\,(w_\ell - 2 b_\ell),
$$

where $w_\ell$ is the clear width, $b_\ell$ the boundary layer on each
side and $F_s$ the specific flow in persons/s per m of effective width.

A link also has:

- **a length $L_\ell$**, the walking distance inside the *source* node up
  to the constriction. Both directions of a two-way connection use the
  same length. On a stair link this model takes it along the incline,
  since SFPE stair speeds apply along the line of travel
  {{< cite 1 "p. 2175" >}};
- **a merge weight $m_\ell$**, the relative share of the link when
  several links feed the same full node.

## Default values and sources

| Quantity | Value | Source | Code |
|----------|-------|--------|------|
| Slope $a$ | 0.266 m² per person | {{< cite 1 "Eq. 67.3, p. 2174" >}} | `hydraulic.SPEED_DENSITY_SLOPE` |
| Lower density | 0.54 m⁻² | {{< cite 1 "p. 2174" >}} | `hydraulic.MIN_DENSITY` |
| $k$, level | 84 m/min = 1.40 m/s | {{< cite 1 "Table 67.2, p. 2174" >}} | `hydraulic.LEVEL_SPEED_CONSTANT` |
| $k$, stair | $51.8\sqrt{T/R}$ m/min | EvacuatioNZ {{< cite 2 "§2.1.3" 3 "p. 17" >}} | `hydraulic.stair_speed_constant` |
| $F_s$, `door` and `opening` | 1.3 persons/s/m | {{< cite 1 "Table 67.5, p. 2176" >}} | `hydraulic.DOOR_SPECIFIC_FLOW` |
| $F_s$, `stair` | $k/(4a)$; 1.01 for 18/28 cm | derived, see below | `hydraulic.max_specific_flow` |
| $b$, `door` and `stair` | 0.15 m | {{< cite 1 "Table 67.1, p. 2174" >}} | `network._BOUNDARY_LAYERS` |
| $b$, `opening` | 0 m | as EvacuatioNZ `enz_opening` {{< cite 3 "p. 14" >}} | `network._BOUNDARY_LAYERS` |
| Peak-flow density | $1/(2a) = 1.88$ m⁻² | SFPE gives 1.9 {{< cite 1 "pp. 2175–2176" >}} | `hydraulic.PEAK_FLOW_DENSITY` |
| Jam density | $1/a = 3.76$ m⁻² | {{< cite 1 "p. 2175" >}} | `hydraulic.JAM_DENSITY` |
| `max_density` | 2.75 m⁻² | EvacuatioNZ default {{< cite 3 "p. 3" >}} | `NetworkSimulation` |

The stair specific flow is the maximum of the SFPE specific flow
$F_s = (1 - aD)\,kD$ {{< cite 1 "Eq. 67.6, p. 2176" >}}, reached at
$D = 1/(2a)$. SFPE tabulates this maximum (Table 67.5) but does not
write it as $k/(4a)$. The formula reproduces the table to rounding, for
example 1.08/1.064 = 1.015 against 1.01. For `door` links the code uses
the tabulated 1.3 instead of the level-ground maximum of $1.40/1.064 = 1.32$.

## Agents

A [population]({{< relref "/docs/using/populations" >}}) places agents in a
start node. Each agent $i$ has

- a free walking speed $v_i^\text{max}$,
- a pre-movement time $t_i^\text{pre}$,
- an extra start distance $s_i$,
- an area factor $a_i$. A value of 1 stands for an average adult.

The area factor scales the agent's contribution to the persons/m²
density of the SFPE relation. It is a choice of this model and is not
calibrated. SFPE notes that the hydraulic model does not consider body
size {{< cite 1 "p. 2185" >}}. The published approach to mixed body
sizes is the Predtechenskii–Milinskii dimensionless density, with its
own speed and flow curves {{< cite 1 "pp. 2185–2187" >}}; the area factor
is not that method.

## Routes

Each agent follows a fixed route to the nearest safe node, measured as
the sum of link lengths. A population with a `target` heads for that
safe node instead. One shortest-path table is computed per target before
the run starts. Details and the handling of ties are in
[Networks]({{< relref "/docs/using/networks#routes" >}}).

## Choices of this model

{{< details title="Where the model departs from the SFPE hydraulic model" closed="true" >}}
The SFPE hydraulic model counts people, not individuals, and gives all
of them one set of movement attributes {{< cite 1 "p. 2185" >}}. This
model adapts it as follows:

- **Individual agents.** Each agent has its own free speed,
  pre-movement time, start distance and area factor.
- **Free speed and congested speed.** An agent walks at
  $\min(v_i^\text{max}, k(1-aD))$. Combining the two is not part of
  SFPE.
- **Area factor.** See [Agents](#agents).
- **Stair speed.** The closed form $51.8\sqrt{T/R}$ comes from
  EvacuatioNZ, not from the SFPE chapter, and is used for any step size.
- **Stair specific flow.** $k/(4a)$ is computed from the stair geometry
  instead of read from SFPE Table 67.5.
- **Opening.** The zero boundary layer of `opening` follows EvacuatioNZ;
  SFPE gives 0 only for theatre chairs and stadium benches
  {{< cite 1 "Table 67.1, p. 2174" >}}.
- **Door specific flow.** 1.3 persons/s/m from SFPE; EvacuatioNZ uses
  1.33 by default {{< cite 2 "§2.2" >}}.
- **Densities above 1.88 m⁻².** SFPE states that densities above
  1.9 m⁻² should not be assumed in engineering designs
  {{< cite 1 "p. 2175" >}}. The whole range between the peak-flow
  density and `max_density`, including the supply reduction, is a
  choice of this model.
- **Passage time.** A fresh link, or one idle for at least $1/C$, lets
  the first agent through at once, so the last of $N$ agents passes
  after $(N-1)/C$. SFPE gives
  $N/C$ {{< cite 1 "Eq. 67.9, p. 2177" >}}
  ([update scheme]({{< relref "/docs/model/update-scheme#carry-update" >}})).
{{< /details >}}
