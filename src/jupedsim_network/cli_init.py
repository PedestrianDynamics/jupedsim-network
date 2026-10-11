# SPDX-License-Identifier: LGPL-3.0-or-later
"""``jupedsim-network init [PATH]``: write a starter scenario.

Copies one of the scenarios that ship with the package, byte for byte, and
prints the next steps. Exit status: 0 written; 1 error (nothing written).
"""

import sys
from importlib import resources
from pathlib import Path

EXIT_OK = 0
EXIT_ERROR = 1

# Example name -> packaged file in jupedsim_network/scenarios/.
EXAMPLES = {
    "getting-started": "getting_started.json",
    "office-wing": "office_wing.json",
}

DESCRIPTION = """\
Write a starter scenario. The getting-started scenario (one office, one stair
flight, the street) runs as it is; edit it into your building. The office
wing has two storeys, a stair and two exits."""

EPILOG = """\
exit status: 0 written; 1 error (nothing written)

examples:
  jupedsim-network init                      # writes scenario.json
  jupedsim-network init wing.json --example office-wing"""


def add_arguments(parser) -> None:
    parser.add_argument(
        "path",
        nargs="?",
        default="scenario.json",
        metavar="PATH",
        help="file to write (default: scenario.json)",
    )
    parser.add_argument(
        "--example",
        choices=tuple(EXAMPLES),
        default="getting-started",
        metavar="NAME",
        help="getting-started (default) or office-wing",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing PATH",
    )


def example_bytes(name: str) -> bytes:
    """The packaged scenario file of example ``name``."""
    scenarios = resources.files("jupedsim_network") / "scenarios"
    return (scenarios / EXAMPLES[name]).read_bytes()


def init(args) -> int:
    """Run the init command; returns the exit status."""
    path = Path(args.path)
    if path.exists() and not args.force:
        return _error(f"{path} exists; pass --force to overwrite it")
    try:
        path.write_bytes(example_bytes(args.example))
    except OSError as exc:
        return _error(f"cannot write {path}: {exc.strerror or exc}")
    print(f"Wrote {path} (the {args.example} scenario).")
    print("\n".join(next_steps(path)))
    return EXIT_OK


def next_steps(path: Path) -> list[str]:
    return [
        "Next steps:",
        f"  1. Check it: jupedsim-network check {path}",
        f"  2. Run it: jupedsim-network run {path}",
        "  3. Edit nodes, connections and populations for your building, "
        "then check and run again.",
    ]


def _error(message: str) -> int:
    print(f"jupedsim-network init: error: {message}", file=sys.stderr)
    return EXIT_ERROR
