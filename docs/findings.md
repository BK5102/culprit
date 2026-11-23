# Findings

**All data in this project is simulated.** No result here says how any method performs on real payment data.

**Status: one sealed result (run `test-1`, 2026-11-23).** Every number below is copied from `artifacts/test/summary.json` (plan config hash `c34f77612d40`, from the full hash `c34f77612d405066cbc7982b3c7bf8b81de81d42bbc947705a074b3b3626312a`). Development numbers are not results; they are in `docs/methodology.md` (M42, M51) and `docs/explain-the-project.md`. Negative results stay in (CLAUDE.md rules 10 and 11).

## Question

- **H1.** Does a time series foundation model (TSFM) catch approval-rate drops sooner than simple detectors when every detector is allowed the same number of false alarms per week?
- **H2a.** How often does a deterministic, no-LLM pipeline name the culprit segment on worlds it has never seen?
- **H2b (development only, not in the sealed test).** Does an LLM agent name the culprit more often than that pipeline, and at what cost per incident? The sealed run left the agent out to avoid about 33 dollars of API calls, so this file reports no agent result (D16, M52, L30).

**Short answer:**
- **H1, mixed:** the TSFM beat the seasonal-naive and MSTL detectors, but lost clearly to the binomial z-score detector (A2).
- **H2a:** the no-LLM pipeline named the right culprit for 57% of the faults it investigated, and for 27% of the held-out fault type.

## Setup

- **Plan and lock:** `configs/test.yaml`, config hash `c34f77612d40`, sealed in commit `1567368` (2026-11-22) before any test world was scored.
- **Run:** one sealed run, `test-1`, recorded in commit `44c63e5`. The lock's uses file shows one attempt, started and finished.
- **Worlds:** 10 simulated test worlds: seeds 607890, 906544, 232922, 667770 and 96065, each in two regimes.
  - **base:** the development settings.
  - **second:** noisier and shiftier (approval base rate 0.82, drift sd 0.10, day noise sd 0.12, leaf-day noise sd 0.15, 3 promotions per week).
  - Each world has 4 evaluation weeks, so 40 evaluation weeks and 206 injected faults in all.
- **Held-out fault type:** `extra_verification`, injected only in the test worlds.
- **Budget:** per_incident (alarms within 6 hours count as one page), 2 false incidents per week, persistence 2 hours, calibrated on each world's calibration weeks.
- **Detectors:** A (seasonal naive), A2 (binomial z-score), B (MSTL) and TSFM (Chronos-Bolt-tiny on CPU).
- **Investigators:** the no-LLM control investigated detector A2's incidents. No LLM call was made in the sealed run.

## Headline table

| Question | Measure | Value | 95% interval | Worlds | Config hash |
|---|---|---|---|---|---|
| H1 | Faults caught within 6 hours, TSFM | 80 of 206 (0.388) | 0.324 to 0.456 | 10 | c34f77612d40 |
| H1 | Faults caught within 6 hours, A (seasonal naive) | 36 of 206 (0.175) | 0.129 to 0.232 | 10 | c34f77612d40 |
| H1 | Faults caught within 6 hours, A2 (binomial z-score) | 104 of 206 (0.505) | 0.437 to 0.572 | 10 | c34f77612d40 |
| H1 | Faults caught within 6 hours, B (MSTL) | 50 of 206 (0.243) | 0.189 to 0.306 | 10 | c34f77612d40 |
| H1 | TSFM minus A (paired, by world) | +0.214 | +0.108 to +0.320 | 10 | c34f77612d40 |
| H1 | TSFM minus A2 (paired, by world) | -0.117 | -0.211 to -0.039 | 10 | c34f77612d40 |
| H1 | TSFM minus B (paired, by world) | +0.146 | +0.076 to +0.207 | 10 | c34f77612d40 |
| H1 | False incidents per week achieved in evaluation (the budget unit; target 2) | A 1.70, A2 1.90, B 2.50, TSFM 1.65 | | 10 | c34f77612d40 |
| H1 | False alarms per week achieved in evaluation (every series alarm) | A 2.42, A2 6.12, B 3.30, TSFM 2.42 | | 10 | c34f77612d40 |
| H2a | Top-1 culprit accuracy, control | 70 of 122 (0.574) | 0.485 to 0.658 | 10 | c34f77612d40 |
| H2a | Top-3 culprit accuracy, control | 81 of 122 (0.664) | 0.576 to 0.742 | 10 | c34f77612d40 |
| H2a | Fault-type accuracy, control | 74 of 122 (0.607) | 0.518 to 0.689 | 10 | c34f77612d40 |
| H2b | Agent against control | Not in the sealed test (D16, M52) | | | |

The control is graded on the 122 faults that detector A2 detected; faults no incident covered were never investigated. Median detection delay was 1 hour for every detector.

## The held-out fault type and the second regime

**Held-out type (`extra_verification`, 38 faults):**
- **Caught within 6 hours:** A2 18 (0.474, 0.325 to 0.627), TSFM 9 (0.237, 0.130 to 0.392), A 6 (0.158) and B 3 (0.079).
- **Control:** top-1 7 of 26 (0.269, 0.137 to 0.461), and top-3 13 of 26 (0.500).
- **Summary:** this is much worse than the control's accuracy on the development types (0.59 to 0.71 top-1 on the test worlds), so the control is partly tuned to the fault types it was built on.

**Second regime (103 faults per regime):**
- **TSFM:** caught 40 in each regime (0.388 both).
- **A2:** dropped from 58 (0.563) to 46 (0.447).
- **B:** dropped from 29 (0.282) to 21 (0.204).
- **Control:** top-1 was 0.544 in base (37 of 68) and 0.611 in the second regime (33 of 54).

## What worked

- **TSFM against two simple detectors:** the TSFM beat the seasonal-naive and MSTL detectors, with paired intervals well above zero.
- **The noisier regime:** the TSFM's catch rate did not fall in the noisier, shiftier second regime, while A2's and B's did (A, the weakest, rose slightly from 0.165 to 0.184).
- **The no-LLM control:** it named the right culprit for over half of the investigated faults on unseen worlds, including the noisier regime.

## What did not work

- **H1 against the strongest simple detector:** the TSFM caught 0.117 fewer faults within 6 hours than the binomial z-score detector A2 (interval -0.211 to -0.039).
  - A2 also caught twice as many of the held-out type.
  - Both stayed within the incident budget (1.90 and 1.65 false incidents per week). But A2 raised 6.12 single-series alarms per week against 2.42 for the TSFM, because per-incident counting chains alarms on many series into one page (L22). A team that pays per series alarm would see A2 as noisier.
- **Overall detection was modest:** the best detector caught about half the faults within 6 hours; A caught under a fifth.
- **The held-out fault type:** the control named its culprit only 27% of the time.
- **Missed faults were never investigated:** 84 of 206 faults were never detected by A2, so no investigator saw them.
- **Budget overrun:** detector B overran the false-incident budget in evaluation (2.50 against 2).

## What could not be tested

- **Real payment data:** none is used; every world is simulated.
- **The LLM agent against the control (H2b):** left out of the sealed run on cost. The development evidence is one world with 10 faults, too few to tell the two apart (L30).
- **The critic's planned LLM review stage:** not built.
- **Power:** the pooled intervals rest on 10 worlds (L26).

## Next steps

- **H2b:** test the LLM agent against the control on new seeds, with a budget of about 35 to 60 dollars.
- **A stronger TSFM detector:** A2's simple count-based model beat it. A TSFM detector could use the same binomial noise model on top of its forecast.
- **The held-out fault type:** improve the control on new fault types without tuning on the test worlds.
