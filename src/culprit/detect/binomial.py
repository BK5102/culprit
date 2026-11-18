"""Detector A2: binomial-aware seasonal z-score, optionally with a CUSUM (methodology M23).

Expected rate for hour t: approvals over attempts pooled across the same hour
of the previous 4 weeks. The z-score asks how many binomial standard
deviations the approvals fell short, with the variance widened for the
uncertainty of the pooled rate: var = n p (1 - p) (1 + n / n_base). Because
real rates also drift, each series' z is divided by its own robust spread over
the previous 4 weeks (at least 1, refreshed daily). The default score is that
z-score. With `mode="cusum"`, a one-sided CUSUM adds up evidence hour by hour,
S_t = max(0, S_{t-1} + z_t - k), like a smoke alarm that tolerates one puff
but not a steady stream. The CUSUM is not the default because its score grows
with an event's length, so a long legitimate promotion in the calibration
window sets a threshold that short outages never reach (seen on a development
world while writing the tests, before any grading existed).
"""

from __future__ import annotations

import numpy as np

from culprit.detect.base import finish, robust_scale_by_day


class BinomialCusum:
    name = "A2"

    def __init__(self, weeks: int = 4, k: float = 0.5, scale_window: int = 672, mode: str = "z"):
        if mode not in ("z", "cusum"):
            raise ValueError("mode must be 'z' or 'cusum'")
        self.weeks = weeks
        self.k = k
        self.scale_window = scale_window
        self.mode = mode

    def zscores(self, attempts: np.ndarray, approved: np.ndarray) -> np.ndarray:
        att = attempts.astype(float)
        app = approved.astype(float)
        n_t = att.shape[1]
        base_att = np.zeros_like(att)
        base_app = np.zeros_like(app)
        for w in range(1, self.weeks + 1):
            lag = 168 * w
            if lag >= n_t:
                break
            base_att[:, lag:] += att[:, :-lag]
            base_app[:, lag:] += app[:, :-lag]
        with np.errstate(invalid="ignore", divide="ignore"):
            p = np.where(base_att > 0, base_app / np.maximum(base_att, 1), np.nan)
            var = att * p * (1 - p) * (1 + att / np.maximum(base_att, 1))
            z = np.where((att > 0) & (var > 0), (att * p - app) / np.sqrt(var), np.nan)
        z[:, :168] = np.nan
        return z

    def score(self, attempts: np.ndarray, approved: np.ndarray, start: int) -> np.ndarray:
        z = self.zscores(attempts, approved)
        warm = max(168, start - 168)  # CUSUM starts one week before scoring, at a fixed hour
        warm -= warm % 24
        phi = robust_scale_by_day(z, warm, self.scale_window, floor=1.0)
        zs = np.where(np.isfinite(z / phi), z / phi, 0.0)
        if self.mode == "z":
            return finish(zs, start)
        s = np.zeros(z.shape)
        state = np.zeros(z.shape[0])
        for t in range(warm, z.shape[1]):
            state = np.maximum(0.0, state + zs[:, t] - self.k)
            s[:, t] = state
        return finish(s, start)
