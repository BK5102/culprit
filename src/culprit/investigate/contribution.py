"""Contribution analysis: which segment explains how much of a drop (methodology M30).

For an investigation window [start, end) known at time `end` (the hour after
the alarm), every leaf gets a baseline approval rate: approvals over attempts
pooled across the same hour of the previous 4 weeks (falling back to the
leaf's rate over the 4 weeks before the window when a pooled hour is empty),
shifted by the leaf's recent level so day-to-day drift is not mistaken for a
drop (see `baseline_rates`). Then, per segment:

- expected approvals = sum of attempts x baseline rate,
- missing approvals = expected - actual (positive means a shortfall),
- z = missing / sqrt(sum of attempts x p x (1 - p)).

Using the actual attempts with the baseline rate means a volume surge alone
creates no missing approvals; only a change in the rate does. Like counting
how many extra people a bouncer turned away tonight compared with his usual
rate for a crowd this size, rather than comparing headcounts.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from culprit.world import ObservedWorld


def _pooled(att: np.ndarray, app: np.ndarray, hours: np.ndarray, weeks: int) -> np.ndarray:
    b_att = np.zeros((att.shape[0], len(hours)))
    b_app = np.zeros_like(b_att)
    for w in range(1, weeks + 1):
        lag = hours - 168 * w
        ok = lag >= 0
        b_att[:, ok] += att[:, lag[ok]]
        b_app[:, ok] += app[:, lag[ok]]
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(b_att > 0, b_app / np.maximum(b_att, 1), np.nan)


def baseline_rates(
    world: ObservedWorld,
    start: int,
    end: int,
    weeks: int = 4,
    level_hours: int = 24,
    level_gap: int = 6,
) -> np.ndarray:
    """(leaves, end - start) baseline approval probability per leaf-hour, from the past only.

    Pooled same-hour rate of the previous `weeks` weeks, shifted by the leaf's
    recent level: its approvals minus pooled-expected approvals, per attempt,
    over the `level_hours` hours that end `level_gap` hours before the window.
    The shift tracks day-to-day drift; the gap keeps a fault that started just
    before the window out of the baseline.
    """
    att = world.attempts.astype(float)
    app = world.approved.astype(float)
    hours = np.arange(start, end)
    pooled = _pooled(att, app, hours, weeks)
    lo = max(0, start - 168 * weeks)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        fallback = app[:, lo:start].sum(1) / np.maximum(att[:, lo:start].sum(1), 1)
        pooled = np.where(np.isfinite(pooled), pooled, fallback[:, None])
        l1 = max(0, start - level_gap)
        l0 = max(0, l1 - level_hours)
        offset = np.zeros(att.shape[0])
        if l1 > l0:
            rh = np.arange(l0, l1)
            pr = _pooled(att, app, rh, weeks)
            pr = np.where(np.isfinite(pr), pr, fallback[:, None])
            a = att[:, rh]
            offset = (app[:, rh] - a * pr).sum(1) / np.maximum(a.sum(1), 1)
    return np.clip(pooled + offset[:, None], 1e-6, 1 - 1e-6)


@dataclass
class LeafWindow:
    """Per-leaf totals over one investigation window; nodes are sums of leaves."""

    start: int
    end: int
    attempts: np.ndarray  # (leaves,)
    approved: np.ndarray
    expected: np.ndarray
    variance: np.ndarray

    @property
    def missing(self) -> np.ndarray:
        return self.expected - self.approved


def leaf_window(world: ObservedWorld, start: int, end: int, weeks: int = 4) -> LeafWindow:
    if end > world.n_hours_seen:
        raise ValueError("the window ends after the data that is visible at this time")
    start = max(0, start)
    p = baseline_rates(world, start, end, weeks)
    att = world.attempts[:, start:end].astype(float)
    app = world.approved[:, start:end].astype(float)
    return LeafWindow(
        start,
        end,
        att.sum(1),
        app.sum(1),
        (att * p).sum(1),
        (att * p * (1 - p)).sum(1),
    )


@dataclass(frozen=True)
class NodeStats:
    attempts: float
    approved: float
    expected: float
    missing: float
    z: float

    @property
    def rate(self) -> float:
        return self.approved / self.attempts if self.attempts else float("nan")

    @property
    def expected_rate(self) -> float:
        return self.expected / self.attempts if self.attempts else float("nan")


def node_stats(world: ObservedWorld, lw: LeafWindow, f: Mapping[str, str]) -> NodeStats:
    m = world.segments.mask(f)
    var = float(lw.variance[m].sum())
    missing = float(lw.missing[m].sum())
    z = missing / np.sqrt(var) if var > 0 else 0.0
    return NodeStats(
        float(lw.attempts[m].sum()),
        float(lw.approved[m].sum()),
        float(lw.expected[m].sum()),
        missing,
        float(z),
    )
