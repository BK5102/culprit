# PROMPT.md: Culprit

Prompts to paste into Claude Code. Put `CLAUDE.md`, `PROMPT.md`, and `PLAN.md` at the repo root first. Build the Cleanroom in Tells before starting.

---

## 1. Kickoff prompt (paste once, on day 1)

```
You are my pair-programmer and teacher. I am a data science and economics student who is new to payments and time series foundation models (TSFMs).

Read CLAUDE.md and PLAN.md in full before doing anything. Then:

1. Summarize the project back to me in 5 sentences of plain English with one real-world analogy (for example a traffic control room), so I can check we agree.
2. Install the shared `cleanroom` package from the Tells repo tag (`uv add "cleanroom @ git+https://github.com/BK5102/tells@cleanroom-v0.1#subdirectory=packages/cleanroom"`) and check it imports. If the tag does not exist or the import fails, stop and tell me exactly what is missing. Never copy Cleanroom code into this repo.
3. Do ONLY Day 1 of PLAN.md Part 6: repo scaffold with uv, ruff, pytest, CI, the cleanroom dependency, and a README skeleton that embeds Diagram 1 from PLAN.md. Do not start Day 2.
4. Create docs/decisions.md and docs/tsfm-notes.md as empty templates.
5. Run tests and lint. Show me the output.
6. End with: what you built (3 sentences, plain English, one analogy), what you did not verify, and the exact first command I should run.

Rules: follow every rule in CLAUDE.md. Do not invent datasets, results, or citations. If you are unsure about something, ask me one specific question. No em-dashes, no emojis.
```

## 2. Daily prompt (paste every day, change the number)

```
Today is Day N of the Culprit 30-day plan.

1. Read CLAUDE.md and the Day N row in PLAN.md Part 6. Read docs/decisions.md for yesterday's notes.
2. Restate today's task in two sentences and list the files you will touch. Wait for my "go" if the task changes the Cleanroom, the sealed fault log, or the agent's permissions; otherwise proceed.
3. Write the test first (a reconciliation, leak, or sealed-log test if it touches the simulator, splits, or evaluation). Then the code.
4. Run pytest and ruff. Fix failures.
5. Append a 3-sentence note to docs/decisions.md: what I built, why it matters, and a real-world analogy.
6. Propose a commit message in the form "type: short summary".
7. Finish with: what changed, what you did NOT verify, and one question that tests whether I understood today's feature.
```

## 3. Sealed-log audit prompt (run at Days 8, 22, 26)

```
Act as a skeptic whose only job is to find any way the agent or the detectors could learn the true fault causes before being graded. Read src/culprit.

Check, with evidence from the code and by running small examples:
- Is there any code path from the agent tools to the fault log, including through files, environment variables, shared state, or logs?
- Do detectors or the investigation pipeline read anything from the evaluation period before the lock exists?
- Does the context period contain only normal behavior?
- Do thresholds get calibrated on the same data they are scored on?
- Is evaluate/grade.py the only module that reads the log?

Report each check as PASS or FAIL with file and line references. Do not fix anything yet. List fixes in priority order.
```

## 4. Fair-fight prompt (run at Days 14, 22, 27)

```
Check that the comparison between detectors, and between the agent and the deterministic control, is fair.

1. Do all detectors run at the same false-alarm budget? Show the actual false alarms per week for each.
2. Did the deterministic control get the same tuning effort as the agent? List what was tuned for each.
3. Are both evaluated on the same incidents, the same seeds, and the held-out fault type?
4. Are cost and latency per incident reported for the agent?
5. List three ways the simulator could be making the agent look better or worse than it would in reality.

Output a short table, then a plain-English paragraph. Do not fix anything yet.
```

## 5. Explain-it-to-me prompt (run after each week)

```
Quiz me. Ask me, one at a time, five questions about what we built this week, starting with the simplest. After each answer, tell me what I got right, what I got wrong, and give a better 2-sentence version using a real-world analogy. Finish by writing a 60-second spoken explanation of the project as it stands today, using only things that actually exist in the repo.
```

## 6. Recruiter rehearsal prompt (run on Days 20, 28, 30)

```
Play a recruiter at a fintech company, then a hiring manager on a payments operations team, then an ML interviewer. Ask me the questions they would really ask about Culprit, one at a time. After each answer, score it from 1 to 5 for clarity and honesty, point out any claim I cannot back with something in the repo, and suggest a tighter version. Use the "Questions you will probably get" and "What not to say" sections of PLAN.md Part 4 as the base, but add new questions, including one about why I used a simulator and one about whether the agent is worth its cost.
```

## 7. Incident walk-through prompt (Day 29)

```
Pick one simulated incident where the agent was right and one where it was wrong. For each, produce a step-by-step walk-through in plain English: what the alert said, which slices the agent looked at, what evidence it cited, what the critic accepted or rejected, what the report concluded, and what the sealed log says the truth was. Use only data from the saved run artifacts. Format it so I can show it in the README as a demo.
```

## 8. Findings write-up prompt (Day 28)

```
Read artifacts/results (all runs). Write docs/findings.md with these sections: question, setup, headline table, what worked, what did not work, what could not be tested, and next steps. Every number must be copied from a results file and tagged with its config hash. State at the top that all data is simulated. Include negative results and any case where the deterministic control beat the agent. Do not use causal language the experiments cannot support. No em-dashes.
```

## 9. When something breaks

```
Do not guess. Reproduce the failure, show me the smallest failing case, explain the cause in plain English, propose the minimal fix, and add a regression test before changing code.
```
