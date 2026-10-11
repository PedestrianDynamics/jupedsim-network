"""Run-time benchmark of the network model.

Times the ten-storey building of the case study (600 agents, seed 11,
best of 20 runs) and a swap of 200 + 200 agents through one two-way
door under each ``counterflow`` value (best of 5), and prints JSON::

    uv run python scripts/bench.py [ROOT] > bench.json

``ROOT`` is a checkout whose ``src/`` and ``scripts/figures/`` are
imported instead of the installed package, so one script can time two
revisions. Compare two results; a ratio above 1.5 prints a GitHub
``::warning::``, never an error::

    python scripts/bench.py --compare base.json head.json
"""

import inspect
import json
import os
import platform
import sys
import time
from pathlib import Path

WARN_RATIO = 1.5


def _import(root):
    sys.path[:0] = [str(root / "src"), str(root / "scripts" / "figures")]
    import scenarios

    import jupedsim_network

    return jupedsim_network, scenarios


def best(sim, runs):
    if runs < 1:
        raise ValueError(f"runs must be at least 1, got {runs}.")
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        result = sim.run(11, record=False)
        times.append(time.perf_counter() - start)
    return dict(best=min(times), evacuation_time=result.evacuation_time)


def swap(jn, counterflow):
    net = jn.Network()
    for name in "AB":
        net.add_room(name, area=400.0)
    net.add_safe("xA")
    net.add_safe("xB")
    net.connect("A", "B", width=1.0)
    net.connect("A", "xA", width=20.0, kind="opening", bidirectional=False)
    net.connect("B", "xB", width=20.0, kind="opening", bidirectional=False)
    pops = [
        jn.Population("A", 200, target="xB"),
        jn.Population("B", 200, target="xA"),
    ]
    return jn.NetworkSimulation(net, pops, **counterflow)


def measure(root):
    jn, scenarios = _import(root)
    sim = jn.NetworkSimulation(
        scenarios.building(), scenarios.building_populations()
    )
    values = ["bounding", "estimate", "independent"]
    if "counterflow" not in inspect.signature(jn.NetworkSimulation).parameters:
        values = [None]
    return dict(
        package=jn.__file__,
        python=platform.python_version(),
        machine=platform.platform(),
        building=best(sim, 20),
        swap200={
            str(cf): best(
                swap(jn, {} if cf is None else {"counterflow": cf}), 5
            )
            for cf in values
        },
    )


def compare(base_path, head_path):
    """Print the table, and append it to the GitHub job summary if set."""
    base = json.loads(Path(base_path).read_text())
    head = json.loads(Path(head_path).read_text())
    rows = [("building", base["building"], head["building"])]
    rows += [
        (f"swap200 {cf}", base["swap200"][cf], head["swap200"][cf])
        for cf in head["swap200"]
        if cf in base["swap200"]
    ]
    lines = ["| case | base (s) | head (s) | ratio |", "|---|---|---|---|"]
    warnings = []
    for name, b, h in rows:
        ratio = h["best"] / b["best"]
        lines.append(
            f"| {name} | {b['best']:.4f} | {h['best']:.4f} | {ratio:.2f} |"
        )
        if ratio > WARN_RATIO:
            warnings.append(f"::warning::{name} is {ratio:.2f} times slower")
    lines += ["", f"base: `{base['package']}`  ", f"head: `{head['package']}`"]
    table = "\n".join(lines) + "\n"
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as f:
            f.write("## Run time, best of runs\n\n" + table)
    print(table + "\n".join(warnings))


def main(argv):
    if argv[:1] == ["--compare"]:
        compare(*argv[1:3])
        return
    root = Path(argv[0]) if argv else Path(__file__).resolve().parents[1]
    print(json.dumps(measure(root.resolve()), indent=2))


if __name__ == "__main__":
    main(sys.argv[1:])
