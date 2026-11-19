# TSFM notes

Every row is checked against the model's own files or documentation at build time. "Not checked" means not verified here, not guessed.

## Chronos-Bolt-tiny (the TSFM detector's forecaster)

| Item | Value | Source |
|---|---|---|
| Checkpoint | `amazon/chronos-bolt-tiny`, revision `a0e552de83495b5c28c14c71c374f3e33280b340` | Same pin as Tells (`tells/docs/tsfm-notes.md`, checked 2026-11-17); the local Hugging Face cache holds exactly this snapshot |
| Package | `chronos-forecasting` (optional extra `tsfm`; Tells used 2.3.2) | `pyproject.toml` |
| License | Apache-2.0 | Hugging Face model card, as recorded in Tells' notes; not re-checked here |
| Size | 8.65M parameters, d_model 256, 4 layers | Parameter count from Tells' notes; d_model and layers read from the cached `config.json` on 2026-11-17 |
| Quantile output | Yes: trained quantiles 0.1, 0.2, ..., 0.9 (`chronos_config.quantiles`) | Cached `config.json` |
| Context length | 2,048 steps (`chronos_config.context_length`); Culprit uses 512 hours | Cached `config.json` |
| Native horizon | 64 steps (`chronos_config.prediction_length`); Culprit forecasts 24 hours per origin | Cached `config.json` |
| Patch size | 16 steps, stride 16 | Cached `config.json` |
| Batch inference | `predict_quantiles` takes a list of 1-D tensors (left-padded with NaN internally) and no batch-size argument, so the adapter sends 256 series at a time | Tells' adapter and notes; Culprit's batch size is not tuned |
| Missing values | NaN in the context is treated as missing (Tells relies on this for padding) | Tells' notes; interior NaN not re-checked here |
| Pre-training data and cutoff | Not checked for Culprit. The data is simulated, so the test world cannot be in the pre-training data, but the model may have seen similar real hourly series | |
| CPU cost in Culprit | Smoke run: 5.07 ms per series per 24-hour forecast origin (4 CPU threads, batch 256, 2026-11-17); the small world (123 series x 28 origins) took 17.5 s. Full development world (2026-11-18): 542.9 s for 1,554 series x 42 origins, 8.3 ms per series per origin, on a laptop CPU that was also running the test suite for part of that time, so treat it as an upper figure | Both runs offline from the cached weights; the full run is described below |

## Smoke run against the real weights (2026-11-17)

The adapter `culprit.detect.tsfm.ChronosBoltForecaster` was run once in a separate virtual environment (`uv sync --extra tsfm`, torch 2.11 CPU, chronos-forecasting 2.3.2) with `HF_HUB_OFFLINE=1`, so the weights came from the local cache and nothing was downloaded. Loading took 45 s (including the first torch import). Three 512-hour contexts, one with 10 missing hours, gave finite quantiles in order (0.1 <= 0.5 <= 0.9). On the small development world the TSFM detector calibrated to 4 alarms in the 2-week calibration window (2 per week) at a threshold of 5.03, like the other detectors, and raised 13 alarms in evaluation. These are development numbers from one seed and not a result. The tests never load the model.

## Full development world run (2026-11-18)

**Development numbers from one seed, not a result. All data is simulated.**

Command, in a clean checkout of commit `9b7ebc0` with the project environment (`uv sync --extra tsfm`: torch 2.15.0 CPU, chronos-forecasting 2.3.2, 4 torch threads) and `HF_HUB_OFFLINE=1`, so the pinned weights came from the local cache:

```
uv run culprit simulate configs/full.yaml
uv run culprit detect configs/full.yaml
uv run culprit attribute configs/full.yaml
uv run culprit evaluate configs/full.yaml
```

Provenance: config hash `f4936cfcf937`, dataset hash `92507feb13f4`, git commit `9b7ebc0` (clean), model `amazon/chronos-bolt-tiny@a0e552de8349/chronos-forecasting-2.3.2`. Budget: 2 false alarms per week counted per series (the default at the time, methodology M27).

Timing (wall clock, laptop CPU): simulate 57 s (30.6 s inside the process); detect 832 s for all four detectors, of which A 29.1 s, A2 18.4 s, B 42.8 s and TSFM 542.9 s; attribute 59 s; evaluate 12 s. The TSFM forecasts every series at 42 daily origins (the 2 calibration and 4 evaluation weeks); the earlier note's "56 origins" counted 8 weeks and was wrong. Part of the run overlapped the test suite on the same CPU.

Calibration and evaluation on the 1,554 monitored series (27 faults in the evaluation weeks: 13 gateway degradations, 8 BIN decline spikes, 6 issuer outages):

| Detector | Threshold | Calibration alarms (incidents) | Evaluation alarms | Evaluation incidents | Faults detected | Caught within 6 h | Median delay (h) | False alarms per week | False incidents per week |
|---|---|---|---|---|---|---|---|---|---|
| A | 16.188 | 4 (4) | 24 | 15 | 10 of 27 | 9 | 1.0 | 3.00 | 2.00 |
| A2 | 4.753 | 4 (2) | 349 | 17 | 20 of 27 | 19 | 1.0 | 1.50 | 0.75 |
| B | 34.931 | 4 (3) | 23 | 13 | 9 of 27 | 9 | 1.0 | 1.75 | 1.50 |
| TSFM | 14.741 | 4 (4) | 28 | 15 | 8 of 27 | 8 | 1.0 | 2.25 | 2.00 |

By fault type, faults detected: A 5 gateway, 4 issuer, 1 BIN; A2 11 gateway, 5 BIN, 4 issuer; B 5 gateway, 3 issuer, 1 BIN; TSFM 3 issuer, 3 gateway, 2 BIN.

The no-LLM control investigated A2's 17 incidents, which covered 20 faults: top-1 0.0, top-3 0.0, fault type 0.25; 2 incidents touched only a promotion and both were blamed on a fault. This is a negative development result and stays in: on the full world the control named no culprit correctly. On the small world it was graded on 1 fault (top-1 0, top-3 1) at per-series counting and on 10 faults (top-1 0.1, top-3 0.4) at per-incident counting (methodology M42). Why the full world is worse is not yet investigated.

What this does and does not say: on one development world, at this budget, the zero-shot TSFM caught fewer faults than the binomial z-score A2 and about as many as A and B. That is one seed and no interval, not an answer to H1, which is scored only on the sealed test worlds.
