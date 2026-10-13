# SPDX-License-Identifier: LGPL-3.0-or-later
"""The textual-free parts of the TUI: document model, route tree, engine.

U2 text → JSON, U3 error location, U6 one engine job at a time (with the
warning isolation of QA-I5), A10 cancel writes nothing, A11 tied routes.
None of these needs Textual.
"""

import dataclasses
import functools
import importlib.util
import json
import re
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

import docpages
import pytest

from jupedsim_network import cli, cli_init, scenario
from jupedsim_network.scenario import ScenarioError, attempt, scenario_from_dict
from jupedsim_network.simulation import NetworkSimulation
from jupedsim_network.tui import engine as jobs
from jupedsim_network.tui import model, netview


def example(name: str = "getting-started") -> dict:
    return json.loads(cli_init.example_bytes(name))


def tie_doc(split_ties: bool = True) -> dict:
    """A room with two equally short routes to the same safe node."""
    door = {"width": 1.0, "length": 5.0, "bidirectional": False}
    return {
        "format_version": 1,
        "nodes": [
            {"name": "r", "kind": "room", "area": 100.0},
            {"name": "a", "kind": "room", "area": 20.0},
            {"name": "b", "kind": "room", "area": 20.0},
            {"name": "out", "kind": "safe"},
        ],
        "connections": [
            {"source": "r", "target": "a", **door},
            {"source": "r", "target": "b", **door},
            {"source": "a", "target": "out", **door},
            {"source": "b", "target": "out", **door},
        ],
        "populations": [{"node": "r", "count": 10}],
        "simulation": {"split_ties": split_ties},
    }


# --- U2: text -> JSON -------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "annotation", "expected"),
    [
        ("", float, (False, None)),
        ("   ", float, (False, None)),
        ("0.9", float, (True, 0.9)),
        ("120", float | None, (True, 120)),
        ("abc", float, (True, "abc")),
        ("null", float | None, (True, None)),
        ("true", bool, (True, True)),
        ("office", str, (True, "office")),
        ("12", str, (True, "12")),
        ("a->b", str | None, (True, "a->b")),
        ("0.5, 0.95", list[float], (True, [0.5, 0.95])),
        ("0.5, x", list[float], (True, "0.5, x")),
    ],
)
def test_u2_text_to_json(text, annotation, expected):
    assert model.to_json(text, annotation) == expected


@pytest.mark.parametrize("text", ["NaN", "1e999", "-Infinity"])
def test_u2_non_finite_text_is_a_loader_error(text):
    doc = example()
    present, value = model.to_json(text, float)
    assert present
    model.put(doc, ("connections", 0, "width"), value)
    with pytest.raises(ScenarioError) as err:
        scenario_from_dict(doc)
    assert err.value.path == "connections[0].width"


def test_u2_abc_is_reported_by_the_loader_in_its_words():
    doc = example()
    model.put(doc, ("connections", 0, "width"), model.to_json("abc", float)[1])
    with pytest.raises(ScenarioError) as err:
        scenario_from_dict(doc)
    assert (
        str(err.value)
        == 'connections[0].width: expected a number, got the string "abc"'
    )


@pytest.mark.parametrize(
    "value", ["office", None, True, False, 0.9, 200.0, 7, [0.5, 0.95], "0.5, x"]
)
def test_u2_text_round_trips(value):
    annotation = list[float] if isinstance(value, list) else float | None
    if isinstance(value, str):
        annotation = str
    assert model.to_json(model.to_text(value), annotation) == (True, value)


def test_empty_text_removes_the_key_and_an_empty_section():
    doc = example()
    model.remove(doc, ("simulation", "dt"))
    assert "simulation" not in doc
    model.put(doc, ("simulation", "t_max"), 100.0)
    assert doc["simulation"] == {"t_max": 100.0}
    model.remove(doc, ("monte_carlo", "runs"))
    assert doc["monte_carlo"] == {"seed": 1, "quantiles": [0.5, 0.95]}
    model.remove(doc, ("nope", "x"))


def test_paths_parse_and_print():
    for text in (
        "",
        "simulation",
        "connections[1].width",
        "populations[0].pre_movement.std",
        "monte_carlo.quantiles[2]",
    ):
        assert model.path_text(model.parse_path(text)) == text
    assert model.parse_path("populations[0].pre_movement.std") == (
        "populations",
        0,
        "pre_movement",
        "std",
    )
    assert model.get({"a": [1]}, ("a", 3), "x") == "x"


# --- U3: where an error is shown --------------------------------------------------


@pytest.mark.parametrize(
    ("path", "anchor"),
    [
        ("connections[1].width", ("connections", 1, "width")),
        ("monte_carlo.quantiles[2]", ("monte_carlo", "quantiles")),
        (
            "populations[0].pre_movement.std",
            ("populations", 0, "pre_movement", "std"),
        ),
        (
            "populations[0].pre_movement.nope",
            ("populations", 0, "pre_movement"),
        ),
        ("populations[0].count", ("populations", 0, "count")),
        ("populations[0]", ("populations", 0)),
        ("populations[5].count", ("populations",)),
        ("nodes[1].unknown", ("nodes", 1)),
        ("nodes[1].riser", ("nodes", 1, "riser")),
        ("simulation", ("simulation",)),
        ("simulation.max_densty", ("simulation",)),
        ("run", ("run",)),
        ("run.seed", ("run", "seed")),
        ("monte_carlo", ("monte_carlo",)),
        ("populations", ("populations",)),
        ("description", ("description",)),
        ("format_version", ()),
        ("", ()),
    ],
)
def test_u3_error_anchor(path, anchor):
    assert model.anchor(model.parse_path(path), example()) == anchor


def test_u3_element_error_from_the_api_message():
    doc = example()
    doc["populations"][0]["node"] = "street"
    with pytest.raises(ScenarioError) as err:
        scenario_from_dict(doc)
    assert err.value.path == "populations[0]"
    assert model.anchor(model.parse_path(err.value.path), doc) == (
        "populations",
        0,
    )


def test_u3_anchor_of_a_document_that_is_no_dict():
    assert model.anchor(("nodes", 0), []) == ()


# --- help text (docs-architect E1, E2) ----------------------------------------


def test_help_has_no_rst_markup_and_json_words():
    for element, kinds in (
        ("node", ("room", "stair", "safe")),
        ("distribution", model.distribution_names()),
        ("connection", (None,)),
        ("population", (None,)),
        ("simulation", (None,)),
        ("run", (None,)),
        ("monte_carlo", (None,)),
        ("document", (None,)),
    ):
        for kind in kinds:
            for key in scenario.keys(element, kind):
                text = model.help_text(element, key) + model.default_text(key)
                assert "``" not in text and ":meth:" not in text, key
                assert not {"None", "False", "True"} & set(text.split()), (
                    key,
                    text,
                )


def test_help_of_seeds_names_what_a_file_holds():
    (seed,) = scenario.keys("run")
    assert model.help_text("run", seed) == "integer seed of the single run"
    assert "Generator" not in model.help_text(
        "monte_carlo", scenario.keys("monte_carlo")[1]
    )


def test_clean_help_examples():
    assert (
        model.clean_help("``None`` or :meth:`Network.add_room`")
        == "null or add_room"
    )
    assert (
        model.clean_help(':class:`~jupedsim_network.Population`, ``"door"``')
        == 'Population, "door"'
    )


def test_default_text():
    keys = {k.name: k for k in scenario.keys("connection")}
    assert model.default_text(keys["source"]) == "required"
    assert model.default_text(keys["kind"]) == "default door"
    assert model.default_text(keys["bidirectional"]) == "default true"
    assert model.default_text(keys["name"]) == "source->target"
    (_runs, _seed, quantiles) = scenario.keys("monte_carlo")
    assert model.default_text(quantiles) == "default 0.5, 0.95"


# --- no defaults of its own ---------------------------------------------------


def test_tui_has_no_default_literals():
    """The TUI shows the API's defaults (keys()) and never a copy of one."""
    folder = Path(model.__file__).parent
    literals = (
        "2.75",
        "3600",
        "1.2,",
        '"bounding"',
        "1.3",
        '"lower", 0.0',
        '"bidirectional", True',
        'or "door"',
        '"door"',
        "0.15 m",  # boundary layer (0.15 alone is the debounce in s)
    )
    for path in sorted(folder.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for literal in literals:
            assert literal not in source, (path.name, literal)


def test_list_cells_take_the_api_defaults(monkeypatch):
    from jupedsim_network import scenario as scenario_module

    keys = scenario_module.keys

    def changed(element, kind=None):
        found = keys(element, kind)
        swap = {"kind": "opening", "bidirectional": False, "lower": 5.0}
        return tuple(
            dataclasses.replace(k, default=swap[k.name])
            if k.name in swap
            else k
            for k in found
        )

    monkeypatch.setattr(scenario_module, "keys", changed)
    assert model.row_cells("connections", {}) == (" → ", "opening", "", "")
    lognormal = {"distribution": "LogNormal", "mean": 1.0, "std": 1.0}
    assert model.distribution_words(lognormal).endswith(", ≥ 5.0")


# --- words and lists ---------------------------------------------------------


def test_distribution_words_and_rows():
    lognormal = {"distribution": "LogNormal", "mean": 120.0, "std": 60.0}
    assert (
        model.distribution_words(lognormal)
        == "LogNormal mean 120.0 std 60.0, ≥ 0.0"
    )
    bounded = {
        "distribution": "Normal",
        "mean": 1.0,
        "std": 0.1,
        "lower": None,
        "upper": 2.0,
    }
    assert model.distribution_words(bounded) == "Normal mean 1.0 std 0.1, ≤ 2.0"
    assert (
        model.distribution_words(
            {"distribution": "Fixed", "value": 3, "lower": None}
        )
        == "Fixed value 3"
    )
    assert model.distribution_words(5) == "5"
    doc = example("office-wing")
    assert model.row_cells("nodes", doc["nodes"][0]) == (
        "G1",
        "room",
        "9.0 × 7.0",
    )
    assert model.row_cells("connections", doc["connections"][0]) == (
        "G1 → GW",
        "door",
        "0.9",
        "",
    )
    assert model.row_cells("connections", {}) == (" → ", "door", "", "two-way")
    assert model.row_cells("populations", "x") == ("", "", "")
    assert model.counts(example()) == "3 nodes · 2 connections · 1 population"
    assert (
        model.counts({"nodes": "x"})
        == "0 nodes · 0 connections · 0 populations"
    )


def test_element_keys_follow_the_node_kind():
    names = [k.name for k in model.element_keys("nodes", {"kind": "stair"})]
    assert names[:4] == ["name", "kind", "riser", "tread"]
    assert [k.name for k in model.element_keys("nodes", {})] == ["name", "kind"]
    assert [k.name for k in model.element_keys("nodes", "x")] == [
        "name",
        "kind",
    ]


def test_references_and_rename():
    doc = example()
    assert model.references(doc, "office") == (1, 1)
    model.rename(doc, "office", "hall")
    assert doc["connections"][0]["source"] == "hall"
    assert doc["populations"][0]["node"] == "hall"
    assert model.references(doc, "office") == (0, 0)


def test_shown_path_and_command(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert model.shown_path(tmp_path / "a" / "s.json") == str(
        Path("a") / "s.json"
    )
    assert model.shown_path("/elsewhere/s.json") == "/elsewhere/s.json"
    assert (
        model.command("s.json", None, False)
        == "jupedsim-network run s.json -o s_results"
    )
    assert (
        model.command("my s.json", "out", True)
        == "jupedsim-network run 'my s.json' -o out --no-monte-carlo"
    )


# --- results helpers ---------------------------------------------------------


def test_results_rows_are_the_cli_strings():
    summary = {
        "monte_carlo": {
            "quantiles": [
                {"q": 0.5, "value": 383.25},
                {"q": 0.95, "value": None},
            ]
        },
        "links": [
            {
                "index": 0,
                "name": "a->b",
                "source": "a",
                "target": "b",
                "kind": "door",
                "capacity": 0.78,
            }
        ],
    }
    assert model.quantile_rows(summary) == [
        ("0.5", "383.25 s"),
        ("0.95", "> t_max"),
    ]
    assert model.link_rows(summary) == [("0", "a->b", "a → b", "door", "0.78")]
    occ = model.Occupancy.parse("time,a,b\n0.0,3,0\n0.5,2,1\n")
    assert occ.at(1) == {"a": "2", "b": "1"}
    assert (
        occ.line(1, "7")
        == "occupancy of the single run, seed 7: t = 0.5 s (step 1 of 1)"
    )


def test_notes_qualify_rset():
    for text in (model.TIME_NOTE, model.SPREAD_NOTE):
        if "RSET" in text:
            assert "Call it an RSET only with that qualification" in text


def test_notes_are_sentences_of_results_reporting():
    """Each sentence of the two notes is on using/results.md under
    "Reporting", once ``**`` and backticks are removed, so an edit of
    that section fails here."""
    page = (docpages.DOCS / "using" / "results.md").read_text()
    section = page.split("\n## Reporting\n", 1)[1].split("\n## ", 1)[0]
    plain = " ".join(section.replace("**", "").replace("`", "").split())
    for note in (model.TIME_NOTE, model.SPREAD_NOTE):
        for sentence in re.split(r"(?<=\.) ", note):
            assert sentence in plain, f"results.md does not say: {sentence}"


# --- recent files and browsing -------------------------------------------------


def test_recent_round_trip(tmp_path):
    recent = model.Recent(tmp_path / "cfg" / "recent.json")
    assert recent.files == [] and recent.theme is None
    recent.add("a.json", "2026-10-11T10:00", "complete")
    recent.add("b.json", "2026-10-11T10:01")
    recent.add("a.json", "2026-10-11T10:02")
    recent.set_theme("solarized-light")
    again = model.Recent(tmp_path / "cfg" / "recent.json")
    assert [Path(f["path"]).name for f in again.files] == ["a.json", "b.json"]
    assert again.files[0]["status"] == "complete"
    assert again.theme == "solarized-light"


def test_recent_ignores_a_bad_file(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = tmp_path / "jupedsim-network" / "recent.json"
    path.parent.mkdir()
    path.write_text('{"files": 3, "theme": "nope"}')
    recent = model.Recent()
    assert recent.path == path and recent.files == [] and recent.theme is None
    path.write_text("not json")
    assert model.Recent().files == []
    monkeypatch.delenv("XDG_CONFIG_HOME")
    assert model.config_dir() == Path.home() / ".config" / "jupedsim-network"


def test_browse_and_complete(tmp_path):
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenario.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("")
    (tmp_path / ".hidden.json").write_text("{}")
    folder, found = model.browse(f"{tmp_path}/")
    assert folder == tmp_path
    assert [(p.name, f) for p, f in found] == [
        ("scenario.json", True),
        ("scenarios", False),
    ]
    assert [p.name for p, _ in model.browse(f"{tmp_path}/.h")[1]] == [
        ".hidden.json"
    ]
    assert model.browse("") == (None, [])
    assert model.browse(f"{tmp_path}/missing/x") == (tmp_path / "missing", [])
    assert model.complete(f"{tmp_path}/scenario.") == str(
        tmp_path / "scenario.json"
    )
    assert (
        model.complete(f"{tmp_path}/scenarios")
        == str(tmp_path / "scenarios") + "/"
    )
    assert model.complete(f"{tmp_path}/sc") == str(tmp_path / "scenario")
    assert model.complete(f"{tmp_path}/zz") == f"{tmp_path}/zz"
    assert model.complete(f"{tmp_path}/") == str(tmp_path / "scenario")
    assert model.complete(f"{tmp_path}/scenarios/") == f"{tmp_path}/scenarios/"
    (tmp_path / "ab.json").write_text("{}")
    (tmp_path / "ac.json").write_text("{}")
    assert model.complete(f"{tmp_path}/a") == f"{tmp_path}/a"
    assert model.match_rank("sn", "scenario") == 2
    assert model.match_rank("x", "scenario") is None


# --- A11: route tree and ties --------------------------------------------------


def _routes(doc: dict) -> netview.Routes:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return netview.build(scenario_from_dict(doc).simulation)


def test_a11_split_ties_marks_the_tie_and_names_both_links():
    routes = _routes(tie_doc(split_ties=True))
    text = "\n".join(netview.lines(routes))
    assert "ties: split between L0 r->a, L1 r->b" in text
    assert "not on a route" not in text


def test_a11_without_split_ties_the_tree_shows_the_first_route():
    routes = _routes(tie_doc(split_ties=False))
    lines = netview.lines(routes)
    text = "\n".join(lines)
    assert "ties" not in text
    assert lines[-1] == "not on a route: L1 r->b"
    assert text.count("r  room") == 1


def test_route_tree_of_getting_started():
    doc = example()
    lines = netview.lines(_routes(doc), {"office": "● 120 agents"})
    assert lines == [
        "street  safe",
        "└─◀ L1 flight->street, stair, capacity 0.91 persons/s",
        "   flight  stair  10.8 m²",
        "   └─◀ L0 office->flight, door, capacity 0.78 persons/s",
        "      office  room  200 m²   ● 120 agents",
    ]


def test_route_tree_per_target_and_without_route():
    doc = example("office-wing")
    doc["populations"][0]["target"] = "side"
    doc["nodes"].append({"name": "island", "kind": "room", "area": 10.0})
    lines = netview.lines(_routes(doc))
    assert (
        "Routes to side:" in lines
        and "Routes to the nearest safe node:" in lines
    )
    assert "no route to safety: island" in lines


# --- U6: one engine job at a time --------------------------------------------


class Collect:
    def __init__(self):
        self.events = []
        self.done = threading.Event()

    def __call__(self, event):
        self.events.append(event)
        if not isinstance(event, jobs.Progress):
            self.done.set()


@pytest.fixture
def engine():
    eng = jobs.Engine(throttle=0)
    before = warnings.showwarning
    eng.start()
    yield eng
    eng.stop()
    assert warnings.showwarning is before


def wait_idle(eng, timeout=60.0):
    end = time.monotonic() + timeout
    while not eng.idle:
        assert time.monotonic() < end, "engine not idle"
        time.sleep(0.005)


def test_u6_jobs_never_overlap_and_warnings_reach_their_own_job(engine):
    spans, results, handlers = [], {}, []

    def make(i):
        def job(eng):
            start = time.monotonic()
            warned = []
            attempt(
                "x",
                lambda: (time.sleep(0.002), warnings.warn(f"job {i}")),
                warned,
            )
            handlers.append(warnings.showwarning == eng._log_foreign)
            spans.append((start, time.monotonic()))
            results[i] = warned
            return i

        return job

    def submit_many(offset):
        for i in range(offset, offset + 10):
            engine.submit(make(i), lambda e: None)

    threads = [
        threading.Thread(target=submit_many, args=(k * 10,)) for k in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wait_idle(engine)
    assert len(spans) == 40
    spans.sort()
    assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))
    assert results == {i: [f"x: job {i}"] for i in range(40)}
    assert all(handlers)


def test_u6_a_foreign_warning_during_a_job_is_logged_not_recorded(
    engine, capfd
):
    entered, warned_outside = threading.Event(), threading.Event()
    seen = {}

    def waiting(eng):
        warned = []

        def call():
            entered.set()
            assert warned_outside.wait(10)
            warnings.warn("own")

        attempt("monte_carlo", call, warned)
        seen["first"] = warned
        return None

    def later(eng):
        warned = []
        attempt("run", lambda: warnings.warn("later"), warned)
        seen["later"] = warned
        return None

    engine.submit(waiting, lambda e: None)
    assert entered.wait(10)
    warnings.warn("from the UI thread")
    warned_outside.set()
    engine.submit(later, lambda e: None)
    wait_idle(engine)
    assert seen == {"first": ["monte_carlo: own"], "later": ["run: later"]}
    assert engine.foreign == ["UserWarning: from the UI thread"]
    assert "from the UI thread" not in capfd.readouterr().err


def test_u6_validation_is_coalesced(engine):
    gate = threading.Event()
    got = Collect()
    engine.submit(lambda eng: gate.wait(10), lambda e: None)
    for gen in range(1, 6):
        engine.submit(jobs.validate(gen, example()), got, key="validate")
    gate.set()
    wait_idle(engine)
    assert [e.gen for e in got.events] == [5]
    assert got.events[0] == jobs.Validated(5)


def test_engine_reports_a_bug_as_failed(engine):
    got = Collect()

    def broken(eng):
        raise KeyError("boom")

    engine.submit(broken, got)
    wait_idle(engine)
    (event,) = got.events
    assert (
        isinstance(event, jobs.Failed) and "KeyError: 'boom'" in event.traceback
    )


def test_stop_drops_waiting_jobs():
    eng = jobs.Engine()
    eng.start()
    eng.start()  # a second start is a no-op
    gate, ran = threading.Event(), []
    eng.submit(lambda e: gate.wait(10), lambda e: None)
    eng.submit(lambda e: ran.append(1), lambda e: None)
    threading.Timer(0.05, gate.set).start()
    eng.stop()
    assert ran == [] and not eng.running
    jobs.Engine().stop()


def test_foreign_warnings_are_capped(engine):
    for i in range(jobs.MAX_FOREIGN + 5):
        engine._log_foreign(f"w{i}", UserWarning, "f", 1)
    assert len(engine.foreign) == jobs.MAX_FOREIGN
    assert engine.foreign[-1] == f"UserWarning: w{jobs.MAX_FOREIGN + 4}"


# --- jobs ----------------------------------------------------------------------


def call(job, eng=None):
    return job(eng or jobs.Engine())


def test_jobs_open_validate_and_save(tmp_path):
    path = tmp_path / "s.json"
    path.write_bytes(cli_init.example_bytes("office-wing"))
    opened = call(jobs.open_file(str(path)))
    assert opened.doc == example("office-wing") and opened.error == ""
    missing = call(jobs.open_file(str(tmp_path / "none.json")))
    assert missing.doc is None and missing.error.startswith("cannot read ")
    typo = example()
    typo["simulation"] = {"max_densty": 1}
    path.write_text(json.dumps(typo))
    bad = call(jobs.open_file(str(path)))
    assert (
        bad.doc is None and "simulation: unknown key 'max_densty'" in bad.error
    )
    example_doc = call(jobs.open_example("getting-started"))
    assert example_doc.path is None and example_doc.doc == example()
    saved = call(jobs.save(example(), str(tmp_path / "new.json")))
    assert saved.doc == example()
    assert (tmp_path / "new.json").read_bytes() == cli_init.example_bytes(
        "getting-started"
    )
    doc = example()
    doc["connections"][0]["width"] = -1.0
    refused = call(jobs.save(doc, str(tmp_path / "refused.json")))
    assert refused.doc is None and refused.error.startswith(
        "Cannot save: connections[0]"
    )
    assert not (tmp_path / "refused.json").exists()
    unwritable = call(jobs.save(example(), str(tmp_path / "no" / "dir.json")))
    assert unwritable.error.startswith("Cannot write ")
    assert call(jobs.validate(3, doc)).error_path == "connections[0]"


def test_check_job_of_a_missing_file(tmp_path):
    checked = call(jobs.check("none.json"))
    assert checked.status == 1 and checked.error_path is None
    assert checked.stream("stderr") == [
        "jupedsim-network check: error: cannot read none.json: No such file or directory"
    ]


def test_routes_of_a_network_without_routes_are_none(monkeypatch):
    sim = scenario_from_dict(example()).simulation

    def cycle(*args, **kwargs):
        raise RuntimeError("tied cycle")

    monkeypatch.setattr(type(sim.network), "route_table", cycle)
    assert jobs._routes(sim) is None


# --- A10: a cancelled run writes nothing ------------------------------------------


def _old_results(folder: Path, scenario_path: Path) -> None:
    assert (
        cli.main(
            ["run", str(scenario_path), "-o", str(folder), "--no-monte-carlo"]
        )
        == 0
    )


def _files(folder: Path) -> dict:
    if not folder.exists():
        return {}
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


@pytest.mark.parametrize(
    "existing", [True, False], ids=["old-results", "no-folder"]
)
@pytest.mark.parametrize("when", ["monte-carlo", "single-run", "single-only"])
def test_a10_cancel_writes_nothing(
    engine, tmp_path, monkeypatch, existing, when
):
    monkeypatch.chdir(tmp_path)
    doc = example()
    doc["monte_carlo"]["runs"] = 6
    Path("s.json").write_text(json.dumps(doc))
    out = tmp_path / "s_results"
    if existing:
        _old_results(out, Path("s.json"))
    before = _files(out)
    got = Collect()

    def post(event):
        got(event)
        if (
            when == "monte-carlo"
            and isinstance(event, jobs.Progress)
            and event.done == 2
        ):
            engine.cancel()

    if when != "monte-carlo":
        original = NetworkSimulation.run

        @functools.wraps(original)  # the loader reads the signature
        def cancelling_run(self, *args, **kwargs):
            engine.cancel()
            return original(self, *args, **kwargs)

        monkeypatch.setattr(NetworkSimulation, "run", cancelling_run)
    single = when == "single-only"
    engine.submit(jobs.run("s.json", "s_results", single, post), post)
    wait_idle(engine)
    finished = got.events[-1]
    assert isinstance(finished, jobs.RunFinished)
    assert (
        finished.status is None
        and finished.files == {}
        and finished.stdout == ()
    )
    assert _files(out) == before
    assert out.exists() == existing
    if when == "monte-carlo":
        assert (finished.phase, finished.done, finished.runs) == (
            "monte carlo",
            2,
            6,
        )
    else:
        assert (finished.phase, finished.done) == ("single run", 0)


@pytest.mark.parametrize(
    "existing", [True, False], ids=["old-results", "no-folder"]
)
def test_a10_cancel_while_the_run_waits_in_the_queue_writes_nothing(
    engine, tmp_path, monkeypatch, existing
):
    """QA2-B1: the run is queued behind another job (a check's trial run)."""
    monkeypatch.chdir(tmp_path)
    doc = example()
    doc["monte_carlo"]["runs"] = 5
    Path("s.json").write_text(json.dumps(doc))
    out = tmp_path / "s_results"
    if existing:
        _old_results(out, Path("s.json"))
    before = _files(out)
    gate, got = threading.Event(), Collect()
    engine.submit(lambda eng: gate.wait(10), lambda e: None)
    engine.submit(jobs.run("s.json", "s_results", False, got), got)
    engine.cancel()  # confirmed before the run job starts
    gate.set()
    wait_idle(engine)
    finished = got.events[-1]
    assert isinstance(finished, jobs.RunFinished) and finished.status is None
    assert _files(out) == before and out.exists() == existing


def test_a10_a_cancel_never_reaches_a_later_run(engine, tmp_path, monkeypatch):
    """QA2-B1: each run has its own cancel; an old one does not carry over."""
    monkeypatch.chdir(tmp_path)
    doc = example()
    doc["monte_carlo"]["runs"] = 3
    Path("s.json").write_text(json.dumps(doc))
    engine.cancel()  # nothing to cancel yet
    first = Collect()
    engine.submit(jobs.run("s.json", "a", False, first), first)
    wait_idle(engine)
    assert first.events[-1].status == 0
    gate, second = threading.Event(), Collect()
    engine.submit(lambda eng: gate.wait(10), lambda e: None)
    engine.submit(jobs.run("s.json", "b", False, second), second)
    engine.cancel()
    gate.set()
    wait_idle(engine)
    assert second.events[-1].status is None and not Path("b").exists()
    engine.cancel()  # late: the second run has ended
    third = Collect()
    engine.submit(jobs.run("s.json", "c", False, third), third)
    wait_idle(engine)
    assert third.events[-1].status == 0
    assert sorted(p.name for p in Path("c").iterdir()) == sorted(
        [
            "summary.json",
            "agents.csv",
            "link_flow.csv",
            "occupancy.csv",
            "runs.csv",
        ]
    )


def test_run_job_progress_and_errors(engine, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    doc = example()
    doc["monte_carlo"]["runs"] = 3
    Path("s.json").write_text(json.dumps(doc))
    got = Collect()
    engine.submit(jobs.run("s.json", "out", False, got), got)
    wait_idle(engine)
    progress = [
        (e.phase, e.done, e.runs)
        for e in got.events
        if isinstance(e, jobs.Progress)
    ]
    assert progress == [
        ("single run", 0, 3),
        ("monte carlo", 1, 3),
        ("monte carlo", 2, 3),
        ("monte carlo", 3, 3),
    ]
    finished = got.events[-1]
    assert finished.status == 0 and list(finished.files) == [
        "summary.json",
        "agents.csv",
        "link_flow.csv",
        "occupancy.csv",
        "runs.csv",
    ]
    # Errors: the file, the API, the write.
    got = Collect()
    engine.submit(jobs.run("none.json", "out", False, got), got)
    doc["populations"][0]["speed"] = 0
    Path("bad.json").write_text(json.dumps(doc))
    engine.submit(jobs.run("bad.json", "out", False, got), got)
    Path("blocker").write_text("")
    engine.submit(jobs.run("s.json", "blocker", True, got), got)
    wait_idle(engine)
    missing, api, write = [
        e for e in got.events if isinstance(e, jobs.RunFinished)
    ]
    assert missing.status == 1 and missing.stderr[0].startswith(
        "jupedsim-network run: error: cannot read none.json"
    )
    assert api.status == 1 and api.error_path == "populations[0]"
    assert api.stderr == (
        "jupedsim-network run: error: bad.json: populations[0]: Agent speeds must be positive.",
    )
    assert write.status == 1 and write.stderr[-1].startswith(
        "jupedsim-network run: error: cannot write blocker"
    )


def test_throttled_progress_always_posts_the_last(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    eng = jobs.Engine(throttle=3600.0)
    got, state = Collect(), {"done": 0, "phase": "single run", "posted": -1.0e9}
    for done in range(1, 6):
        jobs._progress(eng.cancel_event, eng, got, state, done, 5)
    assert [e.done for e in got.events] == [1, 5]
    eng.cancel()
    with pytest.raises(jobs.RunCancelled):
        jobs._progress(eng.cancel_event, eng, got, state, 6, 5)


# --- the missing tui extra (runs on the leg without textual too) ----------------

HINT = (
    "jupedsim-network tui: error: the terminal UI needs the tui extra "
    "(missing module 'textual'). Install it with: pip install "
    '"jupedsim-network[tui]"'
)
# Without textual installed, the hint is tested as users get it; with it,
# its absence is simulated.
_HIDE = (
    ""
    if importlib.util.find_spec("textual") is None
    else ("sys.modules['textual'] = None\n")
)


def test_missing_extra_gives_the_install_hint():
    code = f"import sys\n{_HIDE}from jupedsim_network.cli import main\nsys.exit(main(['tui']))\n"
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True
    )
    assert out.returncode == 1
    assert out.stderr.strip() == HINT


def test_missing_extra_in_process(monkeypatch, capsys):
    from jupedsim_network.tui import launch

    if _HIDE:
        monkeypatch.setitem(sys.modules, "textual", None)
        monkeypatch.delitem(
            sys.modules, "jupedsim_network.tui.app", raising=False
        )
    assert launch.main() == 1
    assert capsys.readouterr().err.strip() == HINT
