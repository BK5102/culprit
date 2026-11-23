# Runbook: from the owner's choices to a sealed result

**All data in this project is simulated.** This is the exact order of commands from "the owner has made the manual choices" to "the sealed result is written up". Run them from the repo root on a laptop CPU. Commands are shown for PowerShell; in Git Bash write `export NAME=value` instead of `$env:NAME = "value"`.

Every step before step 7 is development and may be repeated. From step 7 on, every attempt is counted by the Cleanroom and stays in the record, so read each step before running it.

## 0. Set up and check

```
uv sync --extra tsfm --extra agent
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

The `tsfm` extra installs Chronos-Bolt-tiny's CPU dependencies; the first TSFM run downloads the pinned weights unless they are already cached. The `agent` extra installs the Anthropic SDK.

## 1. API key and spend caps (owner choice a)

```
$env:ANTHROPIC_API_KEY = "<your key>"     # this shell only; never in a file in git
```

Then set the caps in the configs (USD). `agent.max_total_cost_usd` is the total for all live calls in that scope (development worlds share one spend log, `cassettes/spend-dev.jsonl`; the sealed plan has its own, `cassettes/spend-test.jsonl`). `agent.max_cost_usd` is per incident. Each call first reserves its worst case, `max_tokens` of output at USD 20 per million (USD 0.32 at 16,000), so set `max_tokens` and `max_cost_usd` together (methodology M44).

- `configs/small.yaml`: add `agent: {max_total_cost_usd: <dev budget>}` (and `max_cost_usd`, `max_tokens` if you change them).
- `configs/test.yaml`: decided 2026-11-22, the sealed run leaves the agent out (`test.agent: false`, `max_total_cost_usd: null`; D16, M52). No key is needed for the sealed run.

`culprit agent --record` refuses to start without the key or the total cap.

## 2. The false-alarm budget (owner choice b; decided 2026-11-21: per_incident, D13)

```
uv run python scripts/compare_budget_modes.py configs/small.yaml
```

Prints both counting units on the small development world (development only). Then set `budget.mode` in `configs/test.yaml` to `per_series` or `per_incident` (recommended). For development runs that match the test, set the same `budget.mode` in `configs/small.yaml` and `configs/full.yaml`.

## 3. The test plan (owner choice c; decided 2026-11-21: seeds drawn and second regime set, D13)

Draw the seeds once and paste the list into `test.seeds` in `configs/test.yaml`:

```
uv run python -c "import secrets; print([secrets.randbelow(10**6) for _ in range(5)])"
```

Write the second regime under `test.regimes.second` (the recommended one is in the file's comments), confirm `extra_verification` is still in `world.faults.types`, and check the regime's fit on development seeds:

```
uv run python scripts/check_data_fit.py configs/test.yaml --regime second --seeds 301 302 303
```

All gates should pass (methodology M20). The fit check refuses test seeds.

## 4. Record development cassettes and size the caps

```
uv run culprit simulate configs/small.yaml
uv run culprit detect configs/small.yaml
uv run culprit attribute configs/small.yaml
uv run culprit agent configs/small.yaml --incident 0 --record     # one incident first: check its cost
uv run culprit agent configs/small.yaml --all --record
uv run culprit evaluate configs/small.yaml
```

Read the reports in `artifacts/small-seed7/agent/reports/` and the cost lines that `evaluate` prints. Set `agent.max_total_cost_usd` in `configs/test.yaml` to at least (incidents per test world) x (number of test worlds) x (median cost per incident), with room to spare: an incident the cap stops counts as a miss for the agent. Fix `agent.max_cost_usd`, `max_tokens` and `max_tool_calls` now; they are locked in step 7. Commit the recordings:

```
git add cassettes configs
git commit -m "chore: development agent recordings and caps"
```

## 5. Development checks

```
uv run culprit simulate configs/full.yaml
uv run culprit detect configs/full.yaml        # about 15 minutes with the TSFM
uv run culprit attribute configs/full.yaml
uv run culprit evaluate configs/full.yaml
uv run python scripts/diagnose_control.py configs/full.yaml   # control with detector and oracle alerts, about 3 minutes
uv run culprit validate configs/test.yaml      # must print "ready to seal"
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
```

Fix anything that fails before going on. Development numbers are not results.

## 6. Commit everything

```
git status                                      # must show nothing to commit
```

The sealed run refuses a tree with uncommitted changes to tracked files.

## 7. Seal

```
uv run culprit simulate configs/test.yaml       # builds every test world (10 with 5 seeds x 2 regimes)
uv run culprit seal configs/test.yaml --note "sealed test plan"
```

This writes the lock (the plan, the agent prompt hash and one checksum over every world) and one vault record per world's answer key under `locks/`. From now on `configs/test.yaml` and the agent prompt must not change; a change needs a new lock, which is visible in git.

## 8. Commit the lock

```
git add configs/test.yaml locks
git commit -m "chore: seal the test plan"
git push
```

## 9. The sealed run

```
uv run culprit run configs/test.yaml --sealed test-1
```

Runs the detectors and the no-LLM control on every test world, as one sealed run. The agent is left out (`test.agent: false`, D16), so it makes no live call and needs no key. Expect about 2.5 hours of CPU for 10 worlds, plus the agent's time. If it crashes, the attempt stays recorded as started; do not edit the plan, commit the uses file and start a new run id (`test-2`). Recordings already saved are replayed for free, so a second attempt reuses them.

## 10. Commit the run record

```
git add locks cassettes
git commit -m "chore: record sealed run test-1"
```

## 11. Evaluate

```
uv run culprit evaluate configs/test.yaml --run-id test-1
git add locks
git commit -m "chore: answer key releases for test-1"
```

The answer keys open only now, through the vault, and every opening is logged under `locks/vaults/`. Per-world grades go to `artifacts/test-<regime>-seed<seed>/evaluate/grade.json`; the pooled numbers (H1 and H2 with 95% intervals that resample whole worlds) go to `artifacts/test/summary.json` and are printed.

## 12. Write up

Fill `docs/findings.md` from `artifacts/test/summary.json` only, copying each number with the plan's config hash, and keep every negative result (CLAUDE.md rules 10 and 11). Report the held-out fault type and the second regime separately. Update the README's status line, `docs/explain-the-project.md` (a new step), `docs/decisions.md` and the limitations register in `docs/methodology.md`, then:

```
uv run pytest -q
git add docs README.md
git commit -m "docs: sealed result for test-1"
git push
```
