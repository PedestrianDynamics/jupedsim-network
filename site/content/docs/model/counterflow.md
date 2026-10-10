---
title: Counterflow
weight: 3
description: How the two links of a two-way connection share one door when agents use it in both directions, the presets of the counterflow setting, their sources and the candidate forms compared.
---

A two-way `connect` creates two links, one in each direction. When
agents use such a connection in both directions, the two links share
one door. The setting `counterflow` of `NetworkSimulation` decides how
much the door passes in total and how it splits the passages between
the two directions. The default is `"bounding"`.

The SFPE hydraulic model has no counterflow term. The 6th edition
chapter mentions counterflow only through one entry in its reference
list {{< cite 1 "ref. 57, p. 2199" >}}. The rule on this page is
therefore an extension of this model. It is calibrated on walkway and
stair data, not validated
([Limitations]({{< relref "/docs/limitations#movement-and-capacity" >}})).

## Choose a setting

```python
NetworkSimulation(network, populations, counterflow="bounding")
```

| `counterflow` | Total of both directions while both queue | Split | Carry |
|---------------|-------------------------------------------|-------|-------|
| `"bounding"` (default) | 0.84–0.94 C (doors, openings), 0.75–0.94 C (stairs) | by queue share, at least 17 % per direction | one for the pair |
| `"estimate"` | 0.90–1.00 C (doors, openings), 0.80–1.00 C (stairs) | by queue share, at least 17 % per direction | one for the pair |
| `"independent"` | 2 C: each link keeps its full capacity | none | one per link |

$C = F_s\,(w - 2b)$ is the one-way capacity of each link of the pair in
persons/s. Any other value raises `ValueError`. The constants are
private (`simulation._COUNTERFLOW`); there is no public way to change
them.

`"independent"` is the behaviour of versions before this rule. Under
`"estimate"` a door used 50/50 passes $C/2$ each way. Under `"bounding"`
it passes $0.47\,C$ each way.

## When it acts

- **Pairs.** The two links created by one
  `connect(..., bidirectional=True)` call form a pair. A connection into
  a safe node creates one link and no pair. Two one-way `connect` calls
  between the same nodes are two doors, each with its full $C$.
- **Active steps.** A pair is in counterflow in a step when both of its
  links have a queue. There is no smoothing and no memory of earlier
  steps, apart from the carry.
- **The carry is always shared.** Under `"bounding"` and `"estimate"`
  the pair holds one carry, even when only one direction queues. A
  passage in one direction uses credit the other direction would have
  had.
- **Default routing never uses a link both ways.** Without `target`,
  every shortest route moves closer to a safe node, or as close over
  fewer links, so no agent walks a link against another
  ([Verification]({{< relref "/docs/verification#tests" >}}), chain
  row). Counterflow arises only when populations have different
  `target`s.

A run gives the same result under all three values unless some pair is
in counterflow in some step or passes agents in both directions at any
time. The second case can matter. Take two 200 m² rooms A and B joined
by one two-way 1 m door of length 0 ($C\,\Delta t = 0.455$), each with
an exit of length 0. One agent in A heads for B's exit at once. One
agent in B heads for A's exit after a pre-movement time of 0.5 s. The
two queues never exist together.

| `counterflow` | Exit times |
|---------------|------------|
| `"independent"` | 1.0 s and 1.5 s |
| `"estimate"`, `"bounding"` | 1.0 s and 2.0 s |

The first passage leaves a carry of $1.455 - 1 = 0.455$. One step later
the budget is $0.455 + 0.455 = 0.91 < 1$, so the second agent passes one
step later than with its own carry.

## The rule

The rule runs inside stage 4 of the
[update scheme]({{< relref "/docs/model/update-scheme#4-passing-links" >}})
(code: `simulation._Run._pair_state`, `_trim_pairs`, `_pair_excess`,
`_update_carry`, `_update_pair_time`; pairing in
`network.Network.connect`).

| Symbol | Meaning | Unit |
|--------|---------|------|
| $\ell$, $\bar\ell$ | the two links of one pair | – |
| $C$ | one-way capacity of each link, $F_s(w - 2b)$ | persons/s |
| $n_\ell$ | agents queued at $\ell$ in this step, after walking | – |
| $s_\ell = n_\ell/(n_\ell + n_{\bar\ell})$ | queue share of $\ell$ | – |
| $s = \min(s_\ell, s_{\bar\ell})$ | minor share, in $(0, \tfrac12]$ | – |
| $g(s)$ | two-way total in units of $C$ | – |
| $y_\ell$ | pass share of $\ell$; $y_0$ its minimum | – |
| $c_P$, $B_P$ | pair carry and pair budget | agents |
| $\sigma_\ell$, $\lambda$ | pair counter of $\ell$ and pair key | – |
| $j$ | place of a candidate among this step's candidates on its own link, $0, 1, \ldots$ | – |
| $\tilde C_\ell$ | effective capacity of $\ell$ in the supply limit | persons/s |

Shares count agents (heads), not area factors.

**Total and split.** In an active step

$$
g(s) = g_0 + (g_{1/2} - g_0)\,2s ,
$$

$$
y_\ell = y_0 + (1 - 2y_0)\,s_\ell ,
$$

$$
y_{\bar\ell} = 1 - y_\ell .
$$

$g$ is a linear interpolation between two anchors, $g_0$ at a vanishing
minor share and $g_{1/2}$ at balance. It is a choice of this model, not
a fitted law.

**Budget.** The pair has one budget per step:

$$
B_P = c_P + g(s)\,C\,\Delta t \quad\text{(active)},
$$

$$
B_P = c_P + C\,\Delta t \quad\text{(otherwise)} .
$$

At most $\lfloor B_P \rfloor$ agents pass the pair in the step, in both
directions together.

**Order inside stage 4.**

1. Each direction offers its first $\lfloor B_P \rfloor$ queued agents.
2. The target nodes admit them as before: free space, supply and merge
   key.
3. For each active pair, the first $\lfloor B_P \rfloor$ admitted agents
   in order of the pair key pass:
   $$
   \lambda = \sigma_\ell + \frac{j + 1}{y_\ell} .
   $$
   Equal keys go to the link that `connect` created first, without a
   random draw. The other agents stay queued.
4. The node carry $\gamma_n$ is updated with the passages that remain,
   so the allowance of a trimmed agent stays in $\gamma_n$ up to its cap.
5. In an active pair $\sigma_\ell$ grows by $q_\ell / y_\ell$, where
   $q_\ell$ agents passed $\ell$. Otherwise $\sigma_\ell = 0$, so each
   counterflow episode starts fresh.

**Carry.** After the step the pair keeps

$$
c_P = \operatorname{clip}\bigl(B_P - q_\ell - q_{\bar\ell},\ 0,\ 1\bigr),
$$

starting at $c_P = 1$. Under `"independent"` each link keeps its own
carry. Since $g \le 1$, a pair passes at most $1 + C\,t$ agents in any
interval $t$, in both directions together. Under `"independent"` each
link passes up to $1 + C\,t$, the pair up to $2 + 2C\,t$.

**Supply.** In an active step the link enters the supply limit of its
target node with its share of the door,

$$
\tilde C_\ell = y_\ell\,g(s)\,C ,
$$

and with $\tilde C_\ell = C$ otherwise. Since
$\tilde C_\ell \ge y_0\,g_0\,C > 0$, a link with a queue always counts.

## Presets and their sources

| `counterflow` | $y_0$ | $g_0 \to g_{1/2}$, door and opening | $g_0 \to g_{1/2}$, stair |
|---------------|-------|-------------------------------------|--------------------------|
| `"bounding"` | 0.17 | 0.84 → 0.94 | 0.75 → 0.94 |
| `"estimate"` | 0.17 | 0.90 → 1.00 | 0.80 → 1.00 |

Stair entries (`kind="stair"`) use the stair values; doors and openings
use the door values. The anchors are calibration choices, not
validation.

| Value | Source | Note |
|-------|--------|------|
| $y_0 = 0.17$ | Navin and Wheeler: a stream with $V$ % of the flow takes $Y = 17 + 0.64\,V$ % of the width, on 7–8 ft sidewalks {{< cite 21 "p. 36; Fig. 1, p. 31" >}} | Adapted: used as a share of passages, not of width, with slope $1 - 2y_0 = 0.66$ so that $y_\ell + y_{\bar\ell} = 1$ |
| door $g_{1/2} = 0.94$ (`bounding`) | maxima of 24.7 (two-way) and 26.2 (one-way) persons/ft/min, ratio 0.94 {{< cite 22 "p. 4" >}}; 0.94 at 180° {{< cite 28 "Fig. 6" >}} | lowest balanced walkway total; ratio our arithmetic |
| door $g_0 = 0.84$ (`bounding`) | loss of 14.5, 11.5, 8.5, 6.0, 4.0 % at minor share 0.1–0.5, i.e. $g$ = 0.855–0.96 {{< cite 21 "Table III, p. 36" >}}; "capacity reductions of about 15 percent" at 90/10 {{< cite 31 "p. 11-7" >}} | $0.84 + 0.2\,s$ lies at or below Navin and Wheeler for $s$ = 0.2–0.5 and 0.005 above at $s = 0.1$ |
| door $g_{1/2} = 1.00$ (`estimate`) | "pedestrians equally share the width" {{< cite 24 "p. 1613" >}}; two-way about equal to one-way at 50/50 {{< cite 23 "p. 44" >}} | between walkways (0.94–0.96) and Arnott's door (1.05–1.14) |
| door $g_0 = 0.90$ (`estimate`) | gives $g(0.1) = 0.92$, close to the middle (0.91) of the walkway range 0.84–0.98 at $s \approx 0.1$ | 0.98 is Wong et al.'s model at $s \approx 0.1$ {{< cite 28 "Eq. 1" >}}, our computation |
| stair $g_0 = 0.75$ (`bounding`) | Tofiło et al.'s recommendation {{< cite 29 "p. 520" >}}. Their single runs on one 1.15 m stair give 0.75 (Fig. 6, flow, read by eye) to 0.78 (Table 4, last-out time) {{< cite 29 "Fig. 6, p. 520; Table 4, p. 515" >}} | a fraction of the no-counterflow flow, not of capacity; corroborated by Cheung and Lam's about 25 % stair loss {{< cite 24 "Fig. 3, p. 1615" >}} |
| stair $g_0 = 0.80$ (`estimate`) | 17–19 % flow reduction at 1–2 persons/m², read by eye {{< cite 29 "Fig. 6, p. 520" >}}; 20–27 % {{< cite 24 "Fig. 3, p. 1615" >}} | – |
| stair $g_{1/2}$ = 0.94 / 1.00 | 0.94 borrowed from walkways (no stair total at balance); 1.00: loss about 0 at 50/50 {{< cite 24 "Fig. 3, p. 1615" >}} | – |

Whether Navin and Wheeler's 17 % width intercept carries over to a
minimum share of passages is open.

## Evidence

$g$ is the two-way total divided by a one-way value. The baseline
matters. Only Arnott et al.'s door can be stated against this model's
$C = F_s(w - 2b)$; the other studies divide by their own measured
one-way flow or capacity.

{{< details title="Evidence by facility" closed="true" >}}

| Facility | Value | Baseline | Source |
|----------|-------|----------|--------|
| Walkway, balanced | $g \approx$ 0.94–1.0: 0.96; 0.94; about 1; "little reduction"; 0.94 | measured one-way | {{< cite 21 "Table III, p. 36" 22 "p. 4" 24 "p. 1613" 31 "p. 11-7" 28 "Fig. 6" >}} |
| Walkway, minor share about 0.1 | $g \approx$ 0.84–0.86; or 0.98 from Wong et al.'s model (our computation). Not established | measured one-way | {{< cite 21 "Table III, p. 36" 31 "p. 11-7" 24 "p. 1616" 28 "Eq. 1" >}} |
| Door 1.72 m, about 50/50 | 0.97 and 1.05 persons/s per direction: 1.05–1.14 × the SFPE half of 0.92 persons/s (our arithmetic), 1.15–1.25 × half the measured one-way flow of 1.56–1.79 persons/s | SFPE $C$ and measured one-way | {{< cite 6 "pp. 5–6; Table 1, p. 10" >}} |
| Stairs | minor-direction capacity 53/67 = 0.79 ascending and 60/78 = 0.77 descending at flow ratio 0.1 (our arithmetic); about 25 % loss as the minor share → 0 | measured one-way capacity | {{< cite 27 "Observation Results, Figs. 2a–b" 24 "Fig. 3, p. 1615" >}} |
| Firefighters ascending a stair | 5 firefighters against 73 descending students on 1.15 m flights: flow reduction 3–25 %, one run per density; evacuees moved "considerably faster" than in real evacuations; speeds 0.83–0.97 of free speed in the same experiment | measured flow without counterflow | {{< cite 29 "pp. 518, 520" 30 "Table 7, p. 38" >}} |
| Design rules | narrow stairs: a minor flow can "cut … in half" the capacity; lanes of at least 30 in | none (no data) | {{< cite 23 "pp. 61, 79, 160" >}} |
| Corridors, other | 0.75 from Voronoi fundamental diagrams, not a cross-section flow; 1.43 against an unsaturated one-way baseline (our arithmetic) | measured one-way | {{< cite 32 "§4.1, Fig. 9b" 33 "pp. 7–8" >}} |

{{< /details >}}

- No study measures a door away from a 50/50 split. Every door value
  below 50/50 is borrowed from walkways.
- Stairs lose more to opposing flow than walkways.
- Arnott et al. took the flows "only … while people were moving in
  both directions" {{< cite 6 "p. 5" >}}. All data come from
  non-emergency movement or trials.
- $g = 2$ (`"independent"`) lies above every value in the table.

## Candidate forms

Seven forms were compared before the rule was chosen.

| Form | Rule | Evidence (baseline) | Limits | In the code |
|------|------|---------------------|--------|-------------|
| M0 | $C$ each way, $g = 2$ | none; above all data | a door passes twice its capacity | `"independent"` |
| M1 | $C/2$ each way while both are active | Arnott's door at about 50/50: 5–14 % conservative against the SFPE half {{< cite 6 "p. 6" >}}; EvacuatioNZ v2.14 as reported by Arnott et al. {{< cite 6 "p. 8" >}}; "cut … in half" for narrow stairs, a design rule {{< cite 23 "pp. 61, 160" >}} | at $s \approx 0.1$ caps the major stream at $0.5\,C$ against about 0.77–0.80 C in walkway data; jumps at the first opposing agent | not offered; `"estimate"` equals it at $s = \tfrac12$ |
| M2 | shared $C$ split by demand, $g = 1$ | {{< cite 24 "Eqs. 3–4, p. 1613" 25 "p. 184" 23 "p. 44" >}}; 0.96 {{< cite 21 "Table III, p. 36" >}} | no minor-stream penalty; a small group waits behind almost the whole opposing queue | special case of the rule ($y_0 = 0$, $g \equiv 1$); not offered |
| M3 | shared $g(s)\,C$ split by demand | $g(s)$ from {{< cite 21 "Table III" 24 "Eqs. 7, 9" 26 "Tables 3–4" 28 "Eq. 1" 35 "Eqs. 8–14, pp. 22–24" >}} | every $s$-dependent $g$ comes from walkways; on a door it is extrapolation | **basis of the rule** |
| M4 | lanes, $\lfloor w_\text{eff}/w_\text{lane} \rfloor$, at least one per direction | lane counts {{< cite 21 "pp. 32, 36" 34 "p. 38" >}}; lane design {{< cite 23 "p. 160" >}} | no capacity validation; lane width 0.5–0.76 m across sources | not implemented; its minimum share enters as $y_0$ |
| M5 | alternation on single-lane links | none; Pathfinder's SFPE mode exchanges queues as a model rule {{< cite 36 "" >}} | – | not implemented |
| M6 | stair minus one lane while the minor stream is present | $w_\text{lane} \ge 30$ in, a design rule {{< cite 23 "p. 79" >}}; 75 % recommendation {{< cite 29 "p. 520" >}} | the lane rule leaves 0.34 of a 1.15 m stair to the major stream (a 66 % loss) against at most 25 % measured on that stair (our arithmetic, one experiment) | Tofiło et al.'s value enters as stair $g_0 = 0.75$; the lane form is documented only |

The rule follows M3 with a shared door. One shared carry keeps the pair
within $1 + C\,t$, so a sparse opposing stream cannot pass on credit
left idle on its own link. The rule contains M1 and M2 as special
cases. At 50/50, `"estimate"` gives the halving that Arnott et al.
report for EvacuatioNZ v2.14.

### Width form

Arnott et al. describe the halving as "half of the door width is taken
as the clear width", but their arithmetic is $(w - 2b)/2$: 0.92
persons/s for the 1.72 m door {{< cite 6 "p. 6" >}}. With
$F_s = 1.3$ persons/s/m and $b = 0.15$ m (our arithmetic):

| Door | $F_s(w - 2b)/2$ | $F_s(w/2 - 2b)$ | Measured per direction |
|------|-----------------|-----------------|------------------------|
| 1 m | 0.455 persons/s | 0.26 persons/s | – |
| 1.72 m | 0.923 persons/s | 0.728 persons/s | 0.97–1.05 persons/s {{< cite 6 "p. 6" >}} |

This model works on $C$, so its halving equivalent is
$C/2 = F_s(w - 2b)/2$. No source measures a gap between opposing
streams. The published sources do not state when EvacuatioNZ v2.14
applies its rule or how it forms the half width.

## Bounding or estimate

Gwynne et al. define bounding defaults as "derived from relevant
empirical data" {{< cite 11 "pp. 335–336" >}}, not from extreme
outliers {{< cite 11 "p. 343" >}}. They also allow values from "codes
and standards, or common practice" {{< cite 11 "p. 342" >}}.
`"bounding"` follows the first sense: its door values lie at the low
end of the walkway data, and its stair $g_0$ is Tofiło et al.'s
recommendation. M1 would follow the second (EvacuatioNZ, Fruin). The
default is `"bounding"`; `"estimate"` takes the centre of the data.

- The bound holds while both directions keep a queue. When the minor
  stream is sparse, its queue is empty in some steps, the loss is not
  charged then, and the realised total is higher, above Navin and
  Wheeler's 0.855 near $s = 0.1$.
- For doors at 50/50, `"bounding"` lies 10–18 % below the only door
  measurement (0.94 against 1.05–1.14).
- The other defaults of this model are design values, so the default
  set is mixed. Gwynne et al. ask: "Is this default 'scenario'
  conservative, optimal or somewhere in between?"
  {{< cite 11 "p. 342" >}}
  ([Limitations]({{< relref "/docs/limitations#defaults-compared-with-bounding-defaults" >}})).

Neither preset bounds the evacuation time or the realised two-way flow
in every case.

## What it changes

Runs where populations with different `target`s use a two-way
connection in both directions become slower by default than with
`"independent"`. The tests show two cases
([Verification]({{< relref "/docs/verification#tests" >}})).

- **36 against 4 at a 1 m door.** Under `"bounding"` the 4 agents of
  the minor stream pass at 4.0, 9.0, 15.5 and 22.0 s, 5.0–6.5 s apart,
  instead of waiting for the whole opposing queue. The last passage of
  the major stream moves from 38.5 s (`"independent"`) to 46.5 s.
- **Responders on a stair.** 4 responders enter a 1.2 m stair entry
  against 20 evacuees leaving it. The responders are out by 20.5 s
  (`"bounding"`) or 19.5 s (`"estimate"`) instead of 4.5 s. The
  evacuees' clearance rises from 21.5 s to 30.0 s or 29.0 s.

## Not modelled

- Counterflow inside nodes: corridors and stair flights keep the speed
  $k(1 - aD)$ with all agents counted, whatever their direction.
- There is no counterflow output
  ([issue #40](https://github.com/PedestrianDynamics/jupedsim-network/issues/40)).

See [Limitations]({{< relref "/docs/limitations#movement-and-capacity" >}}).
