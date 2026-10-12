# SPDX-License-Identifier: LGPL-3.0-or-later
"""The TUI's document model; imports no Textual.

The TUI edits a plain dict, the JSON document of the scenario file. Every
widget is bound to a path such as ``("connections", 1, "width")``. This
module holds the one conversion from typed text to JSON, the location of
an error from its JSON path, the help text of a key, the recent-files
list, path browsing and the text of the Results step. It checks nothing
itself: every check is the loader's.
"""

import contextlib
import copy
import csv
import io
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from jupedsim_network import sampling, scenario
from jupedsim_network.scenario import Key

THEMES = ("network-dark", "solarized-light")
DEFAULT_THEME = "network-dark"
THEME_ENV = "JUPEDSIM_NETWORK_TUI_THEME"
DOCS_URL = "https://pedestriandynamics.org/jupedsim-network/"

# The list sections of the document and the element name of each.
ELEMENTS = {
    "nodes": "node",
    "connections": "connection",
    "populations": "population",
}
SETTINGS = ("simulation", "run", "monte_carlo")
# Settings sections that are left out of the file once they are empty.
DROPPED_WHEN_EMPTY = ("simulation", "run")

MISSING = object()


# Paths


_TOKEN = re.compile(r"\[(\d+)\]|([^.\[\]]+)")


def parse_path(text: str) -> tuple:
    """``"connections[1].width"`` as ``("connections", 1, "width")``."""
    parts: list = []
    for index, name in _TOKEN.findall(text):
        parts.append(int(index) if index else name)
    return tuple(parts)


def path_text(path: tuple) -> str:
    """The inverse of :func:`parse_path`."""
    text = ""
    for part in path:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else part
    return text


def get(doc, path: tuple, default=MISSING):
    """The value at ``path``; ``default`` if any step is missing."""
    value = doc
    for part in path:
        try:
            value = value[part]
        except (KeyError, IndexError, TypeError):
            return default
    return value


def put(doc: dict, path: tuple, value) -> None:
    """Set the value at ``path``; a missing settings section is created."""
    *head, last = path
    parent = doc
    for part in head:
        if isinstance(parent, dict) and part not in parent:
            parent[part] = {}
        parent = parent[part]
    parent[last] = value


def remove(doc: dict, path: tuple) -> None:
    """Remove the key at ``path``; an emptied ``simulation`` or ``run`` goes too."""
    *head, last = path
    parent = get(doc, tuple(head), None)
    if isinstance(parent, dict):
        parent.pop(last, None)
    if len(head) == 1 and head[0] in DROPPED_WHEN_EMPTY and parent == {}:
        doc.pop(head[0], None)


# Text and JSON


def is_list(annotation) -> bool:
    return getattr(annotation, "__origin__", None) is list


def is_text(annotation) -> bool:
    """``str`` or ``str | None``: the text is the value."""
    return annotation is str or annotation == (str | None)


def is_distributed(key: Key) -> bool:
    """A key that takes a number or a distribution object."""
    return sampling.Distribution in getattr(key.annotation, "__args__", ())


def to_json(text: str, annotation) -> tuple[bool, object]:
    """``(present, value)`` of a typed text; empty text removes the key.

    A text that does not parse is kept as a string, so the loader names
    the error in its own words.
    """
    if not text.strip():
        return False, None
    if is_text(annotation):
        return True, text
    candidate = f"[{text}]" if is_list(annotation) else text
    try:
        return True, json.loads(candidate)
    except ValueError:
        return True, text


def to_text(value) -> str:
    """The text a control shows for a JSON value."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return ", ".join(to_text(v) for v in value)
    return json.dumps(value)


# Keys and help


def element_keys(section: str, element) -> tuple[Key, ...]:
    """The keys of one element; a node without a valid kind shows name and kind."""
    if section == "nodes":
        kind = element.get("kind") if isinstance(element, dict) else None
        if kind in ("room", "stair", "safe"):
            return scenario.keys("node", kind)
        return scenario.keys("node", "safe")
    return scenario.keys(ELEMENTS[section])


def distribution_names() -> tuple[str, ...]:
    return scenario.keys("distribution", "Fixed")[0].choices


def distribution_keys(name: str) -> tuple[Key, ...]:
    """The fields of distribution ``name``, without ``distribution``."""
    return scenario.keys("distribution", name)[1:]


def distribution_of(value) -> str | None:
    """The distribution name of a value, if it is a known one."""
    if not isinstance(value, dict):
        return None
    name = value.get("distribution")
    return name if name in distribution_names() else None


# Help of the seeds as a file holds them; the API text also names forms
# that only Python can pass.
FILE_HELP: dict[tuple[str, str], str] = {
    ("run", "seed"): "integer seed of the single run",
    ("monte_carlo", "seed"): "integer seed of the Monte Carlo runs "
    "(SeedSequence)",
}

_ROLE = re.compile(r":[a-z]+:`~?(?:[\w.]*\.)?([\w]+)`")
_LITERAL = re.compile(r"``(.*?)``")
_PYTHON_WORDS = {"None": "null", "False": "false", "True": "true"}
_WORD = re.compile(r"\b(None|False|True)\b")


def clean_help(text: str) -> str:
    """API help as a file user reads it: no RST markup, JSON words."""
    text = _ROLE.sub(r"\1", text)
    text = _LITERAL.sub(r"\1", text)
    return _WORD.sub(lambda m: _PYTHON_WORDS[m.group(1)], text)


def help_text(section: str, key: Key) -> str:
    return clean_help(FILE_HELP.get((section, key.name), key.help))


def default_text(key: Key) -> str:
    """What an absent key means: required, the API default, or its meaning."""
    if key.required:
        return "required"
    if key.default is None:
        return clean_help(key.meaning)
    return f"default {to_text(key.default)}"


# Where an error is shown


def anchor(path: tuple, doc) -> tuple:
    """The deepest prefix of ``path`` that has a widget (design §2.5)."""
    if not path or not isinstance(doc, dict):
        return ()
    head = path[0]
    if head in ELEMENTS:
        return _element_anchor(path, doc)
    if head in SETTINGS:
        return _settings_anchor(path)
    return ("description",) if head == "description" else ()


def _element_anchor(path: tuple, doc: dict) -> tuple:
    section = path[0]
    items = doc.get(section)
    if len(path) < 2 or not isinstance(items, list) or path[1] >= len(items):
        return (section,)
    element = items[path[1]]
    if len(path) < 3:
        return path[:2]
    names = [k.name for k in element_keys(section, element)]
    if path[2] not in names:
        return path[:2]
    value = get(element, (path[2],), None)
    name = distribution_of(value)
    if len(path) < 4 or name is None:
        return path[:3]
    sub = ["distribution", *(k.name for k in distribution_keys(name))]
    return path[:4] if path[3] in sub else path[:3]


def _settings_anchor(path: tuple) -> tuple:
    names = [k.name for k in scenario.keys(path[0])]
    if len(path) >= 2 and path[1] in names:
        return path[:2]
    return path[:1]


# Words for lists


def api_default(element: str, name: str, kind: str | None = None):
    """The API default of a key (:func:`scenario.keys`); never a literal."""
    return next(
        k.default for k in scenario.keys(element, kind) if k.name == name
    )


def distribution_words(value) -> str:
    """``LogNormal mean 120.0 std 60.0, ≥ 0.0`` or the number."""
    name = distribution_of(value)
    if name is None:
        return to_text(value)
    fields = [
        f"{k.name} {to_text(value[k.name])}"
        for k in distribution_keys(name)
        if k.name in value and k.name not in ("lower", "upper")
    ]
    bounds = []
    lower = value.get("lower", api_default("distribution", "lower", name))
    upper = value.get("upper", api_default("distribution", "upper", name))
    if lower is not None:
        bounds.append(f"≥ {to_text(lower)}")
    if upper is not None:
        bounds.append(f"≤ {to_text(upper)}")
    text = " ".join([name, *fields])
    return f"{text}, {' '.join(bounds)}" if bounds else text


def row_cells(section: str, element) -> tuple[str, ...]:
    """The list columns of an element (design §3.2)."""
    e = element if isinstance(element, dict) else {}

    def cell(name: str) -> str:
        return to_text(e[name]) if name in e else ""

    if section == "nodes":
        area = cell("area")
        if not area and "length" in e and "width" in e:
            area = f"{cell('length')} × {cell('width')}"
        return cell("name"), cell("kind"), area
    if section == "connections":
        two_way = e.get(
            "bidirectional", api_default("connection", "bidirectional")
        )
        both = "two-way" if two_way is True else ""
        link = f"{cell('source')} → {cell('target')}"
        kind = to_text(e.get("kind", api_default("connection", "kind")))
        return link, kind, cell("width"), both
    count = distribution_words(e["count"]) if "count" in e else ""
    return cell("node"), count, cell("target")


COLUMNS = {
    "nodes": ("name", "kind", "area [m²]"),
    "connections": ("source → target", "kind", "width [m]", ""),
    "populations": ("node", "count", "target"),
}


def references(doc: dict, name: str) -> tuple[int, int]:
    """How many connections and populations name node ``name``."""
    links = sum(
        1
        for c in doc.get("connections", [])
        if isinstance(c, dict) and name in (c.get("source"), c.get("target"))
    )
    pops = sum(
        1
        for p in doc.get("populations", [])
        if isinstance(p, dict) and name in (p.get("node"), p.get("target"))
    )
    return links, pops


def rename(doc: dict, old: str, new: str) -> None:
    """Replace node name ``old`` by ``new`` in connections and populations."""
    fields = {
        "connections": ("source", "target"),
        "populations": ("node", "target"),
    }
    found = [
        (element, field)
        for section, names in fields.items()
        for element in doc.get(section, [])
        if isinstance(element, dict)
        for field in names
        if element.get(field) == old
    ]
    for element, field in found:
        element[field] = new


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def counts(doc: dict) -> str:
    """``3 nodes · 2 connections · 1 population``."""
    return " · ".join(
        plural(len(doc.get(s, [])) if isinstance(doc.get(s), list) else 0, w)
        for s, w in (
            ("nodes", "node"),
            ("connections", "connection"),
            ("populations", "population"),
        )
    )


def shown_path(path) -> str:
    """The path as the TUI shows it and passes it on (design §2.2).

    Relative to the working directory when the file is below it, absolute
    otherwise: the string the CLI would get from the command shown.
    """
    path = Path(path).absolute()
    cwd = Path.cwd()
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def command(path: str, out: str | None, single: bool) -> str:
    """The ``jupedsim-network run`` command of a run."""
    from jupedsim_network import cli_run

    out = out or str(cli_run.default_output(path))
    parts = ["jupedsim-network", "run", _quoted(path), "-o", _quoted(out)]
    if single:
        parts.append("--no-monte-carlo")
    return " ".join(parts)


def _quoted(text: str) -> str:
    import shlex

    return shlex.quote(text)


# Results (design §3.5 and the model review's wording)


OUTCOMES = {
    0: ("✓", "complete"),
    2: ("◐", "incomplete: agents were left at t_max; the results are written"),
    1: ("✗", "error; nothing was written"),
    None: ("■", "cancelled"),
}
# Sentences of using/results.md, "Reporting", without its markup;
# SPREAD_NOTE joins sentences of two bullets. test_tui_model.py
# test_notes_are_sentences_of_results_reporting checks each sentence.
TIME_NOTE = (
    "evacuation_time is pre-movement plus movement of the simulated "
    "occupants. Detection and alarm times are included only if you added "
    "them to pre_movement. Call it an RSET only with that qualification."
)
SPREAD_NOTE = (
    "Quantiles are conditional on the inputs. The 95th percentile describes "
    "the spread caused by the input distributions you chose, not the "
    "uncertainty of the model. A high quantile of a few hundred runs has its "
    "own sampling error."
)


def quantile_rows(summary: dict) -> list[tuple[str, str]]:
    """``(q, value)`` of summary.json, the value as the CLI prints it."""
    from jupedsim_network import cli_run

    rows = []
    for entry in summary["monte_carlo"]["quantiles"]:
        value = entry["value"]
        shown = cli_run._seconds(float("inf") if value is None else value)
        rows.append((f"{entry['q']:g}", shown))
    return rows


def link_rows(summary: dict) -> list[tuple[str, ...]]:
    """Index, name, source → target, kind, capacity of summary.json."""
    return [
        (
            str(link["index"]),
            link["name"],
            f"{link['source']} → {link['target']}",
            link["kind"],
            f"{link['capacity']:.2f}",
        )
        for link in summary["links"]
    ]


@dataclass(frozen=True)
class Occupancy:
    """occupancy.csv as written: times and counts as text."""

    nodes: tuple[str, ...]
    times: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]

    @classmethod
    def parse(cls, text: str) -> "Occupancy":
        header, *rows = list(csv.reader(io.StringIO(text)))
        return cls(
            tuple(header[1:]),
            tuple(r[0] for r in rows),
            tuple(tuple(r[1:]) for r in rows),
        )

    def at(self, step: int) -> dict[str, str]:
        return dict(zip(self.nodes, self.rows[step]))

    def line(self, step: int, seed: str) -> str:
        last = len(self.times) - 1
        return (
            f"occupancy of the single run, seed {seed}: t = {self.times[step]} s "
            f"(step {step} of {last})"
        )


# Recent files


MAX_RECENT = 10


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / "jupedsim-network"


class Recent:
    """``recent.json``: files opened before, the last run status and the theme.

    A file that cannot be read or written is ignored: the TUI works
    without it.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or config_dir() / "recent.json"
        self.data: dict = {"theme": None, "files": []}
        with contextlib.suppress(OSError, ValueError, TypeError):
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update(loaded)
        if not isinstance(self.data.get("files"), list):
            self.data["files"] = []

    @property
    def theme(self) -> str | None:
        theme = self.data.get("theme")
        return theme if theme in THEMES else None

    @property
    def files(self) -> list[dict]:
        return [
            f
            for f in self.data["files"]
            if isinstance(f, dict) and isinstance(f.get("path"), str)
        ]

    def set_theme(self, theme: str) -> None:
        self.data["theme"] = theme
        self._save()

    def add(self, path: str, date: str, status: str = "") -> None:
        """Put ``path`` first; an empty ``status`` keeps the last one."""
        absolute = str(Path(path).absolute())
        old = next((f for f in self.files if f["path"] == absolute), {})
        entry = {
            "path": absolute,
            "date": date,
            "status": status or old.get("status", ""),
        }
        rest = [f for f in self.files if f["path"] != absolute]
        self.data["files"] = [entry, *rest][:MAX_RECENT]
        self._save()

    def _save(self) -> None:
        with contextlib.suppress(OSError):
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(self.data, indent=2) + "\n", encoding="utf-8"
            )
            tmp.replace(self.path)


# Browsing for a file (ported from pyFDS-Evac's tui.model)


BROWSE_LIMIT = 200


def match_rank(typed: str, name: str) -> int | None:
    """0 if ``name`` starts with ``typed``, 1 if it contains it, 2 if it
    holds its letters in order, else None; case-insensitive (fzf-like)."""
    typed, name = typed.lower(), name.lower()
    if name.startswith(typed):
        return 0
    if typed in name:
        return 1
    letters = iter(name)
    return 2 if all(c in letters for c in typed) else None


def _scenario_entry(entry: os.DirEntry) -> bool | None:
    if entry.is_dir():
        return False
    return True if entry.name.lower().endswith(".json") else None


def browse(text: str, keep: Callable = _scenario_entry):
    """The folder ``text`` points into and its folders and ``.json`` files.

    ``"/a/b/"`` lists all of ``/a/b``; ``"/a/b/sc"`` the entries of
    ``/a/b`` that match ``sc`` as fzf does. Hidden entries show only when
    the typed name starts with a dot. Each entry comes with whether it is
    a file. At most :data:`BROWSE_LIMIT`.
    """
    raw = os.path.expanduser(text.strip())
    if not raw:
        return None, []
    head, prefix = os.path.split(raw)
    folder = Path(head or ".")
    try:
        entries = sorted(os.scandir(folder), key=lambda e: e.name.lower())
    except OSError:
        return folder, []
    ranked = []
    for entry in entries:
        rank = _rank(entry, prefix, keep)
        if rank is not None:
            ranked.append(
                (rank[0], entry.name.lower(), Path(entry.path), rank[1])
            )
    ranked.sort(key=lambda r: (r[0], r[1]))
    return folder, [
        (path, flag) for _r, _n, path, flag in ranked[:BROWSE_LIMIT]
    ]


def _rank(entry, prefix: str, keep):
    if entry.name.startswith(".") and not prefix.startswith("."):
        return None
    rank = match_rank(prefix, entry.name)
    if rank is None:
        return None
    try:
        flag = keep(entry)
    except OSError:
        return None
    return None if flag is None else (rank, flag)


def complete(text: str) -> str:
    """``text`` completed as far as its matching names agree, as a shell does."""
    folder, found = browse(text)
    if folder is None or not found:
        return text
    typed = os.path.split(os.path.expanduser(text.strip()))[1]
    starting = [e for e in found if match_rank(typed, e[0].name) == 0]
    found = starting or found
    if len(found) == 1:
        path = found[0][0]
        return str(path) if found[0][1] else str(path) + os.sep
    common = os.path.commonprefix([p.name for p, _flag in found])
    if len(common) <= len(typed):
        return text
    return str(folder / common)


def frozen(doc: dict) -> dict:
    """A deep copy that later edits cannot reach (the run's snapshot)."""
    return copy.deepcopy(doc)
