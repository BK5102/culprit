"""Fault injection: four fault types from PLAN.md FR4 (methodology M14 to M16).

Each fault removes a share of approvals (its severity) from every leaf under
its target segment for a stretch of hours, sends the lost approvals to a
signature mix of decline reasons, and may slow responses down.

- issuer_outage: one issuer; severity 0.25 to 0.70; 2 to 8 hours; declines go to
  issuer_unavailable and processing_error; latency x1.2 to 1.6.
- bin_decline_spike: one BIN range; severity 0.15 to 0.50; 4 to 24 hours;
  do_not_honor and suspected_fraud; latency unchanged.
- gateway_degradation: one gateway; severity 0.05 to 0.25; 1 to 6 hours;
  processing_error and issuer_unavailable; latency x2 to 4.
- extra_verification: one issuer's card-not-present payments; severity 0.10 to
  0.30; 12 to 48 hours; authentication_required and do_not_honor; latency x1.1
  to 1.3.

Faults are injected only in the evaluation window, so the context and
calibration periods contain normal behavior only (CLAUDE.md rule 3).
`extra_verification` is the held-out type: development worlds leave it out.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from culprit.segments import Segments
from culprit.sim.surges import Event
from culprit.world import Timeline


@dataclass(frozen=True)
class FaultType:
    name: str
    level: str  # which dimension the target sits on
    severity: tuple[float, float]
    hours: tuple[int, int]  # inclusive range
    latency: tuple[float, float]
    signature: dict[str, float]


FAULT_TYPES: dict[str, FaultType] = {
    "issuer_outage": FaultType(
        "issuer_outage",
        "issuer",
        (0.25, 0.70),
        (2, 8),
        (1.2, 1.6),
        {"issuer_unavailable": 0.85, "processing_error": 0.15},
    ),
    "bin_decline_spike": FaultType(
        "bin_decline_spike",
        "bin",
        (0.15, 0.50),
        (4, 24),
        (1.0, 1.0),
        {"do_not_honor": 0.8, "suspected_fraud": 0.2},
    ),
    "gateway_degradation": FaultType(
        "gateway_degradation",
        "gateway",
        (0.05, 0.25),
        (1, 6),
        (2.0, 4.0),
        {"processing_error": 0.9, "issuer_unavailable": 0.1},
    ),
    "extra_verification": FaultType(
        "extra_verification",
        "issuer_method",
        (0.10, 0.30),
        (12, 48),
        (1.1, 1.3),
        {"authentication_required": 0.9, "do_not_honor": 0.1},
    ),
}


def pick_target(ft: FaultType, segments: Segments, rng) -> dict[str, str]:
    def one(dim: str) -> str:
        vals = segments.values[dim]
        return vals[int(rng.integers(len(vals)))]

    if ft.level == "issuer_method":
        methods = segments.values["method"]
        online = "card_not_present" if "card_not_present" in methods else methods[0]
        return {"issuer": one("issuer"), "method": online}
    return {ft.level: one(ft.level)}


def schedule_faults(
    segments: Segments, timeline: Timeline, cfg: dict[str, Any], rng
) -> list[Event]:
    types = list(cfg["types"])
    unknown = set(types) - set(FAULT_TYPES)
    if unknown:
        raise ValueError(f"unknown fault types {sorted(unknown)}")
    lo, hi = timeline.window_hours("evaluation")
    weeks = (hi - lo) / 168
    events: list[Event] = []
    n = rng.poisson(float(cfg["per_week"]) * weeks) if types else 0
    for _ in range(n):
        ft = FAULT_TYPES[types[int(rng.integers(len(types)))]]
        dur = int(rng.integers(ft.hours[0], ft.hours[1] + 1))
        start = int(rng.integers(lo, hi - dur + 1))
        events.append(
            Event(
                "fault",
                ft.name,
                pick_target(ft, segments, rng),
                start,
                start + dur,
                severity=float(rng.uniform(*ft.severity)),
                latency_factor=float(rng.uniform(*ft.latency)),
                signature=dict(ft.signature),
            )
        )
    events.sort(key=lambda e: (e.start, e.type))
    for i, e in enumerate(events):
        e.id = f"F{i:03d}"
    return events
