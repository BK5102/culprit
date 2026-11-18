# CLAUDE.md: Culprit

Read this first in every session. It tells you what this project is, how it is laid out, and the rules you must not break.

## What this project is

Culprit monitors payment approval rates across many segments (slices). A time series foundation model (TSFM) forecasts what "normal" looks like for every slice, detectors flag slices that fall outside their normal range, and an AI agent investigates which slice and cause explain a drop. Everything is evaluated on a simulated payment world where faults are injected and their true causes are sealed in a log the agent cannot read. A deterministic no-LLM pipeline is the control the agent must beat. See `PLAN.md` for diagrams, requirements, and the 30-day plan.

Plain-English summary: when you tap a card, your bank says yes or no. When the share of yeses drops, the cause hides in one small segment among thousands. Culprit learns normal for each segment and works out where the problem is.

## Who you are working with

The owner is a data science and economics student who is new to payments and TSFMs. Explain every new term in one plain sentence with a real-world analogy the first time it appears. Keep messages short and direct.

Writing style for all docs, comments, commit messages, and chat:

- Concise, specific, plain language.
- No em-dashes. No emojis.
- Prose over bullet points when prose reads fine.
- Make edits precisely. Do not rewrite surrounding content that was not asked about.
- Cite sources for factual claims about the field. If you cannot source it, say so.

## Repo layout

```
culprit/
  CLAUDE.md  PROMPT.md  PLAN.md  README.md
  pyproject.toml  uv.lock
  src/culprit/
    config.py  world.py (observed data only)  segments.py  panel.py  cli.py
    sim/         hierarchy.py  normal.py  surges.py  faults.py  signals.py  build.py
    detect/      seasonal_naive.py  binomial.py  classical.py  tsfm.py  budget.py  run.py
    investigate/ contribution.py  drilldown.py  fault_typing.py  control.py
    agent/       investigator.py  critic.py  reporter.py  tools.py  llm.py
    evaluate/    metrics.py  grade.py   (the only module allowed to read the fault log)
  tests/         cassettes/ (hand-written LLM fixtures)
  scripts/       check_data_fit.py
  configs/       small.yaml  full.yaml
  docs/          methodology.md  explain-the-project.md  decisions.md  data-fit.md  tsfm-notes.md  findings.md
  data/          gitignored. Generated datasets, hashes recorded.
  artifacts/     gitignored except small sample outputs
```

The testing toolkit comes from the shared `cleanroom` package (split, lock, metrics, bootstrap), built in the sibling project Tells under `packages/cleanroom` and installed here from a git tag: `uv add "cleanroom @ git+https://github.com/BK5102/tells@cleanroom-v0.2#subdirectory=packages/cleanroom"` (v0.2 adds events, vault, guard and forecast scoring). Import it. Do not copy it. If something is missing, add it to `cleanroom` in the Tells repo in a domain-neutral way, release a new `cleanroom-vX.Y` tag, then bump the version here.

## Commands

```
uv sync
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run culprit simulate configs/small.yaml     # generate a small simulated dataset
uv run culprit detect configs/small.yaml       # run the detectors at an equal alert budget
uv run culprit attribute configs/small.yaml    # the no-LLM control on the incidents
uv run culprit evaluate configs/small.yaml     # grade a development world against its answer key
uv run python scripts/check_data_fit.py configs/small.yaml   # data-fit gate
uv run culprit seal CONFIG; uv run culprit run CONFIG --sealed RUN_ID; uv run culprit evaluate CONFIG --run-id RUN_ID   # test worlds only
uv sync --extra tsfm                           # Chronos-Bolt-tiny for the TSFM detector (CPU)
```

Not built yet: `culprit agent --incident N` (needs an API key and spend cap from the owner; the investigator loop exists in `agent/investigator.py` and is tested with cassettes).

If a command above does not exist yet, create it as part of the day's task and update this file.

## Rules you must not break

1. **The fault log is sealed.** Only `evaluate/grade.py` may read it, and only after a run finishes. Tools exposed to the agent must have no code path to it. Write a test that proves this.
2. **Equal alert budget.** Detectors are only compared after thresholds are calibrated to the same false-alarm rate per week.
3. **No future information.** Forecasts at time t use only data before t. The context period contains normal behavior only.
4. **All splits go through `cleanroom.split`,** and scoring requires the lock.
5. **Keep the no-LLM control.** The deterministic investigation pipeline must stay as good as you can make it. Never weaken it to make the agent look better.
6. **Read-only agent.** The agent has no write tools, no shell, no network. It has a hard tool-call budget and a cost cap per incident.
7. **Numbers come from code.** Incident reports insert numbers from tool output. The critic rejects any claim whose cited numbers are not in tool output.
8. **Simulator honesty.** Every README, plot, and report states that data is simulated. Never claim real-world performance.
9. **Hold out a fault type and a simulator regime** at test time to check the system is not tuned to the simulator.
10. **Never invent results, datasets, or citations.** Use clearly marked placeholders.
11. **Negative results stay in,** including cases where the control beats the agent.
12. **Record provenance** on every result: config hash, git commit, model name and version, dataset hash.
13. **Every choice is explained.** Any new method, variable, threshold, default, or simulator setting gets an entry in `docs/methodology.md` (what, why, what else was considered, limitation) in the same commit, and any new limitation goes in its limitations register. The owner must be able to defend every choice in an interview.
14. **Keep the story current.** After every step that changes the project or produces a result, update `docs/explain-the-project.md`: what was done, why, what else was considered, cause and effect, and a one-sentence way to say it in an interview.
15. **CPU only.** Every run, including the full config and the TSFM detector, must run on a laptop CPU. Do not add steps that need a GPU.

## Agent safety rules (for `src/culprit/agent/`)

- Tool allow-list: `query_slice`, `forecast`, `decline_reasons`, `latency`. All read-only.
- Tool outputs include the numbers the agent may cite. The critic checks citations against them.
- LLM calls sit behind an interface. Tests use recorded cassettes so they are deterministic and free.
- Reports are labeled "investigation, not a decision."

## Workflow

- One shippable feature per day, as listed in `PLAN.md` Part 6. Small commits, each with a test.
- Commit style: `type: short summary` using `feat`, `fix`, `test`, `docs`, `chore`.
- Before finishing a task: run tests and lint, then state what changed and what you did not verify.
- When a task is ambiguous, ask one specific question instead of guessing.
- After each feature, add a 3-sentence plain-English note to `docs/decisions.md` with an analogy. These become the owner's talking points.
- Check TSFM capabilities (quantile output, context length, batch inference, license) against the model's own documentation at build time and record them in `docs/tsfm-notes.md`. Do not assume.

## Definition of done for any feature

Tests pass, lint passes, a leak or reconciliation test exists if the feature touches the simulator, splits, or the fault log, docs are updated if behavior changed, and the change is explained in plain English.
