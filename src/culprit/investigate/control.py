"""The deterministic no-LLM control: investigate every incident with drill-down and rules.

For each incident from the configured detector, the control sees only data up
to and including the first alarm hour (`world.until(first_hour + 1)`). The
investigation window starts where the first alarm's run of exceedances began
(first hour minus persistence plus one), widened to at least `lookback_hours`
hours, so it covers the hours that looked wrong and few that did not. It then
drills down to a culprit segment, types the fault from decline reasons and
latency, and keeps a top-3 list. It never sees the answer key (CLAUDE.md
rules 1 and 5).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from culprit.detect.budget import Incident
from culprit.investigate.contribution import leaf_window, node_stats
from culprit.investigate.drilldown import DrillSettings, drill_down
from culprit.investigate.fault_typing import classify, signals
from culprit.world import ObservedWorld


@dataclass
class Attribution:
    incident_id: str
    as_of_hour: int
    window_start: int
    culprit: str | None
    top3: list[str]
    top3_scores: list[float]
    fault_type: str
    evidence: dict[str, float]
    investigator: str = "control"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def investigate_incident(
    world: ObservedWorld,
    incident: Incident,
    control_cfg: dict[str, Any],
    weeks: int = 4,
    persistence: int = 2,
) -> Attribution:
    as_of = incident.first_hour + 1
    seen = world.until(as_of)
    run_start = incident.first_hour - persistence + 1
    start = max(0, min(run_start, as_of - int(control_cfg["lookback_hours"])))
    lw = leaf_window(seen, start, as_of, weeks)
    drill = drill_down(seen, lw, DrillSettings.from_config(control_cfg), weeks)
    target = drill.culprit if drill.culprit is not None else {}
    sig = signals(seen, target, start, as_of, weeks)
    fault_type = classify(sig) if drill.culprit is not None else "no_fault"
    stats = node_stats(seen, lw, target)
    scores = {c.key: c.score for c in drill.candidates}
    top3 = drill.ranked(3)
    evidence = {
        "attempts": stats.attempts,
        "approved": stats.approved,
        "rate": stats.rate,
        "expected_rate": stats.expected_rate,
        "missing_approvals": stats.missing,
        "z": stats.z,
        "latency_ratio": sig.latency_ratio,
        **{f"rise_{r}": v for r, v in sig.reason_rise.items()},
    }
    return Attribution(
        incident.id,
        as_of,
        start,
        drill.culprit_key,
        top3,
        [round(float(scores[k]), 3) for k in top3],
        fault_type,
        evidence,
    )


def run_control(
    world: ObservedWorld, incidents: list[Incident], config: dict[str, Any]
) -> list[Attribution]:
    weeks = int(config["detect"]["baseline_weeks"])
    k = int(config["budget"]["persistence_hours"])
    return [investigate_incident(world, inc, config["control"], weeks, k) for inc in incidents]
