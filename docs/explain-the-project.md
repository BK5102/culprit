# Explaining Culprit: the project step by step

This is the guide to read before talking about Culprit with a recruiter, a hiring manager, or an interviewer. It tells the story in the order the work happened. Every step has the same parts:

- **What I did**
- **Why**
- **What else I considered**
- **Cause and effect**: what happened because of this step, including problems it exposed
- **How to say it**: one or two sentences you can say out loud

The technical detail behind each step is in `docs/methodology.md` (numbered M1, M2, ...), and the dated diary is in `docs/decisions.md`. All data is simulated; say so every time.

## Elevator pitch (draft, no results yet)

"When approval rates drop, the cause usually hides in one small segment among thousands. I built a simulated payment world with injected faults whose true causes are sealed away, detectors compared at the same false-alarm rate, and a no-AI drill-down that an LLM agent will have to beat. No result exists yet; the fit checks say the simulated world can answer the question."

---

## Part 1. Setup

### Step 1. Scaffold the repo and reuse the shared Cleanroom

- **What I did:** set up a uv Python project with ruff, pytest and a CI workflow, and installed the Cleanroom (time splits, a sealed-envelope lock, provenance) from a git tag of the Tells repo.
- **Why:** the Cleanroom is what makes cheating mechanically hard, and all three projects must sit the same exam.
- **What else I considered:** copying the Cleanroom code in. Rejected because copies drift.
- **Cause and effect:** the Cleanroom v0.1 has no tools for matching alarms to fault windows yet, so Culprit carries its own small versions with a TODO to switch to v0.2 (M4).
- **How to say it:** "Every project imports the same versioned testing toolkit, so a fix to the exam rules reaches all of them."

## Part 2. The simulated world

### Step 2. Build a payment world where the true cause of every fault is known but sealed

- **What I did:** wrote a simulator that produces hourly attempts, approvals, decline reasons and latency for about 100 (small) or 1,440 (full) leaf segments, adds promotions and paydays that look like problems but are not, and injects four fault types (issuer outage, BIN-range decline spike, gateway slowdown, extra verification) only in the last weeks. The true causes go to `sealed/answer_key.json`; the counts go to `observed/`.
- **Why:** real payment data is private and real incidents rarely come with a verified cause. A simulator is the only way to score "did you name the right segment?".
- **What else I considered:** real public data with an error column (TabFormer), kept as an optional second world if it passes its own fit check.
- **Cause and effect:** because the simulator knows the truth, the main risk becomes the truth leaking into the methods. Tests now prove that detector, control and agent code cannot import the code that writes or reads the key, and that the observed files never mention a fault. The extra-verification type is held out of all development worlds.
- **How to say it:** "I built a fire drill for payments: only the simulator knows where the fault is, and a test proves the detectives can't open the envelope."

### Step 3. Check that the simulated world can answer the question

- **What I did:** wrote `scripts/check_data_fit.py`, which measures signal versus noise for each fault, how many faults hide in the overall rate, whether promotions fool a naive detector, how much room a forecaster has over seasonal naive, and whether "largest drop" already names the culprit. Ran it on five small development worlds and one full one.
- **Why:** if faults are obvious, every detector ties; if the biggest drop is always the culprit, no agent is needed. Measuring first avoids building on a world that cannot answer anything.
- **What else I considered:** just building the detectors and seeing. That is how Tells nearly lost time on a dataset with no room for a model to win.
- **Cause and effect:** run 1 failed in an instructive way: 88.9% of faults were over 10 times the noise. I lowered the fault sizes before any detector existed. Run 2 passes every gate: about a third of faults are hard, about half hide in the total but show at their own segment, the largest drop is the culprit 0.0% of the time, and promotions fire a naive detector 44.4% of the time against 0.4% for quiet windows. It also showed headroom over a simple 4-week average is small at single leaves (oracle error 0.87 of it), so a TSFM can only win on aggregates.
- **How to say it:** "Before building any detector I measured whether the fake world was even a fair test, found it was too easy, fixed the difficulty, and kept the failed check in the docs."
