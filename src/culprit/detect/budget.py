"""Equal alert budget: every detector gets the same false alarms per week (methodology M26, M27).

Alarm rule (`cleanroom.events.persistent_alarms`): a series alarms when its
score is strictly above the threshold for `persistence` consecutive hours; it
fires once, on the k-th hour, and again only after dropping back and
climbing for another k hours. Each monitored series is its own group, so a
run never crosses series.

Calibration (`cleanroom.events.threshold_for_alarm_rate`): on the
calibration window, which has surges but no faults, every alarm is false. The
threshold is the lowest one that keeps alarms across all series at or under
the target per week, for it and every higher candidate. `total_time` is the
calibration length in hours and the unit is 168 hours, so the rate means
"alarms across the whole monitored set per week of wall time".

Incidents: alarms within `gap` hours of each other are grouped into one
incident for investigation (one page to the on-call analyst). Grouping does
not change the budget, which counts series alarms.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from cleanroom.events import AlarmThreshold, persistent_alarms, threshold_for_alarm_rate

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


def calibrate(
    scores: np.ndarray, window: tuple[int, int], per_week: float, persistence: int
) -> AlarmThreshold:
    lo, hi = window
    values, hours, groups = _window(scores, lo, hi)
    return threshold_for_alarm_rate(
        values,
        hours,
        per_week,
        persistence_k=persistence,
        unit=HOURS_PER_WEEK,
        groups=groups,
        total_time=float(hi - lo),
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
