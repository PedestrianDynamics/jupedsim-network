# SPDX-License-Identifier: LGPL-3.0-or-later
"""Start the terminal UI: check the extra, choose the theme, run the app.

Imports nothing of Textual before the extra is checked, so a missing
extra ends with an install hint and exit status 1.
"""

import os
import sys

from jupedsim_network.tui import model

TUI_EXTRA_HINT = (
    "jupedsim-network tui: error: the terminal UI needs the tui extra "
    "(missing module {name!r}). Install it with: pip install "
    '"jupedsim-network[tui]"'
)


def main(scenario: str | None = None, theme: str | None = None) -> int:
    """Run the TUI until it quits; returns the exit status."""
    theme = theme or os.environ.get(model.THEME_ENV) or None
    if theme is not None and theme not in model.THEMES:
        print(
            f"jupedsim-network tui: error: {model.THEME_ENV}={theme!r} is not "
            f"a theme; choose from {', '.join(model.THEMES)}",
            file=sys.stderr,
        )
        return 1
    try:
        from jupedsim_network.tui.app import NetworkTui
    except ModuleNotFoundError as exc:
        if (exc.name or "").split(".")[0] not in {"textual", "rich"}:
            raise
        print(TUI_EXTRA_HINT.format(name=exc.name), file=sys.stderr)
        return 1
    NetworkTui(theme=theme, scenario=scenario).run()
    return 0
