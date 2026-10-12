# AI use in jupedsim-network

jupedsim-network is developed with generative AI coding tools. This file
says which tools, what they do, how their output is reviewed, and what
they do not do. It is a disclosure, not a credit: the model, the
software architecture, the numerical choices and the verification
strategy are defined and reviewed by the human authors, who are
responsible for them (see "How jupedsim-network is built" in the
[README](README.md)).

## Tools

- Claude Code (Anthropic) for implementation, refactoring, tests,
  documentation and release preparation.

## Where AI contributes

Code, tests, documentation pages, figure scripts and issue or pull-request
text may be drafted or written by these tools. Commits and pull requests
carry no per-change AI attribution; this file is the project-level
disclosure instead. We do not report AI contribution as a share of lines
of code: that is not a measure of intellectual contribution.

## How generated work is reviewed

Every change that can affect what the software computes goes through the
same sequence, whoever or whatever wrote it:

1. A model contract, written before the code moves: what is computed, in
   which units, under which assumptions and in which applicable range,
   with the primary sources and hand-calculated expectations.
2. Implementation against that contract, with regression tests. A bug
   fix lands with a test that fails before the fix and passes after.
3. Independent, read-only verification: the tests are re-run, the
   hand-calculated expectations and the invariants (conservation,
   capacity, maximum density, seed reproducibility) are checked, and
   every number quoted in the documentation is checked against the
   current output.
4. The maintainer decides whether it merges and whether it ships.

Scientific statements in the documentation are checked against the
primary sources they cite. A constant without a source is reported as
unsourced.

## What the tools do not do

- They do not choose a model, a default, an applicable range or a
  reference. Those are maintainer decisions, recorded in the issue
  tracker and the documentation.
- They do not merge or release.
- They are not part of the software: nothing in jupedsim-network, its
  command line or its TUI calls an AI service. The package depends only
  on NumPy.

## Contributions

Contributions are welcome whatever tools their authors use. They go
through the same review as everything else.
