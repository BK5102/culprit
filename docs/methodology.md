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

## 5. Detectors ("know normal")

**M21. Every detector watches the same series: the total, every single-dimension segment, and every leaf.**
- What: 1 total + each country, issuer, BIN, method and gateway + each leaf: 123 series in the small config and 1,554 in the full one. Scores start at the first calibration hour.
- Why: a fault on an issuer shows most clearly at the issuer, a gateway fault at the gateway, and a masked fault only below the total. Watching one level would hide some fault types from some detectors. The same set for every detector keeps the comparison fair.
- Considered: leaves only (most series, weakest signal each); every cross combination such as issuer x method (many more series, and more false alarms at a fixed budget).
- Limitation: cross segments such as an issuer's card-not-present payments are not watched directly; the held-out extra-verification fault lives on one and must show through its issuer or its leaves.

**M22. Detector A: seasonal naive with a MAD threshold.**
- What: forecast = the rate at the same hour last week; score = (forecast - actual) / (1.4826 x MAD of that residual over the previous 4 weeks, refreshed daily). Where the MAD is zero, the standard deviation is used.
- Why: the laziest sensible forecaster (PLAN.md Diagram 4, "last week's same hour"). The MAD (median absolute deviation, a spread measure that ignores a few wild values; like judging a commute by a typical day, not the day of the snowstorm) keeps one bad hour from inflating the scale.
- History: on the full world, tiny leaves (one or two attempts an hour) have rates of exactly 0 or 1 almost always, so their MAD was 0, their scores hit 10,000, and the budget threshold rose so high that A raised no alarm at all. The standard-deviation fallback was added on 2026-11-17, before any grading code existed.
- Limitation: one noisy past point per forecast; its error includes last week's noise as well as this week's.

**M23. Detector A2: binomial-aware seasonal z-score (CUSUM available, not the default).**
- What: expected rate = approvals over attempts pooled over the same hour of the previous 4 weeks; z = (n p - approvals) / sqrt(n p (1 - p) (1 + n / n_base)); z is divided by its own robust spread over the previous 4 weeks (at least 1, refreshed daily) to absorb drift. `a2_mode: cusum` adds a one-sided CUSUM with k = 0.5.
- Why: this is the detector that knows a rate from 20 payments is noisier than one from 20,000. The plan allows a z-score or a CUSUM. A CUSUM's score grows with event length: on a development world a long promotion in the calibration week reached 307, set the threshold at 204, and a 6-hour 40% outage (score 169) went unflagged. A per-hour z keeps short outages and long surges on the same scale. The choice was made while writing tests, before any grading code existed.
- Considered: a beta-binomial likelihood ratio. Deferred: more machinery for the same idea.
- Limitation: a slow, mild fault (the held-out extra-verification type lasts 12 to 48 hours) is exactly what a CUSUM would catch better, so A2 may be weak on it; the CUSUM stays in code for that comparison.

**M24. Detector B: MSTL seasonal pattern plus an exponentially smoothed level, with intervals by hour of day.**
- What: statsmodels MSTL (periods 24 and 168, one iteration, LOESS jumps of 24) on the last 4 weeks of the context, once per series. Forecast = weekly-plus-daily pattern + a level updated each hour with exponential smoothing (alpha 0.05) on past deseasonalized values. Interval spread = robust spread of one-step errors over the last 2 weeks of context, one value per hour of day. Score = (forecast - actual) / spread.
- Why: MSTL (a classical split of a series into trend, daily and weekly rhythm; like separating a song into bass line and melody) is the standard decomposition for hourly data with two rhythms. Fitting once on normal-only context and updating only the level is cheap and cannot learn from faults. LOESS jumps cut the fit from about 0.5 s to 0.02 s per series (measured 2026-11-17), so the full config's 1,554 series take about 22 s.
- Considered: statsmodels ExponentialSmoothing (Holt-Winters, the classical ETS model) with a 168-hour season (about 0.1 s per series with a 24-hour season, and it must fit 168 starting values for a weekly one); refitting MSTL every day (more adaptive, about 50 times the cost).
- Limitation: the seasonal pattern is frozen at the end of the context, so a holiday or a slow change in rhythm during evaluation is absorbed only through the level.

**M25. Detector C: Chronos-Bolt-tiny forecasts the rate, zero-shot, with a quantile-based score.**
- What: at origins every 24 hours (fixed points starting at the first calibration hour), the model reads each series' last 512 hourly rates and returns the 0.1, 0.5 and 0.9 quantiles for the next 24 hours. Score = (median - actual) / ((median - q0.1) / 1.2816). Weights pinned to revision `a0e552de83495b5c28c14c71c374f3e33280b340` (`docs/tsfm-notes.md`). CPU only, optional `tsfm` extra, forecasts cacheable on disk. `FakeForecaster` (seasonal mean and robust spread) stands in for tests.
- Why: approved in the plan ("TSFM detector forecasts the rate"; Chronos-Bolt-tiny is already pinned and cheap on CPU from Tells). Zero-shot means the model is used as is, with no training on this data (like asking an experienced forecaster about a new city without a briefing). Forecasting the rate matches what the other detectors judge. Daily origins keep the full config to about 1,554 x 56 forecasts.
- Considered: an hourly rolling origin (24 times the cost); forecasting approvals and attempts separately (two models, harder to compare).
- Limitation: the model does not know how many attempts are behind each rate, so it can only infer that a small segment is noisy from the history's own wiggle. The PLAN.md "persistence rule" is the same k-hour rule as every detector (M26).

**M26. One alarm rule for every detector: score above threshold for 2 consecutive hours, one alarm per run (`cleanroom.events.persistent_alarms`), per series; alarms within 6 hours form one incident.**
- What: persistence k = 2 hours; each monitored series is its own group. Incidents chain alarms whose hours are within 6 hours of the incident's latest alarm.
- Why: one rule for all keeps the comparison about the forecasts, not about alarm logic. Two hours trades about one hour of delay for far fewer one-hour blips. Incidents are what an analyst investigates.
- Considered: k = 1 (faster, noisier) and k = 3. Not tuned; k is a config value and stays fixed before the lock.
- Limitation: a 1-hour fault (gateway degradation can last 1 hour) can never trigger a 2-hour rule.

**M27. Equal false-alarm budget: 2 alarms per week across all monitored series, set on the fault-free calibration window (`cleanroom.events.threshold_for_alarm_rate`).**
- What: per detector, the lowest threshold whose alarm count on the 2-week calibration window is at most 2 per week for it and every higher candidate. `total_time` is the calibration length (336 hours) and the unit 168 hours, so the rate is per week of wall time for the whole monitored set, not per series.
- Why: CLAUDE.md rule 2. A detector that alarms constantly catches everything; comparing at the same false-alarm rate is what an operations team cares about. The calibration window has surges but no faults, so every alarm there is false, and it comes before evaluation.
- Considered: a budget on incidents (pages) instead of series alarms. Series alarms are what the Cleanroom function counts and are unambiguous; one surge that fires three series counts three times, which is stricter.
- Limitation: 2 per week over 2 weeks means the threshold rests on about 4 calibration alarms, so it is itself noisy; evaluation-window false alarms are graded separately and may differ.

**M28. Every score builder has a past-only test.**
- What: `tests/test_detectors.py` runs `cleanroom.pastonly.assert_past_only` on A, A2 (both modes), B and the TSFM detector with the fake forecaster: for probe hours, scores rebuilt from only earlier rows (plus the probe) must equal scores from the full data. A deliberately peeking detector is shown to fail the same check.
- Why: CLAUDE.md rule 3. Forecast origins and scale refreshes are fixed points on the timeline, not "the end of the data", and this test enforces it.
- Limitation: probes are a sample (7 per detector), not every hour.

## 6. Finding the culprit without an LLM (the control)

**M29. The control investigates each incident with only the data visible at its first alarm, over the alarm's own window.**
- What: for an incident whose first alarm fires at hour h, the control works on `world.until(h + 1)`. Its window starts where that alarm's run of exceedances began (h - persistence + 1), widened to at least 3 hours. It investigates every incident of the configured detector (A2 by default).
- Why: an analyst paged at hour h cannot see hour h + 1 (CLAUDE.md rule 3). A test wrecks all data after the alarm and checks the attribution does not change. The first version used the last 6 hours, which, with an alarm 2 hours into a fault, was mostly normal hours and diluted the drop.
- Considered: waiting a few hours after the alarm for more evidence. Deferred: it trades attribution accuracy for time to answer, which should be a measured choice.
- Limitation: a mild, slow fault seen through a 3-hour window gives weak evidence (the held-out type especially).

**M30. Contribution: missing approvals against a level-adjusted seasonal baseline.**
- What: each leaf's expected approval rate is the pooled same-hour rate of the previous 4 weeks, shifted by the leaf's recent level (its approvals minus pooled-expected approvals per attempt over the 24 hours that end 6 hours before the window). Missing approvals = attempts x expected rate - approvals, summed over a segment; z = missing / sqrt(sum of attempts x p x (1 - p)).
- Why: using actual attempts means a volume surge alone creates no missing approvals (tested). The level shift was added after a test showed day-to-day drift giving a big, normal segment a z of about 9, larger than a real injected drop on a small issuer. The 6-hour gap keeps a fault that started just before the window out of its own baseline.
- Considered: the detector's own forecast as the baseline. Rejected for the control: the control should not depend on which detector raised the alarm.
- Limitation: a fault that started more than 6 hours before the window's start is partly absorbed into the level.

**M31. Drill-down by scanning the whole hierarchy, with a stopping rule and a generalization step.**
- What: every segment of the form (none, country, issuer or BIN) x (method or not) x (gateway or not) is scored: z_now / phi, where phi is one overdispersion factor for the window (the median over segments of 1.4826 x median |z| on the same hours of the previous 7 days, at least 1). The best-scoring segment is kept if its score is at least 3 (the stopping rule; otherwise "no localized drop"). Then, while a parent of it (drop one cross dimension, or go one level up the geography) has a "rest" (parent minus segment) whose relative drop is at least half the segment's, move to that parent. Top-3 = the three best scores.
- Why: for a fault on segment T, raw z peaks at T in expectation (parents dilute, children lose affected payments); this is the idea behind expectation-based scan statistics (Neill and Moore's work on spatial scan statistics; not re-read for this project, so cited from memory only). The generalization step settles near-ties between T and its biggest child: a whole-issuer fault hits all its BINs, a one-BIN fault does not. The half-way threshold is the midpoint between "rest untouched" and "rest equally hit".
- History (all before any grading code existed, in tests on development worlds): (1) a greedy top-down walk choosing the child with the largest excess share picked the wrong child when the true child held most of its parent's volume; (2) a complement rule kept it from that, but the walk stopped at the total whenever an unrelated sibling's drift cancelled the faulty segment's shortfall in the parent (an issuer with z of 6 under a country with z of -2.9); (3) a per-segment phi from 7 past windows was too noisy (1.35 to 3.04 in one world) and reordered candidates; (4) requiring the rest to have z of at least 2 blocked generalization when the rest was small.
- Considered: an LLM (that is the agent, H2); a full likelihood model of every segment combination (more machinery than needed for v0.1).
- Limitation: when the true segment and its largest child are nearly the same size, the data cannot tell them apart in a short window; the control will sometimes name the child. Tests require at least 75% of strong, isolated faults right, not all.

**M32. Fault typing: dominant new decline reason, then latency.**
- What: on the culprit segment, the rise in each decline reason's rate per attempt (window against the same hours of the previous 4 weeks) and the latency ratio. Rules, first match: issuer_unavailable rise -> issuer_outage; processing_error rise or latency ratio of at least 1.8 -> gateway_degradation; do_not_honor or suspected_fraud -> bin_decline_spike; authentication_required -> extra_verification; insufficient_funds -> no_fault; a largest rise under 0.2 percentage points -> unknown. No culprit -> no_fault.
- Why: decline reasons are what an analyst reads first. Latency separates gateway trouble. The insufficient_funds rule keeps a promotion from being blamed on the system (tested).
- Considered: dropping the authentication_required rule because extra_verification is held out. Rejected: an analyst would write that rule from the meaning of the reason alone, and removing it would weaken the control to the agent's advantage (CLAUDE.md rule 5). Its 0.2-point threshold is shared with the other rules and was not tuned on any world containing the type.
- Limitation: the mapping matches the simulator's own signature table (M14), so fault typing is easier here than on real data, and on the held-out type it tests the thresholds, not the mapping.

## 7. The agent harness

**M33. Four read-only tools, cut at the investigation time.**
- What: `query_slice` (attempts, approvals, rate, expected rate, missing approvals and z for a segment, optionally split by any dimension it does not fix), `forecast` (hour by hour actual and expected rate with a 90% binomial band), `decline_reasons` (rate per attempt of each reason now, in the same hours of the previous 4 weeks, and the change), `latency` (mean now, before, ratio). Each tool reads a copy of the observed world cut at the hour after the first alarm, over at most 48 hours. Numbers use the same baseline as the control (M30).
- Why: CLAUDE.md agent safety rules. Sharing the control's arithmetic means any accuracy gap between agent and control comes from the search and the reasoning, not from different maths. A test wrecks all later data and checks every tool output is unchanged; the import-graph test covers the agent package.
- Considered: giving the agent the detector's forecasts. Deferred: `forecast` uses the seasonal baseline so it does not depend on which detector alarmed; swapping in the TSFM forecast is one function.
- Limitation: the agent cannot ask for anything the four tools do not compute (for example a breakdown by two dimensions at once in one call).

**M34. Every tool call goes into a ledger with a flat table of the numbers it returned.**
- What: calls are numbered c1, c2, ...; each keeps its arguments, its output and a table such as `rate`, `issuer=C0-I1.missing_approvals`, `issuer_unavailable.change` or `h704.expected_rate`. Values are rounded to 4 decimals before the model sees them.
- Why: citations become exact lookups, which is what lets the critic reject made-up numbers and lets the reporter insert numbers by code (CLAUDE.md rule 7).
- Limitation: the model may cite a real number that does not support its claim; only the planned LLM review would catch that.

**M35. One investigator loop with a hard tool-call budget, a cost cap and a turn limit.**
- What: defaults 12 tool calls, USD 0.50 and 20 turns per incident (`agent` in the config). Cost = input tokens x 4 + output tokens x 20 USD per million for `claude-opus-5-5` (the claude-api skill's model table, cached 2026-11-03; re-check before a paid run). Statuses: submitted, budget_exceeded, cost_cap, no_answer, max_turns. PLAN.md's orchestrator, investigator and hypothesis writer are one loop in v0.1.
- Why: CLAUDE.md rule 6, and cost per incident is one of the two numbers H2 reports.
- Considered: separate orchestrator and writer agents. Deferred until one loop has a measured result; more agents cost more and are harder to compare with the control.
- Limitation: the budget values are guesses until the first live run; they must be fixed before the lock.

**M36. A deterministic critic runs before any report exists.**
- What: claim text may not contain digits (segment ids allowed); numbers appear only as placeholders {0}, {1} matched to citations (call id and field), and every citation must exist in the ledger, with any stated value equal to it. The culprit must exist and have been examined with `query_slice`; fault type and confidence must be allowed values; the start hour must be before the investigation time. Ten rejection cases are tested.
- Why: CLAUDE.md rule 7: the agent can be wrong, but it cannot invent evidence.
- Considered: parsing numbers out of free text and matching them to tool output. Rejected: rounding and formatting make that fuzzy; placeholders make it exact.
- Limitation: the second stage, an LLM review of whether the cited evidence supports the claim (PLAN.md Day 25), is not built.

**M37. The reporter fills a fixed template and inserts every number from the ledger.**
- What: what changed (from the last `query_slice` on the culprit), where, since when, likely cause, confidence, evidence (claim texts with placeholders filled), what to check next. The first lines say "Investigation, not a decision" and that the data is simulated.
- Why: PLAN.md FR15 and CLAUDE.md rules 7 and 8.
- Limitation: formatting rules (rates as percentages, counts as whole numbers) are inferred from field names.

**M38. LLM behind an interface; tests replay cassettes; no live call anywhere in this build.**
- What: `culprit.agent.llm` copies Tells' interface: `AnthropicLLM` (model `claude-opus-5-5`, effort `high` set explicitly because this model's default is medium, strict tool schemas, server-side refusal fallback `fallbacks: "default"` with beta `server-side-fallback-2026-07-01`), and `CassetteLLM` (replay checks a request digest; a digest of "any" marks a hand-written fixture; record mode wraps a real backend). The only cassette, `tests/cassettes/issuer_outage_handwritten.json`, is hand-written and labeled as such: it is not a recording of any model, and its token counts are invented for the cost-cap test.
- Why: tests must be deterministic and free (CLAUDE.md). The API key stays in the environment and never in git.
- Considered: a different provider or a smaller model. Not chosen: the claude-api skill names `claude-opus-5-5` as the default, and Tells uses the same model, so the projects stay comparable.
- Limitation: no recorded real exchange exists yet, so the agent's behaviour on real model output is untested.

## 8. Grading

**M39. Grading reads the key only through the vault, and matching uses `cleanroom.events`.**
- What: an alarm on a series matches a fault when the series' segment shares a leaf with the fault's target and start <= alarm hour <= last fault hour + 6 (`match_alarms` with tolerance 6). Delay = first matching alarm minus start; `caught_within` gives the share caught within 2, 6 and 24 hours; unmatched alarms are false alarms, per week via `false_alarms_per_unit`, and those touching a surge are counted as surge traps. Attribution: each fault's first matching incident is graded on top-1 (culprit equals the target segment exactly), top-3 and fault type; surge-only incidents count as blamed if the investigator names a culprit and a cause other than no_fault. The key is sealed with `cleanroom.vault.seal_answer_key` when a world is written. Development worlds open it after a checksum check against that record, and never for a config with `evaluate.role: test`. Test worlds open it only through `release_answer_key`: valid lock and vault record both committed to git, the sealed run recorded as finished (`cleanroom.guard`), and the key unchanged; each release is logged.
- Why: CLAUDE.md rules 1 and 4. Exact-segment top-1 is strict on purpose: naming the BIN when the issuer failed sends an analyst to the wrong team.
- Considered: partial credit for an ancestor or descendant of the target. Kept out of the headline; top-3 gives some of that.
- Limitation: a 6-hour tolerance after a fault ends credits late alarms that an operations team might call useless; delay is reported next to detection.

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
| L9 | The budget counts series alarms | One surge that fires three related series uses three of the week's two-alarm allowance, so thresholds are strict | Same rule for every detector (M27); incidents reported too |
| L10 | Thresholds rest on about 4 calibration alarms | The achieved false-alarm rate in evaluation can differ from 2 per week | Evaluation false alarms are graded and reported per detector |
| L11 | Detector B's seasonal pattern is frozen at the end of the context | Holidays or rhythm changes in evaluation are only absorbed through the level | Stated (M24) |
| L12 | The TSFM detector is tested only with a fake forecaster | No TSFM detection number exists | Adapter pinned and import-tested; the full run is left for the owner with the `tsfm` extra (M25) |
| L13 | A 2-hour persistence rule cannot catch a 1-hour fault | Some gateway faults are undetectable by design | Stated (M26) |
| L14 | The control's window is short (from the alarm run's start, at least 3 hours) | Mild, slow faults give weak evidence; the held-out type is mild and slow | Stated (M29); a longer wait is a measured option for later |
| L15 | Near-ties between a segment and its biggest child | The control sometimes names the child | Generalization step (M31); top-3 reported; tests require 75%, not 100% |
| L16 | Fault-typing rules mirror the simulator's signature table | Typing accuracy overstates what rules would do on real data | Stated (M32); the held-out type tests thresholds only |
| L17 | The control's design was revised four times on development worlds | It is tuned to this simulator's development worlds to some degree | Every revision happened before any grading code existed and is listed (M31); held-out type and a second regime at test time (rule 9) |
| L18 | No live LLM run and no recorded real cassette | The agent loop is tested only on a hand-written fixture | Stated (M38); recording needs the owner's API key and spend cap |
| L19 | The critic has no LLM review stage | A real but irrelevant number can be cited in support of a wrong claim | Stated (M36); planned for PLAN.md Day 25 |
| L20 | Agent budgets (12 calls, USD 0.50) are unmeasured guesses | Too tight or too loose a budget changes H2 | Fix them from development runs before the lock (M35) |
