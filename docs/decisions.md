# Decisions

One entry per decision or feature: what was decided, why, and an analogy. These are the owner's talking points. Newest at the bottom. The full reasoning for each choice is in `docs/methodology.md`.

## Build 1 (2026-11-17)

### D1. Scaffold: uv, ruff, pytest, CI, and the Cleanroom from its git tag

The repo is a uv project that installs the shared Cleanroom from the `cleanroom-v0.1` tag of the Tells repo instead of copying it, with ruff and pytest run in CI on Python 3.11 and 3.12. Copying the honesty toolkit would let the three projects drift apart, so a leak fix in one would not reach the others. Analogy: three schools using the same sealed exam board instead of each photocopying and editing its own rulebook.

### D2. The simulator: a payment world with a sealed answer key

The simulator builds an hourly world of leaf segments (BIN range x method x gateway, nested under issuers and countries) with daily and weekly rhythm, binomial approvals, decline reasons and latency, then adds legitimate surges and four kinds of faults, and writes the true causes to a separate sealed file. Real approval data with known causes does not exist publicly, and only a simulator lets attribution be scored, so the honesty work goes into keeping the answer key out of reach: an import-graph test proves no detector, control or agent module can reach the code that writes or reads it. Analogy: a fire drill where only the organizer knows where the fire is, and the firefighters are checked at the door for copies of the plan.
