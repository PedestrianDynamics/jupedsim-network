# SPDX-License-Identifier: LGPL-3.0-or-later
"""Scenario files build the same simulation as the Python API, byte for byte.

The Python side is not written out again where the docs already have it:
getting-started runs the first code block of its page, the office wing
imports ``examples/office_wing.py``. ``tests/data/full_keys.json`` sets
every key of the format; its Python twin is ``_full_keys_python``.
"""

import copy
import dataclasses
import functools
import importlib.util
import inspect
import json
import re
import threading
import warnings
from pathlib import Path

import numpy as np
import pytest

from jupedsim_network import (
    Fixed,
    LogNormal,
    Network,
    NetworkSimulation,
    Normal,
    Population,
    Scenario,
    ScenarioError,
    Triangular,
    Uniform,
    Weibull,
    load_scenario,
    save_scenario,
)
from jupedsim_network import scenario as scenario_module
from jupedsim_network.scenario import dumps, scenario_from_dict

ROOT = Path(__file__).resolve().parents[1]
PACKAGED = ROOT / "src" / "jupedsim_network" / "scenarios"
GETTING_STARTED = PACKAGED / "getting_started.json"
OFFICE_WING = PACKAGED / "office_wing.json"
FULL_KEYS = ROOT / "tests" / "data" / "full_keys.json"

RESULT_ARRAYS = (
    "exit_times",
    "pre_movement_times",
    "times",
    "node_occupancy",
    "link_flow",
)


def _getting_started_python() -> NetworkSimulation:
    """The page's first code block, up to the single run."""
    page = ROOT / "site" / "content" / "docs" / "getting-started.md"
    block = re.search(r"^```python\n(.*?)^```", page.read_text(), re.S | re.M)
    code = block.group(1).split("result = simulation.run(seed=1)")[0]
    namespace: dict = {}
    exec(code, namespace)
    return namespace["simulation"]


def _office_wing_module():
    spec = importlib.util.spec_from_file_location(
        "office_wing", ROOT / "examples" / "office_wing.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _full_keys_python() -> NetworkSimulation:
    net = Network()
    net.add_room("west", area=60.0)
    net.add_room("east", length=10.0, width=6.0)
    net.add_room("hall", area=40.0)
    net.add_stair("upper", riser=0.17, tread=0.29, area=12.0)
    net.add_stair("lower", riser=0.17, tread=0.29, length=4.0, width=2.5)
    net.add_safe("yard")
    net.add_safe("street")
    net.connect(
        "west",
        "hall",
        width=1.0,
        kind="opening",
        length=6.0,
        specific_flow=1.2,
        boundary_layer=0.05,
        merge_weight=2.0,
        bidirectional=True,
        name="west opening",
    )
    net.connect("east", "hall", width=0.9, length=5.0)
    net.connect("hall", "yard", width=1.2, length=4.0, bidirectional=False)
    net.connect(
        "hall",
        "yard",
        width=0.8,
        kind="door",
        length=4.0,
        bidirectional=False,
        name="narrow yard door",
    )
    for source, target, length in (
        ("east", "upper", 3.0),
        ("upper", "lower", 5.0),
        ("lower", "street", 5.0),
    ):
        net.connect(
            source,
            target,
            width=1.1,
            kind="stair",
            length=length,
            bidirectional=False,
        )
    populations = [
        Population(
            "west",
            Uniform(minimum=20, maximum=30),
            speed=Normal(mean=1.3, std=0.2, lower=None, upper=2.0),
            pre_movement=Weibull(alpha=30.0, beta=1.5),
            start_distance=Triangular(minimum=0.0, mode=2.0, maximum=5.0),
            area_factor=0.8,
            target="yard",
        ),
        Population(
            "east",
            15,
            speed=LogNormal(mean=1.1, std=0.2, lower=0.5),
            pre_movement=Fixed(value=10.0),
            start_distance=1.5,
            area_factor=1.2,
            target="yard",
        ),
        Population("west", 10, speed=1.0, pre_movement=5.0, target="street"),
    ]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # split_ties=False at a tie
        return NetworkSimulation(
            net,
            populations,
            dt=0.25,
            t_max=1200.0,
            max_density=3.0,
            supply_reduction=False,
            split_ties=False,
            counterflow="estimate",
        )


CASES = {
    "getting_started": (GETTING_STARTED, _getting_started_python),
    "office_wing": (OFFICE_WING, lambda: _office_wing_module().simulation()),
    "full_keys": (FULL_KEYS, _full_keys_python),
}


def _same_simulation(a: NetworkSimulation, b: NetworkSimulation) -> None:
    assert a.network.nodes == b.network.nodes
    assert a.network.links == b.network.links
    assert a.network._reverse == b.network._reverse
    assert a.populations == b.populations
    for name in (
        "dt",
        "t_max",
        "max_density",
        "supply_reduction",
        "split_ties",
        "counterflow",
    ):
        assert getattr(a, name) == getattr(b, name), name


def _same_run(a, b) -> None:
    for name in RESULT_ARRAYS:
        assert getattr(a, name).tobytes() == getattr(b, name).tobytes(), name
    assert a.node_names == b.node_names
    assert a.link_names == b.link_names


# Round trip


@pytest.mark.parametrize("name", CASES)
def test_json_builds_the_python_simulation(name):
    path, python = CASES[name]
    _same_simulation(load_scenario(path).simulation, python())


@pytest.mark.parametrize("name", CASES)
def test_json_run_is_byte_identical(name):
    path, python = CASES[name]
    scenario = load_scenario(path)
    seed = scenario.run_seed
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _same_run(scenario.simulation.run(seed), python().run(seed))
        a = scenario.simulation.run_many(5, seed=1).evacuation_times
        b = python().run_many(5, seed=1).evacuation_times
    assert a.tobytes() == b.tobytes()


def test_office_wing_stair_literals_are_the_script_values():
    ow = _office_wing_module()
    data = json.loads(OFFICE_WING.read_text())
    (stair,) = [n for n in data["nodes"] if n["kind"] == "stair"]
    (link,) = [c for c in data["connections"] if c["source"] == "stair"]
    assert stair["area"] == ow.STAIR_AREA
    assert link["length"] == ow.STAIR_LENGTH


@pytest.mark.parametrize("path", [GETTING_STARTED, OFFICE_WING, FULL_KEYS])
def test_save_reproduces_the_file(path, tmp_path):
    scenario = load_scenario(path)
    out = tmp_path / "saved.json"
    save_scenario(scenario, out)
    assert out.read_bytes() == path.read_bytes()
    assert load_scenario(out).data == scenario.data


def test_full_keys_sets_every_key():
    """The fixture sets every key the format allows."""
    data = json.loads(FULL_KEYS.read_text())
    assert set(data) == set(scenario_module._TOP)
    kinds = {"room", "stair", "safe"}
    assert {n["kind"] for n in data["nodes"]} == kinds
    for kind in kinds:
        annotations, _ = scenario_module._spec(
            scenario_module._NODE_METHODS[kind]
        )
        given = set().union(*(n for n in data["nodes"] if n["kind"] == kind))
        assert given == set(annotations) | {"kind"}, kind
    sections = scenario_module._sections()
    connect, _ = scenario_module._spec(Network.connect)
    assert set().union(*data["connections"]) == set(connect)
    population, _ = scenario_module._spec(Population)
    assert set().union(*data["populations"]) == set(population)
    for name in ("simulation", "run", "monte_carlo"):
        assert set(data[name]) == set(sections[name][0]), name
    used = {
        value["distribution"]
        for pop in data["populations"]
        for value in pop.values()
        if isinstance(value, dict)
    }
    assert used == set(scenario_module._DISTRIBUTIONS)


# Order


def _exit_times(data) -> bytes:
    sim = scenario_from_dict(data).simulation
    return sim.run(seed=7).exit_times.tobytes()


def test_population_order_changes_the_result():
    data = json.loads(FULL_KEYS.read_text())
    swapped = copy.deepcopy(data)
    pops = swapped["populations"]
    pops[0], pops[2] = pops[2], pops[0]
    assert [
        p.node for p in scenario_from_dict(swapped).simulation.populations
    ] == [p["node"] for p in pops]
    assert _exit_times(swapped) != _exit_times(data)


def test_order_of_tied_connections_changes_the_route():
    """With split_ties false the first tied link in file order is taken."""
    data = json.loads(FULL_KEYS.read_text())
    swapped = copy.deepcopy(data)
    links = swapped["connections"]
    links[2], links[3] = links[3], links[2]
    sim = scenario_from_dict(swapped).simulation
    assert sim.network.links[4].name == "narrow yard door"
    assert _exit_times(swapped) != _exit_times(data)


# Defaults


def _minimal():
    return {
        "format_version": 1,
        "nodes": [
            {"name": "room", "kind": "room", "area": 50.0},
            {"name": "out", "kind": "safe"},
        ],
        "connections": [{"source": "room", "target": "out", "width": 1.0}],
        "populations": [{"node": "room", "count": 30}],
    }


def test_omitted_keys_take_the_api_defaults():
    net = Network()
    net.add_room("room", area=50.0)
    net.add_safe("out")
    net.connect("room", "out", width=1.0)
    python = NetworkSimulation(net, [Population("room", 30)])
    loaded = scenario_from_dict(_minimal()).simulation
    _same_simulation(loaded, python)
    _same_run(loaded.run(seed=3), python.run(seed=3))


@pytest.mark.parametrize(
    "fn, section, skip",
    [
        (NetworkSimulation, "simulation", ("self", "network", "populations")),
        (NetworkSimulation.run, "run", ("self", "record")),
        (NetworkSimulation.run_many, "monte_carlo", ("self", "progress")),
    ],
)
def test_section_keys_are_the_api_arguments(fn, section, skip):
    """Only the named exceptions differ from the signatures."""
    names = set(inspect.signature(fn).parameters) - set(skip)
    keys = set(scenario_module._sections()[section][0])
    assert keys == names | set(scenario_module.FILE_ONLY.get(section, ()))


def test_loader_has_no_default_literals():
    """Defaults live only in the API: the loader never assigns one."""
    source = inspect.getsource(scenario_module)
    for default in ("2.75", "3600", "1.2,", '"bounding"', "1.3"):
        assert default not in source, default


def test_lower_omitted_is_zero_and_null_is_no_bound():
    data = _minimal()
    data["populations"][0]["speed"] = {
        "distribution": "Normal",
        "mean": 1.2,
        "std": 0.1,
    }
    assert scenario_from_dict(data).simulation.populations[0].speed.lower == 0.0
    data["populations"][0]["speed"]["lower"] = None
    assert (
        scenario_from_dict(data).simulation.populations[0].speed.lower is None
    )


def test_plain_numbers_stay_numbers():
    pop = scenario_from_dict(_minimal()).simulation.populations[0]
    assert pop.count == 30 and type(pop.count) is int


# Structural errors


def _edit(change):
    data = json.loads(GETTING_STARTED.read_text())
    change(data)
    return data


def _nested(depth: int):
    value: list = []
    for _ in range(depth):
        value = [value]
    return value


def _set(path, value):
    def change(data):
        *head, last = path
        target = data
        for key in head:
            target = target[key]
        target[last] = value

    return change


STRUCTURAL = [
    (_set(["format_version"], 2), "format_version: 2 is not supported"),
    (_set(["format_version"], True), "format_version: true is not supported"),
    (
        lambda d: d.pop("format_version"),
        "missing required key 'format_version'",
    ),
    (
        lambda d: d["nodes"][1].pop("riser"),
        "nodes[1]: missing required key 'riser' for kind 'stair'",
    ),
    (
        _set(["nodes", 0, "kind"], "corridor"),
        "nodes[0].kind: must be one of 'room', 'stair', 'safe'",
    ),
    (
        _set(["simulation", "max_densty"], 3.0),
        "simulation: unknown key 'max_densty'; valid keys: counterflow, dt,",
    ),
    (
        _set(["connections", 0, "width"], True),
        "connections[0].width: expected a number, got true",
    ),
    (
        _set(["populations", 0, "count"], "120"),
        'populations[0].count: expected a distribution object or a number, got the string "120"',
    ),
    (
        _set(
            ["populations", 0, "pre_movement", "distribution"], "Distribution"
        ),
        "populations[0].pre_movement.distribution: must be one of Fixed,",
    ),
    (
        lambda d: d["populations"][0]["pre_movement"].pop("std"),
        "populations[0].pre_movement: missing required key 'std' for LogNormal",
    ),
    (_set(["populations"], []), "populations: at least one population"),
    (
        _set(["run", "seed"], True),
        "run.seed: expected an integer >= 0 or null, got true",
    ),
    (
        _set(["run", "seed"], -1),
        "run.seed: expected an integer >= 0 or null, got -1",
    ),
    (
        _set(["run", "seed"], 1.0),
        "run.seed: expected an integer >= 0 or null, got 1.0",
    ),
    (
        _set(["monte_carlo", "quantiles"], []),
        "monte_carlo.quantiles: expected at least one value",
    ),
    (
        _set(["simulation", "dt"], float("inf")),
        "simulation.dt: non-finite number inf",
    ),
    (
        _set(["nodes", 0, "kind"], ["room"]),
        "nodes[0].kind: expected a string, got an array",
    ),
    (
        _set(["nodes", 0, "kind"], {"room": 1}),
        "nodes[0].kind: expected a string, got an object",
    ),
    (
        _set(["populations", 0, "pre_movement", "distribution"], ["Normal"]),
        "populations[0].pre_movement.distribution: expected a string, "
        "got an array",
    ),
    (
        _set(["populations", 0, "pre_movement", "distribution"], {}),
        "populations[0].pre_movement.distribution: expected a string, "
        "got an object",
    ),
    (
        _set(["simulation", "t_max"], 10**400),
        "simulation.t_max: integer of about 401 digits is too large",
    ),
    (
        _set(["run", "seed"], 10**400),
        "run.seed: integer of about 401 digits is too large",
    ),
    (
        _set(["description"], _nested(100)),
        "description" + "[0]" * 64 + ": nested deeper than 64 levels",
    ),
    (
        _set(["monte_carlo", "runs"], 0),
        "monte_carlo.runs: must be >= 1, got 0",
    ),
    (
        _set(["monte_carlo", "quantiles"], [0.5, 1.5]),
        "monte_carlo.quantiles[1]: must be in [0, 1], got 1.5",
    ),
    (
        _set(["monte_carlo", "quantiles"], [-0.1]),
        "monte_carlo.quantiles[0]: must be in [0, 1], got -0.1",
    ),
]


@pytest.mark.parametrize("change, expected", STRUCTURAL)
def test_structural_errors_name_the_path(change, expected):
    with pytest.raises(ScenarioError) as info:
        scenario_from_dict(_edit(change))
    assert str(info.value).startswith(expected), str(info.value)


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            '{"format_version": 1, "run": {"seed": 1e999}}',
            "run.seed: non-finite",
        ),
        ('{"format_version": 1, "x": NaN}', "x: non-finite number nan"),
        ('{"format_version": 1, "x": -Infinity}', "x: non-finite number -inf"),
        ('{"format_version": 1, "format_version": 1}', "duplicate key"),
        ('{"format_version": 1,}', "invalid JSON: "),
        ("[1]", "a scenario must be a JSON object"),
    ],
)
def test_file_level_errors(tmp_path, text, expected):
    path = tmp_path / "bad.json"
    path.write_text(text)
    with pytest.raises(ScenarioError, match=re.escape(expected)):
        load_scenario(path)


_GOOD = GETTING_STARTED.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "raw, expected",
    [
        (
            _GOOD.replace("\u00b2", "²").encode("cp1252"),
            "not UTF-8 text: byte 0xb2 at position",
        ),
        (_GOOD.encode("utf-16"), "not UTF-8 text: byte 0xff at position 0"),
        (
            b'{"format_version": 1, "x": ' + b"9" * 5000 + b"}",
            "for integer string conversion",  # wording differs by version
        ),
        *(
            (
                b'{"format_version": 1, "x": '
                + b"[" * depth
                + b"]" * depth
                + b"}",
                "nested deeper than 64 levels",
            )
            for depth in (900, 1500, 50_000)
        ),
        *(
            (
                b'{"format_version": 1, "x": '
                + b'{"a": ' * depth
                + b"1"
                + b"}" * depth
                + b"}",
                "nested deeper than 64 levels",
            )
            for depth in (900, 50_000)
        ),
    ],
    ids=[
        "cp1252",
        "utf16",
        "5000-digits",
        "array-900",
        "array-1500",
        "array-50000",
        "object-900",
        "object-50000",
    ],
)
def test_unreadable_files_are_scenario_errors(tmp_path, raw, expected):
    """Encoding, digit-limit and depth errors are ScenarioErrors, not crashes."""
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(ScenarioError, match=re.escape(expected)):
        load_scenario(path)


def test_numbers_that_fit_a_float_are_accepted():
    data = _edit(_set(["simulation", "t_max"], 10**300))
    assert scenario_from_dict(data).simulation.t_max == 10**300


# API errors


def _api_message(call) -> str:
    with pytest.raises(Exception) as info:
        call()
    return str(info.value)


def _gs_net():
    net = Network()
    net.add_room("office", area=200.0)
    net.add_stair("flight", area=10.8, riser=0.18, tread=0.28)
    net.add_safe("street")
    return net


API = [
    (
        _set(["connections", 0, "width"], -1),
        "connections[0]",
        lambda: _gs_net().connect("office", "flight", width=-1),
    ),
    (
        _set(["connections", 0, "target"], "attic"),
        "connections[0]",
        lambda: _gs_net().connect("office", "attic", width=0.9),
    ),
    (
        _set(["simulation", "max_density"], 4),
        "simulation",
        lambda: NetworkSimulation(Network(), [], max_density=4),
    ),
    (
        _set(["simulation", "counterflow"], "free"),
        "simulation",
        lambda: NetworkSimulation(Network(), [], counterflow="free"),
    ),
    (
        _set(["populations", 0, "node"], "street"),
        "populations[0]",
        lambda: _sim_from(Population("street", 1)),
    ),
]


def _sim_from(pop):
    net = _gs_net()
    net.connect("office", "flight", width=0.9)
    net.connect("flight", "street", width=1.2, kind="stair")
    return NetworkSimulation(net, [pop])


@pytest.mark.parametrize("change, path, call", API)
def test_api_errors_keep_the_api_message(change, path, call):
    with pytest.raises(ScenarioError) as info:
        scenario_from_dict(_edit(change))
    assert info.value.path == path
    assert info.value.message == _api_message(call)


def test_population_errors_name_the_population():
    data = _edit(lambda d: None)
    data["populations"].append({"node": "street", "count": 1})
    with pytest.raises(ScenarioError) as info:
        scenario_from_dict(data)
    assert info.value.path == "populations[1]"


@pytest.mark.parametrize(
    "pre_movement, expected",
    [
        (
            {"distribution": "LogNormal", "mean": 0, "std": 60.0},
            "cannot sample LogNormal(lower=0.0, upper=None, mean=0, std=60.0): "
            "float division by zero",
        ),
        (
            {"distribution": "Normal", "mean": 60.0, "std": -1.0},
            "cannot sample Normal(lower=0.0, upper=None, mean=60.0, "
            "std=-1.0): scale < 0",
        ),
        (
            {"distribution": "Uniform", "minimum": 9.0, "maximum": 1.0},
            "cannot sample Uniform(lower=0.0, upper=None, minimum=9.0, "
            "maximum=1.0): high - low < 0",
        ),
    ],
)
def test_sampling_errors_name_the_population_at_load(pre_movement, expected):
    data = _edit(lambda d: None)
    data["populations"].append(
        {"node": "office", "count": 5, "pre_movement": pre_movement}
    )
    with pytest.raises(ScenarioError) as info:
        scenario_from_dict(data)
    assert info.value.path == "populations[1].pre_movement"
    assert info.value.message == expected


@pytest.mark.parametrize(
    "change, message",
    [
        (
            {
                "speed": {
                    "distribution": "Normal",
                    "mean": -5.0,
                    "std": 0.1,
                    "lower": None,
                }
            },
            "Agent speeds must be positive.",
        ),
        ({"speed": 0.0}, "Agent speeds must be positive."),
        ({"count": 10**30}, "Maximum allowed dimension exceeded"),
    ],
    ids=["sampled-speed", "plain-speed", "count"],
)
def test_spawn_errors_name_the_population(change, message):
    """Raised only by run(); the API's "population 1: ..." becomes the path."""
    data = _edit(lambda d: None)
    data["populations"].append({"node": "office", "count": 5, **change})
    sim = scenario_from_dict(data).simulation
    with pytest.raises(
        ValueError, match=f"^population 1: {re.escape(message)}"
    ):
        sim.run(1)
    with pytest.raises(ScenarioError) as info:
        scenario_module.attempt("run", lambda: sim.run(1), None)
    assert info.value.path == "populations[1]"
    assert info.value.message == message


# Warnings


def test_warnings_carry_the_path_and_appear_once():
    data = _edit(_set(["nodes", 1, "riser"], 0.20))
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # none may escape
        scenario = scenario_from_dict(data)
    assert len(scenario.warnings) == 1
    assert scenario.warnings[0].startswith("nodes[1]: Stair 'flight'")


def test_tie_warning_once_per_population():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scenario = load_scenario(FULL_KEYS)
    assert [w.split(":")[0] for w in scenario.warnings] == [
        "populations[0]",
        "populations[1]",
    ]


def test_scenario_is_public():
    import jupedsim_network

    for name in ("Scenario", "ScenarioError", "load_scenario", "save_scenario"):
        assert name in jupedsim_network.__all__
    assert isinstance(load_scenario(GETTING_STARTED), Scenario)


def test_dumps_rejects_nan():
    with pytest.raises(ValueError):
        dumps({"x": np.nan})


# Export from Python


@pytest.mark.parametrize("name", CASES)
def test_export_load_run_is_byte_identical(name, tmp_path):
    """Built in Python, saved, loaded: the same simulation and results."""
    _, python = CASES[name]
    sim = python()
    path = tmp_path / "exported.json"
    save_scenario(Scenario.from_simulation(sim, seed=1), path)
    loaded = load_scenario(path).simulation
    _same_simulation(loaded, sim)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        _same_run(loaded.run(1), sim.run(1))
        a = loaded.run_many(5, seed=1).evacuation_times
        b = sim.run_many(5, seed=1).evacuation_times
    assert a.tobytes() == b.tobytes()


def test_export_keeps_inputs_order_and_settings():
    sim = _full_keys_python()
    data = Scenario.from_simulation(
        sim,
        seed=7,
        monte_carlo={"runs": 20, "seed": 11, "quantiles": [0.1, 0.5, 0.9]},
        description="exported",
    ).data
    fixture = json.loads(FULL_KEYS.read_text())
    assert [n["name"] for n in data["nodes"]] == [
        n["name"] for n in fixture["nodes"]
    ]
    first = data["connections"][0]
    assert first == {
        k: v
        for k, v in fixture["connections"][0].items()
        if k != "bidirectional"
    }
    assert all("capacity" not in c for c in data["connections"])
    assert data["simulation"] == fixture["simulation"]
    assert data["run"] == fixture["run"]
    assert data["monte_carlo"] == fixture["monte_carlo"]
    assert data["populations"][0] == fixture["populations"][0]


def test_save_scenario_takes_a_simulation(tmp_path):
    sim = _getting_started_python()
    path = tmp_path / "gs.json"
    save_scenario(sim, path)
    loaded = load_scenario(path)
    assert "run" not in loaded.data and "monte_carlo" not in loaded.data
    _same_run(loaded.simulation.run(1), sim.run(1))


class _Custom(Uniform):
    """A user-defined distribution the file format cannot express."""


def _draw_twice(self, rng, size):
    return 2.0 * rng.normal(self.mean, self.std, size)


# A user subclass that has the name of a built-in but draws differently.
_SameName = type("Normal", (Normal,), {"_draw": _draw_twice})


@pytest.mark.parametrize(
    "speed, expected",
    [
        (
            _Custom(minimum=1.0, maximum=1.4),
            "populations[0].speed: _Custom is not",
        ),
        (
            _SameName(mean=1.3, std=0.1),
            "populations[0].speed: Normal is not a distribution of the file",
        ),
        (object(), "populations[0].speed: object <object"),
    ],
)
def test_export_refuses_what_the_format_cannot_hold(speed, expected):
    net = _gs_net()
    net.connect("office", "flight", width=0.9)
    net.connect("flight", "street", width=1.2, kind="stair")
    sim = NetworkSimulation(net, [Population("office", 10, speed=speed)])
    with pytest.raises(ScenarioError) as info:
        Scenario.from_simulation(sim)
    assert str(info.value).startswith(expected), str(info.value)


def test_non_finite_speed_is_rejected_at_construction():
    # Was refused by the exporter only; now no Population holds inf (#53).
    with pytest.raises(
        ValueError, match="speed: value must be finite, got inf"
    ):
        Population("office", 10, speed=float("inf"))


# Input checks (issue #53): the error is located at the key of the entry


def _no_area(data):
    node = data["nodes"][0]
    del node["area"]
    node.update(length=-5.0, width=-4.0)


REJECTED = [
    (
        _set(["populations", 0, "area_factor"], -1.0),
        "populations[0].area_factor",
        "must be positive, got -1.0.",
    ),
    (
        _set(["populations", 0, "pre_movement"], -10),
        "populations[0].pre_movement",
        "Fixed value -10.0 lies outside [lower, upper] = [0.0, None].",
    ),
    (
        _set(["populations", 0, "count"], -5),
        "populations[0].count",
        "Fixed value -5.0 lies outside [lower, upper] = [0.0, None].",
    ),
    (
        _set(
            ["populations", 0, "pre_movement"],
            {"distribution": "Fixed", "value": 10, "upper": 3},
        ),
        "populations[0].pre_movement",
        "Fixed value 10 lies outside [lower, upper] = [0.0, 3].",
    ),
    (
        _set(
            ["populations", 0, "pre_movement"],
            {
                "distribution": "Normal",
                "mean": 5,
                "std": 1,
                "lower": 2,
                "upper": 1,
            },
        ),
        "populations[0].pre_movement",
        "lower 2 is greater than upper 1.",
    ),
    (
        _set(
            ["populations", 0, "pre_movement"],
            {"distribution": "Weibull", "alpha": -2, "beta": 3},
        ),
        "populations[0].pre_movement",
        "Weibull alpha and beta must be positive, got -2, 3.",
    ),
    (
        _set(
            ["populations", 0, "pre_movement"],
            {"distribution": "LogNormal", "mean": 120.0, "std": -60.0},
        ),
        "populations[0].pre_movement",
        "std must be >= 0, got -60.0.",
    ),
    (
        _set(
            ["populations", 0, "start_distance"],
            {"distribution": "Normal", "mean": 5.0, "std": 3.0, "lower": None},
        ),
        "populations[0].start_distance",
        "must have lower >= 0, got lower=None.",
    ),
    (
        _set(["connections", 0, "boundary_layer"], -0.5),
        "connections[0].boundary_layer",
        "must be >= 0 m, got -0.5.",
    ),
    (
        _set(["nodes", 0, "length"], 5.0),
        "nodes[0]",
        "Give either area or length and width, not both.",
    ),
    (_no_area, "nodes[0]", "Node area must be positive, got length -5.0."),
    (
        lambda d: d["nodes"][1].update(riser=180, tread=280),
        "nodes[1]",
        "riser and tread are in m and must be below 1 m; got riser 180, "
        "tread 280 (mm?).",
    ),
    (
        _set(["simulation", "dt"], 1e-300),
        "simulation",
        "dt must be at least 1e-6 s, got 1e-300.",
    ),
]


@pytest.mark.parametrize("change, path, message", REJECTED)
def test_input_checks_are_located_at_the_key(change, path, message):
    with pytest.raises(ScenarioError) as info:
        scenario_from_dict(_edit(change))
    assert (info.value.path, info.value.message) == (path, message)


def test_settings_warning_is_reported_once_at_simulation():
    data = _edit(_set(["simulation", "max_density"], 1.5))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        scenario = scenario_from_dict(data)
    assert len(scenario.warnings) == 1
    assert scenario.warnings[0].startswith(
        "simulation: max_density 1.5 is at or below the peak-flow density"
    )
    assert scenario.simulation.run(1).evacuation_time == 323.0


# Run seam of the terminal UI (issue #47)


def test_scenario_from_dict_is_public():
    import jupedsim_network

    assert "scenario_from_dict" in jupedsim_network.__all__
    assert jupedsim_network.scenario_from_dict is scenario_from_dict


def test_progress_is_not_a_key_of_the_file():
    """A5: ``progress`` of run_many is a named exception of the format."""
    assert "progress" not in scenario_module._sections()["monte_carlo"][0]
    names = [k.name for k in scenario_module.keys("monte_carlo")]
    assert names == ["runs", "seed", "quantiles"]
    data = _edit(_set(["monte_carlo", "progress"], 1))
    with pytest.raises(ScenarioError) as info:
        scenario_from_dict(data)
    assert info.value.path == "monte_carlo"
    assert str(info.value).startswith("monte_carlo: unknown key 'progress'")


def _many(progress):
    sim = scenario_from_dict(_edit(_set(["monte_carlo", "runs"], 3))).simulation
    return functools.partial(sim.run_many, 3, 1, progress=progress)


def test_run_cancelled_passes_attempt_unchanged():
    """A3: a cancel is no scenario error and leaves no state behind."""
    from jupedsim_network.cli_run import RunCancelled

    cancel = RunCancelled()

    def progress(done, runs):
        warnings.warn("recorded before the cancel")
        if done == 2:
            raise cancel

    warned = ["before"]
    filters = list(warnings.filters)
    showwarning = warnings.showwarning
    with pytest.raises(RunCancelled) as info:
        scenario_module.attempt("monte_carlo", _many(progress), warned)
    assert info.value is cancel
    assert warned == ["before"]
    assert warnings.filters == filters
    assert warnings.showwarning is showwarning


def test_other_progress_errors_are_scenario_errors():
    """A3: why a cancel must not be an ``Exception``."""

    def progress(done, runs):
        raise ValueError("bug in the callback")

    with pytest.raises(ScenarioError) as info:
        scenario_module.attempt("monte_carlo", _many(progress), [])
    assert info.value.path == "monte_carlo"
    assert info.value.message == "bug in the callback"


def test_attempt_records_only_warnings_of_its_thread():
    """A6: a warning of another thread goes to the previous handler."""
    entered, go = threading.Event(), threading.Event()
    foreign = []

    def call():
        warnings.warn("from the call")
        entered.set()
        go.wait()
        return "done"

    def other_thread():
        entered.wait()
        warnings.warn("from the UI thread")
        go.set()

    def previous(message, category, filename, lineno, file=None, line=None):
        foreign.append(str(message))

    warned = []
    thread = threading.Thread(target=other_thread)
    with warnings.catch_warnings():
        warnings.showwarning = previous
        thread.start()
        result = scenario_module.attempt("monte_carlo", call, warned)
        thread.join()
    assert result == "done"
    assert warned == ["monte_carlo: from the call"]
    assert foreign == ["from the UI thread"]


def _all_keys():
    """Every element and kind of :func:`scenario.keys`."""
    kinds = {
        "node": tuple(scenario_module._NODE_METHODS),
        "distribution": tuple(scenario_module._DISTRIBUTIONS),
    }
    for element in scenario_module.ELEMENTS:
        for kind in kinds.get(element, (None,)):
            yield element, kind, scenario_module.keys(element, kind)


def _distributions(data):
    return [
        value
        for pop in data["populations"]
        for value in pop.values()
        if isinstance(value, dict)
    ]


def _given(data):
    """The keys ``full_keys.json`` sets per element and kind."""
    given: dict = {("document", None): set(data)}

    def add(element, kind, obj):
        given.setdefault((element, kind), set()).update(obj)

    for node in data["nodes"]:
        add("node", node["kind"], node)
    for link in data["connections"]:
        add("connection", None, link)
    for pop in data["populations"]:
        add("population", None, pop)
    for value in _distributions(data):
        add("distribution", value["distribution"], value)
    for name in ("simulation", "run", "monte_carlo"):
        add(name, None, data[name])
    return given


def test_keys_are_the_keys_of_the_format():
    """U1: exactly the keys of full_keys.json, each with a help line."""
    given = _given(json.loads(FULL_KEYS.read_text()))
    found = {(e, k): {key.name for key in ks} for e, k, ks in _all_keys()}
    # full_keys.json leaves the bounds of some distributions unset.
    for name in scenario_module._DISTRIBUTIONS:
        given["distribution", name] |= {"lower", "upper"}
    assert found == given
    for element, kind, ks in _all_keys():
        for key in ks:
            assert key.help, (element, kind, key.name)


def _api_default(element, kind, name):
    if element == "distribution":
        cls = scenario_module._DISTRIBUTIONS[kind]
        (field,) = [f for f in dataclasses.fields(cls) if f.name == name]
        if scenario_module._has_no_default(field):
            return inspect.Parameter.empty
        return field.default
    fn = {
        "node": scenario_module._NODE_METHODS.get(kind),
        "connection": Network.connect,
        "population": Population,
        "simulation": NetworkSimulation,
        "run": NetworkSimulation.run,
        "monte_carlo": NetworkSimulation.run_many,
    }[element]
    return inspect.signature(fn).parameters[name].default


_FILE_ONLY_KEYS = {
    ("node", "kind"),
    ("distribution", "distribution"),
    ("monte_carlo", "quantiles"),
}


def _check_default(element, kind, key):
    if element == "document" or (element, key.name) in _FILE_ONLY_KEYS:
        return
    default = _api_default(element, kind, key.name)
    # The very object of the signature, not an equal literal.
    assert key.default is default, (element, key.name)
    assert key.required is (default is inspect.Parameter.empty)
    if key.default is None:
        assert key.meaning and "None" not in key.meaning, key.name
    else:
        assert key.meaning == "", key.name


def test_keys_defaults_are_the_api_objects():
    """A8: defaults from the signatures, None by its meaning."""
    from jupedsim_network import cli_run

    for element, kind, ks in _all_keys():
        for key in ks:
            _check_default(element, kind, key)
    quantiles = scenario_module.keys("monte_carlo")[-1]
    assert quantiles.default is cli_run.DEFAULT_QUANTILES


def test_keys_name_the_rules_the_signature_cannot():
    """A8: rooms need area or length and width; meanings from the API."""
    from jupedsim_network import hydraulic

    for kind in ("room", "stair"):
        keys = {k.name: k for k in scenario_module.keys("node", kind)}
        for name in ("area", "length", "width"):
            assert not keys[name].required
            assert "area, or length and width" in keys[name].meaning
    connection = {k.name: k for k in scenario_module.keys("connection")}
    flow = f"{hydraulic.DOOR_SPECIFIC_FLOW:g} persons/s/m"
    assert connection["specific_flow"].meaning.startswith(flow)
    assert connection["kind"].choices == ("door", "opening", "stair")
    simulation = {k.name: k for k in scenario_module.keys("simulation")}
    assert simulation["counterflow"].choices == (
        "bounding",
        "estimate",
        "independent",
    )
    seed = {k.name: k for k in scenario_module.keys("run")}["seed"]
    assert seed.annotation == (int | None)
    assert "summary.json" in seed.meaning


@pytest.mark.parametrize(
    "element, kind, message",
    [
        ("nodes", None, "element must be one of 'document'"),
        ("node", None, "kind must be a node kind, one of 'room'"),
        ("distribution", "Gamma", "kind must be a distribution, one of"),
        ("run", "room", "kind must be None for 'run'; got 'room'"),
    ],
)
def test_keys_reject_unknown_elements(element, kind, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        scenario_module.keys(element, kind)
