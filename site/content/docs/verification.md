---
title: Verification
weight: 4
---

The model is verified: tests check that its components reproduce hand
calculations and adapted IMO test cases. It is not validated: it has
not been compared with evacuation drills, experiments, EvacuatioNZ runs
or JuPedSim's microscopic models.

## Tests

The tests are in `tests/test_network.py`. Run them from a clone of the
repository:

```
uv run pytest -q
```

The last line of the output reads `40 passed`, followed by the run
time.

The table lists the tests with a hand-calculated expectation. "Result"
is the evacuation time the current code gives in the test.

| Case | Expected | Result | Tolerance | Test |
|------|----------|--------|-----------|------|
| IMO test 1: 40 m at 1.0 m/s | 40 s | 40.0 s | 0.5 s | `test_free_walking_speed_imo_test_1` |
| IMO test 3 geometry, stair speed from 18/28 cm steps, as in EvacuatioNZ {{< cite 2 "§2.1.3" >}} | $10/(k(1-0.266\cdot0.54)) = 10.84$ s | 11.0 s ($\Delta t = 0.1$ s) | 0.25 s | `test_stair_speed_imo_test_3` |
| IMO test 4 geometry, 100 agents, 1 m door, $F_s = 1.33$, hydraulic door flow as in EvacuatioNZ {{< cite 2 "§2.2" >}} | $(N-1)/C = 99/0.931 = 106.3$ s | 106.5 s | 1 s | `test_door_flow_imo_test_4` |
| 50 agents, 0.6 m opening | $(N-1)/C = 49/0.78 = 62.8$ s | 63.0 s | 0.5 s | `test_opening_has_no_boundary_layer` |
| 200 agents at 2 m⁻² walk 20 m {{< cite 3 "p. 15" >}} | $20/(1.4\,(1-0.266\cdot2)) = 30.5$ s | 31.0 s | 0.6 s | `test_congested_walking_speed` |
| Merge weights 1 : 3 over 150 s | flow ratio 3 | 3.0 | 15 % | `test_merge_weights_split_flow` |
| Stair 7/11 in: $k$ and $F_s = k/(4a)$ | 1.08 m/s, 1.01 persons/s/m (SFPE Table 67.5 {{< cite 1 "p. 2176" >}}) | 1.081, 1.016 | 0.01 | `test_stair_specific_flow_follows_geometry` |

Further tests check pre-movement delays, route choice, conservation of
agents, that `max_density` is never exceeded, reproducibility with a
fixed seed, `nan` for incomplete runs, quantiles with incomplete runs,
the error messages, and the means and truncation of the distributions.

### IMO tests as written and as tested

The IMO test cases are in MSC.1/Circ.1533, Appendix 2, paragraphs 3–6
{{< cite 4 "" >}}.

- **Test 1** (one person, 2 m × 40 m corridor, 1 m/s, 40 s) is tested
  as written.
- **Test 3** as written asks that one person with a walking speed of
  1 m/s covers a 2 m wide stair of 10 m, measured along the incline, in
  10 s {{< cite 4 "" >}}. **This model does not meet it, by design.** On
  a stair the input speed only caps the walking speed, which comes from
  the stair geometry: $k = 51.8\sqrt{T/R}$ gives 1.077 m/s for 18/28 cm
  steps, and $k(1 - 0.266 \cdot 0.54) = 0.922$ m/s. A lone walker takes
  10.84 s instead of 10 s. The test checks this adaptation, the same one
  EvacuatioNZ uses for its stair verification {{< cite 2 "§2.1.3" >}}.
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

## Door flow and merging

![Cumulative door flow against the hand calculation, and the cumulative merge flows](/images/network/door_and_merge.png)

(a) IMO test 4 geometry. The model follows $1 + C\,t$, the
$(N-1)/C$ convention, to within one time step. (b) Two rooms feeding a
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
