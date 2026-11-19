"""Equal alert budget: every detector gets the same false alarms per week (methodology M26, M27).

Alarm rule (`cleanroom.events.persistent_alarms`): a series alarms when its
score is strictly above the threshold for `persistence` consecutive hours; it
fires once, on the k-th hour, and again only after dropping back and
climbing for another k hours. Each monitored series is its own group, so a
run never crosses series.

Calibration: on the calibration window, which has surges but no faults,
every alarm is false. The threshold is the lowest one that keeps the counted
false alarms at or under the target per week, for it and every higher
candidate. The rate is "per week of wall time for the whole monitored set",
not per series. What is counted is a config choice (`budget.mode`,
methodology M27 and M42), which the owner settles before the lock:

- `per_series` (the default): every series alarm counts once
  (`cleanroom.events.threshold_for_alarm_rate`). One promotion that fires
  three related series uses three of the allowance.
- `per_incident`: alarms are first grouped into incidents with the same rule
  used for investigation (chained while each alarm is within `gap` hours of
  the incident's latest alarm), and each incident counts once. One promotion
  that fires three series at about the same time counts once, like one page
  to the on-call analyst.

Incidents: alarms within `gap` hours of each other are grouped into one
incident for investigation in both modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from cleanroom.events import persistent_alarms, threshold_for_alarm_rate

HOURS_PER_WEEK = 168


def _window(scores: np.ndarray, lo: int, hi: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Flatten scores[:, lo:hi] series by series: (values, hours, groups)."""
    block = scores[:, lo:hi]
    n, t = block.shape
    values = np.ascontiguousarray(block).ravel()
    hours = np.tile(np.arange(lo, hi, dtype=float), n)
    groups = np.repeat(np.arange(n), t)
    if not np.isfinite(values).all():
        raise ValueError(f"scores must be finite on hours {lo} to {hi}")
    return values, hours, groups


BUDGET_MODES = ("per_series", "per_incident")


@dataclass(frozen=True)
class BudgetThreshold:
    """A calibrated threshold and what it raises on the calibration window.

    `budget_rate` is the counted unit per week (series alarms or incidents,
    depending on `mode`) and is what must stay at or under the target. Both
    counts are kept so the two modes can be compared.
    """

    threshold: float
    mode: str
    n_alarms: int  # series alarms on the calibration window
    n_incidents: int  # incidents (alarms grouped with `gap_hours`) on the calibration window
    alarm_rate: float  # series alarms per week
    incident_rate: float  # incidents per week
    budget_rate: float  # the counted rate: alarm_rate or incident_rate
    gap_hours: int
    total_time: float
    unit: float
    persistence_k: int

    def to_dict(self) -> dict[str, Any]:
        return self.__dict__.copy()


def _potential_alarms(
    values: np.ndarray, hours: np.ndarray, groups: np.ndarray, k: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Every alarm any threshold could raise: (lo, hi, hour).

    Under the persistence rule, the run of k exceedances that ends at window j
    fires for thresholds in [m[j-1], m[j]), where m is the rolling minimum of
    k scores (the same reasoning as `cleanroom.events.threshold_for_alarm_rate`).
    Rows of one group must be contiguous and in time order, as `_window` makes them.
    """
    los, his, ts = [], [], []
    _, starts = np.unique(groups, return_index=True)
    for rows in np.split(np.arange(len(groups)), np.sort(starts)[1:]):
        if len(rows) < k:
            continue
        m = np.lib.stride_tricks.sliding_window_view(values[rows], k).min(axis=1)
        lo = np.r_[-np.inf, m[:-1]]
        live = lo < m
        los.append(lo[live])
        his.append(m[live])
        ts.append(hours[rows][k - 1 :][live])
    if not los:
        return np.empty(0), np.empty(0), np.empty(0)
    return np.concatenate(los), np.concatenate(his), np.concatenate(ts)


def _n_groups(times: np.ndarray, gap: float) -> int:
    """Incidents among alarm times: a new one starts after a gap of more than `gap` hours."""
    if times.size == 0:
        return 0
    t = np.sort(times)
    return 1 + int((np.diff(t) > gap).sum())


def threshold_for_incident_rate(
    values: np.ndarray,
    hours: np.ndarray,
    groups: np.ndarray,
    target_per_unit: float,
    persistence_k: int,
    gap: float,
    total_time: float,
    unit: float = HOURS_PER_WEEK,
) -> float:
    """The lowest threshold whose incident count stays at or under the target for it and above.

    The candidates are the calibration scores, as in the Cleanroom function.
    The count is not monotone in the threshold (raising it can split one run
    or one incident into two), so the walk goes down from the highest
    candidate and stops at the first one that breaks the target. With `gap`
    below zero every alarm is its own incident, which reproduces
    `cleanroom.events.threshold_for_alarm_rate` (tested).
    """
    lo, hi, t = _potential_alarms(values, hours, groups, persistence_k)
    candidates = np.unique(values)[::-1]  # highest first
    act = np.argsort(-hi, kind="stable")  # active once the candidate is below hi
    deact = np.argsort(-lo, kind="stable")  # inactive once the candidate is below lo
    active: set[int] = set()  # small until the target breaks, so recounting it is cheap
    ia = idd = 0
    pick = 0  # index of the lowest candidate so far that met the target
    for ci, c in enumerate(candidates):
        changed = False
        while ia < len(act) and hi[act[ia]] > c:
            active.add(int(act[ia]))
            ia += 1
            changed = True
        while idd < len(deact) and lo[deact[idd]] > c:
            active.discard(int(deact[idd]))
            idd += 1
            changed = True
        if changed:
            times = t[np.fromiter(active, dtype=np.int64, count=len(active))]
            if _n_groups(times, gap) / total_time * unit > target_per_unit:
                break
        pick = ci
    return float(candidates[pick])


def calibrate(
    scores: np.ndarray,
    window: tuple[int, int],
    per_week: float,
    persistence: int,
    mode: str = "per_series",
    gap: int = 6,
) -> BudgetThreshold:
    """Set one detector's threshold on the calibration window under the chosen counting mode."""
    if mode not in BUDGET_MODES:
        raise ValueError(f"budget.mode must be one of {BUDGET_MODES}, got {mode!r}")
    if gap < 0:
        raise ValueError("the incident gap must not be negative")
    lo, hi = window
    values, hours, groups = _window(scores, lo, hi)
    total = float(hi - lo)
    if mode == "per_series":
        thr = threshold_for_alarm_rate(
            values,
            hours,
            per_week,
            persistence_k=persistence,
            unit=HOURS_PER_WEEK,
            groups=groups,
            total_time=total,
        ).threshold
    else:
        thr = threshold_for_incident_rate(values, hours, groups, per_week, persistence, gap, total)
    found = alarms(scores, thr, persistence, window, lo)
    n_inc = len(group_incidents(found, gap))
    a_rate = len(found) / total * HOURS_PER_WEEK
    i_rate = n_inc / total * HOURS_PER_WEEK
    return BudgetThreshold(
        threshold=thr,
        mode=mode,
        n_alarms=len(found),
        n_incidents=n_inc,
        alarm_rate=a_rate,
        incident_rate=i_rate,
        budget_rate=a_rate if mode == "per_series" else i_rate,
        gap_hours=int(gap),
        total_time=total,
        unit=float(HOURS_PER_WEEK),
        persistence_k=int(persistence),
    )


@dataclass(frozen=True)
class Alarm:
    series: int  # row of the score array (a monitored node)
    hour: int  # the hour the alarm fires (k-th consecutive exceedance)
    score: float


def alarms(
    scores: np.ndarray, threshold: float, persistence: int, window: tuple[int, int], from_hour: int
) -> list[Alarm]:
    """Alarms that fire at hours >= `from_hour`, applying the rule over the whole `window`.

    Runs are tracked from the window start, so a run that began earlier is
    not counted again when it continues past `from_hour`.
    """
    lo, hi = window
    values, hours, groups = _window(scores, lo, hi)
    pos = persistent_alarms(values, threshold, persistence, groups=groups)
    out = [
        Alarm(int(groups[p]), int(hours[p]), float(values[p])) for p in pos if hours[p] >= from_hour
    ]
    return sorted(out, key=lambda a: (a.hour, a.series))


@dataclass
class Incident:
    id: str
    first_hour: int
    last_hour: int
    alarms: list[Alarm]

    def to_dict(self, keys: list[str]) -> dict[str, Any]:
        return {
            "id": self.id,
            "first_hour": self.first_hour,
            "last_hour": self.last_hour,
            "alarms": [
                {"node": keys[a.series], "hour": a.hour, "score": a.score} for a in self.alarms
            ],
        }


def group_incidents(found: list[Alarm], gap: int, prefix: str = "I") -> list[Incident]:
    """Chain alarms whose hours are within `gap` of the incident's latest alarm."""
    incidents: list[Incident] = []
    for a in sorted(found, key=lambda x: (x.hour, x.series)):
        if incidents and a.hour - incidents[-1].last_hour <= gap:
            incidents[-1].alarms.append(a)
            incidents[-1].last_hour = a.hour
        else:
            incidents.append(Incident(f"{prefix}{len(incidents):03d}", a.hour, a.hour, [a]))
    return incidents
