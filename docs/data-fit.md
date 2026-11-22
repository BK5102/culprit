# Data fit check (2026-11-17)

**All data here is simulated.** Culprit's only data source is its own simulator. Before building detectors on it, `scripts/check_data_fit.py` measures whether the simulated world can answer the two questions at all (methodology M20). Analogy: before timing runners on a track, check that the track is not downhill and that the finish line is not visible from the start.

Every number below was produced by that script. Command:

```
uv run python scripts/check_data_fit.py configs/small.yaml --seeds 101 102 103 104 105
uv run python scripts/check_data_fit.py configs/full.yaml --seeds 201
```

The seeds 101 to 105 and 201 are development seeds used only for this check; they are not the seeds of the configs (7 and 17) and not test seeds. The script simulates in memory and uses the simulator's truth (the normal approval probability), which no detector or investigator ever sees; it does not read a sealed answer key from disk.

## Run 1: faults were too easy to see (kept as a negative result)

With the first fault severities (issuer outage 0.25 to 0.70, BIN spike 0.15 to 0.50, gateway 0.05 to 0.25, uniform draws), on the small config and seeds 101 to 105 (45 faults):

| Check | Measured |
|---|---|
| Median hourly signal-to-noise at the fault's segment (binomial noise) | 40.79 |
| Median hourly drop over the empirical noise detectors face | 31.09 |
| Share of faults with hourly drop under 3 x empirical noise (hard) | 0.0% |
| Share with hourly drop at least 10 x empirical noise (easy) | 88.9% |
| Share masked in the total rate | 17.8% |
| Largest rate drop names the culprit (top-1) | 8.9% |

Every detector would have caught almost every fault in its first hour, so H1 (which detector catches faults sooner at the same false-alarm rate) could not have separated anything. The severities were lowered and drawn log-uniformly (methodology M14) before any detector existed. The sizes and seeds did not change.

## Run 2: current settings

Severities now: issuer outage 0.01 to 0.40, BIN spike 0.01 to 0.30, gateway 0.01 to 0.15 (held-out extra verification 0.01 to 0.20, not injected here), log-uniform.

### Small config (96 leaves, 8 weeks, seeds 101 to 105, 45 faults)

| Check | Measured |
|---|---|
| Signal: median hourly SNR at the fault's segment (binomial noise) | 8.44 |
| Signal: median whole-window SNR | 17.81 |
| Signal: share of faults with window SNR of at least 3 | 91.1% |
| Signal: share with window SNR under 1 | 2.2% |
| Signal: median hourly drop over empirical noise | 6.55 |
| Signal: share with hourly drop under 3 x empirical noise (hard) | 33.3% |
| Signal: share with hourly drop at least 10 x empirical noise (easy) | 37.8% |
| Masking: share of faults whose total-rate drop is under 3 x the total's noise | 57.8% |
| Masking: masked in the total but window SNR of at least 3 at the segment | 48.9% |
| Surge traps: promotions that fire the naive detector | 44.4% of 54 |
| Surge traps: paydays that fire it | 7.9% of 38 |
| Surge traps: quiet 8-hour windows that fire it (base rate) | 0.4% of 232 |
| Too easy: largest rate drop is the culprit (top-1) | 0.0% |
| Too easy: largest approval shortfall is the culprit (top-1) | 33.3% |

Headroom on the fault-free calibration window: mean absolute error of the hourly approval rate, median over the nodes of each level.

| Level | Nodes | Oracle | Seasonal naive | 4-week pooled | Oracle / naive | Oracle / pooled |
|---|---|---|---|---|---|---|
| total | 1 | 0.0017 | 0.0047 | 0.0054 | 0.37 | 0.37 |
| country | 2 | 0.0029 | 0.0058 | 0.0051 | 0.46 | 0.46 |
| method | 2 | 0.0028 | 0.0055 | 0.0052 | 0.50 | 0.55 |
| gateway | 4 | 0.0038 | 0.0072 | 0.0072 | 0.53 | 0.52 |
| issuer | 6 | 0.0061 | 0.0101 | 0.0083 | 0.60 | 0.64 |
| bin | 12 | 0.0083 | 0.0152 | 0.0132 | 0.62 | 0.74 |
| leaf | 96 | 0.0288 | 0.0413 | 0.0342 | 0.69 | 0.87 |

By fault type:

| Type | Faults | Median hourly SNR | Median window SNR | Median hourly empirical SNR | Masked | Largest drop right |
|---|---|---|---|---|---|---|
| bin_decline_spike | 12 | 2.33 | 9.55 | 1.74 | 83.3% | 0.0% |
| gateway_degradation | 12 | 8.33 | 13.70 | 6.21 | 58.3% | 0.0% |
| issuer_outage | 21 | 17.40 | 30.79 | 14.79 | 42.9% | 0.0% |

Bookkeeping, per seed: 96 leaves x 1,344 hours = 129,024 rows; mean attempts per hour 20,338 to 21,796; overall approval rate 0.867 to 0.924; leaf-hours with no attempts 1.9% to 5.5%; faults per seed 6, 8, 9, 14, 8; overlapping fault pairs 0, 0, 1, 1, 1. Counts reconcile up the hierarchy, declines by reason sum to attempts minus approvals, approvals never exceed attempts, and all faults start in the evaluation window, for every seed. Simulating one small world took about 0.2 s; the whole check about 1.4 s.

### Full config (1,440 leaves, 12 weeks, seed 201, 30 faults)

| Check | Measured |
|---|---|
| Signal: median hourly SNR at the fault's segment | 6.59 |
| Signal: share of faults with window SNR of at least 3 | 86.7% |
| Signal: share with window SNR under 1 | 6.7% |
| Signal: median hourly drop over empirical noise | 6.58 |
| Signal: hard (under 3 x empirical noise) / easy (at least 10 x) | 40.0% / 30.0% |
| Masking: share masked in the total rate | 100.0% |
| Masking: masked in the total but window SNR of at least 3 at the segment | 86.7% |
| Surge traps: promotions / paydays / quiet windows that fire the naive detector | 66.7% of 18 / 0.0% of 12 / 0.0% of 47 |
| Too easy: largest rate drop / largest shortfall is the culprit | 3.3% / 10.0% |
| Headroom, oracle / naive at leaf, BIN, issuer | 0.72, 0.67, 0.65 |
| Headroom, oracle / 4-week pooled at leaf, BIN, issuer | 0.89, 0.85, 0.81 |

The full check took 5.9 s for one seed.

## Gates and what they mean

All gates pass on both configs in run 2 (run 1 would have failed the "detection not trivial" gate, which was added after seeing it).

- **Too easy** (largest rate drop must be right well under 90% of the time): 0.0% small, 3.3% full. Picking the biggest drop lands on tiny noisy leaves, and picking the biggest shortfall lands on big parents. Finding the culprit needs real drill-down, so H2 is a real question.
- **Masking exists**: 48.9% (small) and 86.7% (full) of faults are hidden in the overall rate yet clearly visible at their own segment. This is the "freezing neighborhood in a warm city" case the project is about.
- **Detection is not trivial**: a third of faults (small) are under 3 times the hour-to-hour noise at their own segment, and fewer than half are over 10 times. Detectors can differ.
- **Surge traps work**: a naive detector fires on 44.4% (small) and 66.7% (full) of promotions against 0.4% and 0.0% of quiet windows. Paydays rarely fire it because they raise the rate.
- **Headroom exists but is modest at the leaves.** The oracle error is 0.69 (small) and 0.72 (full) of seasonal naive's at the leaf level, but 0.87 and 0.89 of a simple 4-week pooled average's. Most of the gap between seasonal naive and the oracle at the leaves is noise that any multi-week average removes. Larger gains are possible only on aggregates (oracle / pooled 0.37 to 0.74 small), where day-to-day drift matters more than binomial noise. This is the same trap as Tells' ceiling: a TSFM can only win where a cheap multi-week baseline leaves error on the table.

## Limits of this check

Signal-to-noise uses the simulator's true rates, which no real team has. The masking threshold (3 times the total's noise) and the naive detector (robust z above 3 for 2 hours) are simple fixed rules chosen for this check, not the calibrated detectors. Five small seeds give 45 faults, so the per-type shares rest on 12 to 21 faults each.

## Test-plan regimes on development seeds (2026-11-21)

Command: `uv run python scripts/check_data_fit.py configs/test.yaml --regime base --seeds 301 302 303`, and the same with `--regime second`, after the owner's choices (methodology M49) and the headroom fix (M50). Test seeds are never used here; the script refuses them.

| Regime | Leaf headroom, oracle / naive | Leaf headroom, oracle / 4-week pooled | Leaves without a defined ratio, per seed | Gates |
|---|---|---|---|---|
| base | 0.72 | 0.89 | 0, 3, 21 of 1,440 | all 7 pass |
| second | 0.69 | 0.84 | 1, 1, 19 of 1,440 | all 7 pass |

Before the M50 fix both regimes failed `headroom_leaf_ratio_below_0.9` because the leaf median was undefined, not because headroom was missing.
