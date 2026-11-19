"""Oracle alerts: investigate every fault as if a perfect detector had paged on time.

Development only (methodology M47). An oracle incident is built for each fault
from its true start hour: it fires at start + persistence - 1, the earliest
hour the shared k-hour alarm rule (M26) could fire on a fault that starts at
`start`. The investigator then runs exactly as it does on a detector's
incident. Each fault is graded on its own oracle incident, so overlapping
faults do not borrow each other's pages.

This separates the two ways the control can fail. With detector alerts, a
miss can come from a late or false page (detection) or from naming the wrong
segment (attribution). With oracle alerts every page is on time and real, so
what is left is attribution alone. Like timing a detective from the moment
the crime happened rather than from when someone happened to call it in.

This module takes the faults as plain inputs and reads no files. It is part of
`culprit.evaluate`, which no detector, control or agent module may import.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from culprit.detect.budget import Alarm, Incident


def oracle_incidents(faults: list[dict[str, Any]], persistence: int) -> list[Incident]:
    """One incident per fault, paged at start + persistence - 1 on the fault's own target."""
    out = []
    for f in faults:
        hour = int(f["start_hour"]) + int(persistence) - 1
        out.append(Incident(f"oracle-{f['id']}", hour, hour, [Alarm(-1, hour, float("nan"))]))
    return out


def oracle_attribution(
    faults: list[dict[str, Any]], attributions: list[dict[str, Any]]
) -> dict[str, Any]:
    """Top-1, top-3 and fault type with each fault graded on its own oracle incident."""
    by_inc = {a["incident_id"]: a for a in attributions}
    rows = []
    for f in faults:
        att = by_inc.get(f"oracle-{f['id']}")
        if att is None:
            continue
        rows.append(
            {
                "fault": f["id"],
                "type": f["type"],
                "top1": att["culprit"] == f["target_key"],
                "top3": f["target_key"] in att["top3"],
                "type_right": att["fault_type"] == f["type"],
                "culprit": att["culprit"],
                "truth": f["target_key"],
                "culprit_attempts": att["evidence"]["attempts"],
            }
        )

    def share(key: str, t: str | None = None) -> float | None:
        r = [x[key] for x in rows if t is None or x["type"] == t]
        return float(np.mean(r)) if r else None

    return {
        "investigated_faults": len(rows),
        "top1": share("top1"),
        "top3": share("top3"),
        "fault_type_accuracy": share("type_right"),
        "by_type": {
            t: {"n": sum(x["type"] == t for x in rows), "top1": share("top1", t)}
            for t in sorted({x["type"] for x in rows})
        },
        "rows": rows,
    }
