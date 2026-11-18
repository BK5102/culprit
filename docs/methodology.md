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

**M3. The shared Cleanroom is installed from the git tag `cleanroom-v0.1`, never copied.**
- What: `pyproject.toml` pulls `cleanroom` from `github.com/BK5102/tells`, tag `cleanroom-v0.1`, subdirectory `packages/cleanroom`. Culprit uses its time split (`cleanroom.split`), sealed-envelope lock (`cleanroom.lock`), provenance stamp and past-only test helper.
- Why: one copy of the honesty machinery for all three projects, so a fix in one place reaches all of them (Tells `docs/decisions.md` D1).
- Considered: a local copy. Rejected: copies drift.
- Limitation: Culprit is pinned to whatever v0.1 contains until it bumps on purpose.

**M4. Event matching and threshold calibration live in Culprit until Cleanroom v0.2 ships.**
- What: matching alarms to fault windows, detection delay, false alarms per week and the threshold for a fixed alarm rate are in `culprit.evaluate.metrics` and `culprit.detect.budget`. The answer key is read by `culprit.evaluate.grade` directly. A TODO in `pyproject.toml` says to bump to `cleanroom-v0.2` and replace these with its event tools and its answer-key vault.
- Why: v0.2 is being built in parallel; waiting would block the simulator and the detectors.
- Considered: pinning to an unreleased commit. Rejected: siblings must only depend on released tags.
- Limitation: until the bump, these pieces are tested here only and are not shared.

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

---

## Limitations register

The honest list. Each item says what could be wrong and what was done about it.

| # | Limitation | Effect | What was done |
|---|---|---|---|
| L1 | Simulated data only | No result shows real-world performance | Stated on the first screen of the README and in every report (CLAUDE.md rule 8) |
| L2 | Event matching and calibration are local until Cleanroom v0.2 | Not shared with the sibling projects yet | TODO in `pyproject.toml`; tested here (M4) |
