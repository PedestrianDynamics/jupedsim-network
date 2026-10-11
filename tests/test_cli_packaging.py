# SPDX-License-Identifier: LGPL-3.0-or-later
"""The command works from an installed wheel, not only from a checkout.

The wheel holds the CLI modules and the packaged scenarios, installs the
``jupedsim-network`` console script, depends on NumPy alone, and keeps
``rich-argparse`` in the ``cli`` extra.
"""

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
CONSOLE_SCRIPT = Path(sys.executable).parent / "jupedsim-network"


def _run(args, cwd, program=sys.executable):
    return subprocess.run(
        [program, *args],
        cwd=cwd,
        env=dict(os.environ),
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def installed_wheel(tmp_path_factory) -> Path:
    """The built wheel, unpacked as it would be into site-packages."""
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv not available to build the wheel")
    dist = tmp_path_factory.mktemp("dist")
    subprocess.run(
        [uv, "build", "--wheel", "--out-dir", str(dist), str(REPO)],
        check=True,
        capture_output=True,
    )
    (wheel,) = dist.glob("jupedsim_network-*.whl")
    site = tmp_path_factory.mktemp("site-packages")
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(site)
    return site


# Runs the wheel's console script the way its generated wrapper does, with
# the checkout removed from sys.path (an editable install puts it there).
_ENTRY_POINT = """
import importlib.metadata, sys
site, repo, name = sys.argv[1], sys.argv[2], sys.argv[3]
checkout = ("", ".", repo, repo + "/src")
sys.path[:] = [site] + [p for p in sys.path if p not in checkout]
(dist,) = importlib.metadata.distributions(path=[site])
(ep,) = [e for e in dist.entry_points if e.name == name]
assert ep.group == "console_scripts", ep
main = ep.load()
import jupedsim_network
assert jupedsim_network.__file__.startswith(site), jupedsim_network.__file__
sys.argv = [name, *sys.argv[4:]]
sys.exit(main())
"""


def test_wheel_contains_the_cli(installed_wheel):
    files = {
        p.relative_to(installed_wheel).as_posix()
        for p in installed_wheel.rglob("*")
    }
    expected = {
        "jupedsim_network/cli.py",
        "jupedsim_network/cli_init.py",
        "jupedsim_network/cli_run.py",
        "jupedsim_network/__main__.py",
        "jupedsim_network/scenario.py",
        "jupedsim_network/scenarios/getting_started.json",
        "jupedsim_network/scenarios/office_wing.json",
    }
    assert expected <= files
    (info,) = installed_wheel.glob("jupedsim_network-*.dist-info")
    entry_points = (info / "entry_points.txt").read_text()
    assert "jupedsim-network = jupedsim_network.cli:main" in entry_points
    requires = [
        line.split(":", 1)[1].strip()
        for line in (info / "METADATA").read_text().splitlines()
        if line.startswith("Requires-Dist:")
    ]
    plain = [r for r in requires if "extra ==" not in r]
    assert [r.split(">")[0].strip() for r in plain] == ["numpy"]
    (rich,) = [r for r in requires if r.startswith("rich-argparse")]
    assert "extra == 'cli'" in rich or 'extra == "cli"' in rich


def test_wheel_command_runs_outside_the_repository(installed_wheel, tmp_path):
    script = tmp_path / "entry.py"
    script.write_text(_ENTRY_POINT)
    args = [str(script), str(installed_wheel), str(REPO), "jupedsim-network"]

    shown = _run([*args, "--help"], tmp_path)
    assert shown.returncode == 0, shown.stderr
    assert shown.stdout.startswith("usage: jupedsim-network")

    assert _run([*args, "init"], tmp_path).returncode == 0
    ran = _run([*args, "run", "scenario.json", "--no-monte-carlo"], tmp_path)
    assert ran.returncode == 0, ran.stderr
    assert "evacuation time 323.0 s" in ran.stdout
    assert (tmp_path / "scenario_results" / "summary.json").is_file()


def test_module_and_console_script_write_the_same_files(tmp_path):
    if not CONSOLE_SCRIPT.is_file():
        pytest.skip(f"{CONSOLE_SCRIPT} not installed; run uv sync")
    scenario = (
        REPO / "src" / "jupedsim_network" / "scenarios" / "getting_started.json"
    )
    a, b = tmp_path / "module", tmp_path / "script"
    common = ["run", str(scenario), "--runs", "3"]
    first = _run(["-m", "jupedsim_network", *common, "-o", str(a)], tmp_path)
    second = _run(
        [*common, "-o", str(b)], tmp_path, program=str(CONSOLE_SCRIPT)
    )
    assert first.returncode == second.returncode == 0, (
        first.stderr + second.stderr
    )
    for name in ("agents.csv", "link_flow.csv", "occupancy.csv", "runs.csv"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
    assert first.stdout.replace(str(a), "OUT") == second.stdout.replace(
        str(b), "OUT"
    )
