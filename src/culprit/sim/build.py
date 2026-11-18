"""Build a simulated world from a config and a seed, and write it in two parts.

`simulate` returns everything in memory, including the truth (normal and
faulty approval probabilities, expected volume) that only the simulator and
the data-fit check see. `write_world` writes:

- `observed/`: the panel of counts and the public leaf table. This is all a
  detector, the control or the agent may read (`culprit.world.load_observed`).
- `sealed/answer_key.json`: every fault and surge with its true segment and
  hours. Only `culprit.evaluate.grade` reads it (CLAUDE.md rule 1).

Randomness comes from one seed split into independent streams, one per
component, so the same seed always gives the same world (methodology M19).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from culprit.config import config_hash, world_hash
from culprit.segments import Segments
from culprit.sim.faults import schedule_faults
from culprit.sim.hierarchy import Hierarchy, build_hierarchy
from culprit.sim.normal import expected_volume, local_hours, normal_logit, sigmoid
from culprit.sim.signals import draw_declines, draw_latency, normal_mix, signature_vector
from culprit.sim.surges import Event, schedule_surges
from culprit.world import REASONS, ObservedWorld, Timeline, dataset_hash, write_observed

SEALED_DIR = "sealed"
ANSWER_KEY_FILE = "answer_key.json"
STREAMS = (
    "hierarchy",
    "volume",
    "approval",
    "surges",
    "faults",
    "attempts",
    "approvals",
    "signals",
)


@dataclass
class SimResult:
    observed: ObservedWorld
    hierarchy: Hierarchy
    surges: list[Event]
    faults: list[Event]
    expected_volume: np.ndarray  # (leaves, hours) after surges
    p_normal: np.ndarray  # (leaves, hours) after surges, before faults: the honest "normal"
    p_actual: np.ndarray  # (leaves, hours) after faults
    answer_key: dict[str, Any]


def _rngs(seed: int) -> dict[str, np.random.Generator]:
    children = np.random.SeedSequence(int(seed)).spawn(len(STREAMS))
    return {name: np.random.default_rng(s) for name, s in zip(STREAMS, children, strict=True)}


def _cells(segments: Segments, e: Event) -> tuple[np.ndarray, slice]:
    return np.flatnonzero(segments.mask(e.target)), slice(e.start, e.end)


def simulate(config: dict[str, Any]) -> SimResult:
    w = config["world"]
    rng = _rngs(config["seed"])
    timeline = Timeline.from_weeks(w["start"], w["weeks"])
    hier = build_hierarchy(w["hierarchy"], w["volume"], rng["hierarchy"])
    seg = hier.segments
    n, t = seg.n_leaves, timeline.n_hours

    lam = expected_volume(hier, timeline, w["volume"], rng["volume"])
    logit = normal_logit(hier, timeline, w["approval"], rng["approval"])
    mix = normal_mix(n, float(w["signals"]["reason_concentration"]), rng["signals"])

    surges = schedule_surges(seg, timeline, hier.tz_offset, w["surges"], rng["surges"])
    faults = schedule_faults(seg, timeline, w["faults"], rng["faults"])

    p = sigmoid(logit)
    mass = (1.0 - p)[..., None] * mix[:, None, :]  # decline probability by reason
    lat_factor = np.ones((n, t))

    for e in surges:
        rows, hours = _cells(seg, e)
        block = np.ix_(rows, np.arange(t)[hours])
        lam[block] *= e.volume_factor
        p_old = p[block]
        p_new = sigmoid(np.log(p_old / (1 - p_old)) + e.logit_shift)
        mass[block] += (p_old - p_new)[..., None] * signature_vector(e.signature)
        p[block] = p_new
    p_normal = p.copy()
    for e in faults:
        rows, hours = _cells(seg, e)
        block = np.ix_(rows, np.arange(t)[hours])
        p_old = p[block]
        p_new = p_old * (1.0 - e.severity)
        mass[block] += (p_old - p_new)[..., None] * signature_vector(e.signature)
        p[block] = p_new
        lat_factor[block] *= e.latency_factor

    attempts = rng["attempts"].poisson(lam).astype(np.int64)
    approved = rng["approvals"].binomial(attempts, p).astype(np.int64)
    declines = draw_declines(attempts - approved, mass, rng["signals"])
    gw_index = np.array([seg.values["gateway"].index(g) for g in seg.cols["gateway"]])
    latency = draw_latency(
        attempts,
        gw_index,
        local_hours(hier, timeline),
        lat_factor,
        w["signals"],
        len(seg.values["gateway"]),
        rng["signals"],
    )

    key = {
        "world": f"{config['name']}-seed{config['seed']}",
        "seed": config["seed"],
        "world_hash": world_hash(config),
        "config_hash": config_hash(config),
        "holdout_fault_types": list(w["holdout_fault_types"]),
        "faults": [e.to_dict(timeline, seg) for e in faults],
        "surges": [e.to_dict(timeline, seg) for e in surges],
    }
    meta = {
        "world": key["world"],
        "seed": config["seed"],
        "world_hash": key["world_hash"],
        "reasons": list(REASONS),
        "dataset_hash": dataset_hash(attempts, approved, declines, latency),
        "answer_key_sha256": _key_digest(key),
        "note": "Simulated data. No real payments.",
    }
    observed = ObservedWorld(seg, timeline, attempts, approved, declines, latency, meta)
    return SimResult(observed, hier, surges, faults, lam, p_normal, p, key)


def _key_digest(key: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()


def write_world(result: SimResult, out_dir: str | Path) -> Path:
    """Write observed/ and sealed/ under `out_dir`. Returns `out_dir`."""
    out = Path(out_dir)
    write_observed(result.observed, out)
    sealed = out / SEALED_DIR
    sealed.mkdir(parents=True, exist_ok=True)
    (sealed / ANSWER_KEY_FILE).write_text(
        json.dumps(result.answer_key, indent=2, sort_keys=True), encoding="utf-8"
    )
    return out
