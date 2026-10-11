# SPDX-License-Identifier: LGPL-3.0-or-later
"""``--help`` and argument errors return before any scenario is read.

Importing ``jupedsim_network.cli`` runs the package ``__init__``, which
imports NumPy (about 60 ms), so unlike pyFDS-Evac this test does not
require NumPy to stay unloaded. It requires that no file is read, no
simulation is built and no plotting library is loaded.
"""

import subprocess
import sys

import pytest

HEAVY = ("matplotlib", "jupedsim", "rich_argparse.__main__")

_PROBE = """\
import contextlib, io, sys
import jupedsim_network.scenario as scenario
calls = []
scenario.load_scenario = lambda *a, **k: calls.append(a)
from jupedsim_network.cli import main
out = io.StringIO()
with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
    try:
        code = main(sys.argv[1:])
    except SystemExit as exc:
        code = exc.code
heavy = [m for m in {heavy!r} if m in sys.modules]
print(code, heavy, len(calls))
"""


@pytest.mark.parametrize(
    ("args", "exit_code"),
    [
        (["--help"], 0),
        (["run", "--help"], 0),
        ([], 1),
        (["run"], 1),
        (["run", "x.json", "--no-such"], 1),
        (["run", "x.json", "--runs", "0"], 1),
        (["run", "x.json", "--seed", "-1"], 1),
        (["frobnicate"], 1),
    ],
)
def test_parse_reads_no_scenario(args, exit_code):
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE.format(heavy=HEAVY), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    assert proc.stdout.strip() == f"{exit_code} [] 0"
