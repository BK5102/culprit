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

## Part 7. Getting ready for the sealed test

### Step 11. Write the test plan as a draft that refuses to be sealed half-finished

- **What I did:** wrote `configs/test.yaml`, one plan for every sealed world: the full-size world with all four fault types (the held-out extra-verification type appears only here), detectors A, A2, B and the TSFM, and a list of seeds crossed with two simulator regimes. Four values are left as marked placeholders for the owner: the budget counting unit, the agent's total spend cap, the seeds and the second regime. `culprit validate` lists what is missing; `culprit seal` refuses until nothing is. The lock now also covers a hash of the agent's prompt, and the sealed run runs the detectors, the control and the agent on every world in one go. Afterwards `culprit evaluate --run-id` writes pooled numbers with intervals that resample whole worlds.
- **Why:** the honesty of the test rests on the plan being fixed before any test number exists. A plan with a forgotten choice should be an error, not a silent default, and a prompt changed after sealing should need a new lock.
- **What else I considered:** one config file per test world. Ten files can drift apart and need ten locks; one plan is one commitment.
- **Cause and effect:** the detectors, the control and the agent now refuse to run on test worlds outside the sealed run, so nobody can peek at test alarms early. A test runs the entire sealed path (seal, commit, sealed run with the agent on a fake backend, grading) on four tiny worlds.
- **How to say it:** "My test plan is one file that the code refuses to seal while any choice is still open, and once sealed, even editing the agent's prompt needs a new lock."

### Step 12. Run the real TSFM once on the full development world

- **What I did:** ran all four detectors, the control and grading on the full development world (1,440 leaf segments, 1,554 monitored series, seed 17) with the real Chronos-Bolt-tiny weights on a laptop CPU, from a clean checkout so the provenance names an exact commit.
- **Why:** the TSFM detector had only been tested with a fake stand-in. Before sealing anything I needed to know it runs on a CPU in reasonable time and behaves like the others at the budget.
- **What else I considered:** waiting for the sealed run. A crash or a ten-hour runtime discovered there would cost a counted attempt.
- **Cause and effect:** the TSFM took 542.9 s (about 9 minutes) for 1,554 series at 42 daily forecast origins, so one full world takes about 15 minutes for every step together and ten test worlds about 2.5 hours, inside the plan's CPU budget. On this one development world (development only, not a result), at 2 false alarms per week counted per series, the TSFM caught 8 of 27 faults within 6 hours, against 19 for the binomial A2, 9 for A and 9 for B. The control named no culprit right on this world (top-1 0 of 20 faults), a negative result I kept; Step 13 explains it.
- **How to say it:** "The foundation model runs a full world on a laptop CPU in about nine minutes; on my one development world it did not beat a simple binomial z-score, and the sealed test is where that question actually gets answered."

### Step 13. Find out why the control failed on the full world, and fix it

- **What I did:** built an oracle-alert diagnostic (`scripts/diagnose_control.py`, development only). It pages the control at each fault's true start, as if a perfect detector had fired as early as the alarm rule allows, so a miss there can only be an attribution miss. On the full development world the control still got 0 of 27 right with perfect pages, and 24 of its 27 named culprits had fewer than 10 payments in the window. The cause was thin leaves: a leaf that approved all 4 of its past payments at that hour got an expected approval rate of 0.999999, so its noise estimate was almost zero and a single decline looked like a 1,000-sigma drop. I fixed it in two steps, both written into the methodology with a decision rule before I measured them. First, a bug fix: no rate estimated from n past payments may sit closer to 0 or 1 than the Jeffreys estimate for n out of n (a standard small-sample correction; like not calling a new restaurant perfect after four good reviews). Second, a design change: rank segments by the exact binomial chance of seeing that many declines, not by the normal approximation, which flatters tiny segments.
- **Why:** H2 asks whether the agent beats the control. A control that never finds the culprit would make any agent look good, and the rules forbid a weak control.
- **What else I considered:** dropping leaf segments from the search (no development fault targets a single leaf, so that would tune the control to my simulator's fault list); a minimum number of payments per candidate (a threshold with no natural value).
- **Cause and effect:** on the full development world (seed 17, development only, not a result) the control went from top-1 0.0 to 0.5 and top-3 0.0 to 0.6 on A2's incidents, and from 0.0 to 0.444 with perfect pages. It stopped blaming promotions on a fault (0 of 2, was 2 of 2). On the small world the perfect-page top-1 went from 0.071 to 0.286. Writing the rule first mattered: the first measurement of the second step had a numerical underflow that an existing test caught, and both runs are recorded. What is left is a real limit, not a bug: with one culprit per 3-hour window, a mild fault loses to a stronger overlapping fault or a promotion.
- **How to say it:** "My no-AI baseline scored zero on the big world, so I separated detection from attribution with perfect pages, found that a single declined payment on a tiny segment looked like a 1,000-sigma event, fixed the statistics, and the baseline went from 0% to 50% top-1, which makes it a real bar for the agent to beat."

### Step 14. Make the test plan's choices, and fix a gate that failed on arithmetic

- **What I did:** set the four open choices in the test plan:
  - Count false alarms per incident.
  - Cap each incident at 1 dollar with 4,000 output tokens.
  - Draw five fresh seeds at random, once.
  - Add a noisier, shiftier second world.

  Then I checked the second world on development seeds. One gate came out "nan" in both worlds, and I traced it to a few tiny segments where the baseline's error was exactly zero.
- **Why:** these choices must be fixed before sealing, and making them before any test world exists means they cannot be bent toward a result. The gate problem was a division by zero, not a property of the world, so the fix was to skip those segments and report how many were skipped.
- **What else I considered:**
  - Counting per series, which let surges use up the budget.
  - A bigger token limit, which multiplied the worst-case cost of each call.
  - Hand-picked seeds.
  - For the gate, filling the undefined values with 1 or loosening the threshold. Both would have changed the rule after seeing it fail.
- **Cause and effect:** every data-fit gate now passes for both test regimes on development seeds, and the development numbers did not change. One item stays open on purpose: the total spend cap for the sealed run, which the development recordings will size.
- **How to say it:** "I fixed every test-plan choice before any test world existed, drew the seeds at random, and when a check failed I found it was a division by zero, fixed the arithmetic, and showed the earlier numbers did not move."

### Step 15. The first live agent runs

- **What I did:** ran the LLM agent against Claude for the first time, on the small development world's 10 incidents.
- **Why:** until now the agent had only replayed hand-written conversations. Only real calls show whether the tool definitions, the citations and the rules work together.
- **What else I considered:**
  - Loosening the critic, which would change the rule after seeing failures.
  - Turning off strict tool checking, which would let malformed arguments reach the tools.
- **Cause and effect:**
  - **Tool format:** the API refused the first two requests for schema reasons. Both were free, and both are fixed by sending each segment as one key.
  - **Citations:** the critic then rejected answers whose citations used the output's own positions, so it now accepts those.
  - **Typed numbers:** the agent kept typing hours and window lengths into its sentences. A clearer instruction took critic acceptance from 1 of 10 to 9 of 10.
  - **Accuracy:** on this one world the agent named the right culprit for 3 of 10 faults against 2 of 10 for the no-LLM control. That is a development number, not a result.
  - **Cost:** about 16 cents per incident, and 3.27 dollars of live calls in total so far.
- **How to say it:** "The first live run found three integration bugs that replayed tests could not, and I fixed the agent's instructions rather than weakening the checker, counting both prompt versions."
