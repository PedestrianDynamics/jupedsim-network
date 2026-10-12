# SPDX-License-Identifier: LGPL-3.0-or-later
"""The terminal UI: Scenario → Edit → Check → Run → Results (design #47).

The TUI is a form editor over the JSON scenario file plus the command
line's own ``check`` and ``run``. It adds no numbers of its own: Check
shows what ``jupedsim-network check FILE`` prints, Run is
``jupedsim-network run FILE -o DIR`` (:mod:`jupedsim_network.cli_run`),
and every value, default and check is the loader's.

Look and keys follow pyFDS-Evac's TUI. Seam for tests: ``engine`` (an
object with ``start()``, ``submit(job, post, key=None)``, ``cancel()``,
``stop()`` and ``busy``); every call into the package is a job on its one
thread (:mod:`.engine`).
"""

import asyncio
import contextlib
import contextvars
import copy
import datetime
import json
import os
import shutil
import sys
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from textual import on, work
from textual.app import App, ComposeResult, SystemCommand
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.content import Content
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    ContentSwitcher,
    DataTable,
    Input,
    OptionList,
    Select,
    Static,
    Switch,
    TabbedContent,
    TabPane,
)
from textual.widgets.option_list import Option

from jupedsim_network import cli_init, cli_run
from jupedsim_network.tui import engine as jobs
from jupedsim_network.tui import model, netview
from jupedsim_network.tui.theme import NETWORK_DARK, THEME_NAMES
from jupedsim_network.tui.widgets import (
    STEP_TITLES,
    AskPathScreen,
    BrowseList,
    ConfirmScreen,
    ElementList,
    FieldRow,
    FileScreen,
    FormScroll,
    NetworkFooter,
    PathBox,
    SectionHead,
    StatusLine,
    StepBar,
    TextBox,
    TextScreen,
    TooSmall,
    m,
    slug,
)

STEPS = ("scenario", "edit", "check", "run", "results")
SECTIONS = ("nodes", "connections", "populations")
MIN_SIZE = (80, 24)
COLOR_SYSTEM_COLOURS = {"256": "256", "standard": "16", "windows": "16"}
RECENT_GLYPHS = {
    "complete": "✓ ",
    "incomplete": "◐ ",
    "error": "✗ ",
    "cancelled": "■ ",
}
STATUS_WORDS = {0: "complete", 2: "incomplete", 1: "error", None: "cancelled"}
NUMBER = "number"
PREVIEW_LINES = 40


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="minutes")


def _clock(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds // 60}:{seconds % 60:02d}"


def _bar(fraction: float, width: int) -> Content:
    n = max(0, min(width, int(round(fraction * width))))
    return m(
        "[$primary]$a[/][$text-muted]$b[/]", a="█" * n, b="░" * (width - n)
    )


@dataclass
class RunState:
    """One run: its frozen snapshot and what the engine reported."""

    path: str
    out: str
    single: bool
    snapshot: dict
    runs: int | None
    started: float
    phase: str = "single run"
    done: int = 0
    cancelling: bool = False
    finished: jobs.RunFinished | None = None
    ended: float | None = None

    @property
    def wall(self) -> float:
        return (self.ended or time.monotonic()) - self.started


# --- steps ---------------------------------------------------------------------


class Step(Vertical):
    """A step of the flow; :meth:`enter` runs when it becomes current."""

    @property
    def tui(self) -> "NetworkTui":
        return cast("NetworkTui", self.app)

    def enter(self) -> None:
        """Focus the step's first control."""


class ScenarioStep(Step):
    BINDINGS = [Binding("ctrl+n", "app.next_step", "next")]

    def compose(self) -> ComposeResult:
        with TabbedContent(id="sc-tabs"):
            with TabPane("Recent", id="tab-recent"):
                yield OptionList(id="recent")
            with TabPane("Examples", id="tab-examples"):
                yield OptionList(id="examples")
            with TabPane("Open file", id="tab-open"):
                yield PathBox(
                    placeholder="path to a scenario .json (Tab completes, ~ is home)",
                    id="open-path",
                )
                yield BrowseList("#open-path", id="open-list")
        yield Static(id="sc-info")
        yield Static(id="sc-error")

    def enter(self) -> None:
        tab = self.query_one("#sc-tabs", TabbedContent).active
        focus = {"tab-recent": "#recent", "tab-examples": "#examples"}
        self.query_one(focus.get(tab, "#open-path")).focus()


class EditStep(Step):
    BINDINGS = [
        Binding("ctrl+n", "app.next_step", "check"),
        Binding("ctrl+p", "app.step_back", "scenario"),
        Binding("ctrl+s", "app.save", "save"),
        Binding("ctrl+r", "app.run", "run"),
        Binding("left_square_bracket", "app.tab(-1)", "tab", key_display="[ ]"),
        Binding("right_square_bracket", "app.tab(1)", "next tab", show=False),
    ]

    def compose(self) -> ComposeResult:
        with TabbedContent(id="ed-tabs"):
            for section in SECTIONS:
                yield _section_pane(section)
            with TabPane("Settings", id="tab-settings"):
                yield FormScroll(id="form-settings", classes="form")

    def enter(self) -> None:
        tabs = self.query_one("#ed-tabs", TabbedContent)
        section = (tabs.active or "tab-nodes")[4:]
        if section in SECTIONS:
            self.query_one(f"#list-{section}").focus()
            return
        controls = self.query("#form-settings .control")
        if controls:
            controls.first().focus()
            return
        # The form is still being built: focus its first field when it is.
        self.tui._focus_after = ("description",)


def _section_pane(section: str) -> TabPane:
    """A list tab: the elements, and the form of the selected one."""
    detail = Vertical(
        SectionHead(id=f"head-{section}"),
        FormScroll(id=f"form-{section}", classes="form"),
        classes="detail",
    )
    body = Horizontal(
        ElementList(section, id=f"list-{section}"),
        detail,
        classes="master-detail",
    )
    return TabPane(section.capitalize(), body, id=f"tab-{section}")


class CheckStep(Step):
    BINDINGS = [
        Binding("ctrl+n", "app.next_step", "run step"),
        Binding("ctrl+p", "app.step_back", "edit"),
        Binding("ctrl+r", "app.run", "run"),
        Binding("ctrl+s", "app.save", "save", show=False),
        Binding("c", "app.copy_command", "copy command"),
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="ck-outcome")
        yield OptionList(id="ck-errors")
        with Horizontal(id="ck-body"):
            with VerticalScroll(id="ck-left"):
                yield Static(id="ck-text")
                yield Static(id="ck-tree-narrow", classes="tree narrow")
            with VerticalScroll(id="ck-right"):
                yield Static(id="ck-tree-wide", classes="tree")
        yield Static(id="ck-command")

    def enter(self) -> None:
        errors = self.query_one("#ck-errors", OptionList)
        (errors if errors.option_count else self.query_one("#ck-left")).focus()


class RunStep(Step):
    BINDINGS = [
        Binding("ctrl+r", "app.run", "run"),
        Binding("x", "app.cancel", "cancel"),
        Binding("ctrl+c", "app.cancel", "cancel", show=False, priority=True),
        Binding("ctrl+p", "app.step_back", "check"),
        Binding("ctrl+n", "app.next_step", "results", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield RunStatus(id="run-status")
        with Horizontal(classes="plain-row"):
            yield Static("Output folder", classes="label")
            yield TextBox(id="run-out", compact=True)
        yield Static(id="run-out-help", classes="help-line")
        with Horizontal(classes="plain-row"):
            yield Static("Single run only", classes="label")
            yield Switch(False, id="run-single")
        yield Static(
            m("[dim]= --no-monte-carlo: the single run, no Monte Carlo set[/]"),
            classes="help-line",
        )
        yield Static(id="run-command")
        yield Static(id="run-note")

    def enter(self) -> None:
        run = self.tui.current_run
        running = run is not None and run.finished is None
        self.query_one("#run-status" if running else "#run-out").focus()


class RunStatus(Static, can_focus=True):
    """The state of the run; holds the focus while it runs, for x and ctrl+c."""


class ResultsStep(Step):
    BINDINGS = [
        Binding("ctrl+r", "app.run", "run again"),
        Binding("ctrl+p", "app.step_back", "run step"),
        Binding(
            "left", "app.scrub(-1)", "time", key_display="←/→", priority=True
        ),
        Binding("right", "app.scrub(1)", "+1 step", show=False, priority=True),
        Binding(
            "shift+left", "app.scrub(-10)", "−10", show=False, priority=True
        ),
        Binding(
            "shift+right", "app.scrub(10)", "+10", show=False, priority=True
        ),
        Binding("e", "app.edit", "edit"),
        Binding("n", "app.new_scenario", "new"),
        Binding("c", "app.copy_command", "command"),
        Binding("w", "app.warnings", "warnings"),
        Binding("y", "app.copy_path", "copy path", show=False),
        Binding("t", "app.traceback", "traceback", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Static(id="res-banner")
        with Horizontal(id="res-body"):
            with VerticalScroll(id="res-left"):
                yield Static(id="res-outcome")
                yield Static(id="res-tree-narrow", classes="tree narrow")
            with VerticalScroll(id="res-right"):
                yield Static(id="res-tree-wide", classes="tree")
        yield Static(m("[b]Output files[/]"), id="res-files-title")
        yield OptionList(id="res-files")

    def enter(self) -> None:
        files = self.query_one("#res-files", OptionList)
        (files if files.option_count else self.query_one("#res-left")).focus()


# --- the app -------------------------------------------------------------------


class NetworkTui(App[None]):
    """``jupedsim-network tui``."""

    TITLE = "jupedsim-network"
    ENABLE_COMMAND_PALETTE = True
    # ``ctrl+p`` is "previous step", paired with ``ctrl+n``.
    COMMAND_PALETTE_BINDING = "ctrl+k"
    CSS = """
    Screen { layout: vertical; }
    #stepbar { height: 1; background: $panel; padding: 0 1; }
    #steps { height: 1fr; }
    Step { height: 1fr; }
    #sc-tabs { height: 1fr; }
    #sc-info, #sc-error { height: auto; padding: 0 1; }
    #sc-error { color: $error; }
    #examples, #recent, #open-list { height: 1fr; }
    #ed-tabs { height: 1fr; }
    .master-detail { layout: vertical; height: 1fr; }
    ElementList { height: auto; max-height: 7; }
    .detail { height: 1fr; }
    .form { height: 1fr; }
    NetworkTui.-wide .master-detail { layout: horizontal; }
    NetworkTui.-wide ElementList { width: 1fr; height: 1fr; max-height: 100%; }
    NetworkTui.-wide .detail { width: 1fr; }
    .plain-row { height: auto; padding: 0 0 0 1; }
    .plain-row .label { width: 26; padding: 0 1 0 0; }
    .plain-row Input { width: 1fr; max-width: 48; }
    .plain-row Switch { width: 6; height: 1; border: none; padding: 0; }
    .help-line { color: $text-muted; padding: 0 0 0 2; height: auto; }
    #ck-outcome { height: auto; padding: 0 1; }
    #ck-errors { height: auto; max-height: 3; }
    #ck-body, #res-body { height: 1fr; }
    #ck-left, #res-left { width: 1fr; padding: 0 1; }
    #ck-right, #res-right { width: 1fr; padding: 0 1; display: none; }
    #ck-command { height: auto; padding: 0 1; background: $surface; }
    NetworkTui.-wide #ck-right, NetworkTui.-wide #res-right { display: block; }
    NetworkTui.-wide .narrow { display: none; }
    .tree { height: auto; }
    #run-status { height: auto; padding: 0 1 1 1; }
    #run-command, #run-note { height: auto; padding: 1 1 0 1; }
    #res-banner { height: auto; padding: 0 1; color: $warning; }
    #res-files-title { height: 1; padding: 0 1; }
    #res-files { height: auto; max-height: 5; }
    NetworkTui.-wide #res-files { max-height: 7; }
    """
    BINDINGS = [
        Binding("ctrl+q", "quit", "quit", priority=True, show=False),
        Binding("ctrl+r", "run", "run", show=False),
        Binding("escape", "step_back", "back", show=False),
        Binding(
            "question_mark", "field_help", "keys", priority=True, show=False
        ),
        Binding("f1", "field_help", "help", show=False),
    ]

    def __init__(
        self,
        *,
        theme: str | None = None,
        scenario: str | None = None,
        cwd: Path | None = None,
        engine: Any = None,
        recent: model.Recent | None = None,
        debounce: float = 0.15,
    ) -> None:
        self.cwd = Path(cwd or Path.cwd()).absolute()
        self.recent = recent if recent is not None else model.Recent()
        self.engine = engine if engine is not None else jobs.Engine()
        self.debounce = debounce
        self.start_theme = theme or self.recent.theme or model.DEFAULT_THEME
        self.start_file = scenario
        self.step = 0
        # The document and what is on disk.
        self.doc: dict | None = None
        self.saved: dict | None = None
        self.path: str | None = None
        self.example: str | None = None
        # The first error of the loader: (path, anchor, message); warnings.
        self.error: tuple[tuple, tuple, str] | None = None
        self.doc_warnings: tuple[str, ...] = ()
        self.validated = False
        self._gen = 0
        self._timer: Any = None
        self.typed: dict[tuple, str] = {}
        self.memory: dict[tuple, dict] = {}
        self.renaming: dict[tuple, str] = {}
        self.selected: dict[str, int] = dict.fromkeys(SECTIONS, 0)
        self._shown: dict[str, tuple] = {}
        self._focus_after: tuple | None = None
        self._settings_stale = True
        self._form_lock = asyncio.Lock()
        self.checked: jobs.Checked | None = None
        self.checking = False
        self.current_run: RunState | None = None
        self.scrub_index = 0
        self.occupancy: model.Occupancy | None = None
        self.failure: jobs.Failed | None = None
        self.open_folder: Path | None = None
        self.open_found: list = []
        self._after_save: Any = None
        self._ui_loop: asyncio.AbstractEventLoop | None = None
        self._ui_context = contextvars.copy_context()
        self._render_timer: Any = None
        self._quitting = False
        super().__init__()

    @property
    def base(self) -> Any:
        """The main screen: queries reach the steps also under a dialog."""
        return self.screen_stack[0] if self.screen_stack else self

    # --- set-up --------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield StepBar(id="stepbar")
        with ContentSwitcher(initial="step-scenario", id="steps"):
            yield ScenarioStep(id="step-scenario")
            yield EditStep(id="step-edit")
            yield CheckStep(id="step-check")
            yield RunStep(id="step-run")
            yield ResultsStep(id="step-results")
        yield StatusLine(id="summary")
        yield NetworkFooter()

    def on_mount(self) -> None:
        self._ui_loop = asyncio.get_running_loop()
        # Textual's context (the active app), for events from the engine.
        self._ui_context = contextvars.copy_context()
        # Built once and reused: the keys list opens without composing.
        self.install_screen(TextScreen("Keys", keys_text()), name="keys")
        self.register_theme(NETWORK_DARK)
        self.theme = self.start_theme
        self.engine.start()
        self._fill_recent()
        self._fill_examples()
        self._browse_open(f"{self.cwd}{os.sep}")
        tabs = self.base.query_one("#sc-tabs", TabbedContent)
        tabs.active = "tab-recent" if self.recent.files else "tab-examples"
        self.base.query_one(
            "#recent" if self.recent.files else "#examples"
        ).focus()
        if self.start_file:
            self.engine.submit(jobs.open_file(self.start_file), self._post)
        self.update_chrome()
        self._check_size()
        self._warn_color_system()

    def _warn_color_system(self) -> None:
        """Say when the terminal shows fewer colours than the theme needs."""
        colours = COLOR_SYSTEM_COLOURS.get(str(self.console.color_system))
        if self.no_color or colours is None:
            return
        self.notify(
            f"This terminal shows {colours} colours, so the theme colours are "
            "approximate. If it supports truecolor, set COLORTERM=truecolor.",
            timeout=15,
            markup=False,
        )

    def exit(self, *args: Any, **kwargs: Any) -> None:
        """Quit; events that the engine posts from now on are dropped."""
        self._quitting = True
        super().exit(*args, **kwargs)

    def on_unmount(self) -> None:
        """Drop queued jobs and wait for the current realisation."""
        self._quitting = True
        self.engine.stop()

    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        for command in super().get_system_commands(screen):
            if command.title != "Theme":
                yield command
        for name, title in THEME_NAMES.items():
            yield SystemCommand(
                f"Theme: {title}",
                f"Switch to the {title} theme",
                lambda n=name: self.set_theme(n),
            )
        for i, title in enumerate(STEP_TITLES):
            yield SystemCommand(
                f"Go to step {i + 1}: {title}", "", lambda i=i: self.goto(i)
            )
        yield SystemCommand("Save as", "Save under another name", self.save_as)
        yield SystemCommand(
            "Copy command",
            "The jupedsim-network run command",
            self.action_copy_command,
        )
        yield SystemCommand("Open docs page", model.DOCS_URL, self.show_docs)

    def set_theme(self, name: str) -> None:
        self.theme = name
        self.recent.set_theme(name)

    def show_docs(self) -> None:
        self.notify(f"Docs: {model.DOCS_URL}", timeout=10, markup=False)

    def on_resize(self, event: Any) -> None:
        self._check_size(event.size)

    def _check_size(self, size: Any = None) -> None:
        if not self.screen_stack:
            return  # the app is closing
        w, h = size or self.size
        self.set_class(w >= 120 and h >= 35, "-wide")
        small = w < MIN_SIZE[0] or h < MIN_SIZE[1]
        notice = self.screen if isinstance(self.screen, TooSmall) else None
        if small and notice is None:
            screen = TooSmall()
            self.push_screen(screen)
            self.call_after_refresh(screen.show, w, h)
        elif small and notice is not None:
            notice.show(w, h)
        elif not small and notice is not None:
            self.pop_screen()
        self.update_chrome()

    # --- events from the engine ----------------------------------------------

    def _post(self, event: Any) -> None:
        """From the engine thread: queue ``event`` for the UI, never wait."""
        loop = self._ui_loop
        if self._quitting or loop is None or loop.is_closed():
            return
        with contextlib.suppress(RuntimeError):  # the app has ended
            loop.call_soon_threadsafe(
                self.on_engine_event, event, context=self._ui_context
            )

    def on_engine_event(self, event: Any) -> None:
        if self._quitting:
            return
        handlers = {
            jobs.Validated: self._validated,
            jobs.Opened: self._opened,
            jobs.Saved: self._saved,
            jobs.Checked: self._checked,
            jobs.Progress: self._progress,
            jobs.RunFinished: self._run_finished,
            jobs.Failed: self._failed,
        }
        handlers[type(event)](event)

    def _failed(self, event: jobs.Failed) -> None:
        self.failure = event
        self.checking = False
        run = self.current_run
        if event.what == "run" and run is not None and run.finished is None:
            run.ended = time.monotonic()
            run.finished = jobs.RunFinished(run.path, run.out, 1)
            self.goto(4)
        self.notify(
            f"✗ internal error in {event.what}; press t on Results for the "
            "traceback",
            severity="error",
            markup=False,
        )
        self.update_chrome()

    # --- navigation ------------------------------------------------------------

    def goto(self, index: int) -> None:
        if index in (1, 2, 3) and self.doc is None:
            self.notify("Open a scenario or an example first.")
            return
        if index == 4 and (
            self.current_run is None or self.current_run.finished is None
        ):
            self.notify("No finished run yet.")
            return
        self.step = index
        self.base.query_one(
            "#steps", ContentSwitcher
        ).current = f"step-{STEPS[index]}"
        if index == 3:
            self.render_run()
        if index == 4:
            self.render_results()
        self.update_chrome()
        self.base.query_one(f"#step-{STEPS[index]}", Step).enter()

    def action_next_step(self) -> None:
        if self.step == 0:
            self._accept_scenario_tab()
        elif self.step == 1:
            self.action_check()
        elif self.step == 2:
            self.goto(3)
        elif self.step == 3 and self.current_run and self.current_run.finished:
            self.goto(4)

    def action_step_back(self) -> None:
        if self.step in (1, 2, 3, 4):
            self.goto(self.step - 1 if self.step != 4 else 3)

    def action_edit(self) -> None:
        self.goto(1)

    def action_new_scenario(self) -> None:
        self.goto(0)

    def action_tab(self, delta: int) -> None:
        tabs = self.base.query_one("#ed-tabs", TabbedContent)
        ids = [f"tab-{s}" for s in (*SECTIONS, "settings")]
        current = ids.index(tabs.active) if tabs.active in ids else 0
        tabs.active = ids[(current + delta) % len(ids)]
        self.base.query_one("#step-edit", EditStep).enter()

    def action_move_field(self, delta: int) -> None:
        if delta > 0:
            self.screen.focus_next()
        else:
            self.screen.focus_previous()

    def check_action(
        self, action: str, parameters: tuple[object, ...]
    ) -> bool | None:
        if not self.screen_stack:
            return False  # the app is closing
        if action == "move_field":
            # An open dropdown keeps up/down for its own list.
            return not any(s.expanded for s in self.screen.query(Select))
        if action == "run":
            return self.step in (1, 2, 3, 4)
        if action == "field_help":
            return not isinstance(self.screen, ModalScreen)
        return True

    # --- scenario step ---------------------------------------------------------

    def _fill_recent(self) -> None:
        recent = self.base.query_one("#recent", OptionList)
        recent.clear_options()
        for i, entry in enumerate(self.recent.files):
            path = Path(entry["path"])
            status = str(entry.get("status", ""))
            line = m(
                "$n  [dim]$p[/]  $s  [dim]$d[/]",
                n=path.name,
                p=model.shown_path(path.parent) + os.sep,
                s=RECENT_GLYPHS.get(status, "") + status,
                d=str(entry.get("date", ""))[:16],
            )
            option = Option(line, id=f"recent-{i}")
            if not path.exists():
                option = Option(
                    m("[dim]$l  missing[/]", l=line.plain), id=f"recent-{i}"
                )
            recent.add_option(option)
        if recent.option_count:
            recent.highlighted = 0

    def _fill_examples(self) -> None:
        options = self.base.query_one("#examples", OptionList)
        options.clear_options()
        for name in cli_init.EXAMPLES:
            data = json.loads(cli_init.example_bytes(name))
            first = data.get("description", "").split(". ")[0].rstrip(".")
            options.add_option(
                Option(
                    m("[b]$n[/]\n  [dim]$d.[/]", n=name, d=first),
                    id=f"ex-{name}",
                )
            )
        options.highlighted = 0

    @on(OptionList.OptionSelected, "#examples")
    def _example_selected(self, event: OptionList.OptionSelected) -> None:
        self.open_example(str(event.option.id)[3:])

    def open_example(self, name: str) -> None:
        self.engine.submit(jobs.open_example(name), self._post)

    @on(OptionList.OptionSelected, "#recent")
    def _recent_selected(self, event: OptionList.OptionSelected) -> None:
        entry = self.recent.files[int(str(event.option.id)[7:])]
        self.open_file(entry["path"])

    def open_file(self, path: str) -> None:
        self.engine.submit(jobs.open_file(model.shown_path(path)), self._post)

    @on(Input.Submitted, "#open-path")
    def _open_path(self, event: Input.Submitted) -> None:
        self._open_typed(event.value)

    def _open_typed(self, text: str) -> None:
        path = Path(os.path.expanduser(text.strip()))
        if path.is_dir():
            self._go_into(path)
            return
        self.open_file(str(path))

    @on(Input.Changed, "#open-path")
    def _open_path_changed(self, event: Input.Changed) -> None:
        self._browse_open(event.value or f"{self.cwd}{os.sep}")

    @work(thread=True, exclusive=True, group="browse-open")
    def _browse_open(self, text: str) -> None:
        folder, found = model.browse(text)
        self.call_from_thread(self._show_open, text, folder, found)

    def _show_open(self, text: str, folder: Path | None, found: list) -> None:
        typed = self.base.query_one("#open-path", Input).value
        if text != (typed or f"{self.cwd}{os.sep}") or folder is None:
            return
        self.open_folder, self.open_found = folder, found
        listing = self.base.query_one("#open-list", OptionList)
        listing.clear_options()
        if folder.parent != folder:
            listing.add_option(Option(m("..  [dim]up[/]"), id="up"))
        for i, (path, is_file) in enumerate(found):
            name = path.name + ("" if is_file else os.sep)
            listing.add_option(Option(name, id=f"e-{i}"))
        if not found:
            listing.add_option(
                Option(m("[dim]No folder or .json here[/]"), disabled=True)
            )
        # After a typed name, the first match (not ".."), so Enter picks it.
        typed = bool(os.path.split(text)[1]) and bool(found)
        listing.highlighted = 1 if typed and folder.parent != folder else 0

    @on(OptionList.OptionSelected, "#open-list")
    def _open_choice(self, event: OptionList.OptionSelected) -> None:
        folder, ident = self.open_folder, str(event.option.id)
        if folder is None:
            return
        if ident == "up":
            self._go_into(folder.parent)
            return
        path, is_file = self.open_found[int(ident[2:])]
        if is_file:
            self.open_file(str(path))
        else:
            self._go_into(path)

    def _go_into(self, folder: Path) -> None:
        box = self.base.query_one("#open-path", Input)
        box.value = str(folder) + os.sep
        box.cursor_position = len(box.value)

    def action_complete_path(self) -> None:
        box = self.base.query_one("#open-path", Input)
        completed = model.complete(box.value)
        if completed != box.value:
            box.value = completed
            box.cursor_position = len(completed)
        elif self.focused is box:
            self.base.query_one("#open-list").focus()
        else:
            box.focus()

    def action_focus_choices(self) -> None:
        self.base.query_one("#open-list").focus()

    def _accept_scenario_tab(self) -> None:
        tab = self.base.query_one("#sc-tabs", TabbedContent).active
        lists = {"tab-recent": "#recent", "tab-examples": "#examples"}
        if tab == "tab-open":
            self._open_typed(self.base.query_one("#open-path", Input).value)
            return
        options = self.base.query_one(lists[tab], OptionList)
        if options.highlighted is not None and options.option_count:
            options.action_select()
        elif self.doc is not None:
            self.goto(1)

    def _opened(self, event: jobs.Opened) -> None:
        if event.doc is None:
            self.base.query_one("#sc-error", Static).update(
                m("$e", e=event.error)
            )
            self.goto(0)
            return
        self.base.query_one("#sc-error", Static).update("")
        self.load_doc(event.doc, event.path, event.example)
        if event.path is not None:
            self.recent.add(event.path, _now())
            self._fill_recent()
        self.goto(1)

    # --- the document ------------------------------------------------------------

    def load_doc(
        self, doc: dict, path: str | None, example: str | None
    ) -> None:
        """Show ``doc``; ``path`` None for an unsaved example."""
        self.doc = doc
        self.saved = copy.deepcopy(doc) if path is not None else None
        self.path = path
        self.example = example
        self.error, self.doc_warnings, self.validated = None, (), False
        self.typed.clear()
        self.memory.clear()
        self.renaming.clear()
        self._focus_after = None
        self.selected = dict.fromkeys(SECTIONS, 0)
        self._shown.clear()
        self.checked = None
        for section in SECTIONS:
            self._fill_list(section)
        self.rebuild_forms()
        self.schedule_validate()

    def rebuild_forms(self) -> None:
        """Mark every form stale; a form is built when its tab is shown.

        Building all four forms on opening a file held the app for about
        0.25 s, so a key pressed right then waited for it (the slow first
        dialog of QA2-O4).
        """
        self._shown.clear()
        self._settings_stale = True
        self.call_later(self._rebuild_visible)

    async def _rebuild_visible(self) -> None:
        tabs = self.base.query_one("#ed-tabs", TabbedContent)
        section = (tabs.active or "tab-nodes")[4:]
        if section in SECTIONS:
            await self._rebuild_form(section)
        elif self._settings_stale:
            await self._rebuild_settings()

    @on(TabbedContent.TabActivated, "#ed-tabs")
    async def _tab_shown(self, event: TabbedContent.TabActivated) -> None:
        await self._rebuild_visible()

    @property
    def title_text(self) -> str:
        if self.path is not None:
            return self.path
        return f"untitled ({self.example})" if self.example else "untitled"

    @property
    def dirty(self) -> bool:
        return self.doc is not None and (
            self.path is None or self.doc != self.saved
        )

    def _fill_list(self, section: str) -> None:
        table = self.base.query_one(f"#list-{section}", ElementList)
        if not table.columns:
            table.add_columns(" ", "#", *model.COLUMNS[section])
        table.clear()
        items = self._items(section)
        for i, element in enumerate(items):
            mark = "✗" if self._error_in((section, i)) else " "
            table.add_row(
                mark, str(i), *model.row_cells(section, element), key=str(i)
            )
        if items:
            index = min(self.selected[section], len(items) - 1)
            self.selected[section] = index
            table.move_cursor(row=index)

    def _items(self, section: str) -> list:
        items = self.doc.get(section) if self.doc else None
        return items if isinstance(items, list) else []

    def _error_in(self, prefix: tuple) -> bool:
        if self.error is None:
            return False
        return self.error[1][: len(prefix)] == prefix

    @on(DataTable.RowHighlighted, "ElementList")
    async def _row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        table = cast(ElementList, event.data_table)
        self.selected[table.section] = event.cursor_row
        await self._rebuild_visible()  # a hidden form waits for its tab

    async def _rebuild_form(self, section: str) -> None:
        async with self._form_lock:
            form = self.base.query_one(f"#form-{section}", FormScroll)
            items = self._items(section)
            index = self.selected[section]
            element = items[index] if index < len(items) else None
            shown = (index, self._shape(section, element))
            if self._shown.get(section) == shown and form.children:
                self._refresh_rows()
                return
            self._shown[section] = shown
            await form.remove_children()
            if element is not None:
                await form.mount_all(
                    self._element_rows(section, index, element)
                )
            self._refresh_rows()
            self._focus_pending()

    def _shape(self, section: str, element) -> tuple:
        """What decides the rows of a form: keys, node kind, distribution types."""
        if not isinstance(element, dict):
            return (id(element),)
        kinds = tuple(
            (k, model.distribution_of(v) or type(v).__name__)
            for k, v in element.items()
        )
        return (id(element), element.get("kind"), kinds)

    def _element_rows(
        self, section: str, index: int, element
    ) -> list[FieldRow]:
        rows: list[FieldRow] = []
        for key in model.element_keys(section, element):
            path = (section, index, key.name)
            if section == "populations" and model.is_distributed(key):
                rows += self._distributed_rows(path, key)
            else:
                rows.append(self._row(path, key, model.ELEMENTS[section]))
        return rows

    def _row(
        self, path: tuple, key, help_section: str, label: str = ""
    ) -> FieldRow:
        value = model.get(self.doc, path, model.MISSING)
        present = value is not model.MISSING
        label = label or key.name
        if key.choices:
            row = FieldRow(
                path, label, "select", value if present else None, key.choices
            )
        elif key.annotation is bool:
            state = value if isinstance(value, bool) else bool(key.default)
            row = FieldRow(path, label, "switch", state)
        else:
            row = FieldRow(path, label, "input", self._text(path, value, key))
        row.key = key
        row.help_section = help_section
        return row

    def _text(self, path: tuple, value, key) -> str:
        """The text of an input: as typed while it still means the value."""
        if value is model.MISSING:
            return ""
        typed = self.typed.get(path)
        if typed is not None and model.to_json(typed, key.annotation) == (
            True,
            value,
        ):
            return typed
        return model.to_text(value)

    def _distributed_rows(self, path: tuple, key) -> list[FieldRow]:
        value = model.get(self.doc, path, model.MISSING)
        name = model.distribution_of(value)
        present = value is not model.MISSING
        kind = name or (NUMBER if present else None)
        choices = (NUMBER, *model.distribution_names())
        head = FieldRow(path, key.name, "dtype", kind, choices, suffix="-type")
        head.key, head.help_section = key, "population"
        if name is None:
            return [head, self._row(path, key, "population", f"└ {NUMBER}")]
        rows = [head]
        for sub in model.distribution_keys(name):
            rows.append(
                self._row(
                    (*path, sub.name), sub, "distribution", f"└ {sub.name}"
                )
            )
        return rows

    async def _rebuild_settings(self) -> None:
        async with self._form_lock:
            form = self.base.query_one("#form-settings", FormScroll)
            self._settings_stale = False
            await form.remove_children()
            await form.mount_all(self._settings_rows())
            self._refresh_rows()
            self._focus_pending()

    def _settings_rows(self) -> list:
        from jupedsim_network import scenario

        doc_keys = {k.name: k for k in scenario.keys("document")}
        rows: list = [SectionHead(m("[b]Document[/]"), id="head-document")]
        rows.append(
            self._row(("description",), doc_keys["description"], "document")
        )
        for section in model.SETTINGS:
            rows.append(SectionHead(id=f"head-{section}"))
            rows += self._section_rows(section, doc_keys[section])
        return rows

    def _section_rows(self, section: str, key) -> list[FieldRow]:
        """The rows of a settings section; Monte Carlo has an on/off switch."""
        from jupedsim_network import scenario

        rows = []
        if section == "monte_carlo":
            present = isinstance(self.doc.get("monte_carlo"), dict)
            switch = FieldRow(
                (section,), "Monte Carlo section", "switch", present
            )
            switch.key, switch.help_section = key, "document"
            rows.append(switch)
            if not present:
                return rows
        for sub in scenario.keys(section):
            rows.append(self._row((section, sub.name), sub, section))
        return rows

    def _focus_pending(self) -> None:
        """Focus the field asked for; it waits until its form is built."""
        path = self._focus_after
        if path is None:
            return
        rows = list(self.base.query(f"#row-{slug(path)}").results(FieldRow))
        rows += list(
            self.base.query(f"#row-{slug(path)}-type").results(FieldRow)
        )
        if rows:
            self._focus_after = None
            self.call_after_refresh(rows[0].control.focus)
            self.call_after_refresh(rows[0].scroll_visible)

    # --- states of rows and heads ----------------------------------------------

    def _refresh_rows(self) -> None:
        anchor = None if self.error is None else self.error[1]
        message = "" if self.error is None else self.error[2]
        for row in self.base.query(FieldRow).results(FieldRow):
            self._show_row(row, anchor, message)
        for section in (*SECTIONS, *model.SETTINGS):
            self._show_head(section, anchor, message)

    def _show_row(self, row: FieldRow, anchor, message: str) -> None:
        key = row.key
        invalid = anchor == row.path
        if row.path == ("monte_carlo",):
            present = isinstance(self.doc.get("monte_carlo"), dict)
        else:
            present = (
                model.get(self.doc, row.path, model.MISSING)
                is not model.MISSING
            )
        if invalid:
            marker = m("[$error]✗ invalid[/]")
            help_line = m("[$error]$e[/]", e=message)
        else:
            marker = self._marker(key, present)
            text = model.help_text(row.help_section, key)
            help_line = m(
                "$h  [dim]· $d · F1 more[/]", h=text, d=model.default_text(key)
            )
        row.show(marker, help_line, invalid)

    def _marker(self, key, present: bool) -> Content:
        if present:
            return m("[$primary]set[/]")
        if key.required:
            return m("[$warning]required[/]")
        if key.default is None and key.name in ("area", "length", "width"):
            # A room needs area, or length and width: none is a default.
            return m("[dim]not set[/]")
        return m("[dim]default[/]")

    def _show_head(self, section: str, anchor, message: str) -> None:
        heads = list(self.base.query(f"#head-{section}").results(SectionHead))
        if not heads:
            return
        if section in SECTIONS:
            index = self.selected[section]
            title = f"{model.ELEMENTS[section].capitalize()} {index}"
            items = self._items(section)
            if not items:
                title = f"No {section} yet"
            own = anchor in ((section,), (section, index))
            keys = "a add · d delete · alt+↑/↓ move"
        else:
            title, own, keys = section, anchor == (section,), ""
        text = m("[b]$t[/]  [dim]$k[/]", t=title, k=keys)
        if own:
            text = Content.assemble(text, m("\n[$error]✗ $e[/]", e=message))
        heads[0].update(text)

    # --- edits -------------------------------------------------------------------

    @on(FieldRow.Changed)
    async def _field_changed(self, event: FieldRow.Changed) -> None:
        event.stop()
        row, value = event.row, event.value
        path = row.path
        if row.kind == "dtype":
            self._change_type(path, value)
            await self._rebuild_for(path)
        elif path == ("monte_carlo",):
            self._toggle_monte_carlo(bool(value))
            await self._rebuild_settings()
        elif row.kind == "switch":
            model.put(self.doc, path, bool(value))
        elif row.kind == "select":
            self._set(path, value is not None, value)
            if path[0] == "nodes" and path[2] == "kind":
                self._change_kind(path[:2])
                await self._rebuild_for(path)
        else:
            self.typed[path] = value
            if path[0] == "nodes" and path[2] == "name":
                self.renaming.setdefault(
                    path[:2], model.get(self.doc, path, None)
                )
            self._set(path, *model.to_json(value, row.key.annotation))
        self.edited(path)

    @on(FieldRow.Reset)
    async def _field_reset(self, event: FieldRow.Reset) -> None:
        event.stop()
        path = event.row.path
        if path == ("monte_carlo",):
            return
        if event.row.kind == "dtype":
            self._change_type(path, None)
            await self._rebuild_for(path)
        else:
            model.remove(self.doc, path)
            key = event.row.key
            event.row.set_value(None if key.choices else bool(key.default))
            if path[0] == "nodes" and path[2] == "kind":
                self._change_kind(path[:2])
                await self._rebuild_for(path)
        self.edited(path)

    def _set(self, path: tuple, present: bool, value) -> None:
        if present:
            model.put(self.doc, path, value)
        else:
            model.remove(self.doc, path)

    async def _rebuild_for(self, path: tuple) -> None:
        if path[0] in SECTIONS:
            self._focus_after = path
            await self._rebuild_form(path[0])
        else:
            await self._rebuild_settings()

    def _change_kind(self, element_path: tuple) -> None:
        """Keys the new node kind does not have go to the row's memory."""
        element = model.get(self.doc, element_path)
        names = {k.name for k in model.element_keys("nodes", element)}
        self._swap(element_path, element, names)

    def _swap(self, memory_path: tuple, element: dict, names: set) -> None:
        stash = self.memory.setdefault(memory_path, {})
        for key in [k for k in element if k not in names]:
            stash[key] = element.pop(key)
        for key in [k for k in stash if k in names and k not in element]:
            element[key] = stash.pop(key)

    def _change_type(self, path: tuple, kind: str | None) -> None:
        """Number ↔ distribution; fields both types share are kept."""
        old = model.get(self.doc, path, model.MISSING)
        stash = self.memory.setdefault(path, {})
        if isinstance(old, dict):
            stash.update({k: v for k, v in old.items() if k != "distribution"})
        elif old is not model.MISSING:
            stash[NUMBER] = old
        if kind is None or (kind == NUMBER and NUMBER not in stash):
            model.remove(self.doc, path)
            return
        if kind == NUMBER:
            model.put(self.doc, path, stash.pop(NUMBER))
            return
        names = {k.name for k in model.distribution_keys(kind)}
        value = {"distribution": kind}
        value |= {k: stash.pop(k) for k in list(stash) if k in names}
        model.put(self.doc, path, value)

    def _toggle_monte_carlo(self, on_: bool) -> None:
        stash = self.memory.setdefault(("monte_carlo",), {})
        if on_:
            self.doc["monte_carlo"] = stash.pop("section", {})
        elif "monte_carlo" in self.doc:
            stash["section"] = self.doc.pop("monte_carlo")

    def edited(self, path: tuple = ()) -> None:
        """Any edit: refresh the list row, validate, update the chrome."""
        if path and path[0] in SECTIONS:
            self._refresh_list_row(path[0], path[1])
        self.schedule_validate()
        self._refresh_rows()
        self.update_chrome()

    def _refresh_list_row(self, section: str, index: int) -> None:
        table = self.base.query_one(f"#list-{section}", ElementList)
        items = self._items(section)
        if index >= len(items) or table.row_count != len(items):
            self._fill_list(section)
            return
        cells = model.row_cells(section, items[index])
        for column, cell in enumerate(cells, start=2):
            table.update_cell_at((index, column), cell)

    @on(FieldRow.Left)
    def _field_left(self, event: FieldRow.Left) -> None:
        event.stop()
        path = event.row.path
        if len(path) != 3 or path[0] != "nodes" or path[2] != "name":
            return
        old = self.renaming.pop(path[:2], None)
        new = model.get(self.doc, path, None)
        if not isinstance(old, str) or not isinstance(new, str) or old == new:
            return
        links, pops = model.references(self.doc, old)
        if not links and not pops:
            return
        parts = [
            model.plural(links, "connection"),
            model.plural(pops, "population"),
        ]
        where = " and ".join(p for p in parts if not p.startswith("0 "))
        question = f"Also rename '{old}' in {where}?"

        def answered(yes: bool | None) -> None:
            if not yes:
                return
            model.rename(self.doc, old, new)
            for section in ("connections", "populations"):
                self._fill_list(section)
                self._shown.pop(section, None)
            self.rebuild_forms()
            self.edited()

        self.push_screen(ConfirmScreen(question, "y rename   n keep"), answered)

    # --- list operations -------------------------------------------------------

    def _focused_section(self) -> str | None:
        focused = self.focused
        return focused.section if isinstance(focused, ElementList) else None

    async def action_add_element(self) -> None:
        section = self._focused_section()
        if section is None or self.doc is None:
            return
        items = self.doc.setdefault(section, [])
        index = min(self.selected[section] + 1, len(items)) if items else 0
        items.insert(index, {})
        await self._restructured(section, index)

    def action_delete_element(self) -> None:
        section = self._focused_section()
        items = self._items(section) if section else []
        if not items:
            return
        index = self.selected[section]
        name = (
            items[index].get("name", "")
            if isinstance(items[index], dict)
            else ""
        )
        what = f"{model.ELEMENTS[section]} {index}" + (
            f" '{name}'" if name else ""
        )

        async def answered(yes: bool | None) -> None:
            if not yes:
                return
            items.pop(index)
            await self._restructured(section, max(0, index - 1))

        self.push_screen(
            ConfirmScreen(f"Delete {what}?", "y delete   n keep"), answered
        )

    async def action_move_element(self, delta: int) -> None:
        section = self._focused_section()
        items = self._items(section) if section else []
        index = self.selected.get(section, 0) if section else 0
        target = index + delta
        if not items or not 0 <= target < len(items):
            return
        items[index], items[target] = items[target], items[index]
        await self._restructured(section, target)

    async def _restructured(self, section: str, index: int) -> None:
        """The order or number of elements changed: memory no longer applies."""
        self.memory = {k: v for k, v in self.memory.items() if k[0] != section}
        self.typed = {k: v for k, v in self.typed.items() if k[0] != section}
        self.selected[section] = index
        self._shown.pop(section, None)
        self._fill_list(section)
        await self._rebuild_form(section)
        self.base.query_one(f"#list-{section}").focus()
        self.edited()

    # --- validation --------------------------------------------------------------

    def schedule_validate(self) -> None:
        if self._timer is not None:
            self._timer.stop()
        self.validated = False
        if self.debounce <= 0:
            self._start_validate()
            return
        self._timer = self.set_timer(self.debounce, self._start_validate)

    def _start_validate(self) -> None:
        self._timer = None
        if self.doc is None:
            return
        self._gen += 1
        job = jobs.validate(self._gen, copy.deepcopy(self.doc))
        self.engine.submit(job, self._post, key="validate")

    def _validated(self, event: jobs.Validated) -> None:
        if event.gen != self._gen or self.doc is None:
            return
        self.validated = True
        self.doc_warnings = event.warnings
        if event.error_path is None:
            self.error = None
        else:
            path = model.parse_path(event.error_path)
            self.error = (path, model.anchor(path, self.doc), event.message)
        for section in SECTIONS:
            self._mark_list(section)
        self._refresh_rows()
        self.update_chrome()

    def _mark_list(self, section: str) -> None:
        table = self.base.query_one(f"#list-{section}", ElementList)
        for i in range(min(table.row_count, len(self._items(section)))):
            mark = "✗" if self._error_in((section, i)) else " "
            table.update_cell_at((i, 0), mark)

    def action_goto_error(self) -> None:
        if self.error is None:
            return
        self.focus_path(self.error[1])

    def focus_path(self, path: tuple) -> None:
        """Show the field (or element, or section) at ``path`` on Edit."""
        self.goto(1)
        tabs = self.base.query_one("#ed-tabs", TabbedContent)
        if not path or path[0] not in SECTIONS:
            tabs.active = "tab-settings"
            self._focus_after = path or None
            self._focus_pending()
            return
        section = path[0]
        tabs.active = f"tab-{section}"
        table = self.base.query_one(f"#list-{section}", ElementList)
        if len(path) < 2:
            table.focus()
            return
        self._focus_after = path if len(path) > 2 else None
        if self.selected[section] == path[1]:
            self._focus_pending()
        else:
            table.move_cursor(row=path[1])
        if len(path) == 2:
            table.focus()

    # --- chrome -----------------------------------------------------------------

    @property
    def settings_changed(self) -> bool:
        run = self.current_run
        return (
            run is not None
            and self.doc is not None
            and self.doc != run.snapshot
        )

    def update_chrome(self) -> None:
        if not self.base.query("#stepbar"):
            return  # resize before the first compose
        marks: dict[int, str] = {}
        if self.doc is not None:
            marks[1] = "✓"
            marks[2] = "!" if self.error else "✓"
        if self.checked is not None:
            marks[3] = {0: "✓", 2: "◐"}.get(self.checked.status, "!")
        run = self.current_run
        if run is not None and run.finished is None:
            marks[4] = "⟳"
        elif run is not None:
            marks[4] = "✓"
            glyph = model.OUTCOMES[run.finished.status][0]
            marks[5] = "✎" if self.settings_changed else glyph
        width = self.size.width or 80
        self.base.query_one("#stepbar", StepBar).show(
            self.step + 1, marks, width
        )
        summary = self.base.query_one("#summary", StatusLine)
        summary.display = self.step in (1, 2)
        summary.update(self.summary_line())

    def summary_line(self) -> Content:
        if self.doc is None:
            return m("[dim]No scenario yet[/]")
        parts = [self._validity()]
        parts.append(
            m(" · [$warning]● unsaved[/]") if self.dirty else m(" · saved")
        )
        n = len(self.doc_warnings)
        if n:
            parts.append(m(" · [$warning]$w[/]", w=model.plural(n, "warning")))
        parts.append(
            m(" · $t · $c", t=self.title_text, c=model.counts(self.doc))
        )
        return Content.assemble(*parts)

    def _validity(self) -> Content:
        if not self.validated:
            running = (
                self.current_run is not None
                and self.current_run.finished is None
            )
            return m(
                "[dim]checks after the run[/]"
                if running
                else "[dim]… checking[/]"
            )
        if self.error is None:
            return m("[$success]✓ valid[/]")
        text = model.path_text(self.error[0])
        where = f"{text}: " if text else ""
        return m(
            "[$error]✗ $p$e[/]  [dim]Enter: go to it[/]",
            p=where,
            e=self.error[2],
        )

    # --- save --------------------------------------------------------------------

    def action_save(self) -> None:
        if self.doc is None:
            return
        if self.path is None:
            self.save_as()
            return
        self._save_to(self.path, None)

    def save_as(self, then: Any = None) -> None:
        if self.doc is None:
            return
        default = self.path or "scenario.json"
        self.push_screen(
            AskPathScreen("Save the scenario as", default),
            lambda path: self._chosen_path(path, then),
        )

    def _chosen_path(self, path: str | None, then: Any) -> None:
        if not path:
            return
        shown = model.shown_path(os.path.expanduser(path))
        if Path(shown).exists() and shown != self.path:
            self.push_screen(
                ConfirmScreen(
                    f"{shown} exists. Replace it?", "y replace   n back"
                ),
                lambda yes: self._save_to(shown, then) if yes else None,
            )
            return
        self._save_to(shown, then)

    def _save_to(self, path: str, then: Any) -> None:
        self._after_save = then
        self.engine.submit(jobs.save(copy.deepcopy(self.doc), path), self._post)

    def _saved(self, event: jobs.Saved) -> None:
        then, self._after_save = self._after_save, None
        if event.doc is None:
            self.notify(event.error, severity="error", markup=False, timeout=10)
            return
        self.path, self.saved, self.example = event.path, event.doc, None
        self.recent.add(event.path, _now())
        self._fill_recent()
        self.notify(f"Saved {event.path}", markup=False)
        self.update_chrome()
        if then is not None:
            then()

    def ensure_saved(self, verb: str, then: Any) -> None:
        """Check and Run use the saved file (design §2.2): save first, asking."""
        if self.doc is None:
            return
        if not self.dirty:
            then()
            return
        if self.path is None:
            self.save_as(then)
            return

        def answered(yes: bool | None) -> None:
            if yes:
                self._save_to(self.path, then)

        question = f"Save {self.path} and {verb}?"
        self.push_screen(
            ConfirmScreen(question, f"y save and {verb}   n back"), answered
        )

    # --- check --------------------------------------------------------------------

    def action_check(self) -> None:
        self.ensure_saved("check", self.start_check)

    def start_check(self) -> None:
        self.checking = True
        self.checked = None
        self.goto(2)
        self.render_check()
        self.engine.submit(jobs.check(self.path), self._post)

    def _checked(self, event: jobs.Checked) -> None:
        self.checking = False
        self.checked = event
        if self.step == 2:
            self.render_check()
            self.base.query_one("#step-check", CheckStep).enter()
        self.update_chrome()

    def render_check(self) -> None:
        outcome = self.base.query_one("#ck-outcome", Static)
        errors = self.base.query_one("#ck-errors", OptionList)
        errors.clear_options()
        errors.display = False
        command = model.command(self.path or "scenario.json", None, False)
        self.base.query_one("#ck-command", Static).update(
            m("[dim]Run it:[/] $c  [dim]c copy[/]", c=command)
        )
        checked = self.checked
        if checked is None:
            outcome.update(m("[b $primary]⟳ Checking $p[/]", p=self.path or ""))
            self.base.query_one("#ck-text", Static).update("")
            self._show_tree("ck", [])
            return
        outcome.update(self._check_outcome(checked))
        parts = []
        for stream, line in checked.lines:
            colour = "$warning" if line.startswith("warning:") else "$error"
            parts.append(
                m(
                    f"[{colour}]$l[/]\n" if stream == "stderr" else "$l\n",
                    l=line,
                )
            )
        self.base.query_one("#ck-text", Static).update(Content.assemble(*parts))
        if checked.status == 1:
            text = checked.stream("stderr")[-1]
            errors.add_option(
                Option(
                    m("[$error]✗[/] $t  [dim]Enter: go to it[/]", t=text),
                    id="err",
                )
            )
            errors.highlighted = 0
            errors.display = True
        tree = (
            []
            if checked.routes is None
            else netview.lines(checked.routes, self._agents())
        )
        self._show_tree("ck", tree)

    def _check_outcome(self, checked: jobs.Checked) -> Content:
        if checked.status == 0:
            return m(
                "[b $success]✓ The scenario is valid[/]  [dim]$p[/]",
                p=checked.path,
            )
        if checked.status == 2:
            return m(
                "[b $warning]◐ Valid, but the trial run did not finish by t_max[/]"
            )
        return m("[b $error]✗ The check failed[/]  [dim]$p[/]", p=checked.path)

    def _agents(self) -> dict[str, str]:
        """``● 120 agents`` per start node, from the document."""
        labels: dict[str, list[str]] = {}
        for pop in self._items("populations"):
            if isinstance(pop, dict) and "count" in pop:
                words = model.distribution_words(pop["count"])
                labels.setdefault(str(pop.get("node")), []).append(words)
        return {node: f"● {' + '.join(c)} agents" for node, c in labels.items()}

    def _show_tree(
        self, prefix: str, lines: list[str], head: str = "", extra=()
    ) -> None:
        text = Content("")
        if lines:
            text = Content.assemble(
                m("[b]Routes[/]  [dim]$h[/]\n", h=head),
                m("$t", t="\n".join(lines)),
                *extra,
            )
        for which in ("narrow", "wide"):
            self.base.query_one(f"#{prefix}-tree-{which}", Static).update(text)

    @on(OptionList.OptionSelected, "#ck-errors")
    def _check_error(self, event: OptionList.OptionSelected) -> None:
        if self.checked is None or self.checked.error_path is None:
            return
        path = model.parse_path(self.checked.error_path)
        self.focus_path(model.anchor(path, self.doc))

    def action_copy_command(self) -> None:
        if self.doc is None:
            return
        run = self.current_run
        if self.step == 4 and run is not None:
            command = model.command(run.path, run.out, run.single)
        else:
            command = model.command(
                self.path or "scenario.json", self._out_text(), self._single()
            )
        self.copy_to_clipboard(command)
        self.notify(f"Sent to clipboard (OSC 52): {command}", markup=False)

    # --- run ---------------------------------------------------------------------

    def _single(self) -> bool:
        return self.base.query_one("#run-single", Switch).value

    def _out_text(self) -> str | None:
        return self.base.query_one("#run-out", Input).value.strip() or None

    def action_run(self) -> None:
        if self.current_run is not None and self.current_run.finished is None:
            self.notify("A run is in progress.")
            return
        if self.doc is None:
            self.notify("Open a scenario or an example first.")
            return
        self.ensure_saved("run", self._before_run)

    def _before_run(self) -> None:
        out = self._out_text() or str(cli_run.default_output(self.path))
        if (Path(out) / "summary.json").exists():
            self.push_screen(
                ConfirmScreen(
                    f"{out}/ holds results; replace them?", "y replace   n back"
                ),
                lambda yes: self.start_run(out) if yes else None,
            )
            return
        self.start_run(out)

    def start_run(self, out: str) -> None:
        snapshot = model.frozen(self.saved)
        single = self._single()
        section = snapshot.get("monte_carlo")
        runs = (
            section.get("runs")
            if isinstance(section, dict) and not single
            else None
        )
        self.current_run = RunState(
            self.path,
            out,
            single,
            snapshot,
            runs if isinstance(runs, int) else None,
            time.monotonic(),
        )
        self.failure = None
        self.goto(3)
        self.engine.submit(
            jobs.run(self.path, out, single, self._post), self._post
        )

    def _progress(self, event: jobs.Progress) -> None:
        run = self.current_run
        if run is None or run.finished is not None:
            return
        run.phase, run.done = event.phase, event.done
        if self._render_timer is None:
            self._render_timer = self.set_timer(0.1, self._render_tick)

    def _render_tick(self) -> None:
        """Redraw the Run step at most ten times per second."""
        self._render_timer = None
        if self.step == 3 and not self._quitting and self.is_running:
            self.render_run()

    def render_run(self) -> None:
        run = self.current_run
        path = self.path or "scenario.json"
        out_default = str(cli_run.default_output(path))
        self.base.query_one("#run-out", Input).placeholder = out_default
        self.base.query_one("#run-out-help", Static).update(
            m("[dim]default: $d, next to the file[/]", d=out_default)
        )
        command = model.command(path, self._out_text(), self._single())
        self.base.query_one("#run-command", Static).update(
            m("[dim]$c[/]", c=command)
        )
        self.base.query_one("#run-note", Static).update(
            m(
                "[dim]Cancel stops at the next realisation; the current one "
                "finishes first. A cancelled run writes nothing.[/]"
            )
        )
        self.base.query_one("#run-status", Static).update(
            self._run_status(run, path)
        )
        running = run is not None and run.finished is None
        self.base.query_one("#run-out", Input).disabled = running
        self.base.query_one("#run-single", Switch).disabled = running

    def _run_status(self, run: RunState | None, path: str) -> Content:
        if run is None or run.finished is not None:
            target = self._out_text() or str(cli_run.default_output(path))
            return m(
                "[b]Ready[/]  $p → $o/   [dim]ctrl+r run[/]", p=path, o=target
            )
        state = "⟳ Cancelling…" if run.cancelling else "⟳ Running"
        head = m(f"[b $primary]{state}[/]  $p → $o/", p=run.path, o=run.out)
        if run.phase == "single run":
            phases = m("\n  [b u]single run[/]")
            if run.runs is not None:
                phases = Content.assemble(
                    phases, m("  ›  [dim]Monte Carlo 0 / $n[/]", n=run.runs)
                )
            return Content.assemble(
                head, phases, m("   $c", c=_clock(run.wall))
            )
        frac = run.done / run.runs if run.runs else 0.0
        return Content.assemble(
            head,
            m(
                "\n  single run ✓  ›  [b]Monte Carlo $d / $n[/]  ",
                d=run.done,
                n=run.runs,
            ),
            _bar(frac, 20),
            m("  $c", c=_clock(run.wall)),
        )

    def action_cancel(self) -> None:
        run = self.current_run
        if run is None or run.finished is not None or run.cancelling:
            return
        self.push_screen(
            ConfirmScreen(
                "Cancel the run? The current realisation finishes first; "
                "nothing is written.",
                "y cancel the run   n keep running",
            ),
            self._confirmed_cancel,
        )

    def _confirmed_cancel(self, yes: bool | None) -> None:
        run = self.current_run
        if yes and run is not None and run.finished is None:
            run.cancelling = True
            self.engine.cancel()
            self.render_run()

    def _run_finished(self, event: jobs.RunFinished) -> None:
        run = self.current_run
        if run is None:
            return
        run.finished, run.ended = event, time.monotonic()
        run.phase, run.done = event.phase, event.done
        self.occupancy = None
        if "occupancy.csv" in event.files:
            self.occupancy = model.Occupancy.parse(event.files["occupancy.csv"])
        self.scrub_index = 0
        status = STATUS_WORDS[event.status]
        self.recent.add(event.path, _now(), status)
        self._fill_recent()
        self.goto(4)

    # --- results -------------------------------------------------------------------

    def render_results(self) -> None:
        run = self.current_run
        if run is None or run.finished is None:
            return
        done = run.finished
        banner = self.base.query_one("#res-banner", Static)
        banner.display = self.settings_changed
        banner.update(
            m(
                "✎ Settings changed since this run. These results show the "
                "file as it was run; ctrl+r runs the current one."
            )
        )
        self.base.query_one("#res-outcome", Static).update(results_text(run))
        self._render_occupancy()
        files = self.base.query_one("#res-files", OptionList)
        files.clear_options()
        for i, name in enumerate(done.files):
            path = Path(done.out) / name
            files.add_option(
                Option(
                    m("$n  [dim]$s[/]", n=str(path), s=_size(path)),
                    id=f"file-{i}",
                )
            )
        if not done.files:
            files.add_option(
                Option(m("[dim]No files were written.[/]"), disabled=True)
            )
        else:
            files.highlighted = 0

    def _render_occupancy(self) -> None:
        run = self.current_run
        done = run.finished if run else None
        occ = self.occupancy
        if done is None or occ is None:
            self._show_tree("res", [])
            return
        summary = json.loads(done.files["summary.json"])
        head = occ.line(self.scrub_index, str(summary["run"]["seed"]))
        counts = {n: f"● {c}" for n, c in occ.at(self.scrub_index).items()}
        lines = []
        if done.routes is not None:
            lines = [*netview.lines(done.routes, counts), ""]
        lines.append("←/→ ±1 step · shift+←/→ ±10 steps")
        self._show_tree("res", lines, head, _links_text(summary))

    def action_scrub(self, steps: int) -> None:
        if self.occupancy is None:
            return
        last = len(self.occupancy.times) - 1
        self.scrub_index = max(0, min(last, self.scrub_index + steps))
        self._render_occupancy()

    @on(OptionList.OptionSelected, "#res-files")
    def _file_selected(self, event: OptionList.OptionSelected) -> None:
        path = self._result_path(event.option_index)
        if path is not None:
            self.push_screen(
                FileScreen(str(path), file_preview(path), file_opener())
            )

    def _result_path(self, index: int | None) -> Path | None:
        run = self.current_run
        if run is None or run.finished is None or index is None:
            return None
        names = list(run.finished.files)
        return (
            Path(run.finished.out) / names[index]
            if index < len(names)
            else None
        )

    def action_copy_path(self) -> None:
        files = self.base.query_one("#res-files", OptionList)
        path = self._result_path(files.highlighted)
        if path is not None:
            self.copy_to_clipboard(str(path))
            self.notify(f"Sent to clipboard (OSC 52): {path}", markup=False)

    def action_warnings(self) -> None:
        run = self.current_run
        if run is None or run.finished is None:
            return
        warned = [
            line for line in run.finished.stderr if line.startswith("warning:")
        ]
        self.push_screen(
            TextScreen("Warnings", "\n".join(warned) or "No warnings.")
        )

    def action_traceback(self) -> None:
        if self.failure is not None:
            self.push_screen(TextScreen("Traceback", self.failure.traceback))

    # --- help and quit ---------------------------------------------------------

    def action_field_help(self) -> None:
        focused = self.focused
        chain = [focused, *focused.ancestors] if focused else []
        row = next((a for a in chain if isinstance(a, FieldRow)), None)
        if row is None:
            self.push_screen("keys")
            return
        key = row.key
        text = "\n".join(
            [
                model.help_text(row.help_section, key),
                "",
                f"Key: {model.path_text(row.path)}",
                f"Absent: {model.default_text(key)}",
                "",
                "Keys",
                keys_text(),
            ]
        )
        self.push_screen(TextScreen(model.path_text(row.path), text))

    async def action_quit(self) -> None:
        run = self.current_run
        if run is not None and run.finished is None:
            self.push_screen(
                ConfirmScreen(
                    "A run is in progress. Quit and cancel it? The current "
                    "realisation finishes first; nothing is written.",
                    "y quit and cancel   n keep running",
                ),
                self._confirmed_quit_run,
            )
            return
        if self.dirty:
            self.push_screen(
                ConfirmScreen(self._unsaved_question(), "y quit   n back"),
                self._confirmed_quit,
            )
            return
        self.exit()

    def _unsaved_question(self) -> str:
        question = f"Quit without saving? Unsaved changes to {self.title_text} are lost."
        if self.error is None:
            return question
        where = model.path_text(self.error[0])
        return (
            f"{question} The scenario has an error ({where}: {self.error[2]}) "
            "and cannot be saved as it is."
        )

    def _confirmed_quit_run(self, yes: bool | None) -> None:
        if not yes:
            return
        if self.dirty:
            self.push_screen(
                ConfirmScreen(self._unsaved_question(), "y quit   n back"),
                self._confirmed_quit_running,
            )
            return
        self._confirmed_quit_running(True)

    def _confirmed_quit_running(self, yes: bool | None) -> None:
        if not yes:
            return
        self.engine.cancel()
        self.exit()

    def _confirmed_quit(self, yes: bool | None) -> None:
        if yes:
            self.exit()


# --- text builders (no widget state) ----------------------------------------------


def results_text(run: RunState) -> Content:
    """The Results blocks: outcome, the CLI's lines, Monte Carlo, links, notes."""
    done = run.finished
    assert done is not None  # Results show a finished run only
    glyph, words = model.OUTCOMES[done.status]
    if done.status is None:
        return _cancelled_text(done)
    colour = {0: "$success", 2: "$warning"}.get(done.status, "$error")
    parts = [
        m(
            f"[b {colour}]$g $w[/]   [dim]exit $x · wall $c[/]\n",
            g=glyph,
            w=words,
            x=done.status,
            c=_clock(run.wall),
        )
    ]
    if done.status == 1:
        parts += [m("[$error]$l[/]\n", l=line) for line in done.stderr]
        return Content.assemble(*parts)
    parts.append(m("[b]Command line output[/]\n"))
    parts += [m("$l\n", l=line) for line in done.stdout]
    warned = [line for line in done.stderr if line.startswith("warning:")]
    if warned:
        parts.append(
            m(
                "[$warning]! $n[/]  [dim]w list[/]\n",
                n=model.plural(len(warned), "warning"),
            )
        )
    summary = json.loads(done.files["summary.json"])
    parts.append(
        m(
            "[b]Evacuation time[/]  [dim]last agent safe, s; a multiple of dt[/]\n"
        )
    )
    parts.append(m("[dim]$n[/]\n", n=model.TIME_NOTE))
    if summary["monte_carlo"] is not None:
        parts += _monte_carlo_text(summary["monte_carlo"])
    return Content.assemble(*parts)


def _cancelled_text(done: jobs.RunFinished) -> Content:
    if done.phase == "monte carlo" and done.runs:
        what = f"after {done.done} of {done.runs} runs"
    elif done.phase == "queued":
        what = "before it started"
    else:
        what = "during the single run"
    return m("[b]■ Cancelled $w; nothing was written.[/]\n", w=what)


def _monte_carlo_text(mc: dict) -> list[Content]:
    runs = mc["runs"]
    parts = [
        m(
            "[b]Monte Carlo set[/]  [dim]separate realisations, not the "
            "single run above; seed $s[/]\n",
            s=f"{mc['seed']} (drawn)" if mc["seed_drawn"] else mc["seed"],
        ),
        m("$h\n", h=f"quantile of evacuation time over {runs} runs [s]"),
    ]
    for q, value in model.quantile_rows({"monte_carlo": mc}):
        parts.append(m("  q $q   $v\n", q=f"{q:<5}", v=value))
    parts.append(m("  runs $r · incomplete $i\n", r=runs, i=mc["incomplete"]))
    parts.append(
        m("[dim]> t_max is a lower bound. $n[/]\n", n=model.SPREAD_NOTE)
    )
    return parts


def _links_text(summary: dict) -> list[Content]:
    parts = [
        m(
            "\n\n[b]Links[/]  [dim]nominal capacity C = Fs (w − 2b), not the "
            "realised flow[/]\n"
        ),
        m(
            "  $h\n",
            h=f"{'#':<3} {'name':<20} {'kind':<8} capacity [persons/s]",
        ),
    ]
    for index, name, _route, kind, capacity in model.link_rows(summary):
        parts.append(
            m("  $r\n", r=f"{index:<3} {name:<20} {kind:<8} {capacity}")
        )
    return parts


def file_preview(path: Path) -> str:
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            lines = [
                line.rstrip("\n")[:200]
                for _, line in zip(range(PREVIEW_LINES + 1), fh)
            ]
    except OSError as exc:
        return f"Cannot read the file: {exc}"
    if len(lines) > PREVIEW_LINES:
        lines = [*lines[:PREVIEW_LINES], f"… first {PREVIEW_LINES} lines shown"]
    return "\n".join(lines) or "(empty file)"


def file_opener() -> list[str] | None:
    """The command that opens a file in the system app; None over SSH or if absent."""
    if os.environ.get("SSH_CONNECTION"):
        return None
    if sys.platform == "darwin":
        return ["open"]
    if sys.platform.startswith("linux") and shutil.which("xdg-open"):
        return ["xdg-open"]
    return None


def _size(path: Path) -> str:
    try:
        size: float = path.stat().st_size
    except OSError:
        return ""
    for unit in ("B", "KB", "MB"):
        if size < 1024 or unit == "MB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def keys_text() -> str:
    return "\n".join(
        [
            "Tab / Shift+Tab     next / previous control",
            "↑ / ↓               previous / next field of a form",
            "[ / ]               previous / next tab (Edit)",
            "a, d, alt+↑/↓       add, delete, move an element (Edit list)",
            "backspace           on a switch or choice: back to the default",
            "                    (an empty text box also removes the key)",
            "Enter               on the status line or an error: go to the field",
            "ctrl+n / ctrl+p     next / previous step (Esc also goes back)",
            "ctrl+s              save (asks for a path the first time)",
            "ctrl+r              run (saves first, asks)",
            "c                   copy the jupedsim-network run command",
            "x or ctrl+c         cancel a run",
            "←/→, shift+←/→      Results: occupancy time ±1 / ±10 steps",
            "w, y, t             Results: warnings, copy path, traceback",
            "e, n                Results: edit, new scenario",
            "? or F1             this list; on a field, its help first",
            "ctrl+k              command palette (themes, steps, save as)",
            "ctrl+q              quit (asks with unsaved changes or during a run)",
        ]
    )
