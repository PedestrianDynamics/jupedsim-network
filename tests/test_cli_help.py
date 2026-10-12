# SPDX-License-Identifier: LGPL-3.0-or-later
"""The ``--help`` pages are grouped, short and plain off a terminal.

``rich-argparse`` (the ``cli`` extra) only formats the help; without it the
command prints plain argparse help with the same groups.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import pytest

from jupedsim_network import cli

REPO = Path(__file__).resolve().parents[1]
CONSOLE_SCRIPT = Path(sys.executable).parent / "jupedsim-network"

USAGE = {
    (): "usage: jupedsim-network {run,check,init,tui} ...",
    ("run",): "usage: jupedsim-network run SCENARIO.json [-o DIR] [options]",
    ("check",): "usage: jupedsim-network check SCENARIO.json",
    ("init",): "usage: jupedsim-network init [PATH] [--example NAME] [--force]",
    ("tui",): "usage: jupedsim-network tui [SCENARIO.json] [--theme NAME]",
}
GROUPS = {"run": ("Scenario & output", "Monte Carlo"), "check": ("Scenario",)}


def _subparser(name: str) -> argparse.ArgumentParser:
    parser = cli._build_parser()
    (commands,) = [
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    ]
    return commands.choices[name]


@pytest.mark.parametrize("name", GROUPS)
def test_every_option_is_in_exactly_one_named_group(name):
    parser = _subparser(name)
    seen = []
    for group in parser._action_groups:
        dests = [a.dest for a in group._group_actions]
        if group.title in GROUPS[name]:
            assert dests, group.title
            seen += dests
        else:
            assert dests in ([], ["help"]), group.title
    assert sorted(seen) == sorted(
        a.dest for a in parser._actions if a.dest != "help"
    )


def test_run_help_names_exit_codes_units_and_examples():
    text = _subparser("run").format_help()
    assert "exit status: 0 every run finished; 2 " in text
    assert "\nexamples:\n" in text
    assert "per step of dt" in text
    for title in GROUPS["run"]:
        assert f"\n{title}:\n" in text, title


def _help(program: list[str], env: dict[str, str]) -> str:
    env = {**os.environ, "COLUMNS": "100", "TERM": "xterm-256color", **env}
    env.pop("FORCE_COLOR", None)
    shown = subprocess.run(
        [*program, "--help"], cwd=REPO, env=env, capture_output=True, text=True
    )
    assert shown.returncode == 0, shown.stderr
    return shown.stdout


@pytest.mark.parametrize(
    "env", [{}, {"NO_COLOR": "1"}], ids=["plain", "no-color"]
)
@pytest.mark.parametrize("command", ["module", "console-script"])
@pytest.mark.parametrize("sub", list(USAGE))
def test_help_exits_zero_and_is_plain_off_a_terminal(command, env, sub):
    if command == "console-script" and not CONSOLE_SCRIPT.is_file():
        pytest.skip(f"{CONSOLE_SCRIPT} not installed; run uv sync")
    program = {
        "module": [sys.executable, "-m", "jupedsim_network"],
        "console-script": [str(CONSOLE_SCRIPT)],
    }[command]
    text = _help([*program, *sub], env)
    assert "\x1b[" not in text
    assert text.splitlines()[0] == USAGE[sub]
    for title in GROUPS.get(sub[0] if sub else "", ()):
        assert f"\n{title}:\n" in text, title


_WITHOUT_RICH = """\
import sys
sys.modules["rich_argparse"] = None  # `import rich_argparse` now fails
from jupedsim_network.cli import main
sys.exit(main(sys.argv[1:]))
"""


@pytest.mark.parametrize("sub", list(USAGE))
def test_help_without_rich_argparse(sub):
    text = _help([sys.executable, "-c", _WITHOUT_RICH, *sub], {})
    assert text.splitlines()[0] == USAGE[sub]
    for title in GROUPS.get(sub[0] if sub else "", ()):
        assert f"\n{title}:\n" in text, title


def test_rich_formatter_is_used_when_installed():
    pytest.importorskip("rich_argparse")
    from rich_argparse import RawDescriptionRichHelpFormatter

    assert issubclass(cli._HelpFormatter, RawDescriptionRichHelpFormatter)
