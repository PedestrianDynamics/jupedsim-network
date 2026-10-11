# jupedsim-network

A coarse network egress model for fast estimates of evacuation times
(pre-movement plus movement). Rooms, corridors and stair flights are
nodes with an area; doors and stair entries are links with a flow
capacity. Agents move
through the graph by relations adapted from the SFPE hydraulic model. A run of a
ten-storey building takes about 0.1 s, so scenarios can be sampled many
times.

The package is a companion to [JuPedSim](https://www.jupedsim.org): use
the network model to screen scenarios and find critical cases, and the
microscopic models of JuPedSim to check geometry details. It depends only
on NumPy.

The model is a prototype. It is verified against hand calculations but
not validated against experiments, and it is not intended for
regulatory or design use; see the
[limitations](https://pedestriandynamics.org/jupedsim-network/docs/limitations/).

## Install

Python 3.10 or later:

```
pip install jupedsim-network
```

## Development

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

`uv run pytest` runs the tests of every pull request and deselects the
long ones. Two further commands run those:

```
uv run pytest -m slow
uv run pytest -m fuzz --hypothesis-profile=fuzz
```

The first runs the documented numbers of long runs (CI job
`docs-numbers`); the second runs the long property runs and fixed-seed
sweeps of `.github/workflows/fuzz.yml`, weekly and on demand. See
[Verification](https://pedestriandynamics.org/jupedsim-network/docs/verification/#tests).

The documentation is a [Hugo](https://gohugo.io) site with the
[Hextra](https://imfing.github.io/hextra/) theme in `site/`. Hugo
(extended) and Go are needed to build it:

```
uv run --group docs python scripts/figures/make_figures.py
uv run --group docs python scripts/figures/make_gifs.py
cd site && hugo server
```

The figures and animations are not stored in git. The two scripts write
them to `site/static/images/network/` (a few minutes); CI runs them
before every build.

## License

LGPL-3.0-or-later, as JuPedSim.
