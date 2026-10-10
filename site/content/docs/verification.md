---
title: Verification
weight: 4
---

The model is verified: tests check that its components reproduce hand
calculations and adapted IMO test cases. It is also compared with the
results published in the EvacuatioNZ verification report; no
EvacuatioNZ runs were made. It is not validated: it has not been
compared with evacuation drills, experiments or JuPedSim's microscopic
models.

## Tests

The tests are in `tests/test_network.py` and
`tests/test_evacuationz_verification.py`. Run them from a clone of the
repository:

```
uv run pytest -q
```

The last line of the output reads `109 passed`, followed by the run
time.

The table lists the tests with a hand-calculated expectation. "Result"
is what the test measures with the current code.

| Case | Expected | Result | Tolerance | Test |
|------|----------|--------|-----------|------|
| IMO test 1: 40 m at 1.0 m/s | 40 s | 40.0 s | 0.5 s | `test_free_walking_speed_imo_test_1` |
| IMO test 3 geometry, stair speed from 18/28 cm steps, as in EvacuatioNZ {{< cite 2 "§2.1.3" >}} | $10/(k(1-0.266\cdot0.54)) = 10.84$ s | 11.0 s ($\Delta t = 0.1$ s) | 0.25 s | `test_stair_speed_imo_test_3` |
| IMO test 4 geometry, 100 agents, 1 m door, $F_s = 1.33$, hydraulic door flow as in EvacuatioNZ {{< cite 2 "§2.2" >}} | $(N-1)/C = 99/0.931 = 106.3$ s | 106.5 s | 1 s | `test_door_flow_imo_test_4` |
| 50 agents, 0.6 m opening | $(N-1)/C = 49/0.78 = 62.8$ s | 63.0 s | 0.5 s | `test_opening_has_no_boundary_layer` |
| 200 agents at 2 m⁻² walk 20 m {{< cite 3 "p. 15" >}} | $20/(1.4\,(1-0.266\cdot2)) = 30.5$ s | 31.0 s | 0.6 s | `test_congested_walking_speed` |
| Merge weights 1 : 3 over 150 s | flow ratio 3 | 3.0 | 15 % | `test_merge_weights_split_flow` |
| Stair 7/11 in: $k$ and $F_s = k/(4a)$ | 1.08 m/s (SFPE Table 67.2 {{< cite 1 "p. 2174" >}}), 1.01 persons/s/m (SFPE Table 67.5 {{< cite 1 "p. 2176" >}}) | 1.081, 1.016 | 0.01 | `test_stair_specific_flow_follows_geometry` |

Further tests check pre-movement delays, route choice, conservation of
agents, that `max_density` is never exceeded, that no link passes more
than $1 + C\,t$ agents in any interval $t$, reproducibility with a
fixed seed, the stair-range warning, `nan` for incomplete runs, quantiles with incomplete runs,
the error messages, and the means and truncation of the distributions.

### IMO tests as written and as tested

The IMO test cases are in MSC.1/Circ.1533, Appendix 2, paragraphs 3–6
{{< cite 4 "" >}}.

- **Test 1** (one person, 2 m × 40 m corridor, 1 m/s, 40 s) is tested
  as written.
- **Test 3** as written asks that one person with a walking speed of
  1 m/s covers a 2 m wide stair of 10 m, measured along the incline, in
  10 s {{< cite 4 "" >}}. **With 18/28 cm steps this model does not
  meet it, by design.** On a stair the input speed only caps the walking
  speed, which comes from the stair geometry: $k = 51.8\sqrt{T/R}$ gives
  1.077 m/s for 18/28 cm steps, and $k(1 - 0.266 \cdot 0.54) = 0.922$
  m/s. A lone walker takes 10.84 s by hand calculation (11.0 s in the
  run at $\Delta t = 0.1$ s) instead of 10 s. Shallower steps with
  $T/R \ge 1.83$ cap the stair speed at or above 1 m/s. The test checks
  this adaptation, the same one EvacuatioNZ uses for its stair
  verification {{< cite 2 "§2.1.3" >}}.
- **Test 4** asks for 100 persons in an 8 m × 5 m room with a 1 m exit,
  and that the flow over the whole period does not exceed 1.33 persons/s
  {{< cite 4 "" >}}. The link capacity of 0.931 persons/s and the mean flow of
  100/106.5 s = 0.94 persons/s both meet this criterion.
  Specific flow, boundary layers and a target time are not part of the
  test; the construction $1.33 \times 0.7$ m is EvacuatioNZ's
  {{< cite 2 "§2.2" >}}.

### Passage time: (N−1)/C and N/C

The door rows check the model's own convention, in which the first
agent passes at once and the last after $(N-1)/C$
([update scheme]({{< relref "/docs/model/update-scheme#carry-update" >}})). The
SFPE hand calculation is $N/C$ {{< cite 1 "Eq. 67.9, p. 2177" >}}:

| Case | Model | $(N-1)/C$ | SFPE $N/C$ | EvacuatioNZ {{< cite 2 "§2.2" >}} |
|------|-------|-----------|------------|-------------|
| IMO 4 geometry | 106.5 s | 106.3 s | 107.4 s | 107.5 s by hand, 108 s simulated |
| 0.6 m opening | 63.0 s | 62.8 s | 64.1 s | |

The SFPE value for IMO 4 lies 1.07 s from the test's expectation, more
than its tolerance of 1 s. The model result lies 0.9 s below it.

## EvacuatioNZ verification cases

The cases of the EvacuatioNZ verification report version 2.11
{{< cite 2 "" >}} are rebuilt with this model and compared three ways:
the hand value, the result published in the report, and this model at
$\Delta t = 0.5$ s. No EvacuatioNZ runs were made. Page numbers are the
printed page numbers of the report; the PDF page is one higher. The
tests are in `tests/test_evacuationz_verification.py`. Every expected
value in them is a hand calculation; values read from figures of the
report are never asserted.

The report's inputs are mapped the same way in every case. These rules
are accepted for the EvacuatioNZ cases only:

- A door (`enz_door`) is a door with $b = 0.15$ m and $F_s = 1.33$
  persons/s/m, EvacuatioNZ's value, passed explicitly in each case; the
  model's default stays $F_s = 1.3$. An untyped connection is an opening
  with $b = 0$ and $F_s = 1.33$, and stairs (`enz_stairs`) are a stair
  node with $F_s = k/(4a)$ from the step geometry.
- A connection that is both stair and door is one link with the lower
  of the two capacities.
- This model walks a link's length inside the source node, so stair
  travel is put on the link leaving the stair node. The total distance
  is unchanged.
- A stair given by its height $H$ has the length
  $L = H\sqrt{1 + (T/R)^2}$.
- A random start distance is $U(0, L_{\max})$ with $L_{\max}$ stated per
  case; the report does not give the range.

| Case | Report | Hand value | EvacuatioNZ | This model | Explanation |
|------|--------|------------|-------------|------------|-------------|
| Travel speed, 40 m along a link or from a start distance at 1.0 m/s | §2.1.1–2.1.2, pp. 6–7 | 40 s | 40.5 s | 40.0 s | `test_travel_speed_from_start_distance` |
| Stair speed, 10 m of 180/280 mm steps | §2.1.3, p. 8 | 10.9 s (Eq. 2.1), 10.5 s (SFPE table) | 12 s | 11.0 s ($\Delta t = 0.1$ s), 11.5 s ($\Delta t = 0.5$ s) | At $\Delta t = 0.5$ s: 10.84 s, plus one step for the transfer into the stair, rounded up to the step. `test_stair_speed_imo_test_3`, `test_stair_flow_uncongested` |
| Door flow, IMO 4 room, 100 agents, 1 m door | §2.2, p. 9 | 107.5 s ($N/C$ with $C = 0.93$) | 108 s | 106.5 s | This model's convention is $(N-1)/C = 106.3$ s, see above |
| Door flow, 1–3 m doors and 1 m opening, 1–100 agents | §2.2, p. 10 | $(N-1)/C$ | Fig. 2.2, graph only | table below | `test_door_flow_widths` |
| Stair flow, 1–1000 agents, stairs 10 × 1, 200 × 1 and 200 × 5 m | §2.3, pp. 12–13 | $L/S_0 + (N-1)/C$ | Fig. 2.6, graph only | table below | `test_stair_flow_*` |
| Fire Engineering Design Guide, 90 agents, room over one stair | §2.4, pp. 13–15 | 186 s (FEDG) | 179 s; 168 s with random start | first exit 30.5 s; last exit 129.0 s | Capacity bound $30.5 + 89/0.911 = 128.2$ s, see below. `test_fedg_first_exit`, `test_fedg_last_exit_bound` |
| SFPE Handbook nine-storey building | §2.5, pp. 15–17 | 1524 s (SFPE Solution A, 25.4 min; Solution B 1518 s); ≥ 1538.9 s in this model's conventions ($t_{\text{first}} + 1199/0.811$) | 1871 s (v2.11); 1471 ± 3 s in {{< cite 7 "manuscript p. 20; Fig. 10" >}} (2009, different network) | 1548.5 s (stand-in) | 300 per floor on floors 2–9 {{< cite 1 "p. 2181" >}} {{< cite 7 "Fig. 11" >}} and a 36 in exit door per stair from the SFPE example {{< cite 1 "p. 2181" >}}; the report gives neither, and neither EvacuatioNZ document gives the ground-floor exit. The exit door (0.811/s) controls: $70.0 + 1199/0.811$. Stair length 6.76 m from $H = 12$ ft. Landings are nodes: each link's length is walked in the node it leaves, so the 4.8 m of landing travel is level travel and corridor→landing is 4.8 m shorter below the top floor. With the landing travel walked on the stair link instead, 1915.0 s. Agents start at the room door; the report draws a random start distance. With a start $U(0, 91.44)$ m, 1543.0 s (seed 1; first exit 64.0 s instead of 70.0 s; the exit door still controls). `test_sfpe_nine_storey` |
| SFPE Guide on Human Behavior, example 1, 300 agents, start at the door | §2.6, pp. 18–20 | 246 s (Guide); 234.95 s in this model's conventions | 221.5 s | 235.5 s (stand-in) | $149/0.682 + 15.27/S_0$. `test_sfpe_guide_example_1` |
| The same, start 200 ft from the door | §2.6, pp. 18–20 | 300 s (Guide); 285.8 s in this model's conventions | 283 s | 286.0 s (stand-in) | Plus 60.96 m at 1.199 m/s |
| Distributions: fixed 45 and 120 s, $U(10, 100)$, $N(120, 30)$, log-normal mean 5, sd 2 | §3.1, pp. 21–25 | means 55, 120, 5; sd 25.98, 30, 2 | Figs. 3.1–3.3, graph only | means 54.88, 119.66, 4.97; sd 26.07, 29.82, 1.99 (20 000 samples) | `test_fixed_distribution_is_exact`, `test_distribution_moments` |
| Room clearance, IMO 4 room, fixed delay 0, 30, 120 s | §3.2, p. 25 | $d + (N-1)/C$ | Fig. 3.4, graph only (≈ 114, 144, 234 s) | 106.5, 136.5, 226.5 s (start 0) | A fixed delay shifts the result by exactly $d$, also with a dispersed start $U(0, 8)$ m and the same seed. EvacuatioNZ's dispersed run without delay lies about 6 s above its own 108 s with the start at the door; this model gives 106.5 s at the door and 106.5–107.0 s with a dispersed start. `test_room_clearance_*` |
| Room clearance, triangular delay (0, $m$, $2m$), $m$ = 15, 30, 60 s, start at the door, seed 0 | §3.2, p. 25 | $\max_i(\tau_{(i)} + (N-1-i)/C)$: 107.84, 110.41, 128.01 s | Fig. 3.4, graph only | 108.5, 111.0, 128.5 s | Each lies 0.49–0.66 s above its bound. `test_room_clearance_triangular_bound` |
| Room clearance, fixed delay 0, dispersed start $U(0, 8)$ m, 20 seeds | §3.2, p. 25 | $(N-1)/C = 106.3$ s | Fig. 3.4, graph only (≈ 114 s) | 106.5–107.0 s, mean 106.6 s | No seed lies below the hand value. `test_room_clearance_dispersed_without_delay` |
| Exit choice, minimum distance | §5.1.1, p. 31 | Exit 5 | Exit 5 | Exit 5 | `test_exit_choice` |
| Exit choice, specified exit | §5.1.5, p. 33 | Exit 6 | Exit 6 | Exit 6 | `test_exit_choice` |
| Required connection | §5.2, pp. 34–35 | direct door | direct door | through Room 2 and Room 3 | Not modelled. `test_required_connection_is_not_modelled` |

Door and opening flow with the IMO 4 room, $F_s = 1.33$, start at the
door. Every result lies within one step above $(N-1)/C$:

| Width | $N = 1$ | $N = 10$ | $N = 100$ |
|-------|---------|----------|-----------|
| 1 m door | 0.5 s | 10.0 s | 106.5 s |
| 2 m door | 0.5 s | 4.0 s | 44.0 s |
| 3 m door | 0.5 s | 3.0 s | 28.0 s |
| 1 m opening | 0.5 s | 7.0 s | 74.5 s |

Stair flow with 180/280 mm steps: $k = 1.0768$ m/s, free stair speed
$S_0 = k(1 - 0.266 \cdot 0.54) = 0.9221$ m/s and $C = 1.012\,(w - 0.3)$.
The text of §2.3 names two stairs; the caption of Fig. 2.7 names 200 m
stairs of 1.0 m and 5.0 m. All three are run.

| Stair | $N$ | This model | $L/S_0 + (N-1)/C$ | Peak on the stair |
|-------|-----|------------|-------------------|-------------------|
| 10 × 1 m | 1 | 11.5 s | 10.84 s | 1 |
| 10 × 1 m | 10 | 26.0 s | 23.55 s | 10 |
| 10 × 1 m | 100 | 168.5 s | 150.60 s | 27 (limit) |
| 10 × 1 m | 1000 | 1439.0 s | 1421.07 s | 27 (limit) |
| 200 × 1 m | 1 | 217.5 s | 216.90 s | 1 |
| 200 × 1 m | 10 | 230.0 s | 229.60 s | 10 |
| 200 × 1 m | 100 | 357.0 s | 356.65 s | 100 |
| 200 × 1 m | 1000 | 1984.0 s | 1627.12 s | 550 (limit) |
| 200 × 5 m | 1 | 217.5 s | 216.90 s | 1 |
| 200 × 5 m | 10 | 219.0 s | 218.79 s | 10 |
| 200 × 5 m | 100 | 238.0 s | 237.71 s | 100 |
| 200 × 5 m | 1000 | 444.5 s | 426.93 s | 1000 |

While fewer than $0.54\,L\,w$ agents are on the stair, everyone walks at
$S_0$ and the result lies within two steps of the hand value. With more
agents the stair fills and everyone on it walks at $k(1 - 0.266\,D)$, so
the hand value is only a lower bound. On the 10 m stair the node stays
at its limit of 27 agents (2.7 m⁻²), and the slower walk adds about
18 s. On the 200 ×
1 m stair the node holds 550 agents, its limit, and all walk at about
0.29 m/s. The flow from the first to the last exit is 1.012 persons/s
per metre of effective width for both 1000-agent runs on the 200 m
stairs, equal to the stair's $F_s = k/(4a) = 1.012$. Fig. 2.7 of the report
shows 1.0 persons/s/m.

**Fire Engineering Design Guide.** 90 agents (read from Fig. 2.8; the
text gives no number) start 20 m from a 1.0 m door into a 10 × 1.2 m
stair. The stair link, $1.012 \times 0.9 = 0.911$ persons/s, limits the
exit, not the door with $1.33 \times 0.7 = 0.931$ persons/s. The first
agent reaches the door at 19.0 s and leaves the stair at 30.5 s: 30.0 s
at the free stair speed, slowed by the agents that follow onto the
stair. The capacity bound for the last exit is $30.5 + 89/0.911 = 128.2$
s; this model gives 129.0 s.
EvacuatioNZ's 179 s is about 50 s longer. In Fig. 2.8 its stair holds
about 33 agents from about 80 s to 133 s, and its exits run at about 0.6
agents/s, below both capacities. In this model the stair holds at most
14 agents. The report does not say what limits the flow out of a full
node in EvacuatioNZ, so the difference is unexplained.

**Stand-ins.** EvacuatioNZ splits the agents of §2.6 between the two
stairs with a least-populated-connection rule. This model has no such
rule and does not split tied routes
([Limitations]({{< relref "/docs/limitations#routes" >}})). The rows above use
an accepted stand-in, labelled as such: two populations of 150, each
with its own exit. Without it
all 300 agents take one stair and leave after 455.5 s (start at the
door) and 506.0 s (start 200 ft away). The report's EvacuatioNZ result
of 221.5 s lies within 1.6 s of $150/0.682 = 219.9$ s, although the
last agent still has about 16 s of stair to descend; the Guide's 246 s
does not match $N/C$ at the door or the stair with these constants.
The §2.5 row uses the same kind of stand-in: one office zone of 150 per
floor goes to each of the two tied stairs, the same 150/150 split as the
SFPE Solution B, which says "Divide each floor in half to produce two exit
calculation zones" {{< cite 1 "p. 2182" >}}. Without it all 2400 agents
take one stair and leave after 3027.5 s.

In §5.1 the report gives no node sizes or widths; the test assumes 25 m²
nodes, 1 m doors and a start $U(0, 5)$ m and checks only the exit used. The report's
distances of 5 m to Exit 5 and 15 m to Exit 3 leave out the 1 m link
from Room 1 to Room 2; the full paths are 6 m and 16 m.

Rules of the report that this model does not have: door leaves and door
closers (§2.2), the maximum-distance, minimum-nodes and random single
exit choices (§5.1.2–5.1.4), required connections (§5.2) and the
least-populated connection (§2.6).

## Door flow and merging

![Cumulative door flow against the model convention and the SFPE hand calculation, and the cumulative merge flows](/images/network/door_and_merge.png)

(a) IMO test 4 geometry. The model follows $1 + C\,t$, the
$(N-1)/C$ convention, to within one time step. The SFPE hand
calculation $C\,t$ lies one agent lower and ends at $N/C = 107.4$ s. (b) Two rooms feeding a
full corridor with merge weights 1 : 3. Over 150 s the flows reach
3 : 1. At the start, room a passes no one from 2.5 s to 17.5 s while
room b catches up on the share it lost before the corridor filled
([Limitations]({{< relref "/docs/limitations#numerics" >}})).

## Sensitivity to max_density

In EvacuatioNZ version 1.2, raising the maximum node density from 2.5
to 3.5 m⁻² more than doubled the evacuation time of a 21-storey hotel
without pre-movement delay, from 539 s to 1232 s
{{< cite 5 "Table 5.5, p. 55" >}}. With pre-movement delay it rose from
796 s to 1156 s. These are means of 100 runs with the local door queue
density fixed at 2.2 m⁻²; the runs ranged from 529 to 553 s at 2.5 m⁻²
and from 1107 to 1502 s at 3.5 m⁻², both without delay. Tsai judged the
3.5 m⁻² result improbable, since it was longer without delay than with
delay {{< cite 5 "p. 56" >}}, and recommended 2.5 m⁻²
{{< cite 5 "pp. 62, 69" >}}. Tsai attributes the wider spread to
queuing at higher allowed densities {{< cite 5 "p. 56" >}}. We attribute
the increase to the speed–density relation: close to the jam density
$1/a = 3.76$ m⁻², a full node lets almost no one move, and a hard
capacity limit lets nodes fill up to that density until the stream
locks up.

The figure repeats the experiment with this model on a ten-storey
building with one stair, comparing the two settings of
`supply_reduction`. With a hard limit only, the evacuation time grows
sharply above 3 m⁻². With supply reduction it stays almost constant.
This shows only that supply reduction removes the effect in this model.
The building is not the one Tsai used, so it says nothing about
EvacuatioNZ's numbers.

![Evacuation time against max_density with and without supply reduction](/images/network/max_density_sweep.png)

Ten floors of 60 agents each (400 m² per floor, pre-movement
U(30, 120) s) and one stair of 1.2 m with 0.9 m doors, all connected one
way. The line is the median of 30 runs and the band covers 5–95 %. No
run was incomplete.

## Reproducing the figures

The figures and animations on this site are produced by
`scripts/figures/make_figures.py` and `scripts/figures/make_gifs.py`:

```
uv run --group docs python scripts/figures/make_figures.py OUTDIR
uv run --group docs python scripts/figures/make_gifs.py OUTDIR
```

Without `OUTDIR` they write to `site/static/images/network/`.
