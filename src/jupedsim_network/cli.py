# SPDX-License-Identifier: LGPL-3.0-or-later
"""The ``jupedsim-network`` command: run, check or start a scenario file."""

import argparse
import math
import sys
from pathlib import Path

try:
    from rich_argparse import RawDescriptionRichHelpFormatter as _BaseFormatter
except ImportError:  # the optional "cli" extra is not installed
    _BaseFormatter = argparse.RawDescriptionHelpFormatter

from jupedsim_network import cli_init, cli_run

PROG = "jupedsim-network"

EXIT_OK = 0
EXIT_ERROR = 1
# A run that reached t_max with agents inside; its outputs are written.
EXIT_INCOMPLETE = 2
# Interrupted with Ctrl-C (128 + SIGINT), as shells report it.
EXIT_INTERRUPTED = 130

# Defaults, units and number formats of the result files (cli_run.py).
DEFAULT_QUANTILES = cli_run.DEFAULT_QUANTILES
UNITS = cli_run.UNITS
_number = cli_run._number
_shown = cli_run._shown

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
        usage="%(prog)s {run,check,init,tui} ...",
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
    _add_tui(commands)
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


_TUI_DESCRIPTION = """\
Open, edit, check and run a scenario file in the terminal. Check and Run
show and write exactly what the check and run commands do. Needs the tui
extra: pip install "jupedsim-network[tui]"."""


def _add_tui(commands) -> None:
    tui = commands.add_parser(
        "tui",
        prog=f"{PROG} tui",
        help="edit, check and run a scenario in a terminal UI",
        usage="%(prog)s [SCENARIO.json] [--theme NAME]",
        description=_TUI_DESCRIPTION,
        formatter_class=_HelpFormatter,
    )
    tui.add_argument(
        "scenario",
        nargs="?",
        metavar="SCENARIO.json",
        help="the scenario file to open (default: start on the Scenario step)",
    )
    tui.add_argument(
        "--theme",
        choices=("network-dark", "solarized-light"),
        metavar="NAME",
        help="network-dark or solarized-light (default: "
        "$JUPEDSIM_NETWORK_TUI_THEME, else the last one used, else "
        "network-dark)",
    )
    tui.set_defaults(command=_tui)


def _tui(args) -> int:
    # textual is imported only here: the other commands never load it.
    from jupedsim_network.tui import launch

    return launch.main(args.scenario, args.theme)


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


def _overrides(args) -> cli_run.Overrides:
    quantiles = None if args.quantile is None else tuple(args.quantile)
    return cli_run.Overrides(
        seed=args.seed,
        runs=args.runs,
        mc_seed=args.mc_seed,
        quantiles=quantiles,
        no_monte_carlo=args.no_monte_carlo,
    )


def _run(args) -> int:
    from jupedsim_network.scenario import ScenarioError

    scenario = _load(args.scenario, "run")
    if scenario is None:
        return EXIT_ERROR
    warned = list(scenario.warnings)
    try:
        outcome = cli_run.execute(scenario, _overrides(args), warned)
    except ScenarioError as exc:
        _print_warnings(warned)
        return _error("run", f"{args.scenario}: {exc}")
    out = (
        Path(args.output)
        if args.output
        else cli_run.default_output(args.scenario)
    )
    files = cli_run.result_files(scenario, outcome, args.scenario, warned)
    _print_warnings(warned)
    try:
        cli_run.write(out, files)
    except OSError as exc:
        where = exc.filename or out
        return _error("run", f"cannot write {where}: {exc.strerror or exc}")
    _print_lines(cli_run.report_lines(scenario, outcome, args.scenario))
    print(f"Wrote {out}/: {', '.join(files)}")
    return EXIT_INCOMPLETE if cli_run.incomplete(outcome) else EXIT_OK


def _print_warnings(warned: list[str]) -> None:
    _print_lines(cli_run.warning_lines(warned), file=sys.stderr)


def _print_lines(lines: list[str], file=None) -> None:
    for line in lines:
        print(line, file=file)


# Checking


def _check(args) -> int:
    from jupedsim_network.scenario import ScenarioError

    scenario = _load(args.scenario, "check")
    if scenario is None:
        return EXIT_ERROR
    warned = list(scenario.warnings)
    _print_lines(cli_run.check_lines(scenario, args.scenario))
    try:
        seed, trial = cli_run.trial(scenario, warned)
    except ScenarioError as exc:
        _print_warnings(warned)
        return _error("check", f"{args.scenario}: {exc}")
    _print_warnings(warned)
    print(cli_run.run_line("Trial run", seed, trial))
    if not math.isfinite(trial.evacuation_time):
        return EXIT_INCOMPLETE
    print("The scenario is valid.")
    return EXIT_OK
