"""Detector B: classical seasonal forecaster with intervals (MSTL from statsmodels; M24).

Fit once per series on the last 4 weeks of the context period (normal only):
MSTL splits the hourly rate into a trend, a daily (24 h) and a weekly (168 h)
seasonal pattern. The forecast for hour t is the weekly-plus-daily pattern at
t's hour of the week plus a level that is updated hour by hour with
exponential smoothing on past values only. The interval width comes from the
one-step errors on the context, one robust spread per hour of day, so quiet
night hours get wider intervals than busy afternoons. Score: how many of those
spreads the actual rate falls below the forecast.

MSTL runs with LOESS "jumps" of 24 (the smoother is evaluated every 24 points
and interpolated), which cut the fit from about 0.5 s to 0.02 s per series on
a laptop CPU (measured 2026-11-17) and keep the shape of the seasonal pattern.
"""

from __future__ import annotations

import warnings

import numpy as np
from statsmodels.tsa.seasonal import MSTL

from culprit.detect.base import finish, rate

JUMPS = {"seasonal_jump": 24, "trend_jump": 24, "low_pass_jump": 24}


def _fill(y: np.ndarray) -> np.ndarray:
    ok = np.isfinite(y)
    if ok.all():
        return y
    idx = np.arange(len(y))
    return np.interp(idx, idx[ok], y[ok])


class MSTLDetector:
    name = "B"

    def __init__(self, fit_hours: int = 672, alpha: float = 0.05, resid_hours: int = 336):
        self.fit_hours = fit_hours
        self.alpha = alpha
        self.resid_hours = resid_hours

    def seasonal_profile(self, r: np.ndarray, start: int) -> np.ndarray:
        """(nodes, 168) weekly-plus-daily pattern indexed by hour % 168."""
        lo = max(0, start - self.fit_hours)
        prof = np.zeros((r.shape[0], 168))
        for i in range(r.shape[0]):
            y = r[i, lo:start]
            if np.isfinite(y).sum() < 2 * 168:
                continue
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                fit = MSTL(_fill(y), periods=(24, 168), iterate=1, stl_kwargs=JUMPS).fit()
            seasonal = np.asarray(fit.seasonal)
            seasonal = seasonal.sum(axis=1) if seasonal.ndim == 2 else seasonal
            hours = np.arange(lo, start)[-168:]
            prof[i, hours % 168] = seasonal[-168:]
        return prof

    def forecast(self, r: np.ndarray, start: int) -> tuple[np.ndarray, np.ndarray]:
        """One-step forecasts for every hour, and the per-hour-of-day spread from context."""
        prof = self.seasonal_profile(r, start)
        n, t_n = r.shape
        season = prof[:, np.arange(t_n) % 168]
        d = r - season
        lo = max(0, start - self.fit_hours)
        level = np.where(np.isfinite(d[:, lo]), d[:, lo], 0.0)
        init = np.nanmean(d[:, lo:start], axis=1) if start > lo else level
        level = np.where(np.isfinite(init), init, 0.0)
        fc = np.full(r.shape, np.nan)
        for t in range(lo, t_n):
            fc[:, t] = level + season[:, t]
            x = d[:, t]
            ok = np.isfinite(x)
            level = np.where(ok, (1 - self.alpha) * level + self.alpha * np.where(ok, x, 0), level)
        # Spread by hour of day from one-step errors on the end of the context.
        e = r[:, start - self.resid_hours : start] - fc[:, start - self.resid_hours : start]
        hod = np.arange(start - self.resid_hours, start) % 24
        spread = np.full((n, 24), np.nan)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            for h in range(24):
                eh = e[:, hod == h]
                med = np.nanmedian(eh, axis=1)
                spread[:, h] = 1.4826 * np.nanmedian(np.abs(eh - med[:, None]), axis=1)
        spread = np.maximum(np.where(np.isfinite(spread), spread, np.nan), 1e-4)
        return fc, spread

    def score(self, attempts: np.ndarray, approved: np.ndarray, start: int) -> np.ndarray:
        r = rate(approved, attempts)
        fc, spread = self.forecast(r, start)
        sd = spread[:, np.arange(r.shape[1]) % 24]
        return finish((fc - r) / sd, start)
