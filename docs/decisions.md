# Decisions

One entry per decision or feature: what was decided, why, and an analogy. These are the owner's talking points. Newest at the bottom. The full reasoning for each choice is in `docs/methodology.md`.

## Build 1 (2026-11-17)

### D1. Scaffold: uv, ruff, pytest, CI, and the Cleanroom from its git tag

The repo is a uv project that installs the shared Cleanroom from the `cleanroom-v0.1` tag of the Tells repo instead of copying it, with ruff and pytest run in CI on Python 3.11 and 3.12. Copying the honesty toolkit would let the three projects drift apart, so a leak fix in one would not reach the others. Analogy: three schools using the same sealed exam board instead of each photocopying and editing its own rulebook.
