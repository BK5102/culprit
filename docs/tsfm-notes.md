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
| CPU cost in Culprit | Not measured yet. The plan budgets about 2 to 3 CPU hours for the full config, cached | `NEXT_PROJECTS_PLAN.md` |

See the end of this file for whether the adapter has been run against the real weights.
