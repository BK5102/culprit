# Methodology: every choice, why it was made, and what it costs

This file is the reasoning behind Culprit. Each decision has the same four parts: **what** was chosen, **why**, **what else was considered**, and the **limitation** it brings. Decision ids (M1, M2, ...) are stable so other docs can point to them. `docs/decisions.md` is the dated diary of when things were built; this file is the argument for why they were built that way.

Rule for contributors (also in `CLAUDE.md`, rule 13): any new method, variable, threshold, default, or simulator setting gets an entry here in the same commit, and any new limitation goes in the register at the bottom.

All data in this project is simulated. Numbers quoted below come from code run on simulated worlds and are labeled as such.

---

## 1. The question

**M1. Two questions, both scored once after a lock: H1 (detection) and H2 (attribution).**
- What: H1 asks whether a TSFM detector catches approval-rate drops sooner than simple detectors when every detector is allowed the same number of false alarms per week. H2 asks whether an LLM agent names the culprit segment more often than a deterministic no-LLM pipeline, and at what cost per incident. Planned headline wording (from `NEXT_PROJECTS_PLAN.md`): H1 faults caught within 6 hours at 2 false alarms per week; H2 top-1 culprit accuracy, agent minus control.
- Why: operations teams feel two things, how fast a problem is noticed and how fast its cause is found. A detector that alarms all the time catches everything, so speed only means something at a fixed false-alarm rate. An agent only earns its cost if it beats a script.
- Considered: one combined score. Rejected: it would hide whether a gain came from detection or from investigation.
- Limitation: both answers hold only for this simulator and its settings.

**M2. Simulated data only.**
- What: every payment count comes from Culprit's own simulator (`src/culprit/sim/`).
- Why: real approval data is private, and real incidents almost never come with a reliable record of the true cause. A simulator lets faults be injected with a known cause, so attribution can be scored at all. No real customer data, no paid data.
- Considered: an optional second world built from a public dataset (`NEXT_PROJECTS_PLAN.md` mentions TabFormer's error column). Deferred until it passes its own fit check.
- Limitation: the simulator encodes the author's assumptions. A method tuned on it may exploit its quirks (mitigated by M16, a held-out fault type).

## 2. Tooling

**M3. The shared Cleanroom is installed from the git tag `cleanroom-v0.2`, never copied.**
- What: `pyproject.toml` pulls `cleanroom` from `github.com/BK5102/tells`, tag `cleanroom-v0.2`, subdirectory `packages/cleanroom`. Culprit uses its time split (`cleanroom.split`), lock (`cleanroom.lock`), sealed runs (`cleanroom.guard`), answer-key vault (`cleanroom.vault`), alarm rules, alarm matching and threshold calibration (`cleanroom.events`), forecast interval coverage (`cleanroom.forecast`), provenance and the past-only test helper.
- Why: one copy of the honesty machinery for all three projects, so a fix in one place reaches all of them (Tells `docs/decisions.md` D1).
- Considered: a local copy. Rejected: copies drift.
- Limitation: Culprit is pinned to whatever v0.2 contains until it bumps on purpose.

**M4. Started on cleanroom-v0.1, bumped to v0.2 the same day; no local stand-ins remain.**
- What: the first scaffold used `cleanroom-v0.1`, with a TODO to bump once v0.2 (events, vault, guard, forecast scoring) was released. v0.2 was tagged while the detectors were being written, so the bump happened before any detector, budget or grading code was committed, and those were written against v0.2 directly.
- Why: siblings depend only on released tags; v0.1 lacked the event tools Culprit needs.
- Considered: writing local versions of event matching and thresholding first. Not needed once v0.2 existed.
- Limitation: none beyond M3.

**M5. CPU only.**
- What: every step, including the full config and the TSFM detector, runs on a laptop CPU. PyTorch comes from the CPU-only wheel index.
- Why: no GPU is available, and a result that needs special hardware is harder for others to rerun. The approved plan budgets about 2 to 3 CPU hours for Chronos-Bolt-tiny on the full config, cached.
- Considered: a cloud GPU for the TSFM. Rejected by the owner.
- Limitation: rules out larger TSFMs on the full config.

**M6. numpy for the simulator and detectors, polars for files, statsmodels for the classical forecaster.**
- What: the world is held as arrays of shape (segments, hours); files are Parquet written by polars; Detector B uses statsmodels.
- Why: counts per segment-hour are a dense grid, so array maths is fast and simple on a CPU. polars is what Cleanroom uses. statsmodels is the standard, well-tested Python source for MSTL.
- Considered: pandas everywhere. Not needed.
- Limitation: none material.

## 3. The simulated world

**M7. Hourly data.**
- What: one row per leaf segment per hour.
- Why: approved in the plan. Faults last hours, not minutes or days, so hourly is fine enough to measure detection delay in hours (H1 asks "within 6 hours") and coarse enough for a TSFM to run on a CPU.
- Considered: 5-minute data (more realistic for outages, about 12 times the compute); daily (too coarse to time a 3-hour outage).
- Limitation: an outage shorter than an hour is smeared across one or two rows.

**M8. Hierarchy: country > issuer > BIN range, crossed with payment method and gateway; leaves are BIN x method x gateway.**
- What: a BIN range (the first digits of a card number, which identify the bank and card product; like a postcode for cards) belongs to one issuer (the customer's bank), and an issuer to one country. Every BIN can be routed through every gateway (the processor that carries the payment to the card network) and used with every method. Small config: 2 countries x 3 issuers x 2 BINs x 2 methods x 4 gateways = 96 leaves. Full config: 4 x 5 x 4 x 3 x 6 = 1,440 leaves. Volume shares at each level come from Dirichlet draws (concentration 4 for countries, methods and gateways; 1 for issuers within a country and BINs within an issuer), times a lognormal leaf wobble (sd 0.2), so there is a long tail of small segments.
- Why: these are the dimensions named in PLAN.md FR1, and the fault types live on different ones (issuer, BIN, gateway, issuer x method), so the investigation has to search more than one path. Approved size: about 1,000 to 2,000 leaves full, about 100 small.
- Considered: a random sparse subset of combinations (more realistic, as not every BIN uses every gateway). Deferred: the full cross product makes the reconciliation test exact and simple.
- Limitation: real routing is uneven and changes over time; here every gateway carries every BIN for the whole run.

**M9. Volume: hour-of-day curve in local time, day-of-week factors, holidays, and day noise.**
- What: expected attempts per leaf-hour = mean attempts per hour (20,000 small, 150,000 full) x leaf share x hour-of-day curve (two bumps, near 12:00 and 19:30 local, with a floor of 0.15 at night, normalized to mean 1) x day-of-week factor (Monday to Sunday 0.95, 0.95, 0.98, 1.0, 1.1, 1.12, 0.9, normalized) x holiday factor (0.6 on simulated day 17) x country-day noise (lognormal sd 0.08) x leaf-day noise (lognormal sd 0.10). Countries get a timezone offset between -6 and +6 hours (the first country 0). Attempts are Poisson draws around the expectation.
- Why: approval monitoring is hard mainly because of rhythm (night hours are thin and noisy) and because volume shifts move parent rates. These shapes are plausible guesses, not measurements.
- Considered: fitting the shapes to a public retail or e-commerce volume dataset (PLAN.md Data). Deferred: needs a license check first; the plan allows it as optional.
- Limitation: the shapes are the author's assumptions (L3).

**M10. Approval: additive log-odds effects, a daily rhythm, slow drift, and binomial draws.**
- What: the normal approval probability of a leaf is the logistic of: logit(0.87) + country (sd 0.25) + issuer (sd 0.35) + BIN (sd 0.30) + method (sd 0.30) + gateway (sd 0.10) + leaf (sd 0.15) effects, plus a daily rhythm of amplitude 0.15 on the log-odds scale (lowest at 03:00 local), plus a day-to-day drift (AR(1) with phi 0.9 and shock sd 0.05, constant within a day). Approvals are a binomial draw over attempts.
- Why: log-odds keep every probability between 0 and 1 and make "this bank approves less than that one" additive. Binomial draws mean small segments are noisy in the right way, which is the core difficulty of finding a drop in one small slice. Drift means a forecaster cannot just memorize a fixed level.
- Considered: fixed rates per segment (too easy for every detector); beta-binomial overdispersion (left for a later simulator regime, which rule 9 needs anyway).
- Limitation: the base rate 0.87 and the effect sizes are not sourced; they give leaf approval rates of roughly 0.68 to 0.97 in the small world (measured on seed 1).

**M11. Decline reasons: a normal mix per leaf, and event signatures for the changed declines.**
- What: six reasons (insufficient_funds, do_not_honor, suspected_fraud, issuer_unavailable, processing_error, authentication_required). Each leaf's normal mix is a Dirichlet draw around (0.42, 0.22, 0.18, 0.03, 0.05, 0.10) with concentration 50. When a surge or fault moves the approval probability from p_old to p_new, the moved share (p_old - p_new) is added to that event's signature reasons; declines are then split by these weights with sequential binomial draws, so they always sum exactly to attempts minus approvals.
- Why: decline reasons are the main evidence an investigator uses to tell an outage from a fraud rule from a verification change. Tying them to the changed declines keeps them consistent with the rate drop.
- Considered: real ISO 8583 response codes. Not used: the names are enough, and the mapping to exact codes was not checked against the standard.
- Limitation: real reason codes are messier (issuers map them differently); here every fault has a clean signature.

**M12. Latency: per-gateway base time, a busy-hour load factor, fault factors, and noise that shrinks with volume.**
- What: base 250 to 600 ms per gateway, times 1 + 0.15 x (hour curve / its max), times the product of active fault latency factors, times exp(noise sd 0.25 / sqrt(attempts)). Missing (NaN) in hours with no attempts.
- Why: gateway degradation shows mainly as slowness; an investigator needs it to separate a gateway problem from an issuer problem.
- Considered: percentiles (p95) instead of the mean. Deferred: the mean is enough for v0.1.
- Limitation: no latency spikes without a fault; real systems have them.

**M13. Two kinds of legitimate surge: promotions and paydays.**
- What: promotions hit one country's card-not-present payments for 4 to 12 hours, with volume x1.5 to 3.0 and approval log-odds -0.10 to -0.35 (the extra declines are insufficient_funds). Paydays hit one country for one local day with volume x1.2 to 1.5 and log-odds +0.05 to +0.15 (fewer insufficient_funds declines). About 2 promotions and 1 payday per week, Poisson, in every window including the context period.
- Why: PLAN.md FR3 and FR17. A promotion is a real approval-rate dip that is not a fault, which is the false-alarm trap: a detector that alarms on it wastes an analyst's time, and an investigator that blames it is wrong. Paydays shift the mix of the total without any segment failing.
- Considered: telling detectors about the marketing calendar. Not done: the trap is only a trap if the detector has to cope with it.
- Limitation: two surge shapes only; real promotions vary much more.

**M14. Four fault types, each with a target level, severity, duration, decline signature and latency factor.**
- What: issuer_outage (one issuer, severity 0.01 to 0.40, 2 to 8 hours, issuer_unavailable 85% and processing_error 15%, latency x1.2 to 1.6); bin_decline_spike (one BIN, 0.01 to 0.30, 4 to 24 hours, do_not_honor 80% and suspected_fraud 20%, no latency change); gateway_degradation (one gateway, 0.01 to 0.15, 1 to 6 hours, processing_error 90% and issuer_unavailable 10%, latency x2 to 4); extra_verification (one issuer's card-not-present payments, 0.01 to 0.20, 12 to 48 hours, authentication_required 90% and do_not_honor 10%, latency x1.1 to 1.3). Severity is the share of approvals lost: p becomes p x (1 - severity) on every leaf under the target. Severity is drawn log-uniformly, so a fault of 1% to 2% is as likely as one of 20% to 40%.
- History: the first ranges were 0.25 to 0.70, 0.15 to 0.50, 0.05 to 0.25 and 0.10 to 0.30, drawn uniformly. Data-fit run 1 showed 88.9% of faults at over 10 times the noise and none under 3 times, so every detector would catch everything at once and H1 could not separate them (`docs/data-fit.md`). The ranges were lowered before any detector existed; this changes the exam's difficulty on development seeds, it does not tune any method.
- Why: these are the four causes in PLAN.md FR4. Their blast radius differs (a gateway carries a quarter or a sixth of all traffic, a BIN about 1%), so some faults hide in the overall rate and some do not.
- Considered: gradual ramps instead of steps. Deferred to a later regime.
- Limitation: ranges are assumptions, chosen so detection is neither trivial nor hopeless; real outages are often total for minutes rather than partial for hours, and the mildest "outages" here (1% of approvals) are really partial degradations.

**M15. Faults only in the evaluation window, Poisson in number, uniform in start and target, overlaps allowed.**
- What: 5 faults per week (small) or 6 (full) on average; the type is uniform among the configured types, the target uniform among segments of that level, the start uniform within the evaluation window so the fault ends inside it.
- Why: CLAUDE.md rule 3 (context is normal only) and the calibration window must be fault-free so every alarm there is false. Overlaps are allowed because FR17 asks for them.
- Considered: a fixed number per week. Poisson gives quiet and busy weeks, which is closer to life.
- Limitation: uniform targets mean tiny BINs are hit as often as big ones.

**M16. `extra_verification` is the held-out fault type.**
- What: development worlds (small and full configs) inject only the other three types. The held-out type appears only in the sealed test worlds. The control's fault-typing rule for it is written from the description of the fault (authentication declines rise), not tuned on any world that contains it.
- Why: CLAUDE.md rule 9. If the system only works on causes it was tuned on, the held-out type will show it. Approved in the plan.
- Considered: holding out gateway_degradation. Rejected: extra_verification is the most different in shape (long, mild, on a cross segment), so it is the stronger test.
- Limitation: one held-out type; a single type can be easy or hard by accident.

**M17. Timeline and split: context (normal only), calibration (no faults), evaluation (faults), through `cleanroom.split`.**
- What: small config 4 + 2 + 2 weeks, full 6 + 2 + 4 weeks, starting on a simulated Monday, 2026-01-05. `Timeline.split()` returns a Cleanroom `Split` with train = context, valid = calibration, test = evaluation.
- Why: forecasters need weeks of normal history (the weekly rhythm repeats every 168 hours). Thresholds are set on calibration, which has surges but no faults, so every calibration alarm is a false alarm and the alarm budget can be set honestly. Evaluation is the only place faults exist.
- Considered: calibrating on the evaluation window. Rejected: thresholds would be tuned on the data they are scored on.
- Limitation: calibration and evaluation come from the same simulated world, so a regime change between them is not tested yet.

**M18. The answer key is written to a separate `sealed/` folder, and only the grader reads it.**
- What: `culprit.sim.build.write_world` writes `observed/` (panel and public leaf table) and `sealed/answer_key.json` (faults and surges with their true targets and hours). `culprit.world.load_observed` reads only `observed/`. Tests prove that no detector, control or agent module can import `culprit.sim` or `culprit.evaluate` (import-graph test), that no other module names the key file, that the observed files mention no fault or surge, and that everything still loads with `sealed/` deleted.
- Why: CLAUDE.md rule 1. A sealed key is like a fire drill where only the organizer knows where the fire is.
- Considered: encrypting the key. Not needed for honesty between code modules, and the key is also sealed with the Cleanroom vault, which releases it only to a finished, locked run (M39).
- Limitation: a person can still open the file; the protection is against code paths, and git history shows who changed what.

**M19. Seeds and hashes.**
- What: one integer seed per world is split with numpy's `SeedSequence.spawn` into eight independent streams (hierarchy, volume, approval, surges, faults, attempts, approvals, signals). `dataset_hash` is a sha256 over the observed arrays; it is stored in `observed/world.json` and checked every time a world is loaded, so a changed file fails loudly. The key's own sha256 is recorded too.
- Why: FR7 and CLAUDE.md rule 12. Separate streams mean, for example, that changing the fault schedule does not change the hierarchy.
- Limitation: the hash is reproducible for the same library versions; a numpy change to its random algorithms could change worlds (uv.lock pins versions).


## 4. Data fit

**M20. A data-fit gate before any detector: signal versus noise, masking, surge traps, headroom, too easy, bookkeeping.**
- What: `scripts/check_data_fit.py` simulates development seeds in memory and measures six things (definitions in the script docstring and `docs/data-fit.md`). Gates: largest-rate-drop top-1 under 90% (from the plan); some faults masked in the total but visible at their segment; at least half of faults with whole-window SNR of at least 3; detection not trivial (under half of faults at 10 times the empirical hourly noise and over 10% under 3 times); promotions fire a naive detector more often than quiet windows; oracle error under 0.9 of seasonal naive's at the leaf level; bookkeeping reconciles.
- Why: Tells' main lesson was to measure whether the data can answer the question before building on it (`NEXT_PROJECTS_PLAN.md`). A world where faults are obvious, invisible, or where the largest drop is always the culprit cannot test H1 or H2.
- Considered: only the plan's four checks. Added "detection not trivial" after run 1 showed every fault was obvious, and a 4-week pooled baseline column to headroom so the TSFM's real room is visible.
- Limitation: the gate thresholds (3 sigma, 10 sigma, 0.9) are judgment calls, written down before any detector or result existed. The check uses the simulator's truth, so it says what is possible, not what a method achieves.

---

## Limitations register

The honest list. Each item says what could be wrong and what was done about it.

| # | Limitation | Effect | What was done |
|---|---|---|---|
| L1 | Simulated data only | No result shows real-world performance | Stated on the first screen of the README and in every report (CLAUDE.md rule 8) |
| L2 | Cleanroom is pinned to one tag | Fixes made in Tells after `cleanroom-v0.2` do not reach Culprit until a deliberate bump | Bump on purpose, as done from v0.1 to v0.2 (M4) |
| L3 | Seasonality, base rates, fault ranges and surge shapes are the author's assumptions | Results depend on these choices | Each value is listed in M9 to M15; a second simulator regime is required at test time (rule 9) |
| L4 | Every fault has a clean decline-reason signature | Fault typing is easier than on real data | Stated; reason leakage (part of each fault's declines go to a second reason) adds some mess |
| L5 | Fault targets are uniform among segments of a level | Tiny BINs are hit as often as large ones, which makes some faults nearly invisible | Measured in the fit check (signal versus noise per fault) |
| L6 | One held-out fault type | A single type can be easy or hard by accident | Stated; reported separately from the development types |
| L7 | The answer key is protected against code paths, not against people | A person could read it | Import-graph and text tests; Cleanroom vault with a release log (M18, M39) |
| L8 | Headroom over a 4-week pooled average is small at the leaf level (oracle / pooled 0.87 small, 0.89 full) | A TSFM has little room to beat a cheap baseline on single leaves; gains, if any, should come on aggregates | Measured and reported in `docs/data-fit.md` before any detector; stated with H1 |
