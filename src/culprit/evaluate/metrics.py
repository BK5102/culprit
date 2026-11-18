"""Scores, given the truth as plain inputs (methodology M39). This module reads no files.

Detection: an alarm on series s at hour a matches fault f when s's segment
shares a leaf with f's target and f.start <= a <= f.last_hour + tolerance
(`cleanroom.events.match_alarms`). Detection delay is the first matching
alarm's hour minus the fault's start. Alarms matching no fault are false
alarms; those that touch a legitimate surge are counted as surge traps.

Attribution: each fault's investigated incident is the earliest incident with
an alarm matching it. Top-1 is right when the culprit equals the fault's
target segment exactly; top-3 when the target is in the top-3 list; fault
type when the typed cause equals the fault type. Surge incidents (no fault,
but touching a surge) are "blamed" when the investigator names a culprit and
a cause other than no_fault.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from cleanroom.events import caught_within, false_alarms_per_unit, match_alarms

from culprit.segments import Segments, parse_key


def _touches(seg: Segments, node_key: str, target: dict[str, str]) -> bool:
    return bool((seg.mask(parse_key(node_key)) & seg.mask(target)).any())


def detection_metrics(
    alarms: list[dict[str, Any]],
    faults: list[dict[str, Any]],
    surges: list[dict[str, Any]],
    seg: Segments,
    eval_hours: int,
    tolerance: float,
    horizons: tuple[int, ...] = (2, 6, 24),
) -> dict[str, Any]:
    """`alarms`: [{"node": key, "hour": int}] in the evaluation window."""
    per_fault = []
    for f in faults:
        hours = [a["hour"] for a in alarms if _touches(seg, a["node"], f["target"])]
        m = match_alarms(hours, [(f["start_hour"], f["end_hour"] - 1)], tolerance)
        per_fault.append(
            {
                "id": f["id"],
                "type": f["type"],
                "detected": bool(m.detected[0]),
                "delay": float(m.delay[0]),
            }
        )
    by_node: dict[str, list[int]] = defaultdict(list)
    for i, a in enumerate(alarms):
        by_node[a["node"]].append(i)
    matched = np.zeros(len(alarms), dtype=bool)
    for node, idx in by_node.items():
        iv = [
            (f["start_hour"], f["end_hour"] - 1) for f in faults if _touches(seg, node, f["target"])
        ]
        if iv:
            m = match_alarms([alarms[i]["hour"] for i in idx], iv, tolerance)
            matched[idx] = m.alarm_matched
    false_idx = np.flatnonzero(~matched)
    trap = 0
    for i in false_idx:
        a = alarms[i]
        if any(
            s["start_hour"] <= a["hour"] <= s["end_hour"] - 1 + tolerance
            and _touches(seg, a["node"], s["target"])
            for s in surges
        ):
            trap += 1
    delays = np.array([p["delay"] for p in per_fault], dtype=float)
    out: dict[str, Any] = {
        "faults": len(faults),
        "alarms": len(alarms),
        "false_alarms": int(len(false_idx)),
        "false_alarms_per_week": false_alarms_per_unit(len(false_idx), eval_hours, 168.0),
        "false_alarms_on_surges": trap,
        "detection_rate": float(np.mean([p["detected"] for p in per_fault])) if faults else None,
        "median_delay_hours": float(np.nanmedian(delays)) if np.isfinite(delays).any() else None,
        "per_fault": per_fault,
    }
    for h in horizons:
        out[f"caught_within_{h}h"] = caught_within(delays, h) if faults else None
    return out


def attribution_metrics(
    incidents: list[dict[str, Any]],
    attributions: list[dict[str, Any]],
    faults: list[dict[str, Any]],
    surges: list[dict[str, Any]],
    seg: Segments,
    tolerance: float,
) -> dict[str, Any]:
    """`incidents`: [{"id", "alarms": [{"node", "hour"}]}]; `attributions` keyed by incident_id."""
    by_inc = {a["incident_id"]: a for a in attributions}

    def matches(inc: dict[str, Any], ev: dict[str, Any]) -> bool:
        return any(
            ev["start_hour"] <= a["hour"] <= ev["end_hour"] - 1 + tolerance
            and _touches(seg, a["node"], ev["target"])
            for a in inc["alarms"]
        )

    rows = []
    for f in faults:
        hits = [i for i in incidents if matches(i, f)]
        if not hits:
            continue
        inc = min(hits, key=lambda i: min(a["hour"] for a in i["alarms"]))
        att = by_inc.get(inc["id"])
        if att is None:
            continue
        rows.append(
            {
                "fault": f["id"],
                "type": f["type"],
                "incident": inc["id"],
                "top1": att["culprit"] == f["target_key"],
                "top3": f["target_key"] in att["top3"],
                "type_right": att["fault_type"] == f["type"],
                "culprit": att["culprit"],
                "truth": f["target_key"],
            }
        )
    surge_only = [
        i
        for i in incidents
        if not any(matches(i, f) for f in faults) and any(matches(i, s) for s in surges)
    ]
    blamed = sum(
        1
        for i in surge_only
        if i["id"] in by_inc
        and by_inc[i["id"]]["culprit"] is not None
        and by_inc[i["id"]]["fault_type"] != "no_fault"
    )

    def share(key: str, subset=None) -> float | None:
        r = rows if subset is None else [x for x in rows if subset(x)]
        return float(np.mean([x[key] for x in r])) if r else None

    by_type = {
        t: {
            "n": sum(r["type"] == t for r in rows),
            "top1": share("top1", lambda x, t=t: x["type"] == t),
            "type_right": share("type_right", lambda x, t=t: x["type"] == t),
        }
        for t in sorted({r["type"] for r in rows})
    }
    return {
        "investigated_faults": len(rows),
        "top1": share("top1"),
        "top3": share("top3"),
        "fault_type_accuracy": share("type_right"),
        "by_type": by_type,
        "surge_incidents": len(surge_only),
        "surge_incidents_blamed": blamed,
        "rows": rows,
    }
