# Findings

**All data in this project is simulated.** No result here says how any method performs on real payment data.

**Status: no sealed result exists yet.** The test plan (`configs/test.yaml`) is a draft with open owner choices, it has not been sealed, and no sealed run has happened. Every cell below that would hold a measured number says "[placeholder: not measured]". Development numbers (from the small and full development worlds) are not results and are kept out of this file; they are in `docs/methodology.md` (M42), `docs/tsfm-notes.md` and `docs/explain-the-project.md`.

Fill this file only from `artifacts/test/summary.json` and the per-world `grade.json` files of the sealed run, copying each number with its config hash (`docs/runbook.md`, last step). Negative results stay in, including any case where the no-LLM control beats the agent or a simple detector beats the TSFM (CLAUDE.md rules 10 and 11).

## Question

- **H1.** Does a time series foundation model (TSFM) catch approval-rate drops sooner than simple detectors when every detector is allowed the same number of false alarms per week?
- **H2.** Does an LLM agent name the culprit segment more often than a deterministic, no-LLM pipeline, and at what cost per incident?

## Setup

[placeholder: not measured] Fill from the sealed lock: plan config hash, git commit of the sealed run, run id and run number (from the lock's uses file), test seeds, the two simulator regimes, the budget counting mode, the held-out fault type, detector versions (including the TSFM checkpoint), the agent model and prompt hash, and the spend caps.

## Headline table

| Question | Measure | Value | 95% interval | Worlds | Config hash |
|---|---|---|---|---|---|
| H1 | Faults caught within 6 hours, TSFM | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | Faults caught within 6 hours, A (seasonal naive) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | Faults caught within 6 hours, A2 (binomial z-score) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | Faults caught within 6 hours, B (MSTL) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | TSFM minus each other detector (paired, by world) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H1 | False alarms per week achieved in evaluation, per detector | [placeholder: not measured] | | [placeholder: not measured] | [placeholder: not measured] |
| H2 | Top-1 culprit accuracy, control | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H2 | Top-1 culprit accuracy, agent | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H2 | Agent minus control top-1 (paired, by world) | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] | [placeholder: not measured] |
| H2 | Agent cost per incident (median, USD) | [placeholder: not measured] | | [placeholder: not measured] | [placeholder: not measured] |

## The held-out fault type and the second regime

[placeholder: not measured] Report `extra_verification` on its own (detection and attribution) and the second regime next to the base regime, from the `by_type` and `by_regime` tables of the summary. Say plainly if either one is much worse than the development types or the base regime.

## What worked

[placeholder: not measured]

## What did not work

[placeholder: not measured] Include every negative result: detectors that missed fault types, the control or the agent losing, surge incidents blamed on a fault, incidents the agent did not run or the critic rejected, and any crashed sealed attempt (the lock's uses file counts every attempt).

## What could not be tested

[placeholder: not measured] At least: real payment data (none is used), the critic's planned LLM review stage (not built), and anything the sealed run skipped.

## Next steps

[placeholder: not measured]
