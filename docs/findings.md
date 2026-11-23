# Findings

**All data in this project is simulated.** No result here says how any method performs on real payment data.

**Status: no sealed result exists yet.** The test plan (`configs/test.yaml`) has every owner choice made but has not been sealed, and no sealed run has happened. The sealed run leaves out the LLM agent (decided 2026-11-22, `docs/decisions.md` D16, methodology M52). Every cell below that would hold a measured number says "[placeholder: not measured]". Development numbers (from the small and full development worlds) are not results and are kept out of this file; they are in `docs/methodology.md` (M42), `docs/tsfm-notes.md` and `docs/explain-the-project.md`.

Fill this file only from `artifacts/test/summary.json` and the per-world `grade.json` files of the sealed run, copying each number with its config hash (`docs/runbook.md`, last step). Negative results stay in, including any case where the no-LLM control beats the agent or a simple detector beats the TSFM (CLAUDE.md rules 10 and 11).

## Question

- **H1.** Does a time series foundation model (TSFM) catch approval-rate drops sooner than simple detectors when every detector is allowed the same number of false alarms per week?
- **H2a.** How often does a deterministic, no-LLM pipeline name the culprit segment on worlds it has never seen?
- **H2b (development only, not in the sealed test).** Does an LLM agent name the culprit more often than that pipeline, and at what cost per incident? The sealed run leaves the agent out to avoid about 33 dollars of API calls, so this file reports no agent result (M52, L30).

## Setup

[placeholder: not measured] Fill from the sealed lock: plan config hash, git commit of the sealed run, run id and run number (from the lock's uses file), test seeds, the two simulator regimes, the budget counting mode, the held-out fault type, detector versions (including the TSFM checkpoint), and a note that the sealed run made no LLM call.

## Headline table

| Question | Measure | Value | 95% interval | Worlds | Config hash |
|---|---|---|---|---|---|
| H1 | Faults caught within 6 hours, TSFM | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | Faults caught within 6 hours, A (seasonal naive) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | Faults caught within 6 hours, A2 (binomial z-score) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | Faults caught within 6 hours, B (MSTL) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | TSFM minus each other detector (paired, by world) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | False alarms per week achieved in evaluation, per detector | [placeholder: not measured] | | [placeholder: not measured] | [placeholder: not measured] |
| H2a | Top-1 culprit accuracy, control | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H2a | Top-3 culprit accuracy, control | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H2a | Fault-type accuracy, control | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H2b | Agent against control | Not in the sealed test (D16, M52) | | | |

## The held-out fault type and the second regime

[placeholder: not measured] Report `extra_verification` on its own (detection and attribution) and the second regime next to the base regime, from the `by_type` and `by_regime` tables of the summary. Say plainly if either one is much worse than the development types or the base regime.

## What worked

[placeholder: not measured]

## What did not work

[placeholder: not measured] Include every negative result: detectors that missed fault types, the control or the agent losing, surge incidents blamed on a fault, and any crashed sealed attempt (the lock's uses file counts every attempt).

## What could not be tested

[placeholder: not measured] At least: real payment data (none is used), the critic's planned LLM review stage (not built), the LLM agent against the control (H2b: left out of the sealed run on cost, development evidence only, L30), and anything else the sealed run skipped.

## Next steps

[placeholder: not measured]
