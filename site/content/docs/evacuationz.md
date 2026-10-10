---
title: Comparison with EvacuatioNZ
linkTitle: EvacuatioNZ
weight: 7
---

EvacuatioNZ is a network evacuation model by M. Spearpoint. It uses
what its author calls "the well established network method"
{{< cite 7 "manuscript p. 3" >}}; its sources are listed under
[network models]({{< relref "/docs/model#network-models" >}}). This model
follows the same approach but is not equivalent to it: several
algorithms differ, and no EvacuatioNZ runs were made for this
comparison. No licensed copy of EvacuatioNZ was used. EvacuatioNZ has
an online user manual {{< cite 12 "" >}}; the table rests on published
documents, which describe different versions of EvacuatioNZ:
1.2 {{< cite 5 "" >}}, 2.3 {{< cite 8 "" >}}, 2.8
{{< cite 10 "" >}}, 2.11 {{< cite 2 "" >}}, 2.11.2 {{< cite 3 "p. 3" >}}
and 2.14 {{< cite 6 "" >}}. Each row names the version where it matters.

| Aspect | EvacuatioNZ | `jupedsim_network` |
|--------|-------------|--------------------|
| Speed in a node | SFPE $S = k(1-0.266D)$, $D \ge 0.54$ {{< cite 2 "§2.1.3" 3 "p. 15" >}} | same |
| Stair speed | $k = 51.8\sqrt{T/R}$ m/min {{< cite 2 "§2.1.3, Eq. 2.1" >}}, "the FEDG approach" {{< cite 3 "p. 17" >}}, from the FEDG's $k_t = 51.8\,(G/R)^{0.5}$ with tread going $G$ {{< cite 18 "p. 223" >}} | same formula |
| Door flow | $F_s = 1.33$ default, boundary layer 0.15 m {{< cite 2 "§2.2" 3 "p. 3" >}}; door leaves and closers {{< cite 2 "§2.2" 3 "p. 14" >}} | $F_s = 1.3$ default (SFPE), configurable per link; no leaves or closers |
| Stairs | stair node with an `enz_stairs` connection; $F_s = 1.09$ from SFPE Table 59.5 in the exercise {{< cite 3 "p. 18" >}}; landings as separate nodes {{< cite 3 "p. 20" >}} | stair node with area and $k(R,T)$; link flow $k/(4a)$ computed from the geometry |
| Node capacity | hard maximum node density, default 2.75 m⁻² {{< cite 3 "p. 3" >}}: an agent passes into a node only if its density is below the maximum {{< cite 8 "p. 165" 10 "p. 111" >}} | hard `max_density` plus a linear supply reduction above 1.88 m⁻² |
| Agent size | one density for all agents. In v1.2 the user lowered the local door queue density, calibrated against EXIT89 and Simulex, to represent disabled occupants; the model cannot represent body sizes {{< cite 5 "pp. 25, 54, 62, 69" >}} | area factor per agent, counted in density and free space |
| Update order | sequential by default (`enz_sequential`); random orders are optional {{< cite 3 "pp. 3, 42" >}} | synchronous; simultaneous arrivals at one queue in population order |
| Queue near the door | "congested node" algorithm shortens the walk of agents who join a queue: 22.5 s with it, 31.5 s without, 30.5 s by hand {{< cite 3 "pp. 15–16" >}} | not modelled; agents walk the full link length at the node speed |
| Merging | 50 : 50 by default; `<Merge>` weights 1 : 3 gave 2.8 : 1 {{< cite 3 "p. 35" >}} | weights, interleaved by virtual time; 1 : 3 gives about 3 : 1 |
| Counterflow | v2.14 applies half the effective door width under counterflow {{< cite 6 "p. 8" >}}; the 2022 exercise is still marked "To do" {{< cite 3 "p. 43" >}} | not modelled; each direction keeps its full capacity |
| Routes | minimum or maximum distance, minimum number of nodes, random, specified exit, required connection {{< cite 2 "§5.1–5.2" >}}; a random choice when two or more required or exit-sign connections leave a node {{< cite 3 "pp. 53–54" >}}; an optional least populated connection subtype of minimum distance, used "to get a close to 50:50 split" {{< cite 2 "§2.6" >}}; preferred paths and probabilistic assignment {{< cite 8 "p. 165" >}}. How minimum distance breaks an exact tie is not documented | shortest distance or a fixed target, no reassessment; agents alternate between equally short routes ([Networks]({{< relref "/docs/using/networks#routes" >}})), a rule of this model, not taken from EvacuatioNZ |
| Pre-movement | fixed, uniform, normal, log-normal {{< cite 2 "§3.1" >}}, triangular {{< cite 2 "§3.2" >}} and Weibull, truncatable {{< cite 10 "p. 110" >}} | the same six types, truncated at 0 by default |
| Lighting | lighting in v1.2 {{< cite 5 "pp. 40–42, 89–92" >}} | no |
| Smoke | v2.3 could not close an escape route because of fire or smoke spread {{< cite 8 "p. 165" >}} | no |
| Verification | travel speed, door and stair flow including the IMO-style cases {{< cite 2 "§2.1–2.3" >}}; Fire Engineering Design Guide example, 179 s against 186 s by hand {{< cite 2 "§2.4" >}}; SFPE 9-storey example, 1871 s against 1524 s by hand {{< cite 2 "§2.5" >}}; SFPE human behaviour guide examples, 221.5 s against 246 s and 283 s against 300 s {{< cite 2 "§2.6" >}}; exercises against hand calculations {{< cite 7 "" >}} | IMO tests 1, 3 (adapted) and 4, plus hand calculations; the cases of the EvacuatioNZ verification report rebuilt and compared with its published results, including the SFPE 9-storey example with occupants and exit doors taken from the SFPE source and tied stairs split by alternation ([Verification]({{< relref "/docs/verification#evacuationz-verification-cases" >}})) |
| Validation | Jean Talon drill: 827 s (mean of 100 runs) against 863 s observed, with the pre-movement spread chosen to fit the drill and many inputs hypothesised {{< cite 5 "pp. 74, 82–88" >}}; 21-storey office drill in Australia, one recorded value of 1800 s against 1730–1830 s simulated {{< cite 5 "pp. 103–105" >}}; v2.8 against 14 stair evacuations, 95th-percentile times within ±17 % except one building up to 26 % faster {{< cite 10 "pp. 115–116" >}}; lecture rooms {{< cite 2 "§6.2" 9 "" >}}. The author of the Station nightclub study states that it would be inappropriate to claim that the work validated EvacuatioNZ {{< cite 8 "p. 180" >}} | none |
| Network resolution | on a hypothetical building, a network of 61 nodes and one of 496 nodes gave relatively small differences {{< cite 5 "pp. 53, 63–64" >}} | not studied |
| Licence | provided under the licence shipped with the program {{< cite 3 "p. 3" >}} | open source, LGPL-3.0 |

This model's congested walking test (200 agents at 2 m⁻², 20 m) uses
the case of the congested-node exercise {{< cite 3 "p. 15" >}}.
