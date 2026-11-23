# Decisions

One entry per decision or feature: what was decided, why, and an analogy. These are the owner's talking points. Newest at the bottom. The full reasoning for each choice is in `docs/methodology.md`.

## Build 1 (2026-11-17)

### D1. Scaffold: uv, ruff, pytest, CI, and the Cleanroom from its git tag

The repo is a uv project that installs the shared Cleanroom from the `cleanroom-v0.1` tag of the Tells repo instead of copying it, with ruff and pytest run in CI on Python 3.11 and 3.12. Copying the honesty toolkit would let the three projects drift apart, so a leak fix in one would not reach the others. Analogy: three schools using the same sealed exam board instead of each photocopying and editing its own rulebook.

### D2. The simulator: a payment world with a sealed answer key

The simulator builds an hourly world of leaf segments (BIN range x method x gateway, nested under issuers and countries) with daily and weekly rhythm, binomial approvals, decline reasons and latency, then adds legitimate surges and four kinds of faults, and writes the true causes to a separate sealed file. Real approval data with known causes does not exist publicly, and only a simulator lets attribution be scored, so the honesty work goes into keeping the answer key out of reach: an import-graph test proves no detector, control or agent module can reach the code that writes or reads it. Analogy: a fire drill where only the organizer knows where the fire is, and the firefighters are checked at the door for copies of the plan.

### D3. Measure the simulated world before building on it

`scripts/check_data_fit.py` checks that faults are neither obvious nor invisible at their own segment, that many hide in the overall rate, that promotions fool a naive detector, that a forecaster has room to beat seasonal naive, and that "pick the biggest drop" does not already find the culprit. The first run showed faults were far too easy (88.9% of them over 10 times the noise), so the fault sizes were lowered before any detector existed, and the first run is kept in `docs/data-fit.md` as a negative result. Analogy: before timing runners, check that the track is not downhill.

### D4. Detectors compared at the same false-alarm budget

Four detectors score every monitored series: A (same hour last week, with a robust spread), A2 (a binomial z-score that knows small segments are noisier), B (MSTL seasonal pattern with intervals) and C (Chronos-Bolt-tiny forecasting the rate, tested so far with a fake stand-in). Each gets its threshold on a fault-free calibration window so that all of them raise at most 2 alarms per week across all series, using the Cleanroom's alarm rule and calibration, and a test proves every score uses only the past. Analogy: four smoke detectors tuned so each beeps falsely twice a week, then judged on how fast they notice a real fire.

### D5. The no-LLM control: scan every segment, then type the cause from decline reasons

For each incident, the control looks only at data up to the first alarm, scores every segment (country, issuer, BIN, and their combinations with method and gateway) by how far its approvals fell short of a drift-adjusted seasonal baseline, picks the most significant, widens it to a parent when the rest of that parent is hit too, and names the cause from the decline reason that rose most and from latency. It went through four designs on development worlds before any grading code existed; each failure is written down in methodology M31. Analogy: instead of walking from the city to the street one turn at a time, the detective checks every street at once and names the one where the trouble is most concentrated.

### D6. Grading through the Cleanroom vault

Only `evaluate/grade.py` reads the answer key, and only after checking it against the vault record made when the world was built; a sealed test world opens only through the Cleanroom vault after a finished, committed sealed run, and every opening is logged. Matching alarms to faults and counting false alarms per week use the Cleanroom's event tools, so all three projects grade alarms the same way. Analogy: the exam board keeps the marking scheme in a sealed envelope, and the envelope logs who opened it and when.

### D7. The agent's harness: four read-only tools, a ledger, a critic, a reporter

The agent can only call four read-only tools that see nothing after the alarm, every call is numbered and its numbers kept in a ledger, the agent writes claims with placeholders and cites ledger entries, a deterministic critic rejects any claim with a typed or unknown number, and the reporter fills the numbers in by code. The LLM sits behind an interface, and the only test conversation is a hand-written cassette, so no test costs money or depends on a live model. Analogy: an intern who may only read the dashboards, must footnote every figure, and whose footnotes are checked before the memo goes out.

### D8. One command per step, and a separate sealed path for test worlds

`culprit simulate`, `detect`, `attribute` and `evaluate` run the small development world end to end on a laptop CPU in well under a minute, and every output file records the config hash, git commit and dataset hash. Test worlds take a different path: seal the config and the answer key, commit them, run detection and the control as one sealed run, and only then grade. Analogy: practice exams can be marked as often as you like; the real exam is sat once, in a sealed room, and the envelope is opened afterwards.

## Build 2 (2026-11-18)

### D9. The false-alarm budget can count incidents instead of series alarms

`budget.mode` now chooses whether the 2-per-week allowance counts every series alarm or every incident (alarms within 6 hours grouped as one page), with the per-incident threshold found by the same rule as the Cleanroom's and checked to reproduce it exactly when nothing is grouped. On the small development world, counting incidents let A2 catch 10 of 14 faults instead of 1 (development only), at the cost of many more series alarms, so both units are graded. Analogy: a smoke alarm budget that counts fires the fire brigade is called to, not every detector that beeped during the same fire.

### D10. `culprit agent`: replay by default, record on purpose, never past the cap

The LLM investigator now runs from the command line on the control's incidents, one cassette per incident, replaying recordings unless `--record` is given with an API key and a total cap in the config. Before every live call the worst case of that call is checked against both the incident's cap and the total in an append-only spend log, and incidents the agent skips or gets rejected count as misses. Analogy: a taxi meter that refuses the next mile if the fare could pass what you said you would pay, with a receipt book you cannot tear pages out of.

### D11. A test plan that cannot be sealed with open choices

`configs/test.yaml` describes every sealed world through seeds and simulator regimes, and its owner choices were marked placeholders (decided 2026-11-21, D13) that `culprit validate` lists and `culprit seal` refuses. The lock covers the plan and the agent's prompt hash, the sealed run includes the agent, and pooled results resample whole worlds for their intervals. Analogy: an exam paper the printer will not print while any question still says "to be written".

### D12. The control's thin-segment defect (L27), found with oracle alerts and fixed

Paging the control at each fault's true start showed its zero score on the full development world was an attribution failure: thin leaves with a spotless past had a baseline rate of 0.999999, so one decline scored as a 1,000-sigma drop. Baseline rates are now held off 0 and 1 by the Jeffreys bound, and segments are ranked by the exact binomial tail of their declines, a choice made by a rule committed before measuring; on that world top-1 went from 0.0 to 0.5 (development only). Analogy: a smoke detector that screamed at a single match in an empty closet, now told how big the closet is.

## Owner decisions for the sealed test (2026-11-21)

### D13. The four test-plan choices

The test plan now counts false alarms per incident, caps each incident at 1 dollar with 4,000 output tokens, uses five seeds drawn at random once, and adds a noisier, shiftier second world. Each choice won over the alternative for a stated reason:
- **Per incident rather than per series:** surges no longer eat the budget (1 of 14 faults caught against 10 of 14 on development), and a real team is paged once per incident.
- **4,000 tokens with 1 dollar:** the old 16,000-token setting reserved 0.32 dollars per call, so the old 0.50 cap allowed one call.
- **Random seeds:** nobody can pick convenient worlds.
- **The second regime:** it changes several settings at once without new simulator code.

The total test cap waits for the development recordings, so it is sized from a measured cost, not a guess (methodology M49). Analogy: fixing the exam's marking rules, time limit and question draw before anyone sits it.

### D14. A data-fit gate that failed on arithmetic, not on the world

The headroom gate reported "nan" on the test plan's worlds because a few tiny leaves had exactly last week's approval rate, so the baseline's error was zero and the ratio undefined. The median now skips those leaves and prints how many it skipped (at most 21 of 1,440). With that, every gate passes, and the development numbers are unchanged (methodology M50). Analogy: a class average that came out blank because one student's score was a division by zero. You report the average of the rest and say who was left out, rather than declaring the class failed.

### D15. What the first live agent calls taught us

The first real calls to Claude found three things the replayed test conversations could not:
- **Tool format:** the API refused our tool definitions twice. Once for how "a dimension or nothing" was written, and once for having too many optional fields. Segments are now sent as one key such as `issuer=C0-I1|method=card`.
- **Citation names:** the critic rejected sound citations because the agent pointed at numbers by their place in the output (`children[0].z`), not by internal names. It now accepts both.
- **Typed numbers:** the agent kept typing hours and window lengths into its sentences, which the critic forbids. Stating that rule plainly raised critic acceptance from 1 of 10 to 9 of 10 on the development world.

We fixed the agent's instructions rather than loosening the critic, because a hand-typed number is exactly what the critic exists to stop. Both prompt versions are counted and named (methodology M51, L29). Analogy: a new hire whose reports kept bouncing because nobody had told them the house style; you write the style guide down, you don't stop checking reports.

### D16. The sealed test runs without the LLM agent (2026-11-22)

Running the agent on all 10 sealed test worlds would have cost about 33 dollars of live calls, so the sealed test leaves it out. The sealed test still covers two questions:
- **H1:** every detector.
- **H2a:** how often the no-LLM pipeline names the culprit on worlds it has never seen.

Whether the agent beats that pipeline (H2b) is answered only on development data, which is too small to settle it, and the write-up says so. Deciding this before the lock means no agent result can be picked after seeing it (methodology M52, L30). Analogy: a trial whose budget covers testing the standard treatment properly but not the new drug, so it publishes a solid benchmark for the standard and labels the new drug's numbers as a small pilot.

### D17. The sealed result (2026-11-23)

The sealed test ran once on 10 simulated worlds (run `test-1`). The foundation model beat two simple detectors, but the simplest statistical one, a binomial z-score that knows how noisy a small segment's approval rate should be, beat it, including on the held-out fault type. The no-LLM investigator named the right culprit for 57% of the faults it saw on unseen worlds, but only 27% of the held-out type. Both negative results lead the write-up in `docs/findings.md`. Analogy: the expensive new smoke detector beat the old ones but not the cheap one wired to know how much smoke a kitchen normally makes.
