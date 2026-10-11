# SPDX-License-Identifier: LGPL-3.0-or-later
"""``jupedsim-network run``, ``check`` and ``init`` end to end, in process."""

import csv
import json
import os
import shutil
from pathlib import Path

import pytest

from jupedsim_network import cli, cli_init, load_scenario

ROOT = Path(__file__).resolve().parents[1]
PACKAGED = ROOT / "src" / "jupedsim_network" / "scenarios"
FULL_KEYS = ROOT / "tests" / "data" / "full_keys.json"


def _scenario(tmp_path, edit=None, source=PACKAGED / "getting_started.json"):
    data = json.loads(source.read_text())
    if edit is not None:
        edit(data)
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(data, indent=2))
    return path


def _fast(data):
    """Getting-started with 5 instead of 500 realisations."""
    data["monte_carlo"]["runs"] = 5


def _rows(path):
    with path.open(newline="") as handle:
        return list(csv.reader(handle))


def _python(path):
    """The same scenario through the Python API: one run and five runs."""
    sim = load_scenario(path).simulation
    return sim.run(1), sim.run_many(5, 1)


def test_run_writes_the_results(tmp_path, capsys):
    path = _scenario(tmp_path, _fast)
    assert cli.main(["run", str(path)]) == cli.EXIT_OK
    out = tmp_path / "scenario_results"
    shown = capsys.readouterr().out
    result, many = _python(path)
    time = round(result.evacuation_time, 2)
    assert (
        f"Run, seed 1: evacuation time {time!r} s; 120 of 120 agents safe."
        in shown
    )
    q = [float(v) for v in many.quantile([0.5, 0.95])]
    assert (
        f"Monte Carlo, 5 runs, seed 1: q 0.5 {round(q[0], 2)!r} s, "
        f"q 0.95 {round(q[1], 2)!r} s; 0 incomplete." in shown
    )
    summary = json.loads((out / "summary.json").read_text())
    assert summary["run"]["evacuation_time"] == result.evacuation_time
    assert [v["value"] for v in summary["monte_carlo"]["quantiles"]] == q
    assert summary["run"]["seed"] == 1 and not summary["run"]["seed_drawn"]
    assert summary["monte_carlo"]["runs"] == 5
    assert [q["q"] for q in summary["monte_carlo"]["quantiles"]] == [0.5, 0.95]
    assert summary["links"][1] == {
        "index": 1,
        "name": "flight->street",
        "source": "flight",
        "target": "street",
        "kind": "stair",
        "capacity": summary["links"][1]["capacity"],
    }
    assert set(summary["units"]) >= {"time", "link_flow", "exit_time"}
    agents = _rows(out / "agents.csv")
    assert agents[0] == ["agent", "pre_movement_sampled", "exit_time"]
    assert len(agents) == 121
    flow = _rows(out / "link_flow.csv")
    assert flow[0] == ["time", "0:office->flight", "1:flight->street"]
    assert flow[1] == ["0.0", "0", "0"]
    assert sum(int(r[2]) for r in flow[1:]) == 120
    assert _rows(out / "occupancy.csv")[0] == ["time", "office", "flight"]
    assert len(_rows(out / "runs.csv")) == 6


def test_result_files_are_the_python_results(tmp_path):
    """agents.csv and runs.csv hold the API's values, digit for digit."""
    path = _scenario(tmp_path, _fast)
    assert cli.main(["run", str(path)]) == cli.EXIT_OK
    out = tmp_path / "scenario_results"
    result, many = _python(path)
    agents = [
        f"{i},{float(p)!r},{float(e)!r}\n"
        for i, (p, e) in enumerate(
            zip(result.pre_movement_times, result.exit_times)
        )
    ]
    expected = "agent,pre_movement_sampled,exit_time\n" + "".join(agents)
    assert (out / "agents.csv").read_text() == expected
    runs = [
        f"{i},{float(t)!r},{int(n)}\n"
        for i, (t, n) in enumerate(
            zip(many.evacuation_times, many.agent_counts)
        )
    ]
    expected = "run,evacuation_time,agents\n" + "".join(runs)
    assert (out / "runs.csv").read_text() == expected


def test_times_are_shown_to_a_hundredth_and_written_in_full():
    assert cli._shown(158.29999999999998) == "158.3"
    assert cli._shown(323.0) == "323.0"
    assert cli._shown(383.25) == "383.25"
    assert cli._number(158.29999999999998) == "158.29999999999998"


def test_run_twice_writes_the_same_bytes(tmp_path):
    path = _scenario(tmp_path, _fast)
    a, b = tmp_path / "a", tmp_path / "b"
    assert cli.main(["run", str(path), "-o", str(a)]) == 0
    assert cli.main(["run", str(path), "-o", str(b)]) == 0
    for name in ("agents.csv", "link_flow.csv", "occupancy.csv", "runs.csv"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_no_numpy_reprs_and_exit_times_not_rounded(tmp_path):
    """Plain float reprs (the same under NumPy 1 and 2), no rounding."""
    path = _scenario(tmp_path, source=PACKAGED / "office_wing.json")
    out = tmp_path / "out"
    assert cli.main(["run", str(path), "-o", str(out), "--no-monte-carlo"]) == 0
    text = "".join(p.read_text() for p in out.iterdir())
    assert "np." not in text and "float64" not in text
    result = load_scenario(path).simulation.run(1)
    exits = [row[2] for row in _rows(out / "agents.csv")[1:]]
    assert exits == [repr(float(x)) for x in result.exit_times]


def test_link_columns_are_unique_with_duplicate_names(tmp_path):
    def twin_doors(data):
        data["connections"].append(dict(data["connections"][1]))

    path = _scenario(tmp_path, twin_doors)
    assert cli.main(["run", str(path), "--no-monte-carlo"]) == 0
    header = _rows(tmp_path / "scenario_results" / "link_flow.csv")[0]
    assert header == [
        "time",
        "0:office->flight",
        "1:flight->street",
        "2:flight->street",
    ]


def test_names_with_commas_are_quoted(tmp_path):
    def comma(data):
        text = json.dumps(data).replace('"office"', '"office, west"')
        data.clear()
        data.update(json.loads(text))

    path = _scenario(tmp_path, comma)
    assert cli.main(["run", str(path), "--no-monte-carlo"]) == 0
    header = _rows(tmp_path / "scenario_results" / "occupancy.csv")[0]
    assert header == ["time", "office, west", "flight"]


def test_run_without_monte_carlo_removes_an_old_runs_csv(tmp_path):
    path = _scenario(tmp_path, _fast)
    out = tmp_path / "st"
    other = out / "notes.txt"
    assert cli.main(["run", str(path), "-o", str(out), "--runs", "3"]) == 0
    assert (out / "runs.csv").is_file()
    other.write_text("mine")
    args = ["run", str(path), "-o", str(out), "--no-monte-carlo"]
    assert cli.main(args) == cli.EXIT_OK
    assert not (out / "runs.csv").exists()
    summary = json.loads((out / "summary.json").read_text())
    assert summary["monte_carlo"] is None
    assert other.read_text() == "mine"


def test_failed_run_leaves_the_directory_untouched(tmp_path):
    path = _scenario(tmp_path, _fast)
    out = tmp_path / "st"
    assert cli.main(["run", str(path), "-o", str(out), "--runs", "3"]) == 0
    before = {p.name: p.read_bytes() for p in out.iterdir()}
    bad = _scenario(tmp_path, lambda d: d["populations"][0].update(speed=0.0))
    args = ["run", str(bad), "-o", str(out), "--no-monte-carlo"]
    assert cli.main(args) == cli.EXIT_ERROR
    assert {p.name: p.read_bytes() for p in out.iterdir()} == before


def _snapshot(directory):
    return {
        p.name: (p.read_bytes() if p.is_file() else None)
        for p in directory.iterdir()
    }


@pytest.mark.parametrize("monte_carlo", [True, False])
def test_failed_write_leaves_the_directory_untouched(
    tmp_path, capsys, monte_carlo
):
    """runs.csv is a directory: written last or removed, it cannot be
    replaced, and no other file of DIR changes."""
    path = _scenario(tmp_path, _fast)
    out = tmp_path / "st"
    assert cli.main(["run", str(path), "-o", str(out), "--no-monte-carlo"]) == 0
    (out / "agents.csv").write_text("old")
    (out / "runs.csv").mkdir()
    before = _snapshot(out)
    capsys.readouterr()
    extra = [] if monte_carlo else ["--no-monte-carlo"]
    assert (
        cli.main(["run", str(path), "-o", str(out), *extra]) == cli.EXIT_ERROR
    )
    err = capsys.readouterr().err
    assert f"cannot write {out / 'runs.csv'}: is a directory" in err
    assert _snapshot(out) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scenario.json", "st"]
    assert not [p for p in out.iterdir() if p.name.startswith(".")]


def test_failed_staged_write_names_the_file(tmp_path, capsys, monkeypatch):
    path = _scenario(tmp_path, _fast)
    out = tmp_path / "st"
    assert cli.main(["run", str(path), "-o", str(out), "--no-monte-carlo"]) == 0
    before = _snapshot(out)
    write_text = Path.write_text

    def full_disk(self, *args, **kwargs):
        if self.name == "link_flow.csv":
            raise OSError(28, "No space left on device", str(self))
        return write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", full_disk)
    capsys.readouterr()
    assert cli.main(["run", str(path), "-o", str(out)]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert f"cannot write {out / 'link_flow.csv'}: No space left" in err
    assert _snapshot(out) == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scenario.json", "st"]
    assert not [p for p in out.iterdir() if p.name.startswith(".")]


@pytest.mark.skipif(
    os.name == "nt" or os.geteuid() == 0,
    reason="needs POSIX permissions and a user other than root",
)
def test_read_only_parent_of_a_writable_output_directory(tmp_path):
    path = _scenario(tmp_path, _fast)
    parent = tmp_path / "ro"
    out = parent / "out"
    out.mkdir(parents=True)
    parent.chmod(0o555)
    try:
        args = ["run", str(path), "-o", str(out), "--no-monte-carlo"]
        assert cli.main(args) == cli.EXIT_OK
        assert sorted(p.name for p in parent.iterdir()) == ["out"]
    finally:
        parent.chmod(0o755)
    assert sorted(p.name for p in out.iterdir()) == [
        "agents.csv",
        "link_flow.csv",
        "occupancy.csv",
        "summary.json",
    ]


def test_failed_run_into_a_new_directory_leaves_no_folder(
    tmp_path, capsys, monkeypatch
):
    path = _scenario(tmp_path, _fast)
    write_text = Path.write_text

    def full_disk(self, *args, **kwargs):
        if self.name == "link_flow.csv":
            raise OSError(28, "No space left on device", str(self))
        return write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", full_disk)
    out = tmp_path / "new" / "out"
    assert cli.main(["run", str(path), "-o", str(out)]) == cli.EXIT_ERROR
    assert f"cannot write {out / 'link_flow.csv'}" in capsys.readouterr().err
    assert sorted(p.name for p in tmp_path.iterdir()) == ["scenario.json"]


def test_interrupt_exits_130_without_a_traceback(tmp_path, capsys, monkeypatch):
    import functools

    from jupedsim_network.simulation import NetworkSimulation

    # wraps keeps the signature, from which the loader reads the run keys.
    @functools.wraps(NetworkSimulation.run)
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(NetworkSimulation, "run", interrupted)
    path = _scenario(tmp_path, _fast)
    for command in ("run", "check"):
        assert cli.main([command, str(path)]) == cli.EXIT_INTERRUPTED
        err = capsys.readouterr().err
        assert err == "jupedsim-network: interrupted\n"
    assert not (tmp_path / "scenario_results").exists()


def test_incomplete_run_exits_2_and_writes(tmp_path, capsys):
    path = _scenario(tmp_path, lambda d: d.update(simulation={"t_max": 100.0}))
    assert (
        cli.main(["run", str(path), "--no-monte-carlo"]) == cli.EXIT_INCOMPLETE
    )
    summary = json.loads(
        (tmp_path / "scenario_results" / "summary.json").read_text()
    )
    assert summary["run"]["evacuation_time"] is None
    assert "not finished by t_max" in capsys.readouterr().out


def test_incomplete_monte_carlo_warns_once(tmp_path, capsys):
    def short(data):
        data["simulation"] = {"t_max": 300.0}
        data["monte_carlo"]["runs"] = 5

    path = _scenario(tmp_path, short)
    assert cli.main(["run", str(path)]) == cli.EXIT_INCOMPLETE
    err = capsys.readouterr().err
    assert err.count("warning: monte_carlo: ") == 1
    summary = json.loads(
        (tmp_path / "scenario_results" / "summary.json").read_text()
    )
    assert summary["monte_carlo"]["quantiles"][1]["value"] is None


def test_null_seed_is_drawn_and_recorded(tmp_path, capsys):
    def null(data):
        data["run"]["seed"] = None
        del data["monte_carlo"]

    path = _scenario(tmp_path, null)
    assert cli.main(["run", str(path)]) == 0
    summary = json.loads(
        (tmp_path / "scenario_results" / "summary.json").read_text()
    )
    seed = summary["run"]["seed"]
    assert summary["run"]["seed_drawn"] and isinstance(seed, int) and seed >= 0
    assert summary["monte_carlo"] is None
    again = tmp_path / "again"
    assert (
        cli.main(["run", str(path), "--seed", str(seed), "-o", str(again)]) == 0
    )
    first = (tmp_path / "scenario_results" / "agents.csv").read_bytes()
    assert (again / "agents.csv").read_bytes() == first


def test_default_quantiles(tmp_path):
    def no_quantiles(data):
        del data["monte_carlo"]["quantiles"]
        data["monte_carlo"]["runs"] = 3

    path = _scenario(tmp_path, no_quantiles)
    assert cli.main(["run", str(path)]) == 0
    summary = json.loads(
        (tmp_path / "scenario_results" / "summary.json").read_text()
    )
    qs = [q["q"] for q in summary["monte_carlo"]["quantiles"]]
    assert qs == list(cli.DEFAULT_QUANTILES)


def test_command_line_overrides_the_file(tmp_path):
    path = _scenario(tmp_path)
    args = [
        "run",
        str(path),
        "--runs",
        "3",
        "--mc-seed",
        "4",
        "--quantile",
        "0.9",
    ]
    assert cli.main(args) == 0
    mc = json.loads(
        (tmp_path / "scenario_results" / "summary.json").read_text()
    )["monte_carlo"]
    assert (mc["runs"], mc["seed"], [q["q"] for q in mc["quantiles"]]) == (
        3,
        4,
        [0.9],
    )


@pytest.mark.parametrize(
    "edit, expected",
    [
        (
            lambda d: d["simulation"].update(dt="0.5"),
            "simulation.dt: expected a number",
        ),
        (
            lambda d: d["populations"][0].update(
                pre_movement={"distribution": "LogNormal", "mean": 0, "std": 1}
            ),
            "populations[0].pre_movement: cannot sample LogNormal(",
        ),
        (
            lambda d: d["populations"][0].update(count=5000),
            "run: Initial population exceeds max_density in ['office'].",
        ),
        (
            lambda d: d["populations"][0].update(speed=0.0),
            "populations[0]: Agent speeds must be positive.",
        ),
        (
            lambda d: d["monte_carlo"].update(quantiles=[1.5]),
            "monte_carlo.quantiles[0]: must be in [0, 1], got 1.5",
        ),
        (
            lambda d: d["simulation"].update(max_density=4.0),
            "simulation: max_density",
        ),
    ],
)
def test_errors_exit_1_with_the_path_and_write_nothing(
    tmp_path, capsys, edit, expected
):
    def small(data):
        _fast(data)
        edit(data)

    path = _scenario(tmp_path, small)
    assert cli.main(["run", str(path)]) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert f"jupedsim-network run: error: {path}: {expected}" in err
    assert "Traceback" not in err
    assert not (tmp_path / "scenario_results").exists()


_GOOD = (PACKAGED / "getting_started.json").read_text(encoding="utf-8")


def _deep(depth: int) -> bytes:
    return b'{"format_version": 1, "x": ' + b"[" * depth + b"]" * depth + b"}"


@pytest.mark.parametrize("command", ["check", "run"])
@pytest.mark.parametrize(
    "raw, expected",
    [
        (_GOOD.encode("utf-16"), "not UTF-8 text: byte 0xff at position 0"),
        (
            _GOOD.replace('"kind": "room"', '"kind": ["room"]').encode(),
            "nodes[0].kind: expected a string, got an array",
        ),
        (
            _GOOD.replace('"LogNormal"', '{"a": 1}').encode(),
            "populations[0].pre_movement.distribution: expected a string, "
            "got an object",
        ),
        (
            _GOOD.replace(
                '"dt": 0.5', '"dt": 0.5, "t_max": 1' + "0" * 400
            ).encode(),
            "simulation.t_max: integer of about 401 digits is too large",
        ),
        # json.loads stops at 1500 on 3.10, but not on 3.13; the cap
        # in the checks catches it there.
        (_deep(1500), "nested deeper than 64 levels"),
        (_deep(900), "x" + "[0]" * 64 + ": nested deeper than 64 levels"),
        (
            _GOOD.replace('"runs": 500', '"runs": 0').encode(),
            "monte_carlo.runs: must be >= 1, got 0",
        ),
        (
            _GOOD.replace("0.95", "1.5").encode(),
            "monte_carlo.quantiles[1]: must be in [0, 1], got 1.5",
        ),
    ],
    ids=[
        "utf16",
        "kind-array",
        "distribution-object",
        "huge-int",
        "deep-1500",
        "deep-900",
        "runs-0",
        "quantile-1.5",
    ],
)
def test_malformed_files_exit_1_without_a_traceback(
    tmp_path, capsys, command, raw, expected
):
    """check rejects whatever run rejects, with the path and no traceback."""
    path = tmp_path / "scenario.json"
    path.write_bytes(raw)
    out = tmp_path / "out"
    args = [command, str(path)] + (["-o", str(out)] if command == "run" else [])
    assert cli.main(args) == cli.EXIT_ERROR
    err = capsys.readouterr().err
    assert err.startswith(f"jupedsim-network {command}: error: {path}: ")
    assert expected in err
    assert "Traceback" not in err
    assert not out.exists()


def test_quantile_option_is_checked_before_running(capsys):
    assert cli.main(["run", "x.json", "--quantile", "1.5"]) == cli.EXIT_ERROR
    assert "--quantile: must be in [0, 1], got 1.5" in capsys.readouterr().err


def test_missing_file_exits_1(tmp_path, capsys):
    assert cli.main(["run", str(tmp_path / "none.json")]) == cli.EXIT_ERROR
    assert "cannot read" in capsys.readouterr().err


def test_warnings_are_printed_once(tmp_path, capsys):
    shutil.copy(FULL_KEYS, tmp_path / "full.json")
    assert cli.main(["check", str(tmp_path / "full.json")]) == 0
    err = capsys.readouterr().err
    assert err.count("warning: populations[0]: Routes are tied") == 1
    assert err.count("warning: ") == 2


@pytest.mark.parametrize("name", ["getting_started.json", "office_wing.json"])
def test_check_packaged_scenarios(name, capsys):
    assert cli.main(["check", str(PACKAGED / name)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "Trial run, seed 1" in out and "The scenario is valid." in out


def test_check_catches_run_time_errors(tmp_path, capsys):
    path = _scenario(tmp_path, lambda d: d["populations"][0].update(count=5000))
    assert cli.main(["check", str(path)]) == cli.EXIT_ERROR
    assert (
        "run: Initial population exceeds max_density" in capsys.readouterr().err
    )


def test_check_exits_2_if_the_trial_run_is_incomplete(tmp_path, capsys):
    path = _scenario(tmp_path, lambda d: d.update(simulation={"t_max": 100.0}))
    assert cli.main(["check", str(path)]) == cli.EXIT_INCOMPLETE
    out = capsys.readouterr().out
    assert "not finished by t_max" in out
    assert "The scenario is valid." not in out


def test_init_writes_the_packaged_bytes(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["init"]) == 0
    written = tmp_path / "scenario.json"
    assert (
        written.read_bytes() == (PACKAGED / "getting_started.json").read_bytes()
    )
    assert "jupedsim-network run scenario.json" in capsys.readouterr().out
    written.write_text("mine")
    assert cli.main(["init"]) == cli.EXIT_ERROR
    assert written.read_text() == "mine"
    assert cli.main(["init", "--force", "--example", "office-wing"]) == 0
    assert written.read_bytes() == cli_init.example_bytes("office-wing")
