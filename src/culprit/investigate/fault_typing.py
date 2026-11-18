"""Rule-based fault typing from decline reasons and latency (methodology M32).

For the culprit segment, compare the investigation window with the same hours
of the previous 4 weeks:

- each decline reason's rate per attempt, now minus then; the reason with the
  largest rise is the dominant new decline reason,
- mean latency now over mean latency then.

Rules, first match wins:

1. dominant reason issuer_unavailable -> issuer_outage
2. dominant reason processing_error, or latency ratio >= 1.8 -> gateway_degradation
3. dominant reason do_not_honor or suspected_fraud -> bin_decline_spike
4. dominant reason authentication_required -> extra_verification
5. dominant reason insufficient_funds -> no_fault (customers short of funds,
   as in a promotion, is not a system fault)
6. otherwise -> unknown

The mapping is what a payments analyst would write from the meaning of each
reason. It matches the simulator's signature table, so on this world fault
typing is easier than on real data (limitations register). Rule 4 covers the
held-out type from that description; its threshold was not tuned on any world
that contains the type.
"""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np

from culprit.world import REASONS, ObservedWorld

RULES = {
    "issuer_unavailable": "issuer_outage",
    "processing_error": "gateway_degradation",
    "do_not_honor": "bin_decline_spike",
    "suspected_fraud": "bin_decline_spike",
    "authentication_required": "extra_verification",
    "insufficient_funds": "no_fault",
}
FAULT_LABELS = (
    "issuer_outage",
    "bin_decline_spike",
    "gateway_degradation",
    "extra_verification",
    "no_fault",
    "unknown",
)
LATENCY_RATIO_GATEWAY = 1.8
MIN_REASON_RISE = 0.002  # 0.2 percentage points of attempts


@dataclass(frozen=True)
class SignalSummary:
    reason_rate_now: dict[str, float]
    reason_rate_before: dict[str, float]
    latency_now: float
    latency_before: float

    @property
    def reason_rise(self) -> dict[str, float]:
        return {r: self.reason_rate_now[r] - self.reason_rate_before[r] for r in REASONS}

    @property
    def latency_ratio(self) -> float:
        if not self.latency_before or not np.isfinite(self.latency_before):
            return float("nan")
        return self.latency_now / self.latency_before

    @property
    def dominant_reason(self) -> str | None:
        rise = self.reason_rise
        r = max(rise, key=lambda k: rise[k])
        return r if rise[r] >= MIN_REASON_RISE else None


def signals(
    world: ObservedWorld, f: Mapping[str, str], start: int, end: int, weeks: int = 4
) -> SignalSummary:
    m = world.segments.mask(f)
    start = max(0, start)
    hours = np.arange(start, end)
    past = np.concatenate([hours - 168 * w for w in range(1, weeks + 1)])
    past = past[past >= 0]
    att = world.attempts[m]
    dec = world.declines[m]
    lat_sum = world.latency_sum()[m]

    def rates(h: np.ndarray) -> tuple[dict[str, float], float]:
        a = att[:, h].sum()
        d = dec[:, h].sum(axis=(0, 1))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            lat = lat_sum[:, h].sum() / a if a else float("nan")
        return {r: float(d[i] / a) if a else 0.0 for i, r in enumerate(REASONS)}, float(lat)

    now, lat_now = rates(hours)
    before, lat_before = rates(past) if len(past) else ({r: 0.0 for r in REASONS}, float("nan"))
    return SignalSummary(now, before, lat_now, lat_before)


def classify(s: SignalSummary) -> str:
    dominant = s.dominant_reason
    if dominant == "issuer_unavailable":
        return "issuer_outage"
    if dominant == "processing_error" or (
        np.isfinite(s.latency_ratio) and s.latency_ratio >= LATENCY_RATIO_GATEWAY
    ):
        return "gateway_degradation"
    if dominant is None:
        return "unknown"
    return RULES.get(dominant, "unknown")
