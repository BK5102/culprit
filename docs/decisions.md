# Decisions

One entry per decision or feature: what was decided, why, and an analogy. These are the owner's talking points. Newest at the bottom. The full reasoning for each choice is in `docs/methodology.md`.

## Build 1 (2026-11-17)

### D1. Scaffold: uv, ruff, pytest, CI, and the Cleanroom from its git tag

The repo is a uv project that installs the shared Cleanroom from the `cleanroom-v0.1` tag of the Tells repo instead of copying it, with ruff and pytest run in CI on Python 3.11 and 3.12. Copying the honesty toolkit would let the three projects drift apart, so a leak fix in one would not reach the others. Analogy: three schools using the same sealed exam board instead of each photocopying and editing its own rulebook.

### D2. The simulator: a payment world with a sealed answer key

The simulator builds an hourly world of leaf segments (BIN range x method x gateway, nested under issuers and countries) with daily and weekly rhythm, binomial approvals, decline reasons and latency, then adds legitimate surges and four kinds of faults, and writes the true causes to a separate sealed file. Real approval data with known causes does not exist publicly, and only a simulator lets attribution be scored, so the honesty work goes into keeping the answer key out of reach: an import-graph test proves no detector, control or agent module can reach the code that writes or reads it. Analogy: a fire drill where only the organizer knows where the fire is, and the firefighters are checked at the door for copies of the plan.

### D3. Measure the simulated world before building on it

`scripts/check_data_fit.py` checks that faults are neither obvious nor invisible at their own segment, that many hide in the overall rate, that promotions fool a naive detector, that a forecaster has room to beat seasonal naive, and that "pick the biggest drop" does not already find the culprit. The first run showed faults were far too easy (88.9% of them over 10 times the noise), so the fault sizes were lowered before any detector existed, and the first run is kept in `docs/data-fit.md` as a negative result. Analogy: before timing runners, check that the track is not downhill.

### D4. Detectors compared at the same false-alarm budget

Four detectors score every monitored series: A (same hour last week, with a robust spread), A2 (a binomial z-score that knows small segments are noisier), B (MSTL seasonal pattern with intervals) and C (Chronos-Bolt-tiny forecasting the rate, tested so far with a fake stand-in). Each gets its threshold on a fault-free calibration window so that all of them raise at most 2 alarms per week across all series, using the Cleanroom's alarm rule and calibration, and a test proves every score uses only the past. Analogy: four smoke detectors tuned so each beeps falsely twice a week, then judged on how fast they notice a real fire.
