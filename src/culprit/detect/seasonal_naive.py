"""Detector A: seasonal naive forecast plus a robust (MAD) threshold (methodology M22).

Forecast for hour t: the approval rate at the same hour one week earlier
(t - 168). Score: (forecast - actual) divided by 1.4826 x the median absolute
deviation of the same residual over the previous 4 weeks, refreshed once a day.
Like guessing "this hour will look like the same hour last week" and alarming
when it is much worse than last week's usual misses.
"""

from __future__ import annotations

import numpy as np

from culprit.detect.base import finish, rate, robust_scale_by_day


class SeasonalNaive:
    name = "A"

    def __init__(self, season: int = 168, scale_window: int = 672):
        self.season = season
        self.scale_window = scale_window

    def score(self, attempts: np.ndarray, approved: np.ndarray, start: int) -> np.ndarray:
        r = rate(approved, attempts)
        resid = np.full(r.shape, np.nan)
        s = self.season
        resid[:, s:] = r[:, :-s] - r[:, s:]
        scale = robust_scale_by_day(resid, start, self.scale_window, floor=1e-4)
        return finish(resid / scale, start)
