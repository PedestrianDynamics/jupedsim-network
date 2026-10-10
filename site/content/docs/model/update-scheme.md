---
title: Update scheme
weight: 2
---

Time advances in fixed steps $\Delta t$, 0.5 s by default. Every step
runs the five stages below, implemented in `simulation._Run`. The update
is synchronous: all transfers of a step are decided from the state at
its start and applied together at its end, so they do not depend on the
order in which links or nodes are processed. Agents that reach the same
queue at the same time are served in the order of their populations
(see [stage 3](#3-walking)).

## 1. Density

The density of node $n$ at the start of the step adds up the area factor
of every agent in the node, including agents still in pre-movement and
agents queuing at a link:

$$
D_n = \frac{1}{A_n} \sum_{i \in n} a_i .
$$

## 2. Pre-movement

An agent starts walking once $t \ge t_i^\text{pre}$. Its first walking
distance is $s_i + L_\ell$, where $\ell$ is the first link of its route.

## 3. Walking

A walking agent in node $n$ moves at

$$
v_i = \min\!\left(v_i^\text{max},\; k_n\,\bigl(1 - a\,\max(D_n, 0.54)\bigr)\right),
$$

with $v_i$ clipped at zero. Its remaining distance shrinks by
$v_i\,\Delta t$. Once the remaining distance reaches zero, the agent
joins the queue of its link, and may pass it in the same step.

The arrival time is interpolated within the step, and the queue is
served in order of arrival. Agents with the same arrival time are served
in the order in which they were created, that is, in the order of the
populations. With two populations that differ only in area factor, the
one listed first leaves first
([Limitations]({{< relref "/docs/limitations#numerics" >}})).

![Speed, specific flow and supply factor plotted against density](/images/network/fundamental_diagram.png)

(a) SFPE speed–density relation for level ground and for an 18/28 cm
stair. (b) Specific flow, with its peak at 1.88 m⁻². Below 0.54 m⁻² the
curve is $S(0.54)\,D$, the speed cap of this model, not an SFPE curve.
The level peak is 1.32 persons/s/m, while the default door value is the
tabulated 1.3. (c) Share of its inflow capacity that a node accepts.
With supply reduction (solid line) the share falls linearly from the
peak-flow density to `max_density`. The dashed line is a hard capacity
limit.

## 4. Passing links

**Link budget.** Each link has a budget for the step, made up of a
carry $c_\ell$ from earlier steps and its capacity for this step:

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
  \alpha_n = \gamma_n + \varphi_n \sum_{\ell \in Q_n} C_\ell\,\Delta t
  \quad (\varphi_n < 1).
  $$

  Here $D_\text{peak} = 1/(2a) = 1.88$ m⁻². The sum runs over $Q_n$,
  the links into $n$ that have a queue in this step, the same links that compete
  in the merge below. Links nobody is waiting at, such as the unused
  direction of a two-way connection or a feeder whose room has emptied,
  do not count. If `max_density` ≤ $D_\text{peak}$, the supply limit is
  not applied and only the free space counts.

  The node carry $\gamma_n$ keeps what was allowed but not used, so that
  low inflow rates aren't rounded away. It starts at $\gamma_n = 0$ and,
  after every step, whether or not an agent was ready to pass, becomes

  $$
  \gamma_n = \operatorname{clip}\!\Bigl(\alpha_n - \textstyle\sum_\text{admitted} a_i,\ 0,\ \max\bigl(\sum_{\ell\in Q_n} C_\ell\,\Delta t,\ 1,\ a^\ast_n\bigr)\Bigr).
  $$

  A node at or below $D_\text{peak}$ has $\alpha_n = \infty$, so after
  such a step its carry is full. Like the link carry, $\gamma_n$
  refills at $\varphi_n \sum_{\ell\in Q_n} C_\ell\,\Delta t$ per step
  and holds at most one cap. A node that has just passed
  $D_\text{peak}$ can take one cap at once, then takes the share
  $\varphi_n$. The cap uses the same sum over links with a queue as
  $\alpha_n$. $a^\ast_n$ is the largest area factor among the
  agents still waiting at the head of a queue into $n$ after this
  step's admissions, 0 if nobody waits. The cap lets a node save enough
  supply for an agent with a large area factor, so that agent waits but
  is not shut out.

Candidates pass one at a time while their summed area factors stay
within $\min(F_n, \alpha_n)$.

The supply reduction is a modelling choice and has not been calibrated
against experiments.

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
This interleaving rule is an implementation choice of this model.

### Carry update

After $q_\ell$ agents have passed, the link keeps its unused budget, but
never more than one agent:

$$
c_\ell = \min\bigl(\beta_\ell - q_\ell,\ 1\bigr).
$$

The carry starts at $c_\ell = 1$. A fresh link, or one idle for at least
$1/C_\ell$, therefore lets the first agent through at once. After a
passage, the next credit builds up at rate $C_\ell$. Unused capacity is
never kept beyond one agent, whether the link was idle or blocked
downstream. As a result, no link passes more than $1 + C_\ell\,t$ agents
in any interval $t$.

When $N$ agents queue at a fresh link, the first passes at once and the
last after $(N-1)/C_\ell$. This is the convention
of this model. The SFPE hand calculation gives the passage time
$t_p = N/C_\ell$ {{< cite 1 "Eq. 67.9, p. 2177" >}}, one headway
$1/C_\ell$ longer. For 100 agents through a 1 m door at
1.33 persons/s/m, that is 106.3 s against 107.4 s
([Verification]({{< relref "/docs/verification" >}})).

## 5. Commit

Agents that passed a link move to its target node. There they walk the
length of their next link, or they are marked safe with exit time
$t + \Delta t$. An agent that has passed a link walks again only in the
next step, so every link on a route costs at least one step. Space
freed by agents who leave a node becomes available in the next step.
