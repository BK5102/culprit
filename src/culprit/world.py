"""The observed world: what a payments team could see, and nothing else.

`ObservedWorld` holds counts per leaf segment and hour (attempts, approvals,
declines by reason, mean latency), the public leaf table and the timeline.
It has no fault or surge information. Detectors, the deterministic control
and the agent tools read only this (methodology M18).

The timeline is split with `cleanroom.split`: train = context (normal
behavior only), valid = calibration (no faults; thresholds are set here),
test = evaluation (faults appear).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from cleanroom.split import Split, Window

from culprit.segments import Segments

REASONS = (
    "insufficient_funds",
    "do_not_honor",
    "suspected_fraud",
    "issuer_unavailable",
    "processing_error",
    "authentication_required",
)
OBSERVED_DIR = "observed"
PANEL_FILE = "panel.parquet"
META_FILE = "world.json"


@dataclass(frozen=True)
class Timeline:
    start: datetime
    n_hours: int
    context_end: int  # first calibration hour
    calibration_end: int  # first evaluation hour

    @classmethod
    def from_weeks(cls, start: str | datetime, weeks: dict[str, int]) -> Timeline:
        s = datetime.fromisoformat(start) if isinstance(start, str) else start
        c, k, e = (int(weeks[x]) * 168 for x in ("context", "calibration", "evaluation"))
        return cls(s, c + k + e, c, c + k)

    def time(self, hour: int) -> datetime:
        return self.start + timedelta(hours=int(hour))

    def times(self) -> list[datetime]:
        return [self.time(h) for h in range(self.n_hours)]

    def split(self) -> Split:
        """The Cleanroom split: context (train), calibration (valid), evaluation (test)."""
        return Split(
            train=Window(None, self.time(self.context_end)),
            valid=Window(self.time(self.context_end), self.time(self.calibration_end)),
            test=Window(self.time(self.calibration_end), self.time(self.n_hours)),
        )

    def window_hours(self, name: str) -> tuple[int, int]:
        """Hour bounds [lo, hi) of a window, read from the Cleanroom split (CLAUDE.md rule 4)."""
        part = {"context": "train", "calibration": "valid", "evaluation": "test"}[name]
        w = dict(self.split().windows())[part]
        lo = 0 if w.start is None else int((w.start - self.start) / timedelta(hours=1))
        return lo, int((w.end - self.start) / timedelta(hours=1))

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "n_hours": self.n_hours,
            "context_end": self.context_end,
            "calibration_end": self.calibration_end,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Timeline:
        return cls(
            datetime.fromisoformat(d["start"]),
            int(d["n_hours"]),
            int(d["context_end"]),
            int(d["calibration_end"]),
        )


@dataclass
class ObservedWorld:
    segments: Segments
    timeline: Timeline
    attempts: np.ndarray  # (leaves, hours) int64
    approved: np.ndarray  # (leaves, hours) int64
    declines: np.ndarray  # (leaves, hours, reasons) int64
    latency_ms: np.ndarray  # (leaves, hours) float64, NaN where attempts == 0
    meta: dict[str, Any]

    @property
    def reasons(self) -> tuple[str, ...]:
        return REASONS

    def latency_sum(self) -> np.ndarray:
        return np.where(self.attempts > 0, np.nan_to_num(self.latency_ms) * self.attempts, 0.0)

    def until(self, hour: int) -> ObservedWorld:
        """A copy holding only hours < `hour`: what was knowable at that time."""
        return ObservedWorld(
            self.segments,
            self.timeline,
            self.attempts[:, :hour],
            self.approved[:, :hour],
            self.declines[:, :hour],
            self.latency_ms[:, :hour],
            self.meta,
        )

    @property
    def n_hours_seen(self) -> int:
        return self.attempts.shape[1]


def dataset_hash(
    attempts: np.ndarray, approved: np.ndarray, declines: np.ndarray, latency_ms: np.ndarray
) -> str:
    """sha256 over the observed arrays in a fixed order and dtype."""
    h = hashlib.sha256()
    for arr, dtype in ((attempts, "<i8"), (approved, "<i8"), (declines, "<i8")):
        h.update(np.ascontiguousarray(arr, dtype=dtype).tobytes())
    lat = np.round(np.nan_to_num(latency_ms, nan=-1.0), 6)
    h.update(np.ascontiguousarray(lat, dtype="<f8").tobytes())
    return h.hexdigest()


def panel_frame(world: ObservedWorld) -> pl.DataFrame:
    """Long table: one row per leaf and hour."""
    n_leaves, n_hours = world.attempts.shape
    leaf = np.repeat(np.arange(n_leaves), n_hours)
    hour = np.tile(np.arange(n_hours), n_leaves)
    times = np.array(world.timeline.times(), dtype="datetime64[us]")
    cols: dict[str, Any] = {
        "leaf": leaf.astype(np.int32),
        "hour": hour.astype(np.int32),
        "time": np.tile(times, n_leaves),
        "attempts": world.attempts.ravel(),
        "approved": world.approved.ravel(),
    }
    for r, name in enumerate(REASONS):
        cols[f"decl_{name}"] = world.declines[:, :, r].ravel()
    cols["latency_ms"] = world.latency_ms.ravel()
    return pl.DataFrame(cols)


def write_observed(world: ObservedWorld, out_dir: str | Path) -> Path:
    d = Path(out_dir) / OBSERVED_DIR
    d.mkdir(parents=True, exist_ok=True)
    panel_frame(world).write_parquet(d / PANEL_FILE)
    leaves = {k: world.segments.cols[k].tolist() for k in world.segments.cols}
    meta = {**world.meta, "timeline": world.timeline.to_dict(), "leaves": leaves}
    (d / META_FILE).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return d


def load_observed(world_dir: str | Path) -> ObservedWorld:
    """Read only the observed folder of a world. Never reads anything else."""
    d = Path(world_dir) / OBSERVED_DIR
    meta = json.loads((d / META_FILE).read_text(encoding="utf-8"))
    segments = Segments(meta.pop("leaves"))
    timeline = Timeline.from_dict(meta.pop("timeline"))
    df = pl.read_parquet(d / PANEL_FILE).sort(["leaf", "hour"])
    shape = (segments.n_leaves, timeline.n_hours)
    attempts = df["attempts"].to_numpy().reshape(shape).astype(np.int64)
    approved = df["approved"].to_numpy().reshape(shape).astype(np.int64)
    declines = np.stack(
        [df[f"decl_{r}"].to_numpy().reshape(shape) for r in REASONS], axis=-1
    ).astype(np.int64)
    latency = df["latency_ms"].to_numpy().reshape(shape).astype(np.float64)
    world = ObservedWorld(segments, timeline, attempts, approved, declines, latency, meta)
    if (
        meta.get("dataset_hash")
        and dataset_hash(attempts, approved, declines, latency) != meta["dataset_hash"]
    ):
        raise ValueError(f"dataset hash mismatch in {d}; the panel file was changed")
    return world
