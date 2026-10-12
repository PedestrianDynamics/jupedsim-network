---
title: Terminal UI
weight: 6
---

The terminal UI is an optional front end of the `jupedsim-network`
command. It edits a scenario file in forms, then runs the command's own
`check` and `run`. Check shows the text that
`jupedsim-network check FILE` prints. Run is
`jupedsim-network run FILE -o DIR`: the same five files and the same
lines, plus progress and cancel. You write no Python.

The UI adds no numbers, no defaults and no checks of its own. Every
field is a key of the
[scenario file]({{< relref "/docs/using/command-line#the-scenario-file" >}}),
an empty field takes the API default, and every error message is the
loader's.

## Install

Python 3.10 or later:

```bash
pip install "jupedsim-network[tui]"
```

The `tui` extra adds `textual` (8.2 or later). The core install stays
NumPy-only: `run`, `check`, `init` and `--help` never import `textual`.

Without the extra, `jupedsim-network tui` ends with exit status 1 and
this message:

```console
jupedsim-network tui: error: the terminal UI needs the tui extra (missing module 'textual'). Install it with: pip install "jupedsim-network[tui]"
```

## Start

```bash
jupedsim-network tui scenario.json
```

The usage line of `jupedsim-network tui --help` is
`usage: jupedsim-network tui [SCENARIO.json] [--theme NAME]`. With a file, the UI opens it on the Edit step. Without one, it starts on
the Scenario step. `python -m jupedsim_network tui` is the same command.

A file that is not valid cannot be opened. The loader's error is shown
under the path box, in the words of the command line, for example
`typo.json: simulation: unknown key 'max_densty'; valid keys: ...`. Fix
the file in an editor, guided by `jupedsim-network check`
([Errors]({{< relref "/docs/using/command-line#errors" >}})).
Opening an invalid file for repair is planned after version 1.0
([issue #47](https://github.com/PedestrianDynamics/jupedsim-network/issues/47)).

**Check:** the step bar at the top reads
`1 Scenario › 2 Edit › 3 Check › 4 Run › 5 Results`. Below 100 columns
it shows the numbers only.

## The five steps

### 1. Scenario

![The Scenario step at 80 by 24 characters: the Examples tab is open and lists getting-started and office-wing, each with its description](/images/tui/scenario.svg)

Three tabs:

- **Recent**: the files you opened before.
- **Examples**: `getting-started` and `office-wing`, the two files of
  `jupedsim-network init --example`. An example opens unsaved as
  `untitled (NAME)`. The first save asks for a path. An unchanged
  example, once saved, is byte for byte the file that `init` writes.
- **Open file**: a path box. Tab completes it and lists folders and
  `.json` files.

Tab to the tab row and use ←/→ to switch tabs; Enter opens the selected
file or example.

### 2. Edit

![The Edit step at 120 by 35 characters: the Connections tab with the list of connections on the left and the form of connection 0 on the right; its width field holds abc, is marked invalid, and the status line shows the error connections[0].width: expected a number, got the string "abc"](/images/tui/edit-error.svg)

The tabs are **Nodes · Connections · Populations · Settings**. Each list
tab pairs the elements, in file order, with a form for the selected one.
A marker next to each field shows its state:

| Marker | Meaning |
|--------|---------|
| `default` | The key is absent; the API default applies. |
| `set` | The file sets the key. |
| `✗ invalid` | The loader rejects the value. |
| `required` | The key must be set. |
| `not set` | Room area, length and width: none of them is set yet. |

The help of a field comes from the API docstrings. It appears when the
field has focus, and it names the unit.

These rules decide what reaches the file:

- **An empty text box removes the key**, so the API default applies.
- **Backspace on a switch or a choice** resets it to the default.
- **The UI never fills in a value.**
- **Text that is not a number is passed on as text.** The loader's
  message then appears, for example
  `connections[0].width: expected a number, got the string "abc"`.
- **Order matters.** Nodes, connections and populations are created in
  file order, and `alt+↑/↓` changes that order
  ([Watch for these]({{< relref "/docs/using/command-line#watch-for-these" >}})).

The scenario is checked on every edit. The UI shows **one error at a
time**, the first one the loader finds, next to its field; an error
about the whole element is shown above its form. Enter on the status
line moves to that field.

Renaming a node offers to rename its references as well
(`Also rename 'office' in ...?`). Changing the kind of a node keeps its
riser and tread in memory.

{{< details title="Distributions in the form" closed="true" >}}

`count`, `speed`, `pre_movement` and `start_distance` take a number or
one of `Fixed`, `Uniform`, `Normal`, `LogNormal`, `Triangular` and
`Weibull` with its fields
([Distributions]({{< relref "/docs/using/populations#distributions" >}})).

`lower` and `upper` are text fields under the same rule as every field:

- empty takes the default (`lower` 0, `upper` none);
- a number sets the bound;
- `null` writes `"lower": null`, which removes the bound.

The form has no separate "none" choice and shows no sampled preview.

{{< /details >}}

### 3. Check

![The Check step at 120 by 35 characters: on the left the text that jupedsim-network check prints, ending with The scenario is valid; on the right the route tree from street back to office, with the kind and capacity of each link; below, the command jupedsim-network run scenario.json -o scenario_results](/images/tui/check.svg)

Check **saves the file first** and asks (`Save scenario.json and check?`),
so the screen shows what `check FILE` prints for the file on disk. The
left pane holds the stdout and stderr of `jupedsim-network check FILE`,
line for line, including the trial run with `run.seed`
([First run]({{< relref "/docs/using/command-line#first-run" >}})).

The right pane is the route tree. Each safe node is a root. Each link
has its own line, with its kind and capacity in persons/s, above the
node that leaves by it; a node line shows its kind and area, and a
start node also its agents (`● 120 agents`).

- Tied links read `ties: split between ...` when `split_ties` is on, the
  default.
- Links on no route are listed as `not on a route: ...`.

The tree comes from `Network.route_table` and `Network.route_choices`
([Routes]({{< relref "/docs/using/networks#routes" >}})). Below the
panes is the equivalent command; `c` copies it.

`check` makes one trial run with one seed. "Valid" means the file is
well formed and the API accepts it; it says nothing about whether the
model is valid for your building
([Command line]({{< relref "/docs/using/command-line#the-four-commands" >}})).

### 4. Run

![The Run step at 80 by 24 characters during a run: the single run is done and the Monte Carlo set is in progress with a progress bar; below are the output folder, the Single run only switch and the equivalent command. The counts shown are fixed test inputs, not a measured run](/images/tui/run.svg "A run in progress. The counts and times on this screen are fixed test inputs, not a measured run.")

`ctrl+r` saves unsaved changes first, with the same question, and
starts the run.

- **Output folder**: by default `<stem>_results` next to the file.
- **Single run only** is `--no-monte-carlo`.
- If the folder already holds a `summary.json`, the UI asks
  `DIR/ holds results; replace them?`. The command line replaces them
  without asking. The files written are the same.

The run goes through the phases `single run` › `Monte Carlo n / N` ›
writing. The progress bar counts the realisations of the Monte Carlo set
(`run_many(progress=)`,
[Running]({{< relref "/docs/using/running#one-run-many-runs" >}})).

The run uses a frozen copy of the saved file. Edits made during the run
do not reach it.

### 5. Results

![The Results step at 120 by 35 characters after a complete run: on the left the outcome line, the command-line output, the evacuation time note and the Monte Carlo block; on the right the route tree with the occupancy of the single run at one time step, and the Links table; at the bottom the list of output files](/images/tui/results.svg "The getting-started file with monte_carlo.runs set to 20 for this figure; the numbers are what jupedsim-network run prints for that file.")

From top to bottom:

1. **The outcome**, with a glyph and the exit status of the command
   line:

   | Glyph | Outcome | Exit status |
   |-------|---------|-------------|
   | ✓ | complete | 0 |
   | ◐ | incomplete: agents were left at `t_max`; the results are written | 2 |
   | ✗ | error; nothing was written | 1 |
   | ■ | cancelled | |

2. **Command line output**: the stdout lines of `run`, unchanged.
3. **`! n warnings  w list`**: the `warning:` lines of the command line,
   which are the `warnings` of `summary.json`. `w` lists them.
4. **The evacuation time note.**
5. **The Monte Carlo block**: the quantiles of the evacuation time over
   the runs, then `runs · incomplete`.
6. **The route tree with occupancy**: the agents in each node in the
   single run at time t. `←/→` moves one step, `shift+←/→` ten steps.
7. **Links**: the capacity of each link in persons/s.
8. **Output files**: Enter previews a file; there `y` copies its path
   and `o` opens it.

After an edit, a banner reads `✎ Settings changed since this run.`

#### What the screen says

These lines appear on the Results step. They state what each number
means.

- `Evacuation time  last agent safe, s; a multiple of dt`, followed by:
  "evacuation_time is pre-movement plus movement of the simulated
  occupants. Detection and alarm times are included only if you added
  them to pre_movement. Call it an RSET only with that qualification."
- `Monte Carlo set  separate realisations, not the single run above; seed N`.
  The single run uses `run.seed`; realisation *i* of the set uses child
  *i* of `SeedSequence(monte_carlo.seed).spawn(runs)`. The single run
  is not one of the set ([First run]({{< relref "/docs/using/command-line#first-run" >}})).
- `quantile of evacuation time over N runs [s]`: a quantile, over the
  runs, of the evacuation time of each run, with NumPy's default linear
  interpolation. `q 0.95` is not the time by which 95 % of the agents
  are out.
- `> t_max is a lower bound.` A quantile that depends on unfinished runs
  is only known to exceed `t_max`. The note goes on: "Quantiles are
  conditional on the inputs. The 95th percentile describes the spread
  caused by the input distributions you chose, not the uncertainty of
  the model. A high quantile of a few hundred runs has its own sampling
  error."
- `Links  nominal capacity C = Fs (w − 2b), not the realised flow`. The
  value includes neither supply reduction nor counterflow sharing. The
  two links of a two-way connection each show $C$ but share one door
  under `"bounding"` and `"estimate"`
  ([Counterflow]({{< relref "/docs/model/counterflow" >}})).
- `occupancy of the single run, seed N: t = T s (step i of n)`. These
  are heads, not weighted by `area_factor`, and safe nodes are left out
  ([Limitations]({{< relref "/docs/limitations#output" >}})). A Monte
  Carlo set records no time series, so occupancy always belongs to the
  single run.

#### Results and the result files

Every number on Results is read from what `run` prints or writes
([Result files]({{< relref "/docs/using/command-line#result-files" >}})):

| On screen | From |
|-----------|------|
| Command line output | the stdout of `run` |
| Quantiles, runs, incomplete | `monte_carlo` in `summary.json` |
| Links and capacity | `links` in `summary.json`, rounded to 0.01 as `check` prints it |
| Warnings | `warnings` in `summary.json` |
| Occupancy | `occupancy.csv` |

The result files are those that `jupedsim-network run FILE -o DIR`
writes for the same file, byte for byte when `FILE` is the same path
string. `summary.json` stores the scenario path as given.

## Cancel

`x` or `ctrl+c` asks first. The current realisation then finishes and
the run stops.

- **A cancelled run writes nothing.** The output folder stays as it
  was, earlier results included. The finished realisations are
  discarded, so no partial quantiles are ever shown.
- A cancel confirmed at any time after `ctrl+r`, even before the run
  has started, holds. It never carries over to a later run.
- Writing the files cannot be cancelled.
- Quitting during a run asks, cancels and waits for the current
  realisation.

The outcome line then reads one of:

```console
■ Cancelled after k of N runs; nothing was written.
■ Cancelled during the single run; nothing was written.
■ Cancelled before it started; nothing was written.
```

On the command line, Ctrl-C ends with exit status 130
([Exit status]({{< relref "/docs/using/command-line#exit-status" >}})).

## Keys

`?` or F1 shows this list in the UI.

| Key | Action |
|-----|--------|
| `Tab / Shift+Tab` | next / previous control |
| `↑ / ↓` | previous / next field of a form |
| `[ / ]` | previous / next tab (Edit) |
| `a, d, alt+↑/↓` | add, delete, move an element (Edit list) |
| `backspace` | on a switch or choice: back to the default (an empty text box also removes the key) |
| `Enter` | on the status line or an error: go to the field |
| `ctrl+n / ctrl+p` | next / previous step (Esc also goes back) |
| `ctrl+s` | save (asks for a path the first time) |
| `ctrl+r` | run (saves first, asks) |
| `c` | copy the jupedsim-network run command |
| `x or ctrl+c` | cancel a run |
| `←/→, shift+←/→` | Results: occupancy time ±1 / ±10 steps |
| `w, y, t` | Results: warnings, copy path, traceback |
| `o` | file preview: open in the default app, if available |
| `e, n` | Results: edit, new scenario |
| `? or F1` | this list; on a field, its help first |
| `ctrl+k` | command palette (themes, steps, save as) |
| `ctrl+q` | quit (asks with unsaved changes or during a run) |

`t` shows the traceback on Results after an internal error.

## Themes and colour

Two themes: `network-dark`, the default, and `solarized-light`. The UI
takes the first of:

1. `--theme NAME`;
2. the variable `JUPEDSIM_NETWORK_TUI_THEME`;
3. the theme you used last;
4. `network-dark`.

An unknown name ends the command with exit status 1. An unknown
`--theme` prints the error after the usage line:

```console
jupedsim-network tui: error: JUPEDSIM_NETWORK_TUI_THEME='x' is not a theme; choose from network-dark, solarized-light
jupedsim-network tui: error: argument --theme: invalid choice: 'x' (choose from 'network-dark', 'solarized-light')
```

With `NO_COLOR` set, the UI is monochrome. Colour is never the only
signal: every state has a glyph and a word.

## Terminal size

The UI needs at least 80×24 characters. In a smaller terminal, the
notice `Terminal is W×H; the TUI needs 80×24.` appears over the screen; a
running run continues. From 120×35, the list and the form, and the
panes of Results, sit side by side. At 80×24, reach the route tree and
the links on Results with shift+Tab or PageDown.

## Recent files

The list of recent files is stored in
`$XDG_CONFIG_HOME/jupedsim-network/recent.json`, or in
`~/.config/jupedsim-network/recent.json` when `XDG_CONFIG_HOME` is unset
or empty. This holds on every platform, macOS and Windows included. The
file keeps at most 10 files, each with its path, date and last run
status, and the last theme. If it cannot be read or written, the UI
works without it. Delete it to clear the list.

## Limits

- One error at a time.
- An invalid file can be neither opened nor saved
  (`Cannot save: <path>: <message>`).
- A cancel waits for the current realisation.
- A single run, without Monte Carlo, shows no progress and cannot be
  cancelled while it runs.
- The terminal must be at least 80×24.
- Distributions have no sampled preview.
- Results shows no per-link counts, peak flows or exit-time statistics,
  because the command line does not produce them.

Opening an invalid file for repair, a sampled preview and per-link
statistics on Results are planned after version 1.0
([issue #47](https://github.com/PedestrianDynamics/jupedsim-network/issues/47)).

The model is verified, not validated. Read
[Limitations]({{< relref "/docs/limitations" >}}) before you use a
result.

## Next steps

- [Command line]({{< relref "/docs/using/command-line" >}}): the
  scenario file, the result files and the exit status.
- [Networks]({{< relref "/docs/using/networks" >}}) and
  [Populations]({{< relref "/docs/using/populations" >}}): what each
  field of the forms means, with its default.
- [Results]({{< relref "/docs/using/results" >}}): how to report the
  evacuation time and the quantiles.
