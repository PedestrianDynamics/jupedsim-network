# jupedsim-network

Coarse SFPE hydraulic network egress model. NumPy is the only runtime
dependency.

## Design principles

Every change to the model follows `docs/DESIGN_PRINCIPLES.md`. Before
substantial work, answer the §9 design-review questions briefly in the
issue, contract or PR. Before calling work done, check the §10 list.
Do not add abstractions, parameters or dependencies without a concrete
requirement.

## Checks before a push

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
cd site && hugo --panicOnWarning -d "$(mktemp -d)"   # when the site changes
```

Numbers quoted on the docs pages are pinned in `tests/test_docs_numbers.py`;
a changed result must change the page and the pin together. Long runs are
marked `slow` and run in the `docs-numbers` CI job.

## Conventions

- Kernel-style commit messages: imperative subject of at most 50
  characters, body wrapped at 72 columns saying what and why. No AI
  attribution lines.
- Feature branch and pull request for every change; no direct pushes to
  `main`.
