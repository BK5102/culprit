"""Normal behavior: expected volume and the normal approval probability.

Volume (methodology M9): a smooth hour-of-day curve in each country's local
time, day-of-week factors, simulated holidays, and day-level noise, so the
series look like a city's traffic: busy at lunch and evening, quiet at night.

Approval (methodology M10): an additive model on the log-odds scale (country,
issuer, BIN, method, gateway and leaf effects), a small daily rhythm (lower
at night), and a slow day-to-day drift. Approvals are later drawn as a
binomial over attempts, so small segments are naturally noisier.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from culprit.sim.hierarchy import Hierarchy
from culprit.world import Timeline

HOUR_PROFILE_PEAKS = ((12.0, 3.5, 1.0), (19.5, 2.5, 0.8))  # (hour, width, height)
DAY_OF_WEEK = np.array([0.95, 0.95, 0.98, 1.0, 1.1, 1.12, 0.9])  # Monday first


def hour_profile() -> np.ndarray:
    h = np.arange(24, dtype=float)
    prof = 0.15 + sum(a * np.exp(-0.5 * ((h - c) / w) ** 2) for c, w, a in HOUR_PROFILE_PEAKS)
    return prof / prof.mean()


def local_hours(hier: Hierarchy, timeline: Timeline) -> np.ndarray:
    """(leaves, hours) local clock hour index since the start (world hour + timezone)."""
    tz = np.array([hier.tz_offset[c] for c in hier.countries])[hier.leaf_country]
    return np.arange(timeline.n_hours)[None, :] + tz[:, None]


def expected_volume(hier: Hierarchy, timeline: Timeline, cfg: dict[str, Any], rng) -> np.ndarray:
    """(leaves, hours) expected attempts per hour before surges."""
    n_days = timeline.n_hours // 24 + 2
    n_c = len(hier.countries)
    local = local_hours(hier, timeline)
    hod = hour_profile()[np.mod(local, 24)]
    day = np.floor_divide(local, 24) + 1  # +1 so a negative offset stays a valid index
    dow_start = timeline.start.weekday()
    dow = DAY_OF_WEEK / DAY_OF_WEEK.mean()
    dow_f = dow[np.mod(day - 1 + dow_start, 7)]

    holiday = np.ones((n_c, n_days))
    for h in cfg.get("holidays", []):
        countries = h.get("countries") or list(range(n_c))
        for c in countries:
            holiday[int(c), int(h["day"]) + 1] = float(h["factor"])
    day_noise = rng.lognormal(0.0, float(cfg["day_noise_sd"]), size=(n_c, n_days))
    leaf_day = rng.lognormal(
        0.0, float(cfg["leaf_day_noise_sd"]), size=(hier.segments.n_leaves, n_days)
    )
    c_idx = hier.leaf_country[:, None]
    day_f = holiday[c_idx, day] * day_noise[c_idx, day]
    leaf_f = np.take_along_axis(leaf_day, day, axis=1)
    mean = float(cfg["mean_attempts_per_hour"])
    return mean * hier.share[:, None] * hod * dow_f * day_f * leaf_f


def normal_logit(hier: Hierarchy, timeline: Timeline, cfg: dict[str, Any], rng) -> np.ndarray:
    """(leaves, hours) log-odds of approval under normal conditions."""
    seg = hier.segments
    n = seg.n_leaves

    def effect(dim: str, sd: float) -> np.ndarray:
        vals = seg.values[dim]
        draws = dict(zip(vals, rng.normal(0.0, sd, size=len(vals)), strict=True))
        return np.array([draws[v] for v in seg.cols[dim]])

    base = np.log(cfg["base_rate"] / (1 - cfg["base_rate"]))
    static = (
        base
        + effect("country", cfg["country_sd"])
        + effect("issuer", cfg["issuer_sd"])
        + effect("bin", cfg["bin_sd"])
        + effect("method", cfg["method_sd"])
        + effect("gateway", cfg["gateway_sd"])
        + rng.normal(0.0, cfg["leaf_sd"], size=n)
    )
    local = local_hours(hier, timeline)
    rhythm = cfg["hour_amplitude"] * np.cos(2 * np.pi * (np.mod(local, 24) - 15) / 24)

    n_days = timeline.n_hours // 24 + 1
    phi, sd = float(cfg["drift_phi"]), float(cfg["drift_sd"])
    drift = np.empty((n, n_days))
    drift[:, 0] = rng.normal(0.0, sd / np.sqrt(1 - phi**2), size=n)
    shocks = rng.normal(0.0, sd, size=(n, n_days))
    for d in range(1, n_days):
        drift[:, d] = phi * drift[:, d - 1] + shocks[:, d]
    day = np.arange(timeline.n_hours) // 24
    return static[:, None] + rhythm + drift[:, day]


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))
