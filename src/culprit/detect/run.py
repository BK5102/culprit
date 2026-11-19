"""Run every configured detector on one observed world at an equal false-alarm budget.

Reads only the observed world. Scores the calibration and evaluation windows,
sets each detector's threshold on calibration (no faults there), then lists
the alarms and incidents in evaluation. Nothing here knows where the faults
are; grading happens later in `culprit.evaluate.grade`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from culprit.detect.base import Detector
from culprit.detect.binomial import BinomialCusum
from culprit.detect.budget import (
    Alarm,
    BudgetThreshold,
    Incident,
    alarms,
    calibrate,
    group_incidents,
)
from culprit.detect.classical import MSTLDetector
from culprit.detect.seasonal_naive import SeasonalNaive
from culprit.detect.tsfm import QuantileForecaster, TSFMDetector, make_forecaster
from culprit.panel import NodePanel, node_panel
from culprit.world import ObservedWorld


@dataclass
class DetectionResult:
    name: str
    version: str
    scores: np.ndarray
    threshold: BudgetThreshold
    alarms: list[Alarm]
    incidents: list[Incident]
    seconds: float
    extra: dict[str, Any] = field(default_factory=dict)

    def summary(self, keys: list[str]) -> dict[str, Any]:
        return {
            "detector": self.name,
            "version": self.version,
            "threshold": self.threshold.to_dict(),
            "evaluation_alarms": len(self.alarms),
            "evaluation_incidents": len(self.incidents),
            "seconds": round(self.seconds, 3),
            **self.extra,
        }


def build_detectors(
    config: dict[str, Any], forecaster: QuantileForecaster | None = None
) -> tuple[list[Detector], list[str]]:
    d = config["detect"]
    built: list[Detector] = []
    skipped: list[str] = []
    for name in d["detectors"]:
        if name == "A":
            built.append(SeasonalNaive(scale_window=d["scale_window_hours"]))
        elif name == "A2":
            built.append(
                BinomialCusum(
                    weeks=d["baseline_weeks"],
                    k=d["cusum_k"],
                    scale_window=d["scale_window_hours"],
                    mode=d["a2_mode"],
                )
            )
        elif name == "B":
            built.append(MSTLDetector(alpha=d["b_level_alpha"]))
        elif name == "TSFM":
            t = d["tsfm"]
            fc = forecaster or make_forecaster(t["adapter"])
            if fc is None:
                skipped.append("TSFM (no adapter configured; see configs and methodology M25)")
                continue
            built.append(
                TSFMDetector(
                    fc,
                    context_hours=t["context_hours"],
                    horizon=t["horizon_hours"],
                    quantiles=t["quantiles"],
                    cache_dir=t.get("cache_dir"),
                )
            )
        else:
            raise ValueError(f"unknown detector {name!r}")
    return built, skipped


def detector_version(det: Detector) -> str:
    if isinstance(det, TSFMDetector):
        return det.forecaster.version
    return f"culprit-{det.name}"


def run_detection(
    world: ObservedWorld,
    config: dict[str, Any],
    forecaster: QuantileForecaster | None = None,
    panel: NodePanel | None = None,
) -> tuple[NodePanel, dict[str, DetectionResult], list[str]]:
    tl = world.timeline
    b = config["budget"]
    panel = panel or node_panel(world)
    start = tl.context_end
    end = world.n_hours_seen
    detectors, skipped = build_detectors(config, forecaster)
    results: dict[str, DetectionResult] = {}
    for det in detectors:
        t0 = time.perf_counter()
        s = det.score(panel.attempts, panel.approved, start)
        thr = calibrate(
            s,
            (tl.context_end, tl.calibration_end),
            b["false_alarms_per_week"],
            b["persistence_hours"],
            mode=b["mode"],
            gap=b["group_gap_hours"],
        )
        found = alarms(s, thr.threshold, b["persistence_hours"], (start, end), tl.calibration_end)
        incidents = group_incidents(found, b["group_gap_hours"], prefix=f"{det.name}-")
        results[det.name] = DetectionResult(
            det.name, detector_version(det), s, thr, found, incidents, time.perf_counter() - t0
        )
    return panel, results, skipped
