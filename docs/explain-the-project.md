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
