# jupedsim-network

A coarse network egress model for fast estimates of the required safe
egress time (RSET). Rooms, corridors and stair flights are nodes with an
area; doors and stair entries are links with a flow capacity. Agents move
through the graph following the SFPE hydraulic relations. A run of a
ten-storey building takes about 0.1 s, so scenarios can be sampled many
times.

The package is a companion to [JuPedSim](https://www.jupedsim.org): use
the network model to screen scenarios and find critical cases, and the
microscopic models of JuPedSim to check geometry details. It depends only
on NumPy.

The model is a prototype. It is verified against hand calculations but
not validated against experiments; see the limitations in the
[documentation](https://pedestriandynamics.org/jupedsim-network/).

## Install

```
pip install git+https://github.com/PedestrianDynamics/jupedsim-network
```

## Development

```
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

The documentation is a [Hugo](https://gohugo.io) site with the
[Hextra](https://imfing.github.io/hextra/) theme in `site/`. Hugo
(extended) and Go are needed to build it:

```
cd site && hugo server
```

Its figures and animations are produced by
`scripts/figures/make_figures.py` and `make_gifs.py`
(`uv run --group docs python scripts/figures/make_figures.py`).

## License

LGPL-3.0-or-later, as JuPedSim.
