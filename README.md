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
documentation.

## Install

```
pip install git+https://github.com/PedestrianDynamics/jupedsim-network
```

## Development

```
uv sync --group dev --group docs
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run --group docs sphinx-build -W -b html docs/source docs/build/html
```

The figures and animations of the documentation are produced by
`docs/source/_scripts/network/make_figures.py` and `make_gifs.py`.

## License

LGPL-3.0-or-later, as JuPedSim.
