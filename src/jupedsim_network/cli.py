# SPDX-License-Identifier: LGPL-3.0-or-later
"""The ``jupedsim-network`` command: run, check or start a scenario file."""

import argparse
import csv
import errno
import functools
import hashlib
import io
import json
import math
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

try:
    from rich_argparse import RawDescriptionRichHelpFormatter as _BaseFormatter
except ImportError:  # the optional "cli" extra is not installed
    _BaseFormatter = argparse.RawDescriptionHelpFormatter

from jupedsim_network import cli_init

PROG = "jupedsim-network"

EXIT_OK = 0
EXIT_ERROR = 1
# A run that reached t_max with agents inside; its outputs are written.
EXIT_INCOMPLETE = 2
# Interrupted with Ctrl-C (128 + SIGINT), as shells report it.
EXIT_INTERRUPTED = 130

# Quantiles reported when neither the file nor --quantile gives any.
DEFAULT_QUANTILES = (0.5, 0.95)

# Units and time base of the result files, also written to summary.json.
UNITS = {
    "time": "s from the start of the run, the origin of pre_movement; "
    "row 0 is time 0, before the first step; the last time can exceed "
    "t_max by less than dt",
    "exit_time": "s, end of the step in which the agent reached safety "
    "(an upper bound to within dt), not rounded",
    "pre_movement_sampled": "s, as sampled; the agent starts walking at "
    "the first step whose start is at or after it",
    "link_flow": "agents (heads) per step of dt that passed the link in "
    "the step (time - dt, time]; a rate in persons/s is value / dt",
    "occupancy": "agents (heads) in each node at time, not weighted by "
    "area factor; safe nodes are left out",
    "capacity": "persons/s",
}

_DESCRIPTION = """\
Coarse network egress model, companion to JuPedSim. A scenario file (JSON)
describes the rooms, stairs and safe places, the doors and stair links that
connect them, the populations and the run settings. Each key is the name of
an argument of the Python API; a key left out takes the API default."""

_EPILOG = f"""\
exit status: 0 success; 2 a run did not finish before t_max; 1 error

examples:
  {PROG} init scenario.json        # the getting-started scenario
  {PROG} check scenario.json
  {PROG} run scenario.json

  # rich help: pip install "jupedsim-network[cli]\""""

_RUN_DESCRIPTION = """\
Run a jupedsim-network scenario (JSON). One realisation is run with the seed
of the scenario's "run" section; if the scenario has a "monte_carlo" section,
or --runs is given, that many realisations follow. Results go to DIR:
summary.json, agents.csv, link_flow.csv, occupancy.csv and, for Monte Carlo,
runs.csv. Times are in s from the start of the run; link_flow counts agents
per step of dt; summary.json states every unit."""

_RUN_EPILOG = f"""\
exit status: 0 every run finished; 2 a run did not finish before t_max
(results are written); 1 error (nothing written)

examples:
  # the getting-started scenario
  {PROG} init scenario.json
  {PROG} run scenario.json

  # 1000 realisations, three quantiles
  {PROG} run scenario.json --runs 1000 --quantile 0.5 \\
      --quantile 0.9 --quantile 0.95"""

_CHECK_DESCRIPTION = """\
Check a jupedsim-network scenario (JSON): build the network and the
simulation through the API, list nodes, links and populations, and make one
trial run with the seed of the "run" section. Writes nothing."""

_CHECK_EPILOG = f"""\
exit status: 0 valid; 2 valid, but the trial run did not finish before
t_max; 1 error

examples:
  {PROG} check scenario.json"""


def _verbatim(heading: str) -> str:
    """Keep group headings as written."""
    return heading


class _HelpFormatter(_BaseFormatter):
    """Rich help, if installed, with literal brackets and headings."""

    group_name_formatter = _verbatim
    help_markup = False
    text_markup = False


class _UsageError(Exception):
    """An argument error, reported with exit status 1 instead of 2."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # type: ignore[override]
        raise _UsageError(f"{self.format_usage()}{self.prog}: error: {message}")


def _non_negative_int(text: str) -> int:
    value = _integer(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {value}")
    return value


def _positive_int(text: str) -> int:
    value = _integer(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {value}")
    return value


def _integer(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not an integer: {text!r}") from None


def _quantile(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text!r}") from None
    if not 0.0 <= value <= 1.0:
        raise argparse.ArgumentTypeError(f"must be in [0, 1], got {text}")
    return value


def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line interface."""
    parser = _Parser(
        prog=PROG,
        usage="%(prog)s {run,check,init} ...",
        description=_DESCRIPTION,
        epilog=_EPILOG,
        formatter_class=_HelpFormatter,
    )
    commands = parser.add_subparsers(
        title="Commands",
        dest="name",
        metavar="COMMAND",
        required=True,
        parser_class=_Parser,
    )
    _add_run(commands)
    _add_check(commands)
    init = commands.add_parser(
        "init",
        prog=f"{PROG} init",
        help="write a starter scenario",
        usage="%(prog)s [PATH] [--example NAME] [--force]",
        description=cli_init.DESCRIPTION,
        epilog=cli_init.EPILOG,
        formatter_class=_HelpFormatter,
    )
    cli_init.add_arguments(init)
    init.set_defaults(command=cli_init.init)
    return parser


def _add_run(commands) -> None:
    run = commands.add_parser(
        "run",
        prog=f"{PROG} run",
        help="run a scenario and write the result files",
        usage="%(prog)s SCENARIO.json [-o DIR] [options]",
        description=_RUN_DESCRIPTION,
        epilog=_RUN_EPILOG,
        formatter_class=_HelpFormatter,
    )
    files = run.add_argument_group("Scenario & output")
    files.add_argument(
        "scenario",
        metavar="SCENARIO.json",
        help=f"the scenario file (see: {PROG} init)",
    )
    files.add_argument(
        "-o",
        "--output",
        metavar="DIR",
        help="directory for the result files "
        "(default: <scenario stem>_results/ next to the file); a run "
        "without Monte Carlo removes runs.csv from DIR",
    )
    files.add_argument(
        "--seed",
        type=_non_negative_int,
        metavar="N",
        help="seed of the single run; overrides run.seed",
    )
    many = run.add_argument_group("Monte Carlo")
    many.add_argument(
        "--runs",
        type=_positive_int,
        metavar="N",
        help="number of realisations; overrides monte_carlo.runs",
    )
    many.add_argument(
        "--mc-seed",
        type=_non_negative_int,
        metavar="N",
        help="seed of the realisations; overrides monte_carlo.seed",
    )
    many.add_argument(
        "--quantile",
        type=_quantile,
        action="append",
        metavar="Q",
        help="quantile to report, in [0, 1] (repeatable); overrides "
        "monte_carlo.quantiles (default: 0.5 and 0.95)",
    )
    many.add_argument(
        "--no-monte-carlo",
        action="store_true",
        help="run only the single realisation",
    )
    run.set_defaults(command=_run)


def _add_check(commands) -> None:
    check = commands.add_parser(
        "check",
        prog=f"{PROG} check",
        help="check a scenario and make one trial run",
        usage="%(prog)s SCENARIO.json",
        description=_CHECK_DESCRIPTION,
        epilog=_CHECK_EPILOG,
        formatter_class=_HelpFormatter,
    )
    files = check.add_argument_group("Scenario")
    files.add_argument(
        "scenario",
        metavar="SCENARIO.json",
        help="the scenario file",
    )
    check.set_defaults(command=_check)


def main(argv: list[str] | None = None) -> int:
    """Parse the arguments and run the command; returns the exit status."""
    try:
        args = _build_parser().parse_args(argv)
    except _UsageError as exc:
        print(exc, file=sys.stderr)
        return EXIT_ERROR
    try:
        return args.command(args)
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED


# Running


@dataclass
class _Seed:
    value: int
    drawn: bool

    def __str__(self) -> str:
        return f"{self.value} (drawn)" if self.drawn else str(self.value)


@dataclass
class _Outcome:
    result: object
    seed: _Seed
    runs: object = None
    mc_seed: _Seed | None = None
    quantiles: tuple = ()
    values: tuple = ()


def _seed(given, from_file) -> _Seed:
    """The seed to use; ``null`` everywhere draws one, so it can be recorded."""
    if given is not None:
        return _Seed(given, False)
    if from_file is not None:
        return _Seed(from_file, False)
    import numpy as np

    return _Seed(int(np.random.SeedSequence().entropy), True)


def _error(command: str, message) -> int:
    print(f"{PROG} {command}: error: {message}", file=sys.stderr)
    return EXIT_ERROR


def _load(path: str, command: str):
    """The scenario, or ``None`` after printing the error."""
    from jupedsim_network.scenario import ScenarioError, load_scenario

    try:
        return load_scenario(path)
    except ScenarioError as exc:
        _error(command, f"{path}: {exc}")
    except OSError as exc:
        _error(command, f"cannot read {path}: {exc.strerror or exc}")
    return None


def _run(args) -> int:
    from jupedsim_network.scenario import ScenarioError

    scenario = _load(args.scenario, "run")
    if scenario is None:
        return EXIT_ERROR
    warned = list(scenario.warnings)
    try:
        outcome = _execute(scenario, args, warned)
    except ScenarioError as exc:
        _print_warnings(warned)
        return _error("run", f"{args.scenario}: {exc}")
    out = Path(args.output) if args.output else _default_output(args.scenario)
    files = _result_files(scenario, outcome, args.scenario, warned)
    _print_warnings(warned)
    try:
        _write(out, files)
    except OSError as exc:
        where = exc.filename or out
        return _error("run", f"cannot write {where}: {exc.strerror or exc}")
    _report(scenario, outcome, args.scenario)
    print(f"Wrote {out}/: {', '.join(files)}")
    return EXIT_INCOMPLETE if _incomplete(outcome) else EXIT_OK


def _execute(scenario, args, warned: list[str]) -> _Outcome:
    from jupedsim_network.scenario import attempt

    sim = scenario.simulation
    seed = _seed(args.seed, scenario.run_seed)
    result = attempt("run", functools.partial(sim.run, seed.value), warned)
    outcome = _Outcome(result=result, seed=seed)
    settings = None if args.no_monte_carlo else scenario.monte_carlo or {}
    runs = None if settings is None else args.runs or settings.get("runs")
    if runs is None:
        return outcome
    outcome.mc_seed = _seed(args.mc_seed, settings.get("seed"))
    outcome.quantiles = tuple(
        args.quantile or settings.get("quantiles") or DEFAULT_QUANTILES
    )
    many = functools.partial(sim.run_many, runs, outcome.mc_seed.value)
    outcome.runs = attempt("monte_carlo", many, warned)
    quantile = functools.partial(outcome.runs.quantile, list(outcome.quantiles))
    outcome.values = tuple(attempt("monte_carlo", quantile, warned))
    return outcome


def _incomplete(outcome: _Outcome) -> bool:
    if not math.isfinite(outcome.result.evacuation_time):
        return True
    return outcome.runs is not None and outcome.runs.incomplete > 0


def _default_output(scenario: str) -> Path:
    """``<scenario stem>_results/`` next to the scenario."""
    path = Path(scenario)
    return path.with_name(f"{path.stem}_results")


def _print_warnings(warned: list[str]) -> None:
    for message in dict.fromkeys(warned):
        print(f"warning: {message}", file=sys.stderr)


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


def _result_files(scenario, outcome, path, warned) -> dict[str, str]:
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
        "jupedsim_network": _version(),
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


def _monte_carlo_summary(outcome: _Outcome):
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


def _version() -> str:
    try:
        return metadata.version("jupedsim-network")
    except metadata.PackageNotFoundError:
        return "unknown"


def _write(out: Path, files: dict[str, str]) -> None:
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


def _report(scenario, outcome: _Outcome, path: str) -> None:
    print(_headline(scenario, path))
    print(_run_line("Run", outcome.seed, outcome.result))
    if outcome.runs is None:
        return
    runs = outcome.runs
    shown = ", ".join(
        f"q {q:g} {_seconds(v)}"
        for q, v in zip(outcome.quantiles, outcome.values)
    )
    print(
        f"Monte Carlo, {runs.evacuation_times.size} runs, seed "
        f"{outcome.mc_seed}: {shown}; {runs.incomplete} incomplete."
    )


def _headline(scenario, path: str) -> str:
    sim = scenario.simulation
    n = len(sim.populations)
    return (
        f"Scenario {path}: {len(sim.network.nodes)} nodes, "
        f"{len(sim.network.links)} links, {n} population{'s' * (n != 1)}."
    )


def _run_line(label: str, seed: _Seed, result) -> str:
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


def _check(args) -> int:
    from jupedsim_network.scenario import ScenarioError, attempt

    scenario = _load(args.scenario, "check")
    if scenario is None:
        return EXIT_ERROR
    warned = list(scenario.warnings)
    sim = scenario.simulation
    print(_headline(scenario, args.scenario))
    _list_network(sim)
    seed = _seed(None, scenario.run_seed)
    try:
        trial = attempt(
            "run", functools.partial(sim.run, seed.value, record=False), warned
        )
    except ScenarioError as exc:
        _print_warnings(warned)
        return _error("check", f"{args.scenario}: {exc}")
    _print_warnings(warned)
    print(_run_line("Trial run", seed, trial))
    if not math.isfinite(trial.evacuation_time):
        return EXIT_INCOMPLETE
    print("The scenario is valid.")
    return EXIT_OK


def _list_network(sim) -> None:
    net = sim.network
    print("Nodes:")
    for node in net.nodes:
        area = "" if math.isinf(node.area) else f"{node.area:g} m²"
        print(f"  {node.index:<3d} {node.name:<16s} {node.kind:<6s} {area}")
    print("Links:")
    for link in net.links:
        print(
            f"  {link.index:<3d} {link.name:<24s} {link.kind:<8s} "
            f"{link.capacity:.2f} persons/s"
        )
    print("Populations:")
    for i, pop in enumerate(sim.populations):
        print(f"  {i:<3d} {pop.node:<16s} -> {_exit_of(net, pop)}")


def _exit_of(net, pop) -> str:
    """Safe node that the route of ``pop`` leads to."""
    routes = net.route_table(pop.target)
    node = net.node(pop.node)
    while routes[node.index] is not None:
        node = net.nodes[net.links[routes[node.index]].target]
    return node.name
