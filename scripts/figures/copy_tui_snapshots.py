"""Terminal UI figures for the documentation.

Copies five SVG snapshots of the TUI tests to ``site/static/images/tui``
or to the directory given as the first argument, under the names the
Terminal UI page uses. The snapshot tests check these files on every
pull request, so the figures show what the UI of the same commit shows;
they are not in git. Standard library only, no textual::

    python scripts/figures/copy_tui_snapshots.py
"""

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOTS = ROOT / "tests" / "__snapshots__" / "test_tui"
DEFAULT_OUT = ROOT / "site" / "static" / "images" / "tui"

# Page figure -> snapshot. The names hold brackets; join them as paths,
# never glob them.
FIGURES = {
    "scenario.svg": "test_snapshot_scenario[network-dark].raw",
    "edit-error.svg": "test_snapshot_edit_connection_error[network-dark-120x35].raw",
    "check.svg": "test_snapshot_check[120x35].raw",
    "run.svg": "test_snapshot_run_in_progress.raw",
    "results.svg": "test_snapshot_results[120x35].raw",
}


def copy(out: Path) -> None:
    missing = [
        name for name in FIGURES.values() if not (SNAPSHOTS / name).is_file()
    ]
    if missing:
        raise SystemExit(
            f"missing snapshots in {SNAPSHOTS}: {', '.join(missing)}"
        )
    try:
        out.mkdir(parents=True, exist_ok=True)
        for figure, source in FIGURES.items():
            shutil.copyfile(SNAPSHOTS / source, out / figure)
    except OSError as exc:
        raise SystemExit(
            f"cannot write the figures: {exc.strerror}: {exc.filename}"
        ) from None


def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    copy(out)
    print(f"Wrote {len(FIGURES)} figures to {out}")


if __name__ == "__main__":
    main()
