# SPDX-License-Identifier: LGPL-3.0-or-later
"""The worked examples run, and their pages quote them verbatim.

Every fenced ``python`` block on an example page must occur, character for
character, in its script, and every fenced ``text`` block (an output shown
on the page) must occur in what the script prints. Together the python
blocks show the whole script. A change to the code
that moves a number on the page fails here.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "site" / "content" / "docs"

PAGES = {"office_wing.py": "examples/office-wing.md"}


def _blocks(page, lang):
    pattern = re.compile(rf"^```{lang}\n(.*?)^```", re.DOTALL | re.MULTILINE)
    return pattern.findall((DOCS / page).read_text())


@pytest.fixture(scope="module")
def outputs():
    """Run each example once from the repository root, as the pages say."""
    runs = {}
    for script in PAGES:
        proc = subprocess.run(
            [sys.executable, f"examples/{script}"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert proc.returncode == 0, proc.stderr
        runs[script] = proc.stdout
    return runs


@pytest.mark.parametrize("script, page", PAGES.items())
def test_page_code_occurs_in_script(script, page):
    source = (ROOT / "examples" / script).read_text()
    blocks = _blocks(page, "python")
    assert blocks, f"{page} has no python block"
    for block in blocks:
        assert block in source, f"{page} block not in {script}:\n{block}"


@pytest.mark.parametrize("script, page", PAGES.items())
def test_page_shows_the_whole_script(script, page):
    """Every code line after the module docstring appears on the page."""
    source = (ROOT / "examples" / script).read_text()
    code = source[source.index("\nimport ") :]
    shown = "\n".join(_blocks(page, "python"))
    for line in code.splitlines():
        if line.strip() and not line.lstrip().startswith("#"):
            assert line in shown, f"{page} does not show: {line}"


@pytest.mark.parametrize("script, page", PAGES.items())
def test_page_output_occurs_in_stdout(outputs, script, page):
    blocks = _blocks(page, "text")
    assert blocks, f"{page} has no text block"
    for block in blocks:
        assert block in outputs[script], f"{page} output changed:\n{block}"


def test_office_wing_key_numbers(outputs):
    """The numbers the office wing page interprets in its prose."""
    out = outputs["office_wing.py"]
    assert "evacuation time: 155.1 s" in out
    assert "main door: 12 agents" in out
    assert "side door: 84 agents" in out
    assert "GE->side: first agent at 48.6 s, last at 155.1 s" in out
    assert "GE->side   0.78 persons/s" in out
    assert "median 143.2 s, 95th percentile 153.9 s" in out
    assert "incomplete runs: 0 of 100" in out
    assert "agents between the corridor halves: 0" in out
    assert "same pre-movement times in every variant: True" in out
    # Supply reduction stays off: every peak is below 1.88 per m².
    peaks = re.findall(r"peak in \w+: \d+ agents, ([\d.]+) per m²", out)
    assert peaks and max(float(p) for p in peaks) < 1.88
