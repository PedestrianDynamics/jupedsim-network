# SPDX-License-Identifier: LGPL-3.0-or-later
"""Themes: ``network-dark`` (default) and Textual's ``solarized-light``.

``network-dark`` takes the token values of pyFDS-Evac's ``evac-dark``, so
the two sibling tools look the same. ``NO_COLOR`` gives Textual's
monochrome rendering; every state also has a glyph and a word.
"""

from textual.theme import Theme

NETWORK_DARK = Theme(
    name="network-dark",
    dark=True,
    primary="#3DB1FF",
    secondary="#9CA3AF",
    accent="#3DB1FF",
    success="#3FB950",
    warning="#D29922",
    error="#F85149",
    foreground="#E6EDF3",
    background="#121A24",
    surface="#18222F",
    panel="#1F2B3A",
)

#: The two themes that ship, with their palette names.
THEME_NAMES = {
    "network-dark": "network dark",
    "solarized-light": "Solarized Light",
}
