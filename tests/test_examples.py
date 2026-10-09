# SPDX-License-Identifier: LGPL-3.0-or-later
"""The worked examples run, and their pages quote them verbatim.

Every fenced ``python`` block on an example page must occur, character for
character, in its script, and every fenced ``text`` block (an output shown
on the page) must occur in what the script prints. Together the python
blocks show the whole script. The numbers that the prose and the tables
quote or derive are recomputed here from the script and its output, so a
change to the code that moves one of them fails, and so does an edit of
the page that no longer matches the code.
"""

import importlib.util
import math
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


def _office_wing_module():
    spec = importlib.util.spec_from_file_location(
        "office_wing", ROOT / "examples" / "office_wing.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _office_wing_page():
    text = (DOCS / PAGES["office_wing.py"]).read_text()
    return re.sub(r"\s+", " ", text.replace("&nbsp;", " "))


def _number(out, pattern):
    match = re.search(pattern, out)
    assert match, f"no output line matches {pattern!r}"
    return [float(g) for g in match.groups()]


def _quoted(page, phrases):
    for phrase in phrases:
        assert phrase in page, f"page does not say: {phrase}"


def test_office_wing_page_tables_match_script():
    """Areas, widths and lengths in the tables and the setup prose."""
    ow = _office_wing_module()
    page = _office_wing_page()
    office = math.prod(ow.ROOMS["G1"])
    training = math.prod(ow.ROOMS["TR"])
    corridor = math.prod(ow.ROOMS["GW"])
    width = {(s, t): w for s, t, _, w, _ in ow.LINKS}
    length = {(s, t): ln for s, t, _, _, ln in ow.LINKS}
    _quoted(
        page,
        [
            f"| G1–G4, U1, U2 | room | {office:g} |",
            f"| TR | room | {training:g} |",
            f"| GW, GE, UW, UE | room | {corridor:g} |",
            f"| stair | stair | {ow.STAIR_AREA} |",
            f"| office → corridor | door | {width['G1', 'GW']} "
            f"| {length['G1', 'GW']} |",
            f"| TR → UE | door | {width['TR', 'UE']} | {length['TR', 'UE']} |",
            f"| GW → GE, GE → GW | door | {width['GW', 'GE']} "
            f"| {length['GW', 'GE']} |",
            f"| UW → UE | door | {width['UW', 'UE']} | {length['UW', 'UE']} |",
            f"| GW → main | door | {width['GW', 'main']} "
            f"| {length['GW', 'main']} |",
            f"| GE → side | door | {width['GE', 'side']} "
            f"| {length['GE', 'side']} |",
            f"| UE → stair | door | {width['UE', 'stair']} "
            f"| {length['UE', 'stair']} |",
            f"| stair → GE | stair | {ow.FLIGHT_WIDTH} | {ow.STAIR_LENGTH} |",
            f"about {office / 6:.1f} m² each",
            f"about {training / 60:.1f} m² each",
            f"{6 * 6 + 60} people in all",
            f"a horizontal run of {ow.FLIGHT_GOING:.2f} m",
            f"= {ow.FLIGHT_GOING * ow.INCLINE:.2f}$ m",
            f"give {ow.STAIR_LENGTH} m",
            f"about {2 * ow.FLIGHT_WIDTH:.1f} m across the half landing",
            f"{2 * ow.FLIGHT_WIDTH:.1f} × "
            f"{ow.FLIGHT_GOING + ow.LANDING_DEPTH:.2f} m: two flights",
            f"would be {2 * ow.FLIGHT_GOING + 2 * ow.FLIGHT_WIDTH:.1f} m as "
            "horizontal run plus landing",
        ],
    )


def test_office_wing_prose_matches_output(outputs):
    """Every number the prose quotes or derives from the output."""
    out = outputs["office_wing.py"]
    page = _office_wing_page()
    cap = {
        name: c
        for name, c in re.findall(
            r"^(\S+->\S+)\s+([\d.]+) persons/s$", out, re.M
        )
    }
    door = float(cap["GE->side"])
    times = {
        link: _number(
            out,
            rf"{re.escape(link)}: first agent at ([\d.]+) s, "
            r"last at ([\d.]+) s",
        )
        for link in ("TR->UE", "UE->stair", "GE->side", "GW->main")
    }
    evac = _number(out, r"evacuation time: ([\d.]+) s")[0]
    main = int(_number(out, r"main door: (\d+) agents")[0])
    side = int(_number(out, r"side door: (\d+) agents")[0])
    peaks = {
        node: _number(out, rf"peak in {node}: (\d+) agents, ([\d.]+) per m²")
        for node in ("UE", "stair", "GE")
    }
    median, p95 = _number(out, r"median ([\d.]+) s, 95th percentile ([\d.]+) s")
    fastest, slowest = _number(out, r"fastest ([\d.]+) s, slowest ([\d.]+) s")
    share = int(_number(out, r"slower than (\d+)% of the runs")[0])
    rows = {
        w: _number(
            out,
            rf"(?m)^{re.escape(w)} m\s+([\d.]+) s\s+([\d.]+) s\s+([\d.]+) s\s+(\d+)$",
        )
        for w in ("0.9", "1.2", "1.8")
    }
    upstairs = 60 + 12

    def span(link):
        return times[link][1] - times[link][0]

    def drain(n):
        return (n - 1) / door

    _quoted(
        page,
        [
            # Check the network.
            f"= {door:.2f}$ persons/s",
            f"the 1.8 m main door {float(cap['GW->main']):.2f} persons/s",
            f"passes {float(cap['stair->GE']):.2f} persons/s",
            # One run: side and main door.
            f"takes {side} of the {main + side} agents",
            f"capacity of {door:.2f} persons/s",
            f"first agent passes at {times['GE->side'][0]:.1f} s and its last at "
            f"{evac:.1f} s, {span('GE->side'):.1f} s later",
            f"passes {side} agents in $({side} - 1)/{door:.2f} = "
            f"{drain(side):.1f}$ s",
            f"SFPE's $N/C$ gives {side / door:.1f} s",
            f"takes the {main} people from G1 and G2 and is idle after "
            f"{times['GW->main'][1]:.1f} s",
            # One run: the three queues.
            f"first at {times['TR->UE'][0]:.1f} s and the last at "
            f"{times['TR->UE'][1]:.1f} s, {span('TR->UE'):.1f} s later",
            f"$(60 - 1)/{door:.2f} = {drain(60):.1f}$ s",
            f"holds up to {int(peaks['UE'][0])} agents. The stair door passes "
            f"its {upstairs} agents from {times['UE->stair'][0]:.1f} to "
            f"{times['UE->stair'][1]:.1f} s, {span('UE->stair'):.1f} s, close to "
            f"$({upstairs} - 1)/{door:.2f} = {drain(upstairs):.1f}$ s",
            f"GE holds up to {int(peaks['GE'][0])} agents",
            f"more than the {door:.2f} persons/s the stair door admits",
            f"holds at most {int(peaks['stair'][0])} agents",
            f"The highest, {max(p[1] for p in peaks.values()):.2f} per m² on the "
            "stair",
            # 100 runs.
            f"within {median:.1f} s and 95 % within {p95:.1f} s",
            f"differ by at most {slowest - fastest:.1f} s, from {fastest:.1f} to "
            f"{slowest:.1f} s",
            f"slower than {share} % of the runs",
            # What-if.
            f"falls by {rows['0.9'][1] - rows['1.2'][1]:.1f} s, from "
            f"{rows['0.9'][1]:.1f} to {rows['1.2'][1]:.1f} s",
            f"peak in GE from {int(rows['0.9'][3])} to {int(rows['1.2'][3])} agents",
            f"must pass {side} agents, {side - upstairs} more than come down",
            f"median changes by {abs(rows['1.2'][1] - rows['1.8'][1]):.1f} s",
            f"seed 1 stays at {rows['1.8'][0]:.1f} s",
        ],
    )
    # The stair-door peak sits on the stair, which the prose names.
    assert max(peaks, key=lambda n: peaks[n][1]) == "stair"
    # Seed 1 is the same run in the one-run block and in the what-if table.
    assert rows["0.9"][0] == evac
    assert [rows["0.9"][1], rows["0.9"][2]] == [median, p95]
    # The side door no longer limits above 1.2 m.
    assert rows["1.2"][0] == rows["1.8"][0]


def test_office_wing_key_numbers(outputs):
    """Facts the prose states without quoting a number."""
    out = outputs["office_wing.py"]
    assert "incomplete runs: 0 of 100" in out
    assert "agents between the corridor halves: 0" in out
    assert "same pre-movement times in every variant: True" in out
    # Every node leading to the side door is downstream of a 0.9 m door.
    assert "TR leaves by the side door" in out
    assert "G1 leaves by the main door" in out
    # Supply reduction stays off in the run with seed 1: every peak is
    # below 1.88 per m².
    peaks = re.findall(r"peak in \w+: \d+ agents, ([\d.]+) per m²", out)
    assert peaks and max(float(p) for p in peaks) < 1.88
