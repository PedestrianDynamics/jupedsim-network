# SPDX-License-Identifier: LGPL-3.0-or-later
"""Run, check and report a scenario file: the code behind ``run`` and ``check``.

``cli.py`` parses the arguments, prints these lines and sets the exit
status. Every front end that must show and write what the command line
does calls this module, so seeds, rounding and the result files cannot
drift apart.
"""

import csv
import errno
import functools
import hashlib
import io
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from jupedsim_network.scenario import software_version

# Quantiles reported when neither the file nor --quantile gives any.
DEFAULT_QUANTILES = (0.5, 0.95)

# Units and time base of the result files, also written to summary.json.
UNITS = {
    "time": "s from the start of the run, the origin of pre_movement; "
    "row 0 is time 0, before the first step; the last time can exceed "
    "t_max by less than dt",
    "exit_time": "s, end of the step in which the agent reached safety "
    "(an upper bound to within dt); equal to the time of that step",
    "pre_movement_sampled": "s, as sampled; the agent starts walking at "
    "the first step whose start is at or after it",
    "link_flow": "agents (heads) per step of dt that passed the link in "
    "the step (time - dt, time]; a rate in persons/s is value / dt",
    "occupancy": "agents (heads) in each node at time, not weighted by "
    "area factor; safe nodes are left out",
    "capacity": "persons/s",
}


class RunCancelled(BaseException):
    """Raised by a ``progress`` callback to stop :func:`execute`.

    A ``BaseException``, so that :func:`~jupedsim_network.scenario.attempt`
    passes it on unchanged instead of reporting a scenario error.
    """


@dataclass(frozen=True)
class Overrides:
    """The options of ``run`` that override the file; ``None`` keeps it."""

    seed: int | None = None
    runs: int | None = None
    mc_seed: int | None = None
    quantiles: tuple[float, ...] | None = None
    no_monte_carlo: bool = False


@dataclass
class Seed:
    value: int
    drawn: bool

    def __str__(self) -> str:
        return f"{self.value} (drawn)" if self.drawn else str(self.value)


@dataclass
class Outcome:
    result: object
    seed: Seed
    runs: object = None
    mc_seed: Seed | None = None
    quantiles: tuple = ()
    values: tuple = ()


# Running


def _seed(given, from_file) -> Seed:
    """The seed to use; ``null`` everywhere draws one, so it can be recorded."""
    if given is not None:
        return Seed(given, False)
    if from_file is not None:
        return Seed(from_file, False)
    import numpy as np

    return Seed(int(np.random.SeedSequence().entropy), True)


def execute(
    scenario, overrides: Overrides, warned: list[str], progress=None
) -> Outcome:
    """The single run and, if requested, the Monte Carlo runs.

    ``progress`` is passed to :meth:`NetworkSimulation.run_many`. Raises
    :class:`~jupedsim_network.scenario.ScenarioError` for an error of the
    API; warnings are appended to ``warned``.
    """
    from jupedsim_network.scenario import attempt

    sim = scenario.simulation
    seed = _seed(overrides.seed, scenario.run_seed)
    result = attempt("run", functools.partial(sim.run, seed.value), warned)
    outcome = Outcome(result=result, seed=seed)
    settings = None if overrides.no_monte_carlo else scenario.monte_carlo or {}
    runs = None if settings is None else overrides.runs or settings.get("runs")
    if runs is None:
        return outcome
    outcome.mc_seed = _seed(overrides.mc_seed, settings.get("seed"))
    outcome.quantiles = tuple(
        overrides.quantiles or settings.get("quantiles") or DEFAULT_QUANTILES
    )
    many = functools.partial(
        sim.run_many, runs, outcome.mc_seed.value, progress=progress
    )
    outcome.runs = attempt("monte_carlo", many, warned)
    quantile = functools.partial(outcome.runs.quantile, list(outcome.quantiles))
    outcome.values = tuple(attempt("monte_carlo", quantile, warned))
    return outcome


def trial(scenario, warned: list[str]):
    """The seed and result of the trial run of ``check`` (not recorded)."""
    from jupedsim_network.scenario import attempt

    sim = scenario.simulation
    seed = _seed(None, scenario.run_seed)
    result = attempt(
        "run", functools.partial(sim.run, seed.value, record=False), warned
    )
    return seed, result


def incomplete(outcome: Outcome) -> bool:
    if not math.isfinite(outcome.result.evacuation_time):
        return True
    return outcome.runs is not None and outcome.runs.incomplete > 0


def default_output(scenario) -> Path:
    """``<scenario stem>_results/`` next to the scenario."""
    path = Path(scenario)
    return path.with_name(f"{path.stem}_results")


def warning_lines(warned: list[str]) -> list[str]:
    """One ``warning:`` line per distinct message, in order."""
    return [f"warning: {message}" for message in dict.fromkeys(warned)]


# Result files


def _number(value) -> str:
    """A float as Python's repr, empty if not finite; same under NumPy 1 and 2."""
    value = float(value)
    return repr(value) if math.isfinite(value) else ""


def _finite(value):
    """A float for JSON; ``None`` where it is nan or inf."""
    value = float(value)
    return value if math.isfinite(value) else None


def _table(header: list[str], rows) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return buffer.getvalue()


def result_files(scenario, outcome, path, warned) -> dict[str, str]:
    """Name and text of each result file."""
    result = outcome.result
    net = scenario.simulation.network
    files = {
        "summary.json": _summary(scenario, outcome, path, warned),
        "agents.csv": _table(
            ["agent", "pre_movement_sampled", "exit_time"],
            (
                [str(i), _number(pre), _number(exit_time)]
                for i, (pre, exit_time) in enumerate(
                    zip(result.pre_movement_times, result.exit_times)
                )
            ),
        ),
        "link_flow.csv": _table(
            ["time", *(f"{link.index}:{link.name}" for link in net.links)],
            (
                [_number(t), *(str(int(v)) for v in flow)]
                for t, flow in zip(result.times, result.link_flow)
            ),
        ),
        "occupancy.csv": _occupancy(result, net),
    }
    if outcome.runs is not None:
        runs = outcome.runs
        files["runs.csv"] = _table(
            ["run", "evacuation_time", "agents"],
            (
                [str(i), _number(t), str(int(n))]
                for i, (t, n) in enumerate(
                    zip(runs.evacuation_times, runs.agent_counts)
                )
            ),
        )
    return files


def _occupancy(result, net) -> str:
    from jupedsim_network.network import SAFE

    kept = [n.index for n in net.nodes if n.kind != SAFE]
    return _table(
        ["time", *(net.nodes[i].name for i in kept)],
        (
            [_number(t), *(str(int(row[i])) for i in kept)]
            for t, row in zip(result.times, result.node_occupancy)
        ),
    )


def _summary(scenario, outcome, path, warned) -> str:
    sim, result = scenario.simulation, outcome.result
    net = sim.network
    summary = {
        "format_version": 1,
        "jupedsim_network": software_version(),
        "scenario": {
            "path": str(path),
            "sha256": hashlib.sha256(Path(path).read_bytes()).hexdigest(),
        },
        "units": UNITS,
        "dt": float(sim.dt),
        "t_max": float(sim.t_max),
        "run": {
            "seed": outcome.seed.value,
            "seed_drawn": outcome.seed.drawn,
            "evacuation_time": _finite(result.evacuation_time),
            "agents": len(result.exit_times),
            "evacuated": result.evacuated,
        },
        "monte_carlo": _monte_carlo_summary(outcome),
        "links": [
            {
                "index": link.index,
                "name": link.name,
                "source": net.nodes[link.source].name,
                "target": net.nodes[link.target].name,
                "kind": link.kind,
                "capacity": float(link.capacity),
            }
            for link in net.links
        ],
        "warnings": list(dict.fromkeys(warned)),
    }
    text = json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False)
    return text + "\n"


def _monte_carlo_summary(outcome: Outcome):
    runs = outcome.runs
    if runs is None:
        return None
    return {
        "runs": int(runs.evacuation_times.size),
        "seed": outcome.mc_seed.value,
        "seed_drawn": outcome.mc_seed.drawn,
        "incomplete": runs.incomplete,
        "quantiles": [
            {"q": float(q), "value": _finite(v)}
            for q, v in zip(outcome.quantiles, outcome.values)
        ],
    }


def write(out: Path, files: dict[str, str]) -> None:
    """Write the result files; DIR then holds the results of this run only.

    The files are written to a hidden folder inside DIR and moved into
    DIR only after every write succeeded, so a failed write leaves DIR
    unchanged; the folder is removed in every case. A DIR that this call
    created, with any parent it created, is removed again on failure. A
    runs.csv of an earlier Monte Carlo run is removed when this run has
    none, so it cannot be read next to this summary.json. An ``OSError``
    names the file in ``filename``.
    """
    if out.exists() and not out.is_dir():
        raise OSError(errno.ENOTDIR, "not a directory", str(out))
    created = _first_missing(out)
    out.mkdir(parents=True, exist_ok=True)
    try:
        _write_into(out, files)
    except BaseException:
        if created is not None:
            shutil.rmtree(created, ignore_errors=True)
        raise


def _first_missing(path: Path) -> Path | None:
    """The outermost of ``path`` and its parents that does not exist."""
    missing = [p for p in (path, *path.parents) if not p.exists()]
    return missing[-1] if missing else None


def _write_into(out: Path, files: dict[str, str]) -> None:
    try:
        stage = Path(tempfile.mkdtemp(prefix=".jupedsim-network-", dir=out))
    except OSError as exc:
        raise OSError(exc.errno, exc.strerror, str(out)) from exc
    try:
        for name, text in files.items():
            _stage(stage / name, out / name, text)
        _check_targets(out, [*files, "runs.csv"])
        for name in files:
            os.replace(stage / name, out / name)
        if "runs.csv" not in files:
            (out / "runs.csv").unlink(missing_ok=True)
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def _stage(path: Path, target: Path, text: str) -> None:
    try:
        path.write_text(text, encoding="utf-8", newline="\n")
    except OSError as exc:
        raise OSError(exc.errno, exc.strerror, str(target)) from exc


def _check_targets(out: Path, names: list[str]) -> None:
    """Refuse before moving anything if a target cannot be replaced."""
    for name in names:
        if (out / name).is_dir():
            raise OSError(errno.EISDIR, "is a directory", str(out / name))


# Reporting


def report_lines(scenario, outcome: Outcome, path) -> list[str]:
    """The lines ``run`` prints after writing, before ``Wrote DIR/``."""
    lines = [
        _headline(scenario, path),
        run_line("Run", outcome.seed, outcome.result),
    ]
    if outcome.runs is None:
        return lines
    runs = outcome.runs
    shown = ", ".join(
        f"q {q:g} {_seconds(v)}"
        for q, v in zip(outcome.quantiles, outcome.values)
    )
    lines.append(
        f"Monte Carlo, {runs.evacuation_times.size} runs, seed "
        f"{outcome.mc_seed}: {shown}; {runs.incomplete} incomplete."
    )
    return lines


def _headline(scenario, path) -> str:
    sim = scenario.simulation
    n = len(sim.populations)
    return (
        f"Scenario {path}: {len(sim.network.nodes)} nodes, "
        f"{len(sim.network.links)} links, {n} population{'s' * (n != 1)}."
    )


def run_line(label: str, seed: Seed, result) -> str:
    agents = f"{result.evacuated} of {len(result.exit_times)} agents safe"
    time = result.evacuation_time
    if not math.isfinite(time):
        return f"{label}, seed {seed}: not finished by t_max; {agents}."
    return f"{label}, seed {seed}: evacuation time {_shown(time)} s; {agents}."


def _seconds(value) -> str:
    value = float(value)
    return f"{_shown(value)} s" if math.isfinite(value) else "> t_max"


def _shown(value) -> str:
    """A time for the terminal, to 0.01 s: 158.3, not 158.29999999999998.

    The result files keep the full value (:func:`_number`).
    """
    return repr(round(float(value), 2))


# Checking


def check_lines(scenario, path) -> list[str]:
    """The headline and the listing that ``check`` prints first."""
    return [_headline(scenario, path), *_list_network(scenario.simulation)]


def _list_network(sim) -> list[str]:
    net = sim.network
    lines = ["Nodes:"]
    for node in net.nodes:
        area = "" if math.isinf(node.area) else f"{node.area:g} m²"
        lines.append(
            f"  {node.index:<3d} {node.name:<16s} {node.kind:<6s} {area}"
        )
    lines.append("Links:")
    for link in net.links:
        lines.append(
            f"  {link.index:<3d} {link.name:<24s} {link.kind:<8s} "
            f"{link.capacity:.2f} persons/s"
        )
    lines.append("Populations:")
    for i, pop in enumerate(sim.populations):
        lines.append(f"  {i:<3d} {pop.node:<16s} -> {_exit_of(net, pop)}")
    return lines


def _exit_of(net, pop) -> str:
    """Safe node that the route of ``pop`` leads to."""
    routes = net.route_table(pop.target)
    node = net.node(pop.node)
    while routes[node.index] is not None:
        node = net.nodes[net.links[routes[node.index]].target]
    return node.name
