"""Side signals: decline reasons and latency, consistent with surges and faults.

Decline reasons (methodology M11): every leaf has a normal reason mix. When a
surge or fault changes the approval probability from p_old to p_new, the
changed declines (p_old - p_new) go to that event's signature reasons. A rise
in approvals (payday) removes declines from the signature reason instead.

Latency (methodology M12): each gateway has a base response time, a little
slower at busy hours, multiplied by any fault's latency factor, with noise
that shrinks as more payments are averaged.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from culprit.sim.normal import hour_profile
from culprit.world import REASONS

BASE_MIX = np.array([0.42, 0.22, 0.18, 0.03, 0.05, 0.10])  # same order as REASONS


def normal_mix(n_leaves: int, concentration: float, rng) -> np.ndarray:
    """(leaves, reasons) normal share of each decline reason."""
    return rng.dirichlet(BASE_MIX * concentration, size=n_leaves)


def signature_vector(signature: dict[str, float]) -> np.ndarray:
    v = np.zeros(len(REASONS))
    for name, w in signature.items():
        v[REASONS.index(name)] = w
    return v / v.sum()


def draw_declines(declines: np.ndarray, mass: np.ndarray, rng) -> np.ndarray:
    """Split declines (leaves, hours) into reasons with weights mass (leaves, hours, reasons)."""
    mass = np.clip(mass, 0.0, None)
    out = np.zeros(mass.shape, dtype=np.int64)
    remaining = declines.astype(np.int64).copy()
    left = mass.sum(axis=-1)
    for r in range(len(REASONS) - 1):
        with np.errstate(invalid="ignore", divide="ignore"):
            q = np.where(left > 0, mass[..., r] / left, 0.0)
        x = rng.binomial(remaining, np.clip(q, 0.0, 1.0))
        out[..., r] = x
        remaining -= x
        left = left - mass[..., r]
    out[..., -1] = remaining
    return out


def draw_latency(
    attempts: np.ndarray,
    gateway_index: np.ndarray,
    local_hour: np.ndarray,
    latency_factor: np.ndarray,
    cfg: dict[str, Any],
    n_gateways: int,
    rng,
) -> np.ndarray:
    """(leaves, hours) mean latency in ms; NaN where there were no attempts."""
    lo, hi = cfg["latency_base_ms"]
    base = rng.uniform(lo, hi, size=n_gateways)[gateway_index]
    prof = hour_profile()
    load = 1.0 + float(cfg["latency_load"]) * prof[np.mod(local_hour, 24)] / prof.max()
    noise = rng.normal(0.0, 1.0, size=attempts.shape) * float(cfg["latency_noise"])
    noise = noise / np.sqrt(np.maximum(attempts, 1))
    lat = base[:, None] * load * latency_factor * np.exp(noise)
    return np.where(attempts > 0, lat, np.nan)
