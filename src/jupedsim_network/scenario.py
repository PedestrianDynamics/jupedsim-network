# SPDX-License-Identifier: LGPL-3.0-or-later
"""Scenario files: a network, its populations and the run settings in JSON.

A scenario file maps one to one onto the public API. Every key is the
name of an API argument and its value is passed to that argument
unchanged; a key that is left out takes the API default. Nodes,
connections and populations are arrays, created in file order, because
the order of nodes, links and agents can change results.

.. code:: json

    {
      "format_version": 1,
      "nodes": [
        {"name": "office", "kind": "room", "area": 200.0},
        {"name": "street", "kind": "safe"}
      ],
      "connections": [{"source": "office", "target": "street", "width": 0.9}],
      "populations": [{"node": "office", "count": 120}],
      "simulation": {"dt": 0.5},
      "run": {"seed": 1},
      "monte_carlo": {"runs": 500, "seed": 1, "quantiles": [0.5, 0.95]}
    }

``nodes[i].kind`` selects :meth:`Network.add_room`, :meth:`Network.add_stair`
or :meth:`Network.add_safe`; ``connections`` go to :meth:`Network.connect`,
``populations`` to :class:`Population`, ``simulation`` to
:class:`NetworkSimulation`, ``run`` to :meth:`NetworkSimulation.run` (without
``record``) and ``monte_carlo`` to :meth:`NetworkSimulation.run_many` plus
``quantiles`` for :meth:`MonteCarloResult.quantile`. A distributed value is a
number or an object such as ``{"distribution": "LogNormal", "mean": 120.0,
"std": 60.0}``; ``"lower": null`` removes the default lower bound of 0.

The loader checks the structure (keys, JSON types, finite numbers),
the two Monte Carlo settings the API checks only at run time, and samples
each distribution once; every other value check is left to the API.
Both kinds of error are raised as
:class:`ScenarioError`, prefixed with the JSON path of the element.
"""

import copy
import dataclasses
import functools
import inspect
import json
import math
import numbers
import re
import sys
import threading
import types
import typing
import warnings
from dataclasses import dataclass
from importlib import metadata
from pathlib import Path

import numpy as np

from jupedsim_network import hydraulic, sampling
from jupedsim_network.network import Network
from jupedsim_network.simulation import NetworkSimulation, Population

FORMAT_VERSION = 1

_DISTRIBUTIONS = {
    cls.__name__: cls
    for cls in (
        sampling.Fixed,
        sampling.Uniform,
        sampling.Normal,
        sampling.LogNormal,
        sampling.Triangular,
        sampling.Weibull,
    )
}

_NODE_METHODS = {
    "room": Network.add_room,
    "stair": Network.add_stair,
    "safe": Network.add_safe,
}

# The three exceptions to "every key is an API argument": ``record`` of
# ``run`` and ``progress`` of ``run_many`` are not in the file,
# ``quantiles`` is the argument of ``MonteCarloResult.quantile``, not of
# ``run_many``.
NOT_IN_FILE = {"run": ("record",), "monte_carlo": ("progress",)}
FILE_ONLY = {"monte_carlo": {"quantiles": list[float]}}

_TOP = {
    "format_version": int,
    "software_version": str,
    "hydraulic_parameters": dict,
    "description": str,
    "nodes": list,
    "connections": list,
    "populations": list,
    "simulation": dict,
    "run": dict,
    "monte_carlo": dict,
}
_TOP_REQUIRED = {"format_version", "nodes", "connections", "populations"}

_SEED = object()  # marker: ``seed`` has no annotation in the API

# Valid files are about five levels deep; the cap keeps every recursive
# step below Python's recursion limit.
_MAX_DEPTH = 64


class ScenarioError(ValueError):
    """An invalid scenario; ``path`` is the JSON path of the element."""

    def __init__(self, path: str, message: str) -> None:
        super().__init__(f"{path}: {message}" if path else message)
        self.path = path
        self.message = message


@dataclass(frozen=True, eq=False)
class Scenario:
    """A validated scenario file and the simulation built from it.

    Attributes:
        data: the document as plain dicts and lists, in file order
        simulation: the :class:`NetworkSimulation` built from ``data``
        warnings: API warnings raised while building, each prefixed with
            the JSON path of its element
        source: the file it was read from, if any
    """

    data: dict
    simulation: NetworkSimulation
    warnings: tuple[str, ...] = ()
    source: Path | None = None

    @property
    def run_seed(self) -> int | None:
        """``run.seed``; ``None`` if the file gives none."""
        return self.data.get("run", {}).get("seed")

    @property
    def monte_carlo(self) -> dict | None:
        """The ``monte_carlo`` section; ``None`` if the file has none."""
        section = self.data.get("monte_carlo")
        return None if section is None else copy.deepcopy(section)

    def build(self) -> tuple[NetworkSimulation, tuple[str, ...]]:
        """Build a fresh simulation and its warnings from ``data``."""
        return _build(self.data)

    def to_dict(self) -> dict:
        return copy.deepcopy(self.data)

    @classmethod
    def from_simulation(
        cls,
        simulation: NetworkSimulation,
        *,
        seed: int | None = None,
        monte_carlo: dict | None = None,
        description: str | None = None,
    ) -> "Scenario":
        """The scenario of a simulation built in Python.

        Writes the arguments the network, the populations and the
        simulation were built with, in creation order; an argument equal
        to its API default is left out. Derived values such as link
        capacities are never written.

        Arguments:
            simulation: the simulation to export
            seed: ``run.seed``; ``None`` leaves the ``run`` section out
            monte_carlo: the ``monte_carlo`` section, e.g.
                ``{"runs": 500, "seed": 1, "quantiles": [0.5, 0.95]}``
            description: free text for the file

        Raises:
            ScenarioError: a value the file format cannot express, such as
                a user-defined :class:`Distribution` subclass, named by its
                JSON path; nothing is dropped silently
        """
        data = _export(simulation, seed, monte_carlo, description)
        return scenario_from_dict(data)


def load_scenario(path) -> Scenario:
    """Read, check and build a scenario file.

    Raises:
        ScenarioError: the file is not a valid scenario
        OSError: the file cannot be read
    """
    text = _decode(Path(path).read_bytes())
    return scenario_from_dict(_parse(text), source=path)


def scenario_from_dict(data, source=None) -> Scenario:
    """Check and build a scenario held in memory as dicts and lists.

    The checks and errors are those of :func:`load_scenario`, except the
    checks of the JSON text itself (UTF-8, duplicate keys). The returned
    :attr:`Scenario.data` is a copy of ``data``; it is not checked again
    when the :class:`Scenario` is saved, so edit a dict of your own and
    save that dict with :func:`save_scenario`, which checks it first.

    Arguments:
        data: the document as ``json.load`` returns it: dicts, lists,
            strings, finite numbers, booleans and ``None``; a tuple is
            rejected
        source: the file it was read from, stored as
            :attr:`Scenario.source`; ``None`` for none

    Raises:
        ScenarioError: ``data`` is not a valid scenario
    """
    _check_document(data)
    plain = _plain(data)
    simulation, warned = _build(plain)
    return Scenario(
        data=plain,
        simulation=simulation,
        warnings=warned,
        source=None if source is None else Path(source),
    )


def save_scenario(scenario, path) -> None:
    """Write a :class:`Scenario`, a scenario dict or a simulation as JSON.

    Keys keep their order and no default is added. A dict is checked and
    built first, so only valid scenarios are written. A
    :class:`NetworkSimulation` is exported with
    :meth:`Scenario.from_simulation` (no seed, no Monte Carlo section).
    """
    if isinstance(scenario, NetworkSimulation):
        scenario = Scenario.from_simulation(scenario)
    if not isinstance(scenario, Scenario):
        scenario = scenario_from_dict(scenario)
    Path(path).write_text(dumps(scenario.data), encoding="utf-8", newline="\n")


def dumps(data) -> str:
    """The text that :func:`save_scenario` writes."""
    return (
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


# Reading


class _Object(dict):
    """A JSON object that remembers keys given more than once."""

    duplicates: tuple[str, ...] = ()


def _object(pairs) -> _Object:
    obj = _Object(pairs)
    if len(obj) < len(pairs):
        keys = [key for key, _ in pairs]
        obj.duplicates = tuple(k for k in obj if keys.count(k) > 1)
    return obj


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScenarioError(
            "",
            f"not UTF-8 text: byte 0x{raw[exc.start]:02x} at position "
            f"{exc.start}; save the file as UTF-8",
        ) from None


def _parse(text: str):
    try:
        return json.loads(text, object_pairs_hook=_object)
    except json.JSONDecodeError as exc:
        raise ScenarioError(
            "",
            f"invalid JSON: {exc.msg} (line {exc.lineno}, column {exc.colno})",
        ) from None
    except RecursionError:
        raise ScenarioError(
            "", f"invalid JSON: nested deeper than {_MAX_DEPTH} levels"
        ) from None
    except ValueError as exc:  # an integer beyond Python's digit limit
        raise ScenarioError("", f"invalid JSON: {exc}") from None


def _plain(value):
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


# Structure


def _join(path: str, key: str) -> str:
    return f"{path}.{key}" if path else key


def _check_document(data) -> None:
    if not isinstance(data, dict):
        raise ScenarioError("", "a scenario must be a JSON object")
    _check_values(data, "")
    _check_format_version(data)
    _check_object(data, "", _TOP, _TOP_REQUIRED)
    if "hydraulic_parameters" in data:
        fields = {
            f.name: float
            for f in dataclasses.fields(hydraulic.HydraulicParameters)
        }
        _check_object(
            data["hydraulic_parameters"], "hydraulic_parameters", fields, set()
        )
    for i, node in enumerate(data["nodes"]):
        _check_node(node, f"nodes[{i}]")
    connect = _spec(Network.connect)
    for i, link in enumerate(data["connections"]):
        _check_object(link, f"connections[{i}]", *connect)
    if not data["populations"]:
        raise ScenarioError(
            "populations", "at least one population is required"
        )
    population = _spec(Population)
    for i, pop in enumerate(data["populations"]):
        _check_object(pop, f"populations[{i}]", *population)
    for name, spec in _sections().items():
        if name in data:
            _check_object(data[name], name, *spec)
    if "monte_carlo" in data:
        _check_monte_carlo(data["monte_carlo"])


def _sections() -> dict:
    run, many = NetworkSimulation.run, NetworkSimulation.run_many
    annotations, required = _spec(many, NOT_IN_FILE["monte_carlo"])
    return {
        "simulation": _spec(NetworkSimulation, ("network", "populations")),
        "run": _spec(run, NOT_IN_FILE["run"]),
        "monte_carlo": (annotations | FILE_ONLY["monte_carlo"], required),
    }


def _spec(fn, skip=()) -> tuple[dict, set]:
    """Annotation of each keyword of ``fn`` and the required ones."""
    params = inspect.signature(fn).parameters
    annotations, required = {}, set()
    for name, param in params.items():
        if name == "self" or name in skip:
            continue
        annotations[name] = _SEED if name == "seed" else param.annotation
        if param.default is inspect.Parameter.empty:
            required.add(name)
    return annotations, required


def _check_values(value, path: str, depth: int = 0) -> None:
    """Reject deep nesting, duplicate keys and non-finite numbers anywhere."""
    if depth > _MAX_DEPTH:
        raise ScenarioError(path, f"nested deeper than {_MAX_DEPTH} levels")
    _check_number(value, path)
    if isinstance(value, dict):
        duplicates = getattr(value, "duplicates", ())
        if duplicates:
            raise ScenarioError(path, f"duplicate key {duplicates[0]!r}")
        for key, item in value.items():
            _check_values(item, _join(path, key), depth + 1)
    if isinstance(value, list):
        for i, item in enumerate(value):
            _check_values(item, f"{path}[{i}]", depth + 1)


def _check_number(value, path: str) -> None:
    """Every number must convert to a finite float."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ScenarioError(
            path, f"non-finite number {value!r}; give a finite value"
        )
    if not _is_int(value):
        return
    try:
        float(value)
    except OverflowError:
        digits = int(value.bit_length() * math.log10(2)) + 1
        raise ScenarioError(
            path,
            f"integer of about {digits} digits is too large; give a number "
            f"of magnitude below {sys.float_info.max:.1e}",
        ) from None


def _check_format_version(data: dict) -> None:
    if "format_version" not in data:
        raise ScenarioError("", "missing required key 'format_version'")
    version = data["format_version"]
    if version == FORMAT_VERSION and _is_int(version):
        return
    raise ScenarioError(
        "format_version",
        f"{json.dumps(version)} is not supported; this version of "
        f"jupedsim-network reads {FORMAT_VERSION}",
    )


def _check_node(node, path: str) -> None:
    if not isinstance(node, dict):
        raise ScenarioError(path, f"expected an object, got {_json_type(node)}")
    if "kind" not in node:
        raise ScenarioError(path, "missing required key 'kind'")
    kind = node["kind"]
    if not isinstance(kind, str):
        raise ScenarioError(
            _join(path, "kind"), f"expected a string, got {_json_type(kind)}"
        )
    if kind not in _NODE_METHODS:
        valid = ", ".join(repr(k) for k in _NODE_METHODS)
        raise ScenarioError(
            _join(path, "kind"),
            f"must be one of {valid}; got {json.dumps(kind)}",
        )
    annotations, required = _spec(_NODE_METHODS[kind])
    annotations["kind"] = str
    _check_object(node, path, annotations, required, f" for kind {kind!r}")


def _check_object(obj, path, annotations, required, context="") -> None:
    if not isinstance(obj, dict):
        raise ScenarioError(path, f"expected an object, got {_json_type(obj)}")
    _check_keys(obj, path, annotations, required, context)
    for key, value in obj.items():
        _check_value(value, annotations[key], _join(path, key))


def _check_keys(obj, path, annotations, required, context="") -> None:
    unknown = [key for key in obj if key not in annotations]
    if unknown:
        valid = ", ".join(sorted(annotations))
        raise ScenarioError(
            path, f"unknown key {unknown[0]!r}{context}; valid keys: {valid}"
        )
    missing = [key for key in annotations if key in required and key not in obj]
    if missing:
        raise ScenarioError(
            path, f"missing required key {missing[0]!r}{context}"
        )


def _check_value(value, annotation, path: str) -> None:
    if annotation is _SEED:
        _check_seed(value, path)
        return
    if not _accepts(value, annotation):
        raise ScenarioError(
            path, f"expected {_describe(annotation)}, got {_json_type(value)}"
        )
    if typing.get_origin(annotation) is list:
        _check_list(value, annotation, path)
    elif isinstance(value, dict) and annotation is not dict:
        _check_distribution(value, path)


def _check_list(value, annotation, path: str) -> None:
    if not value:
        raise ScenarioError(path, "expected at least one value")
    (item,) = typing.get_args(annotation)
    for i, element in enumerate(value):
        _check_value(element, item, f"{path}[{i}]")


def _check_seed(value, path: str) -> None:
    if value is None or (_is_int(value) and value >= 0):
        return
    raise ScenarioError(
        path, f"expected an integer >= 0 or null, got {json.dumps(value)}"
    )


def _check_distribution(value: dict, path: str) -> None:
    if "distribution" not in value:
        raise ScenarioError(path, "missing required key 'distribution'")
    name = value["distribution"]
    if not isinstance(name, str):
        raise ScenarioError(
            _join(path, "distribution"),
            f"expected a string, got {_json_type(name)}",
        )
    if name not in _DISTRIBUTIONS:
        valid = ", ".join(_DISTRIBUTIONS)
        raise ScenarioError(
            _join(path, "distribution"),
            f"must be one of {valid}; got {json.dumps(name)}",
        )
    annotations = {"distribution": str}
    required = {"distribution"}
    for field in dataclasses.fields(_DISTRIBUTIONS[name]):
        annotations[field.name] = field.type
        if _has_no_default(field):
            required.add(field.name)
    _check_object(value, path, annotations, required, f" for {name}")


def _check_monte_carlo(section: dict) -> None:
    """The checks ``run_many`` and ``quantile`` would make only at run time."""
    runs = section["runs"]
    if runs < 1:
        raise ScenarioError("monte_carlo.runs", f"must be >= 1, got {runs}")
    for i, q in enumerate(section.get("quantiles", ())):
        if not 0.0 <= q <= 1.0:
            raise ScenarioError(
                f"monte_carlo.quantiles[{i}]", f"must be in [0, 1], got {q!r}"
            )


def _has_no_default(field) -> bool:
    return (
        field.default is dataclasses.MISSING
        and field.default_factory is dataclasses.MISSING
    )


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _accepts(value, annotation) -> bool:
    """Whether a JSON value fits an API annotation."""
    if isinstance(annotation, types.UnionType):
        return any(_accepts(value, a) for a in typing.get_args(annotation))
    if annotation is type(None):
        return value is None
    if annotation is bool:
        return isinstance(value, bool)
    if annotation is int:
        return _is_int(value)
    if annotation is float:
        return _is_int(value) or isinstance(value, float)
    if typing.get_origin(annotation) is list:
        return isinstance(value, list)
    if annotation is sampling.Distribution:
        return isinstance(value, dict)
    return isinstance(annotation, type) and isinstance(value, annotation)


_NAMES = {
    type(None): "null",
    bool: "true or false",
    int: "an integer",
    float: "a number",
    str: "a string",
    list: "an array",
    dict: "an object",
    sampling.Distribution: "a distribution object",
}


def _describe(annotation) -> str:
    if isinstance(annotation, types.UnionType):
        return " or ".join(_describe(a) for a in typing.get_args(annotation))
    if typing.get_origin(annotation) is list:
        return "an array of numbers"
    return _NAMES[annotation]


def _json_type(value) -> str:
    if isinstance(value, bool) or value is None:
        return json.dumps(value)
    if isinstance(value, (int, float)):
        return f"the number {json.dumps(value)}"
    if isinstance(value, str):
        return f"the string {json.dumps(value)}"
    return "an array" if isinstance(value, list) else "an object"


# Keys of the format


@dataclass(frozen=True)
class Key:
    """One key of a scenario element, as the loader checks it.

    Attributes:
        name: the key
        annotation: the type the loader accepts (``int | None`` for a seed)
        required: whether the loader requires the key
        default: the API's own default object (``inspect.Parameter.empty``
            if required); ``None`` for an optional section of the document
        choices: the valid values of an enumerated key, from the tables
            the API checks against
        help: the description of the argument in the API docstring, or of
            a key that only the file has
        meaning: what an absent key means, for a key whose default is
            ``None``; empty otherwise
    """

    name: str
    annotation: object
    required: bool
    default: object
    choices: tuple[str, ...] = ()
    help: str = ""
    meaning: str = ""


ELEMENTS = (
    "document",
    "node",
    "connection",
    "population",
    "simulation",
    "run",
    "monte_carlo",
    "distribution",
)

# Help of the keys that are no API argument.
FILE_ONLY_HELP: dict[tuple[str, str], str] = {
    ("document", "format_version"): "version of the file format; this "
    f"version of jupedsim-network reads {FORMAT_VERSION}",
    (
        "document",
        "software_version",
    ): "version of jupedsim-network that wrote the file; not read back",
    (
        "document",
        "hydraulic_parameters",
    ): "HydraulicParameters fields that differ from the SFPE defaults",
    ("document", "description"): "free text; not used by the model",
    ("document", "nodes"): "rooms, stairs and safe places, created in "
    "file order",
    ("document", "connections"): "doors, openings and stair links "
    "(Network.connect), created in file order",
    ("document", "populations"): "groups of agents (Population), in file "
    "order; at least one",
    ("document", "simulation"): "settings of NetworkSimulation",
    ("document", "run"): "the single run (NetworkSimulation.run)",
    ("document", "monte_carlo"): "repeated runs "
    "(NetworkSimulation.run_many) and the quantiles to report",
    ("node", "kind"): "room, stair or safe: selects Network.add_room, "
    "add_stair or add_safe",
    ("distribution", "distribution"): "name of the distribution class",
    ("monte_carlo", "quantiles"): "quantiles of the evacuation time over "
    "the runs, each in [0, 1]; absent: the defaults of the command line",
}


def keys(element: str, kind: str | None = None) -> tuple[Key, ...]:
    """The keys of one element of the file format.

    The keys follow the API signature (the format for ``"document"``),
    with ``kind`` after ``name`` for a node, ``distribution`` first and
    ``lower`` and ``upper`` last for a distribution, and ``quantiles``
    last for ``"monte_carlo"``.

    Arguments:
        element: one of :data:`ELEMENTS`
        kind: the node kind for ``"node"``, the distribution name for
            ``"distribution"``; ``None`` otherwise

    Returns:
        One :class:`Key` per key the loader accepts for that element.

    Raises:
        ValueError: ``element`` is not in :data:`ELEMENTS`, or ``kind``
            does not fit ``element``
    """
    if element not in ELEMENTS:
        valid = ", ".join(repr(e) for e in ELEMENTS)
        raise ValueError(f"element must be one of {valid}; got {element!r}")
    if element == "node":
        return _node_keys(_kind(kind, _NODE_METHODS, "node kind"))
    if element == "distribution":
        return _distribution_keys(_kind(kind, _DISTRIBUTIONS, "distribution"))
    if kind is not None:
        raise ValueError(f"kind must be None for {element!r}; got {kind!r}")
    return _ELEMENT_KEYS[element]()


def _kind(kind, table: dict, what: str) -> str:
    if kind in table:
        return kind
    valid = ", ".join(repr(k) for k in table)
    raise ValueError(f"kind must be a {what}, one of {valid}; got {kind!r}")


def _document_keys() -> tuple[Key, ...]:
    return tuple(
        Key(
            name,
            annotation,
            name in _TOP_REQUIRED,
            inspect.Parameter.empty if name in _TOP_REQUIRED else None,
            help=FILE_ONLY_HELP["document", name],
            meaning="" if name in _TOP_REQUIRED else _none_means()[name],
        )
        for name, annotation in _TOP.items()
    )


def _node_keys(kind: str) -> tuple[Key, ...]:
    method = _NODE_METHODS[kind]
    name, *rest = _signature_keys(method, method)
    kind_key = Key(
        "kind",
        str,
        True,
        inspect.Parameter.empty,
        tuple(_NODE_METHODS),
        FILE_ONLY_HELP["node", "kind"],
    )
    return (name, kind_key, *rest)


def _connection_keys() -> tuple[Key, ...]:
    from jupedsim_network import network

    choices = {"kind": tuple(network._BOUNDARY_LAYERS)}
    return _signature_keys(Network.connect, Network.connect, choices=choices)


def _population_keys() -> tuple[Key, ...]:
    return _signature_keys(Population, Population)


def _simulation_keys() -> tuple[Key, ...]:
    from jupedsim_network import network, simulation

    choices = {
        "counterflow": tuple(simulation._COUNTERFLOW),
        "routing_policy": network.ROUTING_POLICIES,
    }
    skip = ("network", "populations")
    return _signature_keys(
        NetworkSimulation, NetworkSimulation, skip, choices=choices
    )


def _run_keys() -> tuple[Key, ...]:
    run = NetworkSimulation.run
    return _signature_keys(run, run, NOT_IN_FILE["run"])


def _monte_carlo_keys() -> tuple[Key, ...]:
    from jupedsim_network import cli_run

    many = NetworkSimulation.run_many
    quantiles = Key(
        "quantiles",
        FILE_ONLY["monte_carlo"]["quantiles"],
        False,
        cli_run.DEFAULT_QUANTILES,
        help=FILE_ONLY_HELP["monte_carlo", "quantiles"],
    )
    found = _signature_keys(many, many, NOT_IN_FILE["monte_carlo"])
    return (*found, quantiles)


_ELEMENT_KEYS = {
    "document": _document_keys,
    "connection": _connection_keys,
    "population": _population_keys,
    "simulation": _simulation_keys,
    "run": _run_keys,
    "monte_carlo": _monte_carlo_keys,
}


def _signature_keys(fn, documented, skip=(), choices=None) -> tuple[Key, ...]:
    """The keys of the arguments of ``fn``, with the help of ``documented``."""
    params = inspect.signature(fn).parameters
    annotations, required = _spec(fn, skip)
    helps = _argument_help(documented)
    return tuple(
        _key(
            name,
            (int | None) if annotation is _SEED else annotation,
            name in required,
            params[name].default,
            (choices or {}).get(name, ()),
            helps.get(name, ""),
        )
        for name, annotation in annotations.items()
    )


def _distribution_keys(name: str) -> tuple[Key, ...]:
    cls = _DISTRIBUTIONS[name]
    helps = {}
    for base in reversed(cls.__mro__):
        helps |= _argument_help(base)
    first = Key(
        "distribution",
        str,
        True,
        inspect.Parameter.empty,
        tuple(_DISTRIBUTIONS),
        FILE_ONLY_HELP["distribution", "distribution"],
    )
    bounds = {f.name for f in dataclasses.fields(sampling.Distribution)}
    fields = sorted(dataclasses.fields(cls), key=lambda f: f.name in bounds)
    found = tuple(
        _key(
            field.name,
            field.type,
            _has_no_default(field),
            inspect.Parameter.empty
            if _has_no_default(field)
            else field.default,
            (),
            helps.get(field.name, ""),
        )
        for field in fields
    )
    return (first, *found)


def _key(name, annotation, required, default, choices, text) -> Key:
    meaning = _none_means().get(name, "") if default is None else ""
    return Key(name, annotation, required, default, choices, text, meaning)


def _none_means() -> dict[str, str]:
    """What an absent key with the default ``None`` means."""
    from jupedsim_network import hydraulic, network

    layers = ", ".join(
        f"{width:g} m for {kind}"
        for kind, width in network._BOUNDARY_LAYERS.items()
    )
    area = "give area, or length and width"
    return {
        "area": area,
        "length": area,
        "width": area,
        "specific_flow": f"{hydraulic.DOOR_SPECIFIC_FLOW:g} persons/s/m for "
        "doors and openings; for stairs, the maximum flow of the adjacent "
        "stair node",
        "boundary_layer": layers,
        "name": "source->target",
        "target": "the nearest safe node",
        "upper": "no upper bound",
        "seed": "the command line draws a seed and records it in "
        "summary.json (seed_drawn: true)",
        "software_version": "no version recorded",
        "hydraulic_parameters": "every coefficient takes its default",
        "description": "no description",
        "simulation": "every setting takes the API default",
        "run": "run.seed absent: the command line draws a seed",
        "monte_carlo": "the single run only, unless --runs is given",
    }


_HELP_SECTION = re.compile(r"^(Arguments|Attributes):$")
_HELP_ENTRY = re.compile(r"^    (\w+): (.*)$")


def _argument_help(obj) -> dict[str, str]:
    """``name: text`` of the ``Arguments:``/``Attributes:`` docstring section.

    The section ends at a blank line or at a line indented less than its
    entries.
    """
    helps: dict[str, str] = {}
    lines = iter((inspect.getdoc(obj) or "").splitlines())
    for line in lines:
        if _HELP_SECTION.match(line):
            _read_section(lines, helps)
    return {name: " ".join(text.split()) for name, text in helps.items()}


def _read_section(lines, helps: dict[str, str]) -> None:
    current = None
    for line in lines:
        entry = _HELP_ENTRY.match(line)
        if entry is not None:
            current = entry.group(1)
            helps[current] = entry.group(2)
        elif current is not None and line.startswith("        "):
            helps[current] += " " + line.strip()
        else:
            return


# Building


def attempt(path: str, call, warned: list[str] | None):
    """Call the API; prefix its errors and warnings with ``path``.

    Every exception the call raises becomes a :class:`ScenarioError` with
    the API's own message; a ``BaseException`` that is not an
    ``Exception`` passes unchanged. Warnings raised on the calling thread
    are appended to ``warned``, or dropped if it is ``None``; warnings of
    other threads go to the handler that was in place before the call.
    """
    caught: list[str] = []
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        warnings.showwarning = _recorder(caught, warnings.showwarning)
        try:
            result = call()
        except Exception as exc:  # the API's own error, re-raised with a path
            raise ScenarioError(*_located(path, _message(exc))) from exc
    if warned is not None:
        warned.extend(f"{path}: {message}" for message in caught)
    return result


def _recorder(caught: list[str], previous):
    """A ``showwarning`` that records only the warnings of this thread."""
    owner = threading.get_ident()

    def showwarning(message, category, filename, lineno, file=None, line=None):
        if threading.get_ident() != owner:
            previous(message, category, filename, lineno, file, line)
            return
        caught.append(str(message))

    return showwarning


_POPULATION = re.compile(r"population (\d+): (.*)", re.S)
_KEYED = re.compile(r"(\w+): (.*)", re.S)
_CHOICE = re.compile(r"(\w+) must be one of .*", re.S)
_ELEMENT_PATH = re.compile(r"(nodes|connections|populations)\[\d+\]|simulation")


def _located(path: str, message: str) -> tuple[str, str]:
    """The path and the rest of an API message that names its element.

    ``population i: ...`` locates at ``populations[i]``; ``key: ...`` with
    a key of the element at ``path`` locates at ``path.key``, as does
    ``key must be one of ...``, which keeps its text. API messages that must
    land at a key therefore start with ``key: `` or ``key must be one of``;
    any other message starting with a key name and ``: `` would be
    relocated too.
    """
    match = _POPULATION.fullmatch(message)
    if match is not None:
        return f"populations[{match.group(1)}]", match.group(2)
    match = _CHOICE.fullmatch(message)
    if match is not None and match.group(1) in _keys_of(path):
        return _join(path, match.group(1)), message
    match = _KEYED.fullmatch(message)
    if match is None or match.group(1) not in _keys_of(path):
        return path, message
    return _join(path, match.group(1)), match.group(2)


def _keys_of(path: str) -> set[str]:
    """The keys of the element at ``path``; empty if it is no element."""
    if _ELEMENT_PATH.fullmatch(path) is None:
        return set()
    if path.startswith("nodes"):
        return {k.name for kind in _NODE_METHODS for k in keys("node", kind)}
    element = {"c": "connection", "p": "population", "s": "simulation"}
    return {k.name for k in keys(element[path[0]])}


def _message(exc: Exception) -> str:
    if isinstance(exc, (ValueError, RuntimeError)) and str(exc):
        return str(exc)
    return f"{type(exc).__name__}: {exc}"


def _build(data: dict) -> tuple[NetworkSimulation, tuple[str, ...]]:
    """Build the simulation, attributing each error to its element."""
    warned: list[str] = []
    settings = data.get("simulation", {})
    parameters = attempt(
        "hydraulic_parameters",
        functools.partial(
            hydraulic.HydraulicParameters,
            **data.get("hydraulic_parameters", {}),
        ),
        warned,
    )
    attempt(
        "simulation",
        functools.partial(_probe_settings, settings, parameters),
        warned,
    )
    # The settings alone warned these; every population build repeats them.
    from_settings = {w.removeprefix("simulation: ") for w in warned}
    net = Network(parameters=parameters)
    for i, node in enumerate(data["nodes"]):
        attempt(f"nodes[{i}]", functools.partial(_add_node, net, node), warned)
    for i, link in enumerate(data["connections"]):
        attempt(
            f"connections[{i}]", functools.partial(_connect, net, link), warned
        )
    populations = []
    for i, entry in enumerate(data["populations"]):
        path = f"populations[{i}]"
        pop = _population(entry, path, warned)
        _probe_sampling(pop, entry, path, warned)
        one = functools.partial(NetworkSimulation, net, [pop], **settings)
        caught: list[str] = []
        attempt(path, one, caught)
        warned.extend(
            w
            for w in caught
            if w.removeprefix(f"{path}: ") not in from_settings
        )
        populations.append(pop)
    # Every check of the full build ran per population above; its
    # warnings repeat theirs and are dropped.
    full = functools.partial(NetworkSimulation, net, populations, **settings)
    return attempt("populations", full, None), tuple(warned)


def _probe_settings(
    settings: dict, parameters: hydraulic.HydraulicParameters
) -> None:
    """Let the API check the ``simulation`` settings on their own."""
    net = Network(parameters=parameters)
    net.add_room("room", area=100.0)
    net.add_safe("safe")
    net.connect(
        "room", "safe", width=1.0, boundary_layer=0.0, specific_flow=1.0
    )
    NetworkSimulation(net, [Population("room", 1)], **settings)


def _probe_sampling(pop: Population, entry: dict, path: str, warned) -> None:
    """Sample each distribution once, so bad parameters fail at load."""
    for key, value in entry.items():
        if isinstance(value, dict):
            probe = functools.partial(_sample_once, getattr(pop, key))
            attempt(_join(path, key), probe, warned)


def _sample_once(distribution: sampling.Distribution) -> None:
    # A generator of its own: the run's random stream is not touched.
    try:
        distribution.sample(np.random.default_rng(0), 1)
    except Exception as exc:
        raise ValueError(f"cannot sample {distribution!r}: {exc}") from exc


def _add_node(net: Network, node: dict) -> None:
    method = getattr(net, _NODE_METHODS[node["kind"]].__name__)
    method(**{key: value for key, value in node.items() if key != "kind"})


def _connect(net: Network, link: dict) -> None:
    net.connect(**link)


def _population(entry: dict, path: str, warned) -> Population:
    """Build each value at its own key, then the population at ``path``."""
    fields = {
        key: attempt(_join(path, key), functools.partial(_value, value), warned)
        for key, value in entry.items()
    }
    return attempt(path, functools.partial(Population, **fields), warned)


def _value(value):
    """A distribution object as its class; plain numbers stay numbers."""
    if not isinstance(value, dict):
        return value
    fields = {k: v for k, v in value.items() if k != "distribution"}
    return _DISTRIBUTIONS[value["distribution"]](**fields)


# Writing a simulation built in Python


def software_version() -> str:
    """The installed version of jupedsim-network, or ``"unknown"``."""
    try:
        return metadata.version("jupedsim-network")
    except metadata.PackageNotFoundError:
        return "unknown"


def _export(sim, seed, monte_carlo, description) -> dict:
    data: dict = {
        "format_version": FORMAT_VERSION,
        "software_version": software_version(),
    }
    changed = _non_default(
        dataclasses.asdict(sim.network.parameters),
        hydraulic.HydraulicParameters,
    )
    if changed:
        data["hydraulic_parameters"] = changed
    if description is not None:
        data["description"] = description
    data["nodes"], data["connections"] = [], []
    for call, arguments in sim.network._inputs:
        _export_call(data, call, arguments)
    data["populations"] = [
        _export_population(pop, f"populations[{i}]")
        for i, pop in enumerate(sim.populations)
    ]
    data["simulation"] = _export_settings(sim)
    if seed is not None:
        data["run"] = {"seed": _to_json(seed, "run.seed")}
    if monte_carlo is not None:
        data["monte_carlo"] = _to_json_object(monte_carlo, "monte_carlo")
    return data


def _export_call(data: dict, call: str, arguments: dict) -> None:
    if call == "connect":
        path = f"connections[{len(data['connections'])}]"
        given = _non_default(arguments, Network.connect)
        data["connections"].append(_to_json_object(given, path))
        return
    path = f"nodes[{len(data['nodes'])}]"
    given = _non_default(arguments, _NODE_METHODS[call])
    entry = {"name": given.pop("name"), "kind": call, **given}
    data["nodes"].append(_to_json_object(entry, path))


def _export_population(pop: Population, path: str) -> dict:
    arguments = {f.name: getattr(pop, f.name) for f in dataclasses.fields(pop)}
    return _to_json_object(_non_default(arguments, Population), path)


def _export_settings(sim: NetworkSimulation) -> dict:
    annotations, _ = _spec(NetworkSimulation, ("network", "populations"))
    arguments = {name: getattr(sim, name) for name in annotations}
    return _to_json_object(
        _non_default(arguments, NetworkSimulation), "simulation"
    )


def _non_default(arguments: dict, fn) -> dict:
    """The arguments that differ from the defaults of ``fn``."""
    params = inspect.signature(fn).parameters
    return {
        key: value
        for key, value in arguments.items()
        if key not in params or not _is_default(value, params[key].default)
    }


def _is_default(value, default) -> bool:
    if default is inspect.Parameter.empty:
        return False
    return value is default or (
        type(value) is type(default) and value == default
    )


def _to_json_object(values: dict, path: str) -> dict:
    return {
        key: _to_json(value, _join(path, key)) for key, value in values.items()
    }


def _to_json(value, path: str):
    """A value the file format can hold, or a ScenarioError naming it."""
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, numbers.Integral):
        return int(value)
    if isinstance(value, numbers.Real):
        return _finite(float(value), path)
    if isinstance(value, sampling.Distribution):
        return _export_distribution(value, path)
    if isinstance(value, (list, tuple)):
        return [_to_json(item, f"{path}[{i}]") for i, item in enumerate(value)]
    if isinstance(value, dict):
        return _to_json_object(value, path)
    raise ScenarioError(
        path,
        f"{type(value).__name__} {value!r} cannot be written to a scenario file",
    )


def _finite(value: float, path: str) -> float:
    if not math.isfinite(value):
        raise ScenarioError(
            path, f"non-finite number {value!r} cannot be written"
        )
    return value


def _export_distribution(value, path: str) -> dict:
    name = type(value).__name__
    if _DISTRIBUTIONS.get(name) is not type(value):
        valid = ", ".join(_DISTRIBUTIONS)
        raise ScenarioError(
            path,
            f"{name} is not a distribution of the file format; use one of {valid}",
        )
    entry = {"distribution": name}
    for field in dataclasses.fields(value):
        item = getattr(value, field.name)
        if _has_no_default(field) or not _is_default(item, field.default):
            entry[field.name] = _to_json(item, _join(path, field.name))
    return entry
