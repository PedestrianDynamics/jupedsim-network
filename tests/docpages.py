# SPDX-License-Identifier: LGPL-3.0-or-later
"""Read the documentation pages: fenced blocks and quoted text."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "site" / "content" / "docs"

_FENCE = re.compile(r"^```(\w*)\n(.*?)^```", re.DOTALL | re.MULTILINE)


def blocks(page, lang):
    """Contents of the fenced blocks of ``page`` tagged ``lang``."""
    return [body for tag, body in fences(page) if tag == lang]


def fences(page):
    """(language tag, content) of every fenced block, in page order."""
    return _FENCE.findall((DOCS / page).read_text())


def text(page):
    """The page with runs of whitespace and ``&nbsp;`` as one space."""
    raw = (DOCS / page).read_text().replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", raw)


def quoted(page_text, phrases):
    for phrase in phrases:
        assert phrase in page_text, f"page does not say: {phrase}"
