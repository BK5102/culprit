"""Shared pieces for detectors.

Every detector turns node-level counts into a drop score per node and hour:
`score(attempts, approved, start) -> (nodes, hours)`. Higher means "lower
approval rate than expected". Scores exist only for hours >= `start` (the
first calibration hour); earlier hours are NaN. A score at hour t may use the
counts at t (the observation being judged) and anything before t, never
anything after (CLAUDE.md rule 3; tested in tests/test_detectors.py).
"""

from __future__ import annotations

import warnings
from typing import Protocol

import numpy as np


class Detector(Protocol):
    name: str

    def score(self, attempts: np.ndarray, approved: np.ndarray, start: int) -> np.ndarray: ...


def rate(approved: np.ndarray, attempts: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(attempts > 0, approved / np.maximum(attempts, 1), np.nan)


def robust_scale_by_day(
    x: np.ndarray, start: int, window: int = 672, step: int = 24, floor: float = 1e-6
) -> np.ndarray:
    """Robust spread (1.4826 x MAD) of each row of x over the `window` hours before each day.

    Blocks start at `start` and are `step` hours long; the scale for hours
    [d, d + step) uses x[:, d - window : d] only, so it never sees the hour it
    scales. Where the MAD is zero (a tiny segment whose hourly rate is almost
    always exactly 0 or 1), the standard deviation is used instead, so one
    unusual hour does not get an absurd score. Rows with no finite values get NaN.
    """
    out = np.full(x.shape, np.nan)
    for d in range(start, x.shape[1], step):
        w = x[:, max(0, d - window) : d]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            med = np.nanmedian(w, axis=1)
            mad = 1.4826 * np.nanmedian(np.abs(w - med[:, None]), axis=1)
            mad = np.where(mad > 0, mad, np.nanstd(w, axis=1))
        out[:, d : d + step] = np.maximum(mad, floor)[:, None]
    return out


def finish(score: np.ndarray, start: int) -> np.ndarray:
    """NaN before `start`; no evidence (NaN) at or after `start` becomes 0."""
    out = np.where(np.isfinite(score), score, 0.0)
    out[:, :start] = np.nan
    return out
