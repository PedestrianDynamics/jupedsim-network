# SPDX-License-Identifier: LGPL-3.0-or-later
"""``run`` and ``check`` give the bytes recorded on e80834e (issue #47).

The run, write and report code moved from ``cli.py`` to ``cli_run.py``
without a change in behaviour. Each case in ``tests/data/cli_golden``
holds its input ``scenario.json`` and the exit status, stdout, stderr
and result files that ``cli.main`` produced on e80834e, before the
move. Only the package version in ``summary.json`` is normalised; the
``sha256`` is that of the stored input. Seeds that the file leaves
``null`` are drawn from a patched ``SeedSequence`` with fixed entropy,
in the order the CLI draws them (run seed first).

Every byte is compared under the install the cases were recorded with
(``environment``). Under another NumPy build the sampled pre-movement
times can differ in the last bits (up to 8 ulp measured between NumPy
2.4.6 on arm64, 2.2.6 on x86_64 and Linux; bound 16 ulp), because the distributions
call the platform's ``log``, ``exp`` and ``pow``. There the
``pre_movement_sampled`` column of ``agents.csv`` is compared exactly
with the samples of ``run(seed)`` through the API in that install, and
with the recording to within 16 ulp; every other byte is compared with
the recording.

To record again (only for an intended change of the output)::

    JPSNET_RECORD_GOLDEN=1 uv run pytest tests/test_cli_golden.py
"""

import contextlib
import csv
import io
import itertools
import json
import os
import platform
import re
from pathlib import Path

import numpy as np
import pytest

from jupedsim_network import cli, load_scenario

GOLDEN = Path(__file__).resolve().parent / "data" / "cli_golden"
RECORD = os.environ.get("JPSNET_RECORD_GOLDEN") == "1"

# Entropy of the seeds drawn for ``null``, in drawing order.
DRAWN = (271828182845904523536, 314159265358979323846)

CASES = {
    "gs_run": ["run", "scenario.json"],
    "gs_check": ["check", "scenario.json"],
    "gs_no_monte_carlo": ["run", "scenario.json", "--no-monte-carlo"],
    "gs_overrides": [
        "run",
        "scenario.json",
        "-o",
        "out_results",
        "--seed",
        "3",
        "--runs",
        "4",
        "--mc-seed",
        "9",
        "--quantile",
        "0.1",
        "--quantile",
        "0.9",
    ],
    "gs_default_quantiles": ["run", "scenario.json"],
    "gs_empty_quantiles": ["run", "scenario.json"],
    "gs_null_seeds": ["run", "scenario.json"],
    "gs_incomplete": ["run", "scenario.json"],
    "ow_run": ["run", "scenario.json"],
    "ow_check": ["check", "scenario.json"],
}

_VERSION = re.compile(r'("jupedsim_network": )"[^"]*"')
_SAMPLED = "pre_movement_sampled"


def _environment() -> str:
    python = ".".join(platform.python_version_tuple()[:2])
    system, machine = platform.system(), platform.machine()
    return f"python {python}, numpy {np.__version__}, {system} {machine}\n"


def _normalised(name: str, raw: bytes) -> bytes:
    if name != "summary.json":
        return raw
    return _VERSION.sub(r'\1"VERSION"', raw.decode()).encode()


def _seed_sequence(real):
    entropy = itertools.chain(DRAWN, itertools.count())

    def seed_sequence(*args, **kwargs):
        if not args and not kwargs:
            return real(next(entropy))
        return real(*args, **kwargs)

    return seed_sequence


def _produce(case: str, tmp_path: Path, monkeypatch) -> dict[str, bytes]:
    """Exit status, stdout, stderr and result files of one case."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        np.random, "SeedSequence", _seed_sequence(np.random.SeedSequence)
    )
    (tmp_path / "scenario.json").write_bytes(
        (GOLDEN / case / "scenario.json").read_bytes()
    )
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(CASES[case])
    produced = {
        "status": f"{code}\n".encode(),
        "stdout": out.getvalue().encode(),
        "stderr": err.getvalue().encode(),
    }
    for path in sorted(tmp_path.glob("*_results/*")):
        produced[f"results/{path.name}"] = _normalised(
            path.name, path.read_bytes()
        )
    return produced


def _recorded(case: str) -> dict[str, bytes]:
    root = GOLDEN / case
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file() and path.name not in ("scenario.json", "environment")
    }


def _record(case: str, produced: dict[str, bytes]) -> None:
    (GOLDEN / "environment").write_text(_environment())
    root = GOLDEN / case
    for name, raw in produced.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(raw)


@pytest.mark.parametrize("case", CASES)
def test_cli_output_is_the_recorded_bytes(case, tmp_path, monkeypatch):
    produced = _produce(case, tmp_path, monkeypatch)
    if RECORD:
        _record(case, produced)
    recorded = _recorded(case)
    name = "results/agents.csv"
    other = (GOLDEN / "environment").read_text() != _environment()
    if other and name in recorded:
        agents = produced.pop(name, b""), recorded.pop(name)
        _same_agents(*agents, tmp_path, produced["results/summary.json"])
    assert produced == recorded


def _within_16_ulp(written: list[str], kept: list[str]) -> None:
    """Same cells; numbers within 16 ulp of the recorded value."""
    assert [w == "" for w in written] == [k == "" for k in kept]
    pairs = [(float(w), float(k)) for w, k in zip(written, kept) if k]
    for value, recorded in pairs:
        assert abs(value - recorded) <= 16 * np.spacing(abs(recorded))


def _same_agents(produced, recorded, tmp_path, summary) -> None:
    """agents.csv as recorded, the samples as the API draws them here."""
    rows = [
        list(csv.DictReader(io.StringIO(t.decode())))
        for t in (produced, recorded)
    ]
    written = [row.pop(_SAMPLED) for row in rows[0]]
    kept = [row.pop(_SAMPLED) for row in rows[1]]
    assert rows[0] == rows[1]
    _within_16_ulp(written, kept)
    sim = load_scenario(tmp_path / "scenario.json").simulation
    seed = json.loads(summary)["run"]["seed"]
    sampled = sim.run(seed, record=False).pre_movement_times
    assert written == [cli._number(t) for t in sampled]


def test_cases_cover_the_paths_of_the_move():
    """The recorded cases exercise what the move must keep."""
    status = {case: _recorded(case)["status"] for case in CASES}
    assert status["gs_incomplete"] == b"2\n"
    assert status["gs_empty_quantiles"] == b"1\n"
    assert "warning: " in _recorded("ow_run")["stderr"].decode()
    assert "results/runs.csv" not in _recorded("gs_no_monte_carlo")
    stdout = _recorded("gs_null_seeds")["stdout"].decode()
    assert f"seed {DRAWN[0]} (drawn)" in stdout
    assert f"seed {DRAWN[1]} (drawn)" in stdout


def test_drawn_seeds_rerun_to_the_same_results(tmp_path, monkeypatch):
    """Both seeds drawn for ``null`` reproduce the run when given back."""
    monkeypatch.chdir(tmp_path)
    source = GOLDEN / "gs_null_seeds" / "scenario.json"
    (tmp_path / "scenario.json").write_bytes(source.read_bytes())
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["run", "scenario.json"]) == 0
    first = tmp_path / "scenario_results"
    summary = json.loads((first / "summary.json").read_text())
    seeds = summary["run"]["seed"], summary["monte_carlo"]["seed"]
    assert summary["run"]["seed_drawn"] and summary["monte_carlo"]["seed_drawn"]
    again = ["-o", "again", "--seed", str(seeds[0]), "--mc-seed", str(seeds[1])]
    with contextlib.redirect_stdout(io.StringIO()):
        assert cli.main(["run", "scenario.json", *again]) == 0
    rerun = json.loads((tmp_path / "again" / "summary.json").read_text())
    for name in ("agents.csv", "runs.csv", "link_flow.csv", "occupancy.csv"):
        assert (tmp_path / "again" / name).read_bytes() == (
            first / name
        ).read_bytes(), name
    assert (
        rerun["monte_carlo"]["quantiles"] == summary["monte_carlo"]["quantiles"]
    )
    assert (rerun["run"]["seed"], rerun["monte_carlo"]["seed"]) == seeds
