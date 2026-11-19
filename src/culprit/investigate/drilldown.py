"""Drill-down by scanning the whole hierarchy, with a stopping rule (methodology M31).

Every segment that can be written as (geography level) x (method or not) x
(gateway or not) is a candidate: the total, each country, issuer and BIN,
each method and gateway, and every combination such as an issuer's
card-not-present payments or a BIN on one gateway. For each candidate:

1. z_now: its shortfall of approvals in the investigation window, in binomial
   standard deviations (`contribution.node_stats`).
2. phi: how big z usually is when nothing is wrong, measured on windows of
   the same hours on each of the previous 7 days (past only): for each
   segment 1.4826 x the median of |z|, then the median over all segments, at
   least 1. Rates drift more than binomial noise allows, and phi absorbs that.
   One phi for all segments keeps their ranking by raw z; a separate phi per
   segment, from only 7 past windows, was too noisy (it ranged from 1.35 to
   3.04 across segments in one test world and reordered the candidates).
3. score = z_now / phi. Since methodology M48 the z the scan ranks by (and
   measures phi with) is the exact binomial tail z of the window's declines
   (`exact_tail_z`, `score: exact_tail`), because the normal approximation
   gives one decline on a thin segment a nominal z of 5 or more. `score:
   normal` keeps the M31 ranking for comparison.

The best candidate is the one with the highest score, if that score is at
least `min_z` (the stopping rule); otherwise "no localized drop". For a fault
on segment T, the score peaks at T in expectation: a parent adds unaffected
payments that dilute the drop, and a child loses affected ones. Near-ties
between T and its biggest child are settled by a generalization step: move
from the best segment to a parent (drop one cross dimension, or go one level
up the geography) when the rest of that parent looks hit too: its relative
drop is at least `rest_min_ratio` (0.5) of the segment's, which is the
midpoint between "the rest is untouched" and "the rest has the same drop",
and its score is at least `rest_min_z` (0 by default; a z requirement of 2
was tried and blocked generalization whenever the rest was small). A fault on
a whole issuer hits all of its BINs; a fault on one BIN leaves the others
alone. Like a
detective who checks every street at once and names the one where the
trouble is most clearly concentrated.

History: a greedy top-down walk (move into a child only if it holds most of
the drop and more than its share, later only if the rest of the parent was
clearly less hit) was written first. On development worlds in the tests it
stopped at the total whenever an unrelated sibling's drift cancelled the
faulty segment's shortfall in the parent (an issuer with z of 6 under a
country with z of -2.9), so it was replaced by this scan before any grading.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any

import numpy as np
from scipy.special import ndtri_exp, xlogy
from scipy.stats import binom

from culprit.investigate.contribution import LeafWindow, NodeStats, leaf_window
from culprit.segments import Segments, canonical, depth, node_key
from culprit.world import ObservedWorld


@dataclass(frozen=True)
class DrillSettings:
    min_z: float = 3.0
    history_days: int = 7
    rest_min_z: float = 0.0
    rest_min_ratio: float = 0.5
    score: str = "exact_tail"  # M48 Variant 2; "normal" is the M31 score

    def __post_init__(self) -> None:
        if self.score not in SCORES:
            raise ValueError(f"control score must be one of {SCORES}, not {self.score!r}")

    @classmethod
    def from_config(cls, c: dict[str, Any]) -> DrillSettings:
        return cls(
            float(c["min_z"]),
            int(c["history_days"]),
            float(c["rest_min_z"]),
            float(c["rest_min_ratio"]),
            str(c.get("score", "exact_tail")),
        )


SCORES = ("normal", "exact_tail")


def exact_tail_z(attempts: np.ndarray, approved: np.ndarray, expected: np.ndarray) -> np.ndarray:
    """Rank score from the exact binomial tail of the declines (methodology M48, Variant 2).

    Declines in the window are compared with Binomial(attempts, expected declines
    / attempts). Above expectation the score is the normal quantile of
    P(declines >= observed), so one decline where 0.03 was expected scores 1.9,
    not the 5.7 of the normal approximation; at or below expectation it is the
    normal quantile of P(declines <= observed), which is negative or near 0.
    For large segments it agrees with the normal z.

    Where a tail is smaller than the smallest float (beyond a z of about 37),
    its log is taken from the large-deviation (Chernoff) form of the same tail,
    -n x KL(d / n, q), so very strong drops keep finite, ordered scores instead
    of all tying at infinity.
    """
    n = np.rint(np.asarray(attempts, dtype=float))
    d = np.rint(n - np.asarray(approved, dtype=float))
    mu = n - np.asarray(expected, dtype=float)
    ok = n > 0
    q = np.clip(np.where(ok, mu / np.maximum(n, 1), 0.5), 1e-12, 1 - 1e-12)
    out = np.zeros(len(n))
    up = ok & (d > mu)
    lo = ok & ~up
    log_up = binom.logsf(d[up] - 1, n[up], q[up])
    log_lo = binom.logcdf(d[lo], n[lo], q[lo])
    log_up = np.where(np.isfinite(log_up), log_up, _chernoff(d[up], n[up], q[up]))
    log_lo = np.where(np.isfinite(log_lo), log_lo, _chernoff(d[lo], n[lo], q[lo]))
    out[up] = -ndtri_exp(log_up)
    out[lo] = ndtri_exp(log_lo)
    return out


def _chernoff(d: np.ndarray, n: np.ndarray, q: np.ndarray) -> np.ndarray:
    """Log of a binomial tail by its large-deviation form: -n x KL(d / n, q)."""
    f = d / n
    return -n * (xlogy(f, f / q) + xlogy(1 - f, (1 - f) / (1 - q)))


def parents(f: dict[str, str], seg: Segments) -> list[dict[str, str]]:
    """Segments one step more general than f: drop a cross key, or go one geography level up."""
    out = [
        canonical({k: v for k, v in f.items() if k != c}) for c in ("method", "gateway") if c in f
    ]
    if "bin" in f:
        issuer = f["bin"].rsplit("-", 1)[0]
        out.append(canonical({**{k: v for k, v in f.items() if k != "bin"}, "issuer": issuer}))
    elif "issuer" in f:
        country = f["issuer"].split("-", 1)[0]
        out.append(canonical({**{k: v for k, v in f.items() if k != "issuer"}, "country": country}))
    elif "country" in f:
        out.append(canonical({k: v for k, v in f.items() if k != "country"}))
    return [p for p in out if p and seg.exists(p)]


def candidate_nodes(seg: Segments) -> list[dict[str, str]]:
    geo: list[dict[str, str]] = [{}]
    geo += [{"country": v} for v in seg.values["country"]]
    geo += [{"issuer": v} for v in seg.values["issuer"]]
    geo += [{"bin": v} for v in seg.values["bin"]]
    methods: list[dict[str, str]] = [{}] + [{"method": v} for v in seg.values["method"]]
    gateways: list[dict[str, str]] = [{}] + [{"gateway": v} for v in seg.values["gateway"]]
    return [canonical({**g, **m, **w}) for g, m, w in product(geo, methods, gateways)]


@dataclass
class Candidate:
    node: dict[str, str]
    stats: NodeStats
    phi: float
    rank_z: float  # the z the scan ranks by: stats.z, or the exact tail z (M48)

    @property
    def key(self) -> str:
        return node_key(self.node)

    @property
    def score(self) -> float:
        return self.rank_z / self.phi


@dataclass
class DrillResult:
    culprit: dict[str, str] | None  # None means no localized drop
    root: NodeStats
    candidates: list[Candidate] = field(default_factory=list)

    @property
    def culprit_key(self) -> str | None:
        return None if self.culprit is None else node_key(self.culprit)

    def ranked(self, k: int = 3) -> list[str]:
        """Segments (not the total) by score, highest first: the top-k list."""
        order = sorted(self.candidates, key=lambda c: (-c.score, depth(c.node), c.key))
        return [c.key for c in order if c.node][:k]


def _node_z(m, lw: LeafWindow) -> tuple[np.ndarray, ...]:
    att, app = m @ lw.attempts, m @ lw.approved
    exp, var = m @ lw.expected, m @ lw.variance
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(var > 0, (exp - app) / np.sqrt(np.maximum(var, 1e-12)), 0.0)
    return att, app, exp, z, var


def _rank_z(settings: DrillSettings, att, app, exp, z) -> np.ndarray:
    return exact_tail_z(att, app, exp) if settings.score == "exact_tail" else z


def drill_down(
    world: ObservedWorld, lw: LeafWindow, settings: DrillSettings, weeks: int = 4
) -> DrillResult:
    seg = world.segments
    nodes = candidate_nodes(seg)
    m = seg.membership(nodes)
    att, app, exp, z_now, var = _node_z(m, lw)
    rank_now = _rank_z(settings, att, app, exp, z_now)
    span = lw.end - lw.start
    past_z = []
    for d in range(1, settings.history_days + 1):
        end = lw.end - 24 * d
        if end - span < 0:
            break
        pa, pp, pe, pz, _ = _node_z(m, leaf_window(world.until(end), end - span, end, weeks))
        past_z.append(_rank_z(settings, pa, pp, pe, pz))
    if past_z:
        per_node = 1.4826 * np.median(np.abs(np.array(past_z)), axis=0)
        phi = np.full(len(nodes), max(1.0, float(np.median(per_node))))
    else:
        phi = np.ones(len(nodes))
    cands = [
        Candidate(
            n,
            NodeStats(att[i], app[i], exp[i], exp[i] - app[i], z_now[i]),
            float(phi[i]),
            float(rank_now[i]),
        )
        for i, n in enumerate(nodes)
    ]
    result = DrillResult(None, cands[0].stats, cands)
    best = max(cands, key=lambda c: (c.score, -depth(c.node)))
    if not best.node or best.score < settings.min_z:
        return result
    index = {c.key: i for i, c in enumerate(cands)}
    i = index[best.key]
    while True:
        rel = (exp[i] - app[i]) / exp[i] if exp[i] > 0 else 0.0
        step = None
        for par in parents(cands[i].node, seg):
            j = index.get(node_key(par))
            if j is None or j == 0:
                continue
            r_exp, r_app, r_var = exp[j] - exp[i], app[j] - app[i], var[j] - var[i]
            if r_exp <= 0 or r_var <= 0:
                continue
            r_score = (r_exp - r_app) / np.sqrt(r_var) / phi[j]
            rest_hit = r_score >= settings.rest_min_z and (r_exp - r_app) / r_exp >= (
                settings.rest_min_ratio * rel
            )
            if rest_hit and (step is None or cands[j].score > cands[step].score):
                step = j
        if step is None:
            break
        i = step
    result.culprit = cands[i].node
    return result
