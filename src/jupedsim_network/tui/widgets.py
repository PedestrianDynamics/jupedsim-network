# SPDX-License-Identifier: LGPL-3.0-or-later
"""Widgets of the terminal UI: field rows, the step bar, dialogs.

Ported from pyFDS-Evac's ``tui.widgets``: the field row, the step bar,
the path box and its list, the footer with its fixed keys, and the
dialogs. A field row shows what the app tells it; it holds no scenario
logic.
"""

import subprocess
from typing import Any, cast

from textual import events, on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import (
    Horizontal,
    HorizontalGroup,
    Vertical,
    VerticalScroll,
)
from textual.content import Content
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import (
    DataTable,
    Footer,
    Input,
    Label,
    OptionList,
    Select,
    Static,
    Switch,
    TextArea,
)
from textual.widgets._footer import FooterKey

STEP_TITLES = ("Scenario", "Edit", "Check", "Run", "Results")


def m(markup: str, **values: Any) -> Content:
    """Markup with ``values`` inserted as plain text (never parsed as markup)."""
    return Content.from_markup(markup, **{k: str(v) for k, v in values.items()})


def slug(path: tuple) -> str:
    """A widget id for a document path: ``connections-1-width``."""
    return "-".join(str(part) for part in path) or "document"


class StepBar(Static):
    """`` 1 Scenario › 2 Edit › … `` with the state of each step."""

    def show(self, current: int, marks: dict[int, str], width: int) -> None:
        parts = [m("[b]jupedsim-network[/]  ")]
        for i, title in enumerate(STEP_TITLES, start=1):
            mark = marks.get(i, "")
            text = f"{i}{mark}" if width < 100 else f"{i} {title}{mark}"
            if i == current:
                parts.append(m("[reverse b] $t [/]", t=text))
            else:
                parts.append(m("[$text-muted] $t [/]", t=text))
            if width >= 100 and i < len(STEP_TITLES):
                parts.append(m("[dim]›[/]"))
        self.update(Content.assemble(*parts))


class TextBox(Input):
    """An Input that leaves ``?`` to the app, so the footer's ``? keys`` holds."""

    def check_consume_key(self, key: str, character: str | None) -> bool:
        return character != "?" and super().check_consume_key(key, character)


class FieldRow(Vertical):
    """One key: label, control, marker, and a help line when focused.

    ``kind`` is ``input``, ``select``, ``switch`` or ``dtype`` (the type of
    a distributed value: a number or a distribution). Backspace on a
    switch or a select removes the key, so the API default applies.
    """

    DEFAULT_CSS = """
    FieldRow { height: auto; padding: 0 0 0 1; }
    FieldRow > Horizontal { height: auto; }
    FieldRow .label { width: 26; padding: 0 1 0 0; content-align: left middle; }
    FieldRow Input, FieldRow Select { width: 1fr; max-width: 32; }
    FieldRow Switch { width: 6; height: 1; border: none; padding: 0; }
    FieldRow Switch:focus { border: none; background: $primary 30%; }
    FieldRow .marker { width: 1fr; padding: 0 0 0 1; color: $text-muted; }
    FieldRow .help { display: none; color: $text-muted; padding: 0 0 0 2; }
    FieldRow:focus-within .help { display: block; }
    FieldRow.-invalid .marker { color: $error; }
    FieldRow:hover { background: $block-hover-background; }
    FieldRow:focus-within { background: $block-cursor-blurred-background; }
    FieldRow:focus-within .label { text-style: bold; }
    """

    BINDINGS = [Binding("backspace", "reset", "default", show=False)]

    class Changed(Message):
        def __init__(self, row: "FieldRow", value: Any) -> None:
            super().__init__()
            self.row = row
            self.value = value

    class Reset(Message):
        def __init__(self, row: "FieldRow") -> None:
            super().__init__()
            self.row = row

    class Left(Message):
        """The control lost the focus (a node name is then committed)."""

        def __init__(self, row: "FieldRow") -> None:
            super().__init__()
            self.row = row

    def __init__(
        self,
        path: tuple,
        label: str,
        kind: str,
        value: Any,
        choices: tuple[str, ...] = (),
        blank: bool = True,
        suffix: str = "",
    ) -> None:
        super().__init__(id=f"row-{slug(path)}{suffix}")
        self.path = path
        self.label = label
        self.kind = kind
        self.value = value
        self.choices = choices
        self.blank = blank
        # Set by the app: the format key and the element its help is of.
        self.key: Any = None
        self.help_section = ""

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Label(self.label, classes="label", markup=False)
            yield self._control()
            yield Static("", classes="marker")
        yield Static("", classes="help")

    def _control(self) -> Widget:
        if self.kind == "switch":
            return Switch(bool(self.value), classes="control")
        if self.kind in ("select", "dtype"):
            value = self.value if self.value in self.choices else Select.NULL
            return Select(
                [(c, c) for c in self.choices],
                prompt="not set",
                allow_blank=self.blank,
                value=value,
                classes="control",
                compact=True,
            )
        return TextBox(str(self.value), classes="control", compact=True)

    @property
    def control(self) -> Widget:
        return self.query_one(".control")

    def show(self, marker: Content, help_line: Content, invalid: bool) -> None:
        """Set the marker and help line; kept until the row is composed."""
        self._state = (marker, help_line)
        self.set_class(invalid, "-invalid")
        self._apply()

    def on_mount(self) -> None:
        self._apply()

    def _apply(self) -> None:
        state = getattr(self, "_state", None)
        markers = list(self.query(".marker").results(Static))
        helps = list(self.query(".help").results(Static))
        if state is None or not markers or not helps:
            return
        markers[0].update(state[0])
        helps[0].update(state[1])

    def set_value(self, value: Any) -> None:
        """Put ``value`` into the control without posting a change."""
        self.value = value
        control = self.control
        with control.prevent(Input.Changed, Select.Changed, Switch.Changed):
            if isinstance(control, Switch):
                control.value = bool(value)
            elif isinstance(control, Select):
                control.value = value if value in self.choices else Select.NULL
            elif isinstance(control, Input):
                control.value = str(value)

    def action_reset(self) -> None:
        if self.kind in ("switch", "select", "dtype"):
            self.post_message(self.Reset(self))

    @on(Input.Changed)
    def _input(self, event: Input.Changed) -> None:
        event.stop()
        if event.value != self.value:
            self.value = event.value
            self.post_message(self.Changed(self, event.value))

    @on(Input.Blurred)
    def _blurred(self, event: Input.Blurred) -> None:
        event.stop()
        self.post_message(self.Left(self))

    @on(Input.Submitted)
    def _submitted(self, event: Input.Submitted) -> None:
        event.stop()
        self.post_message(self.Left(self))

    @on(Switch.Changed)
    def _switch(self, event: Switch.Changed) -> None:
        event.stop()
        if event.value != self.value:
            self.value = event.value
            self.post_message(self.Changed(self, event.value))

    @on(Select.Changed)
    def _select(self, event: Select.Changed) -> None:
        event.stop()
        value = None if event.value is Select.NULL else str(event.value)
        if value != self.value:
            self.value = value
            self.post_message(self.Changed(self, value))


class SectionHead(Static):
    """The head of a form or section; shows the error of its element."""

    DEFAULT_CSS = "SectionHead { height: auto; padding: 0 1; }"


class FormScroll(VerticalScroll):
    """A form: ↑/↓ move between the fields (template ``move_field``)."""

    BINDINGS = [
        Binding(
            "down", "app.move_field(1)", "next field", show=False, priority=True
        ),
        Binding(
            "up",
            "app.move_field(-1)",
            "previous field",
            show=False,
            priority=True,
        ),
    ]


class ElementList(DataTable):
    """The elements of one section: a add, d delete, alt+↑/↓ move."""

    BINDINGS = [
        Binding("a", "app.add_element", "add"),
        Binding("d", "app.delete_element", "delete"),
        Binding("alt+up", "app.move_element(-1)", "move up", show=False),
        Binding("alt+down", "app.move_element(1)", "move down", show=False),
    ]

    def __init__(self, section: str, **kwargs: Any) -> None:
        super().__init__(cursor_type="row", zebra_stripes=False, **kwargs)
        self.section = section


class StatusLine(Static, can_focus=True):
    """The one-line summary; Enter goes to the field of the error."""

    DEFAULT_CSS = """
    StatusLine { height: 1; padding: 0 1; background: $surface; }
    StatusLine:focus { background: $block-cursor-blurred-background; }
    """
    BINDINGS = [
        Binding("enter", "app.goto_error", "go to the error", show=False)
    ]


class PathBox(TextBox):
    """A path box: Tab completes the name, Down goes to the list below."""

    BINDINGS = [
        Binding("tab", "app.complete_path", "complete", show=False),
        Binding("down", "app.focus_choices", "list", show=False),
    ]


class BrowseList(OptionList):
    """The list a path box browses: typing here goes to the box, as in fzf."""

    BINDINGS = [Binding("tab", "app.complete_path", "complete", show=False)]

    def __init__(self, box_id: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.box_id = box_id

    def on_key(self, event: events.Key) -> None:
        box = self.screen.query_one(self.box_id, Input)
        if event.key == "backspace":
            box.value = box.value[:-1]
        elif event.is_printable and event.character:
            box.value += event.character
        else:
            return
        box.cursor_position = len(box.value)
        event.stop()
        event.prevent_default()


# The keys every footer shows on the right, whatever the step.
FIXED_KEYS = (
    ("ctrl+q", "quit", "quit"),
    ("question_mark", "field_help", "keys"),
)


class NetworkFooter(Footer):
    """The step's keys, then a fixed group ``^q quit ? keys ^k palette``.

    The group is docked right, so on a narrow terminal the step keys are
    cut first and the way out and the key list stay visible.
    """

    DEFAULT_CSS = """
    NetworkFooter { overflow-x: hidden; }
    NetworkFooter .fixed-keys {
        dock: right;
        width: auto;
        border-left: vkey $foreground 20%;
    }
    NetworkFooter .fixed-keys FooterKey:last-child { padding-right: 1; }
    """

    def __init__(self) -> None:
        super().__init__(show_command_palette=False)

    def compose(self) -> ComposeResult:
        yield from super().compose()
        palette = (
            self.app.COMMAND_PALETTE_BINDING,
            "command_palette",
            "palette",
        )
        # A class, not an id: the footer recomposes when the bindings change.
        with HorizontalGroup(classes="fixed-keys"):
            for key, action, label in (*FIXED_KEYS, palette):
                display = self.app.get_key_display(Binding(key, action, label))
                yield FooterKey(key, display, label, action).data_bind(
                    compact=Footer.compact
                )


class ConfirmScreen(ModalScreen[bool]):
    """A yes/no question."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > Vertical {
        width: 68; height: auto; padding: 1 2; background: $panel;
        border: tall $primary;
    }
    """
    BINDINGS = [
        Binding("y", "answer(True)", "yes", show=False),
        Binding("n", "answer(False)", "no", show=False),
        Binding("escape", "answer(False)", "back"),
    ]

    def __init__(self, question: str, choices: str = "y yes   n no") -> None:
        super().__init__()
        self.question = question
        self.choices = choices

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(m("[b]$q[/]", q=self.question), id="question")
            yield Static(m("[dim]$c[/]", c=self.choices))

    def action_answer(self, value: bool) -> None:
        self.dismiss(value)


class AskPathScreen(ModalScreen[str | None]):
    """Ask for the path of a file to save (Enter saves, Esc cancels)."""

    DEFAULT_CSS = """
    AskPathScreen { align: center middle; }
    AskPathScreen > Vertical {
        width: 72; height: auto; padding: 1 2; background: $panel;
        border: tall $primary;
    }
    """
    BINDINGS = [Binding("escape", "close", "back")]

    def __init__(self, question: str, default: str) -> None:
        super().__init__()
        self.question = question
        self.default = default

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(m("[b]$q[/]", q=self.question))
            yield TextBox(self.default, id="ask-path")
            yield Static(m("[dim]Enter save · Esc cancel[/]"))

    @on(Input.Submitted, "#ask-path")
    def _submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_close(self) -> None:
        self.dismiss(None)


class TextScreen(ModalScreen[None]):
    """A read-only text (keys, warnings, traceback) in a dialog."""

    DEFAULT_CSS = """
    TextScreen { align: center middle; }
    TextScreen > Vertical {
        width: 96%; height: 90%; padding: 0 1; background: $panel;
        border: tall $primary;
    }
    TextScreen TextArea { height: 1fr; }
    """
    BINDINGS = [
        Binding("escape", "close", "close"),
        Binding("c", "copy", "copy"),
    ]

    def __init__(self, title: str, text: str, note: str = "") -> None:
        super().__init__()
        self.title_text = title
        self.text = text
        self.note = note

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(m("[b]$t[/]", t=self.title_text))
            yield TextArea(self.text, read_only=True, soft_wrap=True, id="text")
            yield Static(m("[dim]$n[/]", n=self.note or "c copy · Esc close"))

    def action_close(self) -> None:
        self.dismiss(None)

    def action_copy(self) -> None:
        self.app.copy_to_clipboard(self.text)
        self.app.notify(
            "Sent to clipboard (OSC 52). If nothing was copied, select the text."
        )


class FileScreen(TextScreen):
    """An output file: its path, a preview, and keys to copy the path or open it."""

    BINDINGS = [
        Binding("escape", "close", "close"),
        Binding("y", "copy_path", "copy path"),
        Binding("o", "open", "open"),
    ]

    def __init__(
        self, path: str, preview: str, opener: list[str] | None
    ) -> None:
        keys = (
            "y copy path · o open · Esc close"
            if opener
            else "y copy path · Esc close"
        )
        super().__init__(path, preview, keys)
        self.path = path
        self.opener = opener

    def check_action(
        self, action: str, parameters: tuple[object, ...]
    ) -> bool | None:
        if action == "open":
            return self.opener is not None
        return True

    def action_copy_path(self) -> None:
        self.app.copy_to_clipboard(self.path)
        self.app.notify(
            f"Sent to clipboard (OSC 52): {self.path}", markup=False
        )

    def action_open(self) -> None:
        if self.opener is None:
            return
        subprocess.Popen(
            [*self.opener, self.path],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        self.app.notify(f"Opening {self.path}", markup=False)


class TooSmall(ModalScreen[None]):
    """The size notice; leaves on its own when the terminal grows."""

    DEFAULT_CSS = """
    TooSmall { align: center middle; }
    TooSmall Static { width: auto; padding: 1 2; background: $panel; }
    """

    def compose(self) -> ComposeResult:
        yield Static(id="notice")

    def on_resize(self, event: Any) -> None:
        cast(Any, self.app)._check_size(event.size)

    def show(self, width: int, height: int) -> None:
        self.query_one("#notice", Static).update(
            m(
                "Terminal is $w×$h; the TUI needs 80×24.\nResize, or zoom out.\n"
                "[dim]A run continues meanwhile.[/]",
                w=width,
                h=height,
            )
        )
