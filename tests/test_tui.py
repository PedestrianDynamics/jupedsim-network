# SPDX-License-Identifier: LGPL-3.0-or-later
"""The terminal UI (#47): flows, equality with the CLI, snapshots.

Pilot tests drive the app headless with the real engine thread, so what
the TUI shows and writes comes from the same calls as the command line.
Fast unit tests of the textual-free parts are in ``test_tui_model.py``.
"""

import asyncio
import csv
import importlib.util
import io
import json
import re
import sys
import threading
import time
import warnings
from pathlib import Path

import pytest

pytest.importorskip("textual")

from textual import events  # noqa: E402
from textual.widgets import Input, OptionList, Select, Switch  # noqa: E402

from jupedsim_network import cli, cli_init  # noqa: E402
from jupedsim_network.tui import engine as jobs  # noqa: E402
from jupedsim_network.tui import model  # noqa: E402
from jupedsim_network.tui.app import NetworkTui  # noqa: E402
from jupedsim_network.tui.widgets import (  # noqa: E402
    ConfirmScreen,
    ElementList,
    FieldRow,
    TooSmall,
)

SIZE = (80, 24)
WIDE = (120, 35)


# --- fixtures ----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _tui_env(tmp_path, monkeypatch):
    """No test writes ~/.config; a colour terminal; no engine thread left."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("TERM", "xterm-256color")
    monkeypatch.setenv("COLORTERM", "truecolor")
    for name in ("NO_COLOR", model.THEME_ENV, "SSH_CONNECTION"):
        monkeypatch.delenv(name, raising=False)
    yield
    left = [t for t in threading.enumerate() if t.name == jobs.THREAD_NAME]
    for thread in left:
        thread.join(30)
    assert not [t for t in left if t.is_alive()], "an engine thread is left"


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    """A working directory; paths on screen are relative to it."""
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    return work


def make_app(**kwargs) -> NetworkTui:
    kwargs.setdefault("debounce", 0)
    return NetworkTui(**kwargs)


def run(coro):
    return asyncio.run(coro)


async def settle(pilot, app, rounds: int = 3) -> None:
    """Wait until the engine is idle and its events reached the UI."""
    quiet = 0
    for _ in range(4000):
        await pilot.pause()
        idle = app.engine.idle and app._timer is None
        quiet = quiet + 1 if idle else 0
        if quiet >= rounds:
            return
        await asyncio.sleep(0.005)
    raise AssertionError("the engine did not become idle")


async def tap(app, *keys: str) -> None:
    """Press keys while a run keeps the app busy.

    ``pilot.press`` waits until the app is idle, which a run with its
    progress redraws postpones for seconds; this posts the key events and
    gives the app a moment to handle each.
    """
    for key in keys:
        app.post_message(events.Key(key, key if len(key) == 1 else None))
        await asyncio.sleep(0.05)


async def until(predicate, timeout: float = 30.0) -> None:
    end = asyncio.get_running_loop().time() + timeout
    while not predicate():
        assert asyncio.get_running_loop().time() < end, "timed out"
        await asyncio.sleep(0.005)


def question(app) -> str:
    """The question of the dialog on top, once it is composed; else ""."""
    found = app.screen.query("#question")
    return str(found.first().render()) if found else ""


def text_of(app, selector: str) -> str:
    return str(app.query_one(selector).render())


def row(app, path: tuple, suffix: str = "") -> FieldRow:
    return app.query_one(f"#row-{'-'.join(map(str, path))}{suffix}", FieldRow)


def write_example(path: Path, name: str = "getting-started", **changes) -> Path:
    data = json.loads(cli_init.example_bytes(name))
    for dotted, value in changes.items():
        model.put(data, model.parse_path(dotted), value)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return path


async def open_example(pilot, app, name: str = "getting-started") -> None:
    app.open_example(name)
    await settle(pilot, app)


async def type_into(pilot, app, path: tuple, text: str) -> None:
    control = row(app, path).control
    control.focus()
    control.value = text
    await settle(pilot, app)


def tree_files(folder: Path) -> dict[str, bytes]:
    if not folder.exists():
        return {}
    return {
        str(p.relative_to(folder)): p.read_bytes()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


# --- F1: new from example, save -----------------------------------------------


def test_f1_example_saved_unchanged_is_the_packaged_file(workdir):
    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            assert app.step == 1
            assert "untitled (getting-started)" in text_of(app, "#summary")
            assert "● unsaved" in text_of(app, "#summary")
            await pilot.press("ctrl+s")
            await pilot.pause()
            box = app.screen.query_one("#ask-path", Input)
            assert box.value == "scenario.json"
            await pilot.press("enter")
            await settle(pilot, app)
            assert app.path == "scenario.json"
            assert "saved" in text_of(app, "#summary")
            assert "● unsaved" not in text_of(app, "#summary")

    run(go())
    expected = cli_init.example_bytes("getting-started")
    assert (workdir / "scenario.json").read_bytes() == expected


def test_only_the_shown_form_is_built(workdir):
    """Opening a file builds one form; the others wait for their tab, so
    a key pressed right after opening is not held up (QA2-O4)."""

    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app, "office-wing")
            assert app.query("#form-nodes FieldRow")
            for form in ("connections", "populations", "settings"):
                assert not app.query(f"#form-{form} FieldRow"), form
            app.action_tab(1)
            await settle(pilot, app)
            assert app.query("#form-connections FieldRow")
            assert not app.query("#form-populations FieldRow")

    run(go())


# --- F2: a file that is not valid is not opened ------------------------------------


def test_f2_invalid_file_shows_the_cli_error_and_opens_nothing(workdir, capsys):
    write_example(workdir / "typo.json", **{"simulation.max_densty": 2.0})
    assert cli.main(["check", "typo.json"]) == 1
    (line,) = capsys.readouterr().err.splitlines()
    expected = line.removeprefix("jupedsim-network check: error: ")

    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            app.query_one("#sc-tabs").active = "tab-open"
            box = app.query_one("#open-path", Input)
            box.focus()
            box.value = "typo.json"
            await pilot.press("enter")
            await settle(pilot, app)
            assert text_of(app, "#sc-error") == expected
            assert app.doc is None and app.step == 0

    run(go())


# --- F3: a typed error, then fixed --------------------------------------------------


def test_f3_typed_error_is_shown_at_its_field_and_the_text_is_kept(workdir):
    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            app.action_tab(1)
            await settle(pilot, app)
            width = ("connections", 0, "width")
            await type_into(pilot, app, width, "abc")
            assert app.doc["connections"][0]["width"] == "abc"
            assert row(app, width).has_class("-invalid")
            message = 'expected a number, got the string "abc"'
            assert message in text_of(
                app, f"#row-{'-'.join(map(str, width))} .help"
            )
            assert "✗ connections[0].width: " + message in text_of(
                app, "#summary"
            )
            table = app.query_one("#list-connections", ElementList)
            assert table.get_cell_at((0, 0)) == "✗"
            # A change of step loses nothing.
            app.goto(0)
            app.goto(1)
            await settle(pilot, app)
            assert row(app, width).control.value == "abc"
            await type_into(pilot, app, width, "0.90")
            assert app.doc["connections"][0]["width"] == 0.9
            assert not row(app, width).has_class("-invalid")
            assert "✓ valid" in text_of(app, "#summary")
            assert table.get_cell_at((0, 0)) == " "
            # Empty text removes the key: the API default applies.
            length = ("connections", 0, "length")
            await type_into(pilot, app, length, "")
            assert "length" not in app.doc["connections"][0]
            assert "default" in text_of(
                app, "#row-connections-0-length .marker"
            )

    run(go())


# --- F4: an error at element level, found by the trial run ---------------------------


def test_f4_trial_error_goes_to_its_element(workdir):
    write_example(workdir / "scenario.json", **{"populations[0].speed": 0})

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            assert app.step == 1 and app.path == "scenario.json"
            await pilot.press("ctrl+n")
            await settle(pilot, app)
            assert app.step == 2 and app.checked.status == 1
            assert app.checked.error_path == "populations[0]"
            errors = app.query_one("#ck-errors", OptionList)
            assert app.focused is errors
            await pilot.press("enter")
            await settle(pilot, app)
            assert app.step == 1
            assert app.query_one("#ed-tabs").active == "tab-populations"
            assert app.focused is app.query_one("#list-populations")

    run(go())


# --- F5: add, delete and move -------------------------------------------------------


def test_f5_add_delete_move_follow_the_file_order(workdir):
    write_example(workdir / "scenario.json")

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            app.action_tab(1)
            await settle(pilot, app)
            table = app.query_one("#list-connections", ElementList)
            assert app.focused is table
            await pilot.press("a")
            await settle(pilot, app)
            assert app.doc["connections"][1] == {}
            assert "required" in text_of(
                app, "#row-connections-1-source .marker"
            )
            assert app.error[0][:2] == ("connections", 1)
            await pilot.press("alt+up")
            await settle(pilot, app)
            assert (
                app.doc["connections"][0] == {}
                and app.selected["connections"] == 0
            )
            await pilot.press("alt+up")  # already first
            await pilot.press("d")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            assert "Delete connection 0?" in text_of(app.screen, "#question")
            await pilot.press("y")
            await settle(pilot, app)
            assert len(app.doc["connections"]) == 2
            await pilot.press("down")
            await pilot.press("alt+up")
            await settle(pilot, app)
            assert [c["source"] for c in app.doc["connections"]] == [
                "flight",
                "office",
            ]
            await pilot.press("ctrl+s")
            await settle(pilot, app)

    run(go())
    saved = json.loads((workdir / "scenario.json").read_text())
    assert [c["source"] for c in saved["connections"]] == ["flight", "office"]


# --- F6: rename a node, change a kind ------------------------------------------------


def test_f6_rename_asks_and_kind_change_restores_values(workdir):
    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            await type_into(pilot, app, ("nodes", 0, "name"), "hall")
            await pilot.press("tab")
            await pilot.pause()
            assert isinstance(app.screen, ConfirmScreen)
            question = text_of(app.screen, "#question")
            assert (
                question
                == "Also rename 'office' in 1 connection and 1 population?"
            )
            await pilot.press("y")
            await settle(pilot, app)
            assert app.doc["connections"][0]["source"] == "hall"
            assert app.doc["populations"][0]["node"] == "hall"
            assert "✓ valid" in text_of(app, "#summary")
            # stair -> room -> stair
            table = app.query_one("#list-nodes", ElementList)
            table.focus()
            table.move_cursor(row=1)
            await settle(pilot, app)
            kind = row(app, ("nodes", 1, "kind")).control
            kind.value = "room"
            await settle(pilot, app)
            assert app.doc["nodes"][1] == {
                "name": "flight",
                "kind": "room",
                "area": 10.8,
            }
            assert not app.query("#row-nodes-1-riser")
            row(app, ("nodes", 1, "kind")).control.value = "stair"
            await settle(pilot, app)
            node = app.doc["nodes"][1]
            assert (node["riser"], node["tread"]) == (0.18, 0.28)
            # backspace on a select removes the key (the default applies)
            row(app, ("nodes", 1, "kind")).control.focus()
            await pilot.press("backspace")
            await settle(pilot, app)
            assert "kind" not in app.doc["nodes"][1]

    run(go())


def test_rename_without_references_asks_nothing(workdir):
    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            app.doc["nodes"].append({"name": "spare", "kind": "safe"})
            app._fill_list("nodes")
            table = app.query_one("#list-nodes", ElementList)
            table.move_cursor(row=3)
            await settle(pilot, app)
            await type_into(pilot, app, ("nodes", 3, "name"), "spare2")
            await pilot.press("enter")
            await pilot.pause()
            assert not isinstance(app.screen, ConfirmScreen)
            table.move_cursor(row=0)
            await settle(pilot, app)
            await type_into(pilot, app, ("nodes", 0, "name"), "hall")
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("n")
            await settle(pilot, app)
            assert app.doc["connections"][0]["source"] == "office"

    run(go())


# --- distributions and settings -----------------------------------------------------


def test_distribution_type_keeps_shared_fields(workdir):
    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            app.action_tab(2)
            await settle(pilot, app)
            pre = ("populations", 0, "pre_movement")
            row(app, pre, "-type").control.value = "Normal"
            await settle(pilot, app)
            assert app.doc["populations"][0]["pre_movement"] == {
                "distribution": "Normal",
                "mean": 120.0,
                "std": 60.0,
            }
            row(app, pre, "-type").control.value = "number"
            await settle(pilot, app)
            assert "pre_movement" not in app.doc["populations"][0]
            await type_into(pilot, app, pre, "30")
            assert app.doc["populations"][0]["pre_movement"] == 30
            row(app, pre, "-type").control.value = "LogNormal"
            await settle(pilot, app)
            assert app.doc["populations"][0]["pre_movement"] == {
                "distribution": "LogNormal",
                "mean": 120.0,
                "std": 60.0,
            }
            await type_into(pilot, app, (*pre, "lower"), "null")
            assert app.doc["populations"][0]["pre_movement"]["lower"] is None
            row(app, pre, "-type").control.value = "number"
            await settle(pilot, app)
            assert app.doc["populations"][0]["pre_movement"] == 30
            row(app, pre, "-type").control.focus()
            await pilot.press("backspace")
            await settle(pilot, app)
            assert "pre_movement" not in app.doc["populations"][0]
            assert "default 0.0" in text_of(
                app, "#row-populations-0-pre_movement-type .help"
            )

    run(go())


def test_settings_switches_and_monte_carlo_section(workdir):
    async def go():
        app = make_app()
        async with app.run_test(size=WIDE) as pilot:
            await open_example(pilot, app)
            app.action_tab(-1)
            await settle(pilot, app)
            assert app.query_one("#ed-tabs").active == "tab-settings"
            split = row(app, ("simulation", "split_ties"))
            split.control.value = False
            await settle(pilot, app)
            assert app.doc["simulation"]["split_ties"] is False
            split.control.focus()
            await pilot.press("backspace")
            await settle(pilot, app)
            assert "split_ties" not in app.doc["simulation"]
            assert split.control.value is True
            flow = row(app, ("simulation", "counterflow"))
            flow.control.value = "estimate"
            await settle(pilot, app)
            assert app.doc["simulation"]["counterflow"] == "estimate"
            flow.control.focus()
            await pilot.press("backspace")
            await settle(pilot, app)
            assert flow.control.value is Select.NULL
            await type_into(pilot, app, ("simulation", "dt"), "")
            assert "simulation" not in app.doc  # an empty section is left out
            mc = row(app, ("monte_carlo",))
            mc.control.value = False
            await settle(pilot, app)
            assert "monte_carlo" not in app.doc
            assert not app.query("#row-monte_carlo-runs")
            row(app, ("monte_carlo",)).control.value = True
            await settle(pilot, app)
            assert app.doc["monte_carlo"] == {
                "runs": 500,
                "seed": 1,
                "quantiles": [0.5, 0.95],
            }
            await type_into(
                pilot, app, ("monte_carlo", "quantiles"), "0.5, 0.9"
            )
            assert app.doc["monte_carlo"]["quantiles"] == [0.5, 0.9]
            await type_into(pilot, app, ("description",), "")
            assert "description" not in app.doc
            # ↑/↓ move between the fields
            row(app, ("run", "seed")).control.focus()
            await pilot.press("down")
            assert app.focused is row(app, ("monte_carlo",)).control
            await pilot.press("up")
            assert app.focused is row(app, ("run", "seed")).control

    run(go())


def test_new_elements_of_each_list(workdir):
    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            for section in ("nodes", "populations"):
                app.query_one("#ed-tabs").active = f"tab-{section}"
                app.query_one(f"#list-{section}").focus()
                await pilot.press("a")
                await settle(pilot, app)
            assert app.doc["nodes"][1] == {} and app.doc["populations"][1] == {}
            assert app.error is not None and app.error[1][0] == "nodes"
            assert "✗" in text_of(app, "#summary")
            await pilot.press("enter")  # nothing: the list has the focus
            app.query_one("#summary").focus()
            await pilot.press("enter")
            await settle(pilot, app)
            assert app.query_one("#ed-tabs").active == "tab-nodes"
            app.doc["nodes"] = []
            app._fill_list("nodes")
            app._shown.pop("nodes", None)
            await app._rebuild_form("nodes")
            app._refresh_rows()
            assert "No nodes yet" in text_of(app, "#head-nodes")

    run(go())


# --- F7: Check equals `jupedsim-network check` ----------------------------------------


@pytest.mark.parametrize(
    ("name", "changes", "status"),
    [
        ("getting-started", {}, 0),
        ("office-wing", {"nodes[11].riser": 0.20}, 0),
        ("getting-started", {"populations[0].count": 3000}, 1),
        ("getting-started", {"simulation.t_max": 100.0}, 2),
    ],
    ids=["valid", "stair-warning", "trial-error", "incomplete"],
)
def test_f7_check_text_equals_the_cli(workdir, capsys, name, changes, status):
    write_example(workdir / "scenario.json", name, **changes)
    assert cli.main(["check", "scenario.json"]) == status
    out, err = capsys.readouterr()

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            app.action_check()
            await settle(pilot, app)
            checked = app.checked
            assert checked.status == status
            assert checked.stream("stdout") == out.splitlines()
            assert checked.stream("stderr") == err.splitlines()
            shown = text_of(app, "#ck-text").splitlines()
            assert [line for _s, line in checked.lines] == shown
            assert (
                "jupedsim-network run scenario.json -o scenario_results"
                in text_of(app, "#ck-command")
            )
            await pilot.press("c")

    run(go())


# --- A9 / F8: run equals `jupedsim-network run`, also while the UI thread warns ---------


def _ui_warning_at(app, done: int, message: str):
    """Make the UI thread warn while the Monte Carlo set is running."""
    loop = asyncio.get_running_loop()
    released = threading.Event()
    original = app._post

    def post(event):
        if (
            isinstance(event, jobs.Progress)
            and event.phase == "monte carlo"
            and event.done == done
        ):

            def ui_warn():
                warnings.warn(message)
                released.set()

            loop.call_soon_threadsafe(ui_warn)
            assert released.wait(10)
        original(event)

    app._post = post


@pytest.mark.parametrize(
    ("name", "changes"),
    [
        ("getting-started", {"monte_carlo.runs": 20}),
        ("office-wing", {"nodes[11].riser": 0.20, "monte_carlo.runs": 10}),
    ],
    ids=["getting-started", "office-wing-stair-warning"],
)
def test_a9_tui_files_equal_cli_files_while_the_ui_thread_warns(
    workdir, capsys, name, changes
):
    runs = changes["monte_carlo.runs"]
    write_example(
        workdir / "scenario.json",
        name,
        **{**changes, "monte_carlo.runs": runs + 1},
    )
    message = "a warning of the UI thread"

    async def go():
        app = make_app(scenario="scenario.json", engine=jobs.Engine(throttle=0))
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            # F8: an unsaved edit, then ctrl+r asks to save first.
            app.action_tab(-1)
            await settle(pilot, app)
            await type_into(pilot, app, ("monte_carlo", "runs"), str(runs))
            _ui_warning_at(app, 3, message)
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert (
                text_of(app.screen, "#question")
                == "Save scenario.json and run?"
            )
            await pilot.press("y")
            await settle(pilot, app)
            assert app.step == 4
            finished = app.current_run.finished
            assert any(message in w for w in app.engine.foreign)
            return finished, text_of(app, "#res-outcome")

    finished, shown = run(go())
    capsys.readouterr()
    status = cli.main(["run", "scenario.json", "-o", "cli_out"])
    out, err = capsys.readouterr()
    assert finished.status == status
    assert list(finished.stdout[:-1]) == out.splitlines()[:-1]
    assert finished.stdout[-1].startswith("Wrote scenario_results/: ")
    assert list(finished.stderr) == err.splitlines()
    assert (
        message
        not in json.loads(
            (workdir / "scenario_results" / "summary.json").read_text()
        )["warnings"]
    )
    for line in finished.stdout:
        assert line in shown
    names = [
        "summary.json",
        "agents.csv",
        "link_flow.csv",
        "occupancy.csv",
        "runs.csv",
    ]
    assert list(finished.files) == names
    for file in names:
        assert (workdir / "scenario_results" / file).read_bytes() == (
            workdir / "cli_out" / file
        ).read_bytes(), file
    if name == "office-wing":
        assert any(
            "riser" in line or "SFPE" in line for line in finished.stderr
        )


# --- A10 / F9: cancel in the UI ---------------------------------------------------------


def test_f9_cancel_during_monte_carlo_writes_nothing(workdir, capsys):
    write_example(workdir / "scenario.json")
    assert cli.main(["run", "scenario.json", "--no-monte-carlo"]) == 0
    capsys.readouterr()
    before = tree_files(workdir / "scenario_results")

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            await pilot.press("ctrl+r")
            await pilot.pause()
            assert (
                text_of(app.screen, "#question")
                == "scenario_results/ holds results; replace them?"
            )
            await pilot.press("y")
            await until(lambda: app.current_run.phase == "monte carlo")
            app.render_run()
            assert "Monte Carlo" in text_of(app, "#run-status")
            assert app.focused is app.query_one("#run-status")
            await tap(app, "x")
            await until(lambda: question(app) != "")
            await asyncio.sleep(0.3)  # progress redraws under the dialog
            await tap(app, "y")
            await until(lambda: not isinstance(app.screen, ConfirmScreen))
            assert "Cancelling" in text_of(app, "#run-status")
            await tap(app, "x")  # a second cancel asks nothing
            assert not isinstance(app.screen, ConfirmScreen)
            await until(lambda: app.current_run.finished is not None)
            await settle(pilot, app)
            finished = app.current_run.finished
            assert finished.status is None and app.step == 4
            outcome = text_of(app, "#res-outcome")
            assert outcome.startswith(
                f"■ Cancelled after {finished.done} of 500 runs; nothing was written."
            )
            assert "q 0." not in outcome and "quantile" not in outcome
            files = app.query_one("#res-files", OptionList)
            assert (
                str(files.get_option_at_index(0).prompt)
                == "No files were written."
            )

    run(go())
    assert tree_files(workdir / "scenario_results") == before


def test_cancel_while_the_run_waits_behind_a_check_writes_nothing(
    workdir, monkeypatch
):
    """QA2-B1 in the UI: ctrl+r while Check's trial run is still going."""
    from jupedsim_network import cli_run

    write_example(workdir / "scenario.json", **{"monte_carlo.runs": 5})
    trial = cli_run.trial

    def slow_trial(*args, **kwargs):
        time.sleep(1.0)
        return trial(*args, **kwargs)

    monkeypatch.setattr(cli_run, "trial", slow_trial)

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            app.action_check()
            await until(lambda: not app.engine.idle)
            await tap(app, "ctrl+r")
            await until(lambda: app.current_run is not None)
            assert app.checking  # the run waits behind the trial run
            await tap(app, "x")
            await until(lambda: question(app) != "")
            await tap(app, "y")
            await until(lambda: app.current_run.finished is not None)
            await settle(pilot, app)
            assert app.current_run.finished.status is None
            assert text_of(app, "#res-outcome").startswith(
                "■ Cancelled before it started; nothing was written."
            )

    run(go())
    assert not (workdir / "scenario_results").exists()


# --- F10: quit asks the right question ---------------------------------------------------


def test_f10_quit_questions(workdir):
    write_example(workdir / "scenario.json")

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert not app.is_running  # saved: quits at once
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            app.action_tab(1)
            await settle(pilot, app)
            await type_into(pilot, app, ("connections", 0, "width"), "1.0")
            await pilot.press("ctrl+q")
            await pilot.pause()
            assert (
                text_of(app.screen, "#question")
                == "Quit without saving? Unsaved changes to scenario.json are lost."
            )
            await pilot.press("n")
            await type_into(pilot, app, ("connections", 0, "width"), "abc")
            await pilot.press("ctrl+q")
            await pilot.pause()
            question = text_of(app.screen, "#question")
            assert (
                "The scenario has an error (connections[0].width: expected a number"
                in question
            )
            assert question.endswith("and cannot be saved as it is.")
            await pilot.press("y")
            await pilot.pause()
            assert not app.is_running

    run(go())


def test_f10_quit_during_a_run_cancels_it(workdir):
    write_example(workdir / "scenario.json")

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            await pilot.press("ctrl+r")
            await until(lambda: app.current_run.phase == "monte carlo")
            app.doc["description"] = "edited during the run"
            await tap(app, "ctrl+q")
            await until(lambda: question(app) != "")
            assert text_of(app.screen, "#question").startswith(
                "A run is in progress. Quit and cancel it?"
            )
            await tap(app, "y")
            await until(lambda: question(app).startswith("Quit without"))
            # The answer that quits: a posted key could still be in
            # Textual's queue when the screens are gone.
            app.screen.action_answer(True)
            await asyncio.sleep(0.05)
        assert app.engine.cancel_event.is_set()

    run(go())
    assert not (workdir / "scenario_results").exists()


# --- F11: a drawn seed -------------------------------------------------------------------


def test_f11_drawn_seed_is_shown_and_recorded(workdir):
    write_example(
        workdir / "scenario.json", **{"run.seed": None, "monte_carlo.runs": 3}
    )

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            app.action_tab(-1)  # Settings; its form is built when shown
            await settle(pilot, app)
            help_line = text_of(app, "#row-run-seed .help")
            assert "the command line draws a seed and records it" in help_line
            await pilot.press("ctrl+r")
            await settle(pilot, app)
            assert "(drawn)" in text_of(app, "#res-outcome")

    run(go())
    summary = json.loads(
        (workdir / "scenario_results" / "summary.json").read_text()
    )
    assert summary["run"]["seed_drawn"] is True


# --- A12: Results wording ---------------------------------------------------------------


def test_a12_results_wording_and_occupancy(workdir):
    # The run seed differs from the Monte Carlo seed (1), so a heading
    # with the wrong seed fails.
    write_example(
        workdir / "scenario.json", **{"monte_carlo.runs": 20, "run.seed": 4242}
    )

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=WIDE) as pilot:
            await settle(pilot, app)
            app.query_one("#run-single", Switch).value = False
            await pilot.press("ctrl+r")
            await settle(pilot, app)
            text = text_of(app, "#res-outcome") + text_of(app, "#res-tree-wide")
            for words in (
                "✓ complete",
                "Monte Carlo set",
                "not the single run above",
                "quantile of evacuation time over 20 runs [s]",
                "runs 20 · incomplete 0",
                "capacity [persons/s]",
                "nominal capacity C = Fs (w − 2b), not the realised flow",
                "> t_max is a lower bound.",
            ):
                assert words in text, words
            flat = " ".join(text.split())
            assert model.TIME_NOTE in flat and model.SPREAD_NOTE in flat
            assert flat.count("RSET") == flat.count(
                "Call it an RSET only with that qualification"
            )
            rows = list(
                csv.reader(
                    io.StringIO(
                        (
                            workdir / "scenario_results" / "occupancy.csv"
                        ).read_text()
                    )
                )
            )
            header, rows = rows[0], rows[1:]
            # Every step, by the keys first, then by the action they call;
            # the counts change from step to step, so a shifted row fails.
            assert any(a[1:] != b[1:] for a, b in zip(rows, rows[1:]))
            visited = [0]
            for key, delta in (
                ("shift+right", 10),
                ("right", 1),
                ("left", -1),
                ("shift+left", -10),
                ("left", -1),
            ):
                await pilot.press(key)
                visited.append(max(0, visited[-1] + delta))
                assert_occupancy(app, header, rows, visited[-1])
            for step in range(1, len(rows) + 2):
                app.action_scrub(1)
                assert_occupancy(app, header, rows, min(step, len(rows) - 1))
            tree = text_of(app, "#res-tree-wide")
            assert "persons/s" in tree and "RSET" not in tree
            files = app.query_one("#res-files", OptionList)
            files.focus()
            await pilot.press("enter")
            await pilot.pause()
            assert "format_version" in app.screen.query_one("#text").text
            await pilot.press("y")
            await pilot.press("escape")
            await pilot.press("y")
            await pilot.press("w")
            await pilot.pause()
            assert app.screen.query_one("#text").text == "No warnings."
            await pilot.press("escape")
            await pilot.press("c")
            await pilot.press("e")
            assert app.step == 1
            await type_into(pilot, app, ("nodes", 0, "area"), "201")
            app.goto(4)
            assert app.query_one("#res-banner").display

    run(go())


def assert_occupancy(app, header, rows, step):
    """The tree shows occupancy.csv row ``step`` and the run's own seed."""
    tree = text_of(app, "#res-tree-wide")
    time_, *counts = rows[step]
    heading = (
        f"occupancy of the single run, seed 4242: t = {time_} s "
        f"(step {step} of {len(rows) - 1})"
    )
    assert heading in " ".join(tree.split()), (step, heading)
    shown = {}
    for line in tree.splitlines():
        words = re.sub(r"^[\s│├└─◀]+", "", line).split()
        if words and "●" in words:
            shown[words[0]] = words[-1]
    assert shown == dict(zip(header[1:], counts)), step


# --- F12: a small terminal ----------------------------------------------------------


class FakeEngine:
    """Records the jobs; the test sends the events itself."""

    def __init__(self):
        self.jobs = []
        self.cancelled = 0
        self.idle = True
        self.foreign = []

    def start(self):
        pass

    def submit(self, job, post, key=None):
        self.jobs.append(job)

    def cancel(self):
        self.cancelled += 1

    def stop(self):
        pass


def test_f12_small_terminal_notice_and_the_run_continues(workdir):
    async def go():
        app = make_app(engine=FakeEngine())
        async with app.run_test(size=SIZE) as pilot:
            app.load_doc(
                json.loads(cli_init.example_bytes("getting-started")),
                "scenario.json",
                None,
            )
            app.saved = app.doc
            app.start_run("scenario_results")
            app.on_engine_event(jobs.Progress("monte carlo", 5, 500))
            await pilot.resize_terminal(79, 23)
            await pilot.pause(0.2)
            assert isinstance(app.screen, TooSmall)
            assert "Terminal is 79×23; the TUI needs 80×24." in text_of(
                app.screen, "#notice"
            )
            app.on_engine_event(jobs.Progress("monte carlo", 6, 500))
            await pilot.resize_terminal(78, 23)
            await pilot.pause(0.2)
            await pilot.resize_terminal(*SIZE)
            await pilot.pause(0.2)
            assert not isinstance(app.screen, TooSmall)
            assert (
                app.current_run.done == 6 and app.current_run.finished is None
            )

    run(go())


# --- smaller paths of the app ---------------------------------------------------------


def test_scenario_step_recent_open_and_palette(workdir):
    write_example(workdir / "scenario.json")
    (workdir / "sub").mkdir()
    recent = model.Recent()
    recent.add("scenario.json", "2026-10-11T10:00", "complete")
    recent.add("gone.json", "2026-10-11T09:00", "error")

    async def go():
        app = make_app(recent=recent)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            assert app.query_one("#sc-tabs").active == "tab-recent"
            recent_list = app.query_one("#recent", OptionList)
            assert "missing" in str(recent_list.get_option_at_index(0).prompt)
            await pilot.press("ctrl+n")
            await settle(pilot, app)
            assert app.doc is None and "cannot read " in text_of(
                app, "#sc-error"
            )
            recent_list.highlighted = 1
            await pilot.press("ctrl+n")
            await settle(pilot, app)
            assert app.path == "scenario.json" and app.step == 1
            app.goto(0)
            app.query_one("#sc-tabs").active = "tab-open"
            box = app.query_one("#open-path", Input)
            box.focus()
            box.value = f"{workdir}{'/'}su"
            await pilot.press("tab")
            assert box.value == f"{workdir}/sub/"
            await pilot.press("tab")  # nothing more to complete: to the list
            assert app.focused is app.query_one("#open-list")
            await pilot.press("tab")
            assert app.focused is box
            await pilot.press("down")
            assert app.focused is app.query_one("#open-list")
            await pilot.press("enter")  # ".." up
            await pilot.pause(0.2)
            assert box.value == f"{workdir}/"
            await pilot.press("s", "c", "x", "backspace")
            await pilot.pause(0.2)
            assert box.value == f"{workdir}/sc"
            await pilot.press("enter")
            await settle(pilot, app)
            assert app.step == 1
            app.goto(0)
            box.value = str(workdir / "sub")
            app._accept_scenario_tab()
            await pilot.pause(0.2)
            assert box.value == f"{workdir}/sub/"
            app.query_one("#sc-tabs").active = "tab-examples"
            app.query_one("#examples").focus()
            await pilot.press("ctrl+n")
            await settle(pilot, app)
            assert app.example == "getting-started" and app.path is None
            titles = [c.title for c in app.get_system_commands(app.screen)]
            assert (
                "Theme: Solarized Light" in titles
                and "Go to step 5: Results" in titles
            )
            app.set_theme("solarized-light")
            assert model.Recent().theme == "solarized-light"
            app.show_docs()
            app.goto(4)  # no run yet
            assert app.step == 1
            await pilot.press("question_mark")
            await pilot.pause()
            assert "ctrl+r" in app.screen.query_one("#text").text
            await pilot.press("escape")
            row(app, ("nodes", 0, "area")).control.focus()
            await pilot.press("f1")
            await pilot.pause()
            text = app.screen.query_one("#text").text
            assert (
                text.startswith("floor area in m²")
                and "Key: nodes[0].area" in text
            )
            await pilot.press("escape")
            await pilot.press("escape")
            assert app.step == 0

    run(go())


def test_save_as_asks_before_replacing_and_reports_errors(workdir):
    write_example(workdir / "other.json")

    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            await pilot.press("ctrl+s")
            await pilot.pause()
            box = app.screen.query_one("#ask-path", Input)
            box.value = "other.json"
            await pilot.press("enter")
            await pilot.pause()
            assert (
                text_of(app.screen, "#question")
                == "other.json exists. Replace it?"
            )
            await pilot.press("n")
            await pilot.press("ctrl+s")
            await pilot.pause()
            await pilot.press("escape")
            assert app.path is None
            await type_into(pilot, app, ("nodes", 0, "area"), "-1")
            app.save_as()
            await pilot.pause()
            app.screen.query_one("#ask-path", Input).value = "bad.json"
            await pilot.press("enter")
            await settle(pilot, app)
            assert app.path is None and not (workdir / "bad.json").exists()
            # Check of an unsaved scenario asks for the path first.
            await type_into(pilot, app, ("nodes", 0, "area"), "200.0")
            app.action_check()
            await pilot.pause()
            app.screen.query_one("#ask-path", Input).value = "new.json"
            await pilot.press("enter")
            await settle(pilot, app)
            assert app.path == "new.json" and app.checked.status == 0
            await pilot.press("ctrl+p")
            assert app.step == 1
            await pilot.press("ctrl+n")
            await settle(pilot, app)
            await pilot.press("ctrl+n")
            assert app.step == 3
            await pilot.press("ctrl+n")  # no results yet
            assert app.step == 3

    run(go())


def test_internal_error_is_shown_with_its_traceback(workdir):
    async def go():
        app = make_app(engine=FakeEngine())
        async with app.run_test(size=SIZE) as pilot:
            app.load_doc(
                json.loads(cli_init.example_bytes("getting-started")),
                "scenario.json",
                None,
            )
            app.start_run("scenario_results")
            # A validation bug does not end the run.
            app.on_engine_event(jobs.Failed("validate", "Traceback: other"))
            assert app.step == 3 and app.current_run.finished is None
            app.on_engine_event(jobs.Failed("run", "Traceback: boom"))
            await pilot.pause()
            assert app.step == 4
            assert text_of(app, "#res-outcome").startswith("✗ error")
            await pilot.press("t")
            await pilot.pause()
            assert app.screen.query_one("#text").text == "Traceback: boom"
            await pilot.press("escape")
            app.action_run()
            app.current_run.finished = None
            app.action_run()  # a run is in progress
            app.action_cancel()
            await pilot.pause()
            await pilot.press("n")
            assert app.current_run.cancelling is False
            app.on_engine_event(jobs.Progress("single run", 0, None))
            app.goto(3)
            assert "single run" in text_of(app, "#run-status")
            app._quitting = True
            app.on_engine_event(jobs.Progress("monte carlo", 1, 2))
            app._quitting = False

    run(go())


def test_run_error_shows_the_cli_error(workdir):
    write_example(workdir / "scenario.json", **{"populations[0].count": 3000})

    async def go():
        app = make_app(scenario="scenario.json")
        async with app.run_test(size=SIZE) as pilot:
            await settle(pilot, app)
            app.query_one("#run-single", Switch).value = True
            await pilot.press("ctrl+r")
            await settle(pilot, app)
            assert app.current_run.finished.status == 1
            text = text_of(app, "#res-outcome")
            assert (
                "jupedsim-network run: error: scenario.json: run: Initial population exceeds max_density"
                in text
            )

    run(go())


# --- launch ---------------------------------------------------------------------------


def test_launch_chooses_the_theme(monkeypatch):
    from jupedsim_network.tui import app as app_module
    from jupedsim_network.tui import launch

    started = []

    class Fake:
        def __init__(self, theme, scenario):
            started.append((theme, scenario))

        def run(self):
            pass

    monkeypatch.setattr(app_module, "NetworkTui", Fake)
    assert cli.main(["tui", "s.json", "--theme", "solarized-light"]) == 0
    monkeypatch.setenv(model.THEME_ENV, "solarized-light")
    assert launch.main() == 0
    assert started == [("solarized-light", "s.json"), ("solarized-light", None)]
    monkeypatch.setenv(model.THEME_ENV, "nope")
    assert launch.main() == 1


def test_launch_reraises_other_import_errors(monkeypatch):
    from jupedsim_network.tui import launch

    monkeypatch.setitem(sys.modules, "jupedsim_network.tui.app", None)
    with pytest.raises(ModuleNotFoundError):
        launch.main()


# --- snapshots (SVG; the docs page can reuse them) -----------------------------------


# The snapshot fixture comes from the tui-test dependency group.
snapshots = pytest.mark.skipif(
    importlib.util.find_spec("pytest_textual_snapshot") is None,
    reason="needs the tui-test dependency group (pytest-textual-snapshot)",
)


def steady(before=None):
    """Run ``before``, then stop the cursors blinking (pyFDS-Evac #553)."""

    async def run_before(pilot):
        if before is not None:
            await before(pilot)
        for widget in pilot.app.screen.query("*"):
            if hasattr(widget, "cursor_blink"):
                widget.cursor_blink = False
        await pilot.pause()

    return run_before


def pin_wall(state, seconds: int) -> None:
    """Fix the wall time a snapshot shows: both ends exact."""
    state.started, state.ended = 1000.0, 1000.0 + seconds


@snapshots
@pytest.mark.parametrize("theme", model.THEMES)
def test_snapshot_scenario(workdir, snap_compare, theme):
    assert snap_compare(
        make_app(theme=theme), terminal_size=SIZE, run_before=steady()
    )


@snapshots
@pytest.mark.parametrize(
    ("theme", "size"),
    [(model.THEMES[0], SIZE), (model.THEMES[1], SIZE), (model.THEMES[0], WIDE)],
    ids=["network-dark", "solarized-light", "network-dark-120x35"],
)
def test_snapshot_edit_connection_error(workdir, snap_compare, theme, size):
    async def before(pilot):
        app = pilot.app
        await open_example(pilot, app)
        app.action_tab(1)
        await settle(pilot, app)
        await type_into(pilot, app, ("connections", 0, "width"), "abc")

    app = make_app(theme=theme)
    assert snap_compare(app, terminal_size=size, run_before=steady(before))


@snapshots
@pytest.mark.parametrize(
    ("theme", "size"),
    [(model.THEMES[0], SIZE), (model.THEMES[0], WIDE), (model.THEMES[1], WIDE)],
    ids=["80x24", "120x35", "solarized-light-120x35"],
)
def test_snapshot_check(workdir, snap_compare, theme, size):
    write_example(workdir / "scenario.json")

    async def before(pilot):
        app = pilot.app
        await settle(pilot, app)
        app.action_check()
        await settle(pilot, app)

    app = make_app(scenario="scenario.json", theme=theme)
    assert snap_compare(app, terminal_size=size, run_before=steady(before))


@snapshots
def test_snapshot_run_in_progress(workdir, snap_compare):
    async def before(pilot):
        app = pilot.app
        app.load_doc(
            json.loads(cli_init.example_bytes("getting-started")),
            "scenario.json",
            None,
        )
        app.saved = app.doc
        app.start_run("scenario_results")
        app.on_engine_event(jobs.Progress("monte carlo", 132, 500))
        pin_wall(app.current_run, 7)
        await pilot.pause(0.2)
        app.render_run()
        await pilot.pause()

    app = make_app(engine=FakeEngine())
    assert snap_compare(app, terminal_size=SIZE, run_before=steady(before))


def _results_before(workdir):
    write_example(workdir / "scenario.json", **{"monte_carlo.runs": 20})

    async def before(pilot):
        app = pilot.app
        await settle(pilot, app)
        await pilot.press("ctrl+r")
        await settle(pilot, app)
        pin_wall(app.current_run, 2)
        app.action_scrub(240)
        app.render_results()
        await pilot.pause()

    return before


@snapshots
@pytest.mark.parametrize("size", [SIZE, WIDE], ids=["80x24", "120x35"])
def test_snapshot_results(workdir, snap_compare, size):
    app = make_app(scenario="scenario.json")
    assert snap_compare(
        app, terminal_size=size, run_before=steady(_results_before(workdir))
    )


@snapshots
def test_snapshot_results_no_color(workdir, snap_compare, monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    app = make_app(scenario="scenario.json")
    assert snap_compare(
        app, terminal_size=WIDE, run_before=steady(_results_before(workdir))
    )


def test_guards_and_helpers(workdir, monkeypatch, tmp_path):
    from jupedsim_network.tui import app as app_module

    async def go():
        app = make_app(engine=FakeEngine(), debounce=0.05)
        async with app.run_test(size=SIZE) as pilot:
            # Nothing open yet.
            app.goto(1)
            assert app.step == 0
            for action in (
                app.action_save,
                app.save_as,
                app.action_copy_command,
            ):
                action()
            app.ensure_saved("check", lambda: None)
            app.action_run()
            app.render_results()
            app.action_scrub(1)
            app.action_warnings()
            app.action_copy_path()
            app._check_error(None)
            app._run_finished(jobs.RunFinished("s.json", "out", 0))
            app._progress(jobs.Progress("single run", 0, None))
            app.open_folder = None
            app._open_choice(
                type("E", (), {"option": type("O", (), {"id": "up"})()})()
            )
            assert app._result_path(0) is None
            # A document; validation is debounced.
            app.load_doc(
                json.loads(cli_init.example_bytes("getting-started")),
                "scenario.json",
                None,
            )
            app.saved = json.loads(json.dumps(app.doc))
            app.schedule_validate()
            app.schedule_validate()
            await pilot.pause(0.2)
            assert isinstance(app.engine.jobs[-1], type(jobs.validate(0, {})))
            app.on_engine_event(
                jobs.Validated(app._gen, "nodes[0].area", "must be positive")
            )
            await pilot.pause()
            app.on_engine_event(jobs.Validated(app._gen - 1))  # stale: ignored
            assert app.error[1] == ("nodes", 0, "area")
            for path in (
                (),
                ("simulation", "dt"),
                ("connections",),
                ("populations", 0),
                ("nodes", 2, "name"),
            ):
                app.focus_path(path)
                await pilot.pause()
            assert app.selected["nodes"] == 2
            # Scenario step: Enter with an empty list goes back to Edit.
            app.goto(0)
            app.query_one("#sc-tabs").active = "tab-recent"
            app._accept_scenario_tab()
            assert app.step == 1
            await pilot.press("ctrl+p", "ctrl+n")
            # Runs: cancel, quit questions answered "no".
            app.start_run("scenario_results")
            app.on_engine_event(jobs.Progress("single run", 0, 500))
            await pilot.pause()
            app.action_cancel()
            await pilot.pause()
            app._render_tick()  # a redraw under the dialog reaches the step
            await pilot.press("y")
            assert app.engine.cancelled == 1 and app.current_run.cancelling
            app.action_cancel()  # already cancelling
            app._confirmed_quit_run(False)
            app.doc["description"] = "x"
            app._confirmed_quit_run(True)
            await pilot.pause()
            await pilot.press("n")
            assert app.is_running
            app.on_engine_event(
                jobs.RunFinished(
                    "scenario.json",
                    "scenario_results",
                    None,
                    phase="single run",
                    runs=500,
                )
            )
            await pilot.pause()
            assert text_of(app, "#res-outcome").startswith(
                "■ Cancelled during the single run; nothing was written."
            )
            app.goto(3)
            await pilot.press("ctrl+n")
            assert app.step == 4
            await pilot.press("n")
            assert app.step == 0
            app._confirmed_quit(False)

    run(go())
    assert app_module.file_preview(tmp_path / "missing").startswith(
        "Cannot read the file"
    )
    big = tmp_path / "big.csv"
    big.write_text("\n".join(map(str, range(100))))
    assert app_module.file_preview(big).endswith("… first 40 lines shown")
    (tmp_path / "empty").write_text("")
    assert app_module.file_preview(tmp_path / "empty") == "(empty file)"
    assert app_module._size(tmp_path / "missing") == ""
    assert app_module._size(big) == "289 B"
    (tmp_path / "kb").write_bytes(b"x" * 3000)
    assert app_module._size(tmp_path / "kb") == "2.9 KB"
    monkeypatch.setenv("SSH_CONNECTION", "1")
    assert app_module.file_opener() is None
    monkeypatch.delenv("SSH_CONNECTION")
    monkeypatch.setattr(app_module.sys, "platform", "linux")
    monkeypatch.setattr(
        app_module.shutil, "which", lambda name: "/usr/bin/xdg-open"
    )
    assert app_module.file_opener() == ["xdg-open"]
    monkeypatch.setattr(app_module.sys, "platform", "win32")
    assert app_module.file_opener() is None
    monkeypatch.setattr(app_module.sys, "platform", "darwin")
    assert app_module.file_opener() == ["open"]


def test_few_colours_are_reported(workdir, monkeypatch):
    async def go():
        app = make_app(engine=FakeEngine())
        async with app.run_test(size=SIZE) as pilot:
            notes = []
            monkeypatch.setattr(
                app, "notify", lambda text, **kw: notes.append(text)
            )
            monkeypatch.setattr(
                type(app.console), "color_system", property(lambda self: "256")
            )
            app._warn_color_system()
            await pilot.pause()
            assert notes and notes[0].startswith(
                "This terminal shows 256 colours"
            )

    run(go())


def test_dialogs_and_row_values(workdir, monkeypatch):
    from jupedsim_network.tui import widgets
    from jupedsim_network.tui.widgets import FileScreen, TextScreen

    opened = []
    monkeypatch.setattr(
        widgets.subprocess, "Popen", lambda args, **kw: opened.append(args)
    )

    async def go():
        app = make_app()
        async with app.run_test(size=SIZE) as pilot:
            await open_example(pilot, app)
            app.action_tab(1)
            await settle(pilot, app)
            both = row(app, ("connections", 0, "bidirectional"))
            both.set_value(True)
            assert both.control.value is True
            width = row(app, ("connections", 0, "width"))
            width.set_value(1.5)
            assert width.control.value == "1.5"
            width.action_reset()  # an input resets by clearing its text
            app.push_screen(TextScreen("t", "text"))
            await pilot.pause()
            await pilot.press("c")
            await pilot.press("escape")
            app.push_screen(FileScreen("a.csv", "x", ["open"]))
            await pilot.pause()
            await pilot.press("o")
            await pilot.press("escape")
            app.push_screen(FileScreen("a.csv", "x", None))
            await pilot.pause()
            assert app.screen.check_action("open", ()) is False
            app.screen.action_open()
            await pilot.press("escape")
            await pilot.pause()
            assert opened == [["open", "a.csv"]]

    run(go())


# --- the keys table of the Terminal UI page --------------------------------------


def _keys_rows(text: str) -> list[tuple[str, str]]:
    """``(key, action)`` of ``keys_text()``; an indented line continues
    the action above it."""
    rows: list[tuple[str, str]] = []
    for line in text.splitlines():
        if line.startswith(" "):
            key, action = rows.pop()
            rows.append((key, f"{action} {line.strip()}"))
            continue
        key, action = re.split(r"\s{2,}", line, maxsplit=1)
        rows.append((key, action))
    return rows


def test_page_keys_table_is_keys_text():
    """The Keys table of using/terminal-ui.md, row by row, is what ``?``
    shows."""
    import docpages

    from jupedsim_network.tui.app import keys_text

    page = (docpages.DOCS / "using" / "terminal-ui.md").read_text()
    section = page.split("\n## Keys\n", 1)[1].split("\n## ", 1)[0]
    table = [
        tuple(cell.strip().strip("`") for cell in line.strip("|").split("|"))
        for line in section.splitlines()
        if line.startswith("| ")
    ]
    assert table[0] == ("Key", "Action")
    assert table[1:] == _keys_rows(keys_text())
