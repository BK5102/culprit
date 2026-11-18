"""Legitimate surges: unusual but not faults. They are the false-alarm traps.

Two kinds (methodology M13):

- promotion: a flash sale in one country's card-not-present channel. Volume
  jumps and the approval rate dips a little, because a sale pulls in buyers
  whose cards are near their limit (more "insufficient funds"). A detector
  that alarms on it raised a false alarm.
- payday: a whole day in one country with more volume and a slightly higher
  approval rate (fewer "insufficient funds"). It shifts the mix of the total
  without any segment failing.

Surges can happen in every window, including the context period, because
they are part of normal life.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from culprit.segments import Segments, node_key
from culprit.world import Timeline


@dataclass
class Event:
    """One surge or fault: which segment, when, and what it does."""

    kind: str  # "surge" or "fault"
    type: str
    target: dict[str, str]
    start: int  # first affected hour
    end: int  # first hour after the event
    volume_factor: float = 1.0
    logit_shift: float = 0.0  # surges: change in approval log-odds
    severity: float = 0.0  # faults: share of approvals lost (p -> p * (1 - severity))
    latency_factor: float = 1.0
    signature: dict[str, float] = field(default_factory=dict)  # reason mix of the changed declines
    id: str = ""

    def to_dict(self, timeline: Timeline, segments: Segments) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "type": self.type,
            "target": dict(self.target),
            "target_key": node_key(self.target),
            "start_hour": self.start,
            "end_hour": self.end,
            "start_time": timeline.time(self.start).isoformat(),
            "end_time": timeline.time(self.end).isoformat(),
            "volume_factor": self.volume_factor,
            "logit_shift": self.logit_shift,
            "severity": self.severity,
            "latency_factor": self.latency_factor,
            "signature": dict(self.signature),
            "n_leaves": int(segments.mask(self.target).sum()),
        }


def schedule_surges(
    segments: Segments,
    timeline: Timeline,
    tz_offset: dict[str, int],
    cfg: dict[str, Any],
    rng,
) -> list[Event]:
    weeks = timeline.n_hours / 168
    countries = segments.values["country"]
    methods = segments.values["method"]
    online = "card_not_present" if "card_not_present" in methods else methods[0]
    events: list[Event] = []
    for _ in range(rng.poisson(float(cfg["promotions_per_week"]) * weeks)):
        c = countries[int(rng.integers(len(countries)))]
        dur = int(rng.integers(4, 13))
        start = int(rng.integers(0, timeline.n_hours - dur))
        events.append(
            Event(
                "surge",
                "promotion",
                {"country": c, "method": online},
                start,
                start + dur,
                volume_factor=float(rng.uniform(1.5, 3.0)),
                logit_shift=float(rng.uniform(-0.35, -0.10)),
                signature={"insufficient_funds": 1.0},
            )
        )
    n_days = timeline.n_hours // 24
    for _ in range(rng.poisson(float(cfg["paydays_per_week"]) * weeks)):
        c = countries[int(rng.integers(len(countries)))]
        # A local calendar day: world hour = local hour - offset.
        start = int(rng.integers(1, n_days - 1)) * 24 - tz_offset[c]
        start = max(0, min(start, timeline.n_hours - 24))
        events.append(
            Event(
                "surge",
                "payday",
                {"country": c},
                start,
                start + 24,
                volume_factor=float(rng.uniform(1.2, 1.5)),
                logit_shift=float(rng.uniform(0.05, 0.15)),
                signature={"insufficient_funds": 1.0},
            )
        )
    events.sort(key=lambda e: (e.start, e.type))
    for i, e in enumerate(events):
        e.id = f"S{i:03d}"
    return events
