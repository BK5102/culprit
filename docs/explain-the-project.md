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
- **Cause and effect:** Cleanroom v0.1 had no tools for matching alarms to fault windows, so the scaffold carried a TODO to bump. v0.2 (alarm matching, thresholds for a fixed alarm rate, an answer-key vault and sealed runs) was released the same day, and Culprit moved to it before writing any detector, so nothing was duplicated (M4).
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

## Part 3. Knowing normal

### Step 4. Build four detectors and give them the same false-alarm budget

- **What I did:** wrote Detector A (same hour last week, with a robust spread), A2 (a binomial z-score that knows a rate from 20 payments is noisier than one from 20,000), B (MSTL, a classical split into daily and weekly rhythm, with intervals) and the TSFM detector (Chronos-Bolt-tiny forecasts the rate; a fake forecaster stands in for tests). Every detector watches the same 123 (small) or 1,554 (full) series and uses the same alarm rule: above threshold for 2 hours in a row. Each threshold is set on a fault-free calibration window so it raises at most 2 alarms per week.
- **Why:** without an equal budget, the most trigger-happy detector would look best. The calibration window has promotions but no faults, so every alarm there is a false alarm.
- **What else I considered:** a CUSUM for A2, which adds up evidence over hours. On a development world a long promotion piled up a huge CUSUM score in the calibration week and pushed the threshold above what a 6-hour outage reached, so the per-hour z-score is the default and the CUSUM stays as an option.
- **Cause and effect:** the full world exposed a bug in Detector A: tiny segments whose rate is always 0 or 1 had zero spread and absurd scores, so A raised no alarm at all at the budget. A standard-deviation fallback fixed it before any grading existed. A past-only test on every detector proves no score uses later hours, and a deliberately cheating detector fails it.
- **How to say it:** "I tuned every detector to the same two false alarms a week on a quiet calibration period, so the comparison is about who notices real faults first, not who alarms most."

## Part 4. Finding the culprit without an LLM

### Step 5. Build the no-LLM control the agent must beat

- **What I did:** wrote a deterministic investigator. For each incident it uses only data up to the alarm, measures every segment's shortfall of approvals against a seasonal baseline adjusted for recent drift, picks the most significant segment, widens it to a parent when the rest of the parent is hit too, and names the cause from decline reasons and latency.
- **Why:** research on agentic forecasters found that removing the LLM often kept performance (PLAN.md Part 8, Nexus). The agent only earns its cost if it beats a strong script, so the script has to be as good as I can make it.
- **What else I considered:** a greedy walk from the total down to the culprit. It failed in tests in two ways: it picked the wrong child when the right one held most of its parent's volume, and it stopped at the top whenever another segment's normal drift cancelled the drop in a parent. The scan fixed both.
- **Cause and effect:** the tests also showed the honest limits: when a segment and its biggest child are nearly the same size, a few hours of data cannot tell them apart, so the control is required to get most strong faults right, not all. A promotion is typed as "no fault" because its extra declines are "insufficient funds".
- **How to say it:** "My no-AI baseline scans every segment at once and names the one where the shortfall is most concentrated; it took four designs, and I wrote down why each one failed."

### Step 6. Grade only through a sealed envelope

- **What I did:** `evaluate/grade.py` is the only code that reads the answer key. It matches alarms to faults with the Cleanroom's event tools (a fault counts as caught if an alarm on an overlapping segment fires between its start and 6 hours after its end), measures delay and false alarms per week, and grades the investigator on top-1, top-3 and fault type. Test worlds open only through the Cleanroom vault after a finished sealed run.
- **Why:** the result is only believable if nothing could peek, and if the peeking rules are the same across all three projects.
- **What else I considered:** partial credit for naming a parent or child of the true segment. Kept out of the headline because it sends the analyst to the wrong team; top-3 covers near misses.
- **Cause and effect:** a test proves the key will not open for a test world until a sealed run has finished and the lock and vault record are committed.
- **How to say it:** "The answer key sits in a vault that only opens after the run has written its answers, and every opening is logged."

## Part 5. The agent

### Step 7. Build the agent's harness before the agent ever runs

- **What I did:** gave the LLM investigator four read-only tools (query a segment, see its hourly forecast, its decline reasons, its latency), all cut at the alarm time, a hard budget of tool calls and dollars per incident, a critic that rejects any claim whose numbers are not in tool output, and a reporter that inserts every number by code.
- **Why:** the risk with an agent is that it invents a cause and dresses it in plausible numbers. Making typed numbers impossible and citations exact removes the second half of that risk; the comparison with the control handles the first.
- **What else I considered:** letting the model write numbers and checking them afterwards. Rejected: matching "about 61%" to 0.6123 is fuzzy, while a placeholder that points at tool call c2, field `rate`, is exact.
- **Cause and effect:** the agent uses the same arithmetic as the control, so if it wins or loses, it is because of where it looked and how it reasoned. No live model call has been made yet: the only test conversation is a hand-written fixture, clearly labeled. The real run needs an API key and a spend cap from the owner.
- **How to say it:** "The agent can't type a number. It cites tool call c2, field rate, and code fills the number in, so every figure in a report is traceable."

## Part 6. Running it

### Step 8. One command per step, with provenance on every file

- **What I did:** wrote the CLI. `simulate` builds the world, `detect` runs the detectors at the shared budget, `attribute` runs the control on the incidents, `evaluate` grades a development world. For test worlds, `seal`, `run --sealed` and `evaluate --run-id` go through the Cleanroom's lock, guard and vault. Also made every window bound come from the Cleanroom split, with a test that checks it on the real rows.
- **Why:** the plan asks for one-command reproduction on a small world, and every number needs to trace back to a config, a commit and a dataset.
- **What else I considered:** one big "do everything" command. Kept separate so a failure shows which step broke and so the sealed path cannot be confused with development.
- **Cause and effect:** the first development run (small config, seed 7, development only, not a result) showed how strict the budget is. At 2 false alarms per week counted over all 123 series, Detector A and A2 caught 1 of 14 faults and B 3 of 14, and the control investigated A2's incidents and covered 1 fault. Promotions in the calibration weeks fire several related series at once and use up the allowance, so thresholds sit high. Whether to count the budget per incident instead of per series is an open decision for the owner, to settle before the lock.
- **How to say it:** "Four commands rebuild the whole small experiment in under a minute, and the first run already told me my false-alarm budget was probably too strict."

### Step 9. Make the false-alarm budget's counting unit a switch

- **What I did:** made the budget count either every series alarm (`budget.mode: per_series`, the default so far) or every incident, where alarms within 6 hours of each other are one page to the analyst (`per_incident`). Both keep 2 per week. Grading now reports false alarms and false incidents per week, and `scripts/compare_budget_modes.py` runs both on a development world.
- **Why:** Step 8 showed that one promotion firing a country, its method and a few leaves used up the whole weekly allowance under per-series counting, so the detectors were nearly blind. An analyst pays per page, not per series.
- **What else I considered:** just raising the number to 5 per week. That still counts one promotion several times.
- **Cause and effect:** on the small development world (seed 7, development only, not a result), per-incident counting moved faults caught from 1, 1 and 3 of 14 to 1, 10 and 4 of 14 for A, A2 and B, and let the control investigate 10 faults instead of 1. The price is visible too: A2 raised 15 series alarms per week in evaluation (2.5 false incidents per week). The owner picks the unit before the lock; the per-incident option is the recommended one in the handoff.
- **How to say it:** "I budget false alarms the way an on-call analyst feels them, as pages, and I report both units so nobody can hide a noisy detector behind the grouping."

### Step 10. Give the agent one command, cassettes per incident, and caps it cannot pass

- **What I did:** built `culprit agent CONFIG --incident N` and `--all`. The agent investigates the same incidents as the control. Each incident's conversation with the model is a cassette (a saved recording of every request and reply; like a flight recorder you can replay). Replay is the default, free and needs no key. `--record` calls Claude only for incidents without a cassette and saves new ones. Two caps from the config, one per incident and one for all runs together, are checked before every call against that call's worst possible cost, and every billed reply goes into an append-only spend log.
- **Why:** H2 compares agent and control on the same incidents and reports cost per incident, and the rules ask for a hard cost cap. Checking after a reply can overshoot by one reply; checking the worst case first cannot, as long as the estimate is an upper bound.
- **What else I considered:** one cassette per world, and keeping the running total in memory. Both lose information when a run stops halfway.
- **Cause and effect:** an incident the agent never ran, or whose answer the critic rejected, counts as a miss, so a budget that runs out can only hurt the agent. No live call has been made: all tests use the hand-written cassette or a fake backend that serves it. The conservative reservation means the owner has to set `max_tokens` and the per-incident cap together.
- **How to say it:** "Every model call is recorded and replayable, and the spend cap is checked against the worst case before each call, so the bill cannot pass the number I set."
