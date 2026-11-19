"""Pool the graded worlds of a test plan into the H1 and H2 numbers (methodology M46).

Input: the per-world grade dicts written by `culprit evaluate` (they already
hold every per-fault outcome). Nothing here reads an answer key.

- Detection, per detector: share of faults caught within 6 hours (the H1
  headline) with a Wilson interval (`cleanroom.stats.wilson_interval`), share
  detected, median delay, and false alarms and false incidents per week
  pooled over all evaluation weeks. Also split by fault type (so the held-out
  type is visible on its own) and by simulator regime.
- H1 comparison: the TSFM detector minus each other detector on caught within
  6 hours, over the same faults, with a paired bootstrap that resamples whole
  worlds (`cleanroom.bootstrap.paired_bootstrap`), because faults in one
  world share its noise.
- Attribution, per investigator: top-1, top-3 and fault type over the faults
  each investigated, split the same way.
- H2 comparison: agent minus control top-1 on the faults both were graded on,
  with the same world-level paired bootstrap, plus the agent's cost per
  incident.

With one world the bootstrap has one cluster and its interval has no width;
the summary records the number of clusters so nobody mistakes that for
certainty.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from cleanroom.bootstrap import paired_bootstrap
from cleanroom.stats import wilson_interval

H1_HOURS = 6
NOTE = "Simulated data. Pooled over the plan's worlds; intervals are 95%."


def _share(k: int, n: int) -> dict[str, Any]:
    if n == 0:
        return {"k": 0, "n": 0, "share": None, "ci95": None}
    lo, hi = wilson_interval(k, n)
    return {"k": int(k), "n": int(n), "share": k / n, "ci95": [lo, hi]}


def _detection_rows(grades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for g in grades:
        for det, m in g["detection"].items():
            for f in m["per_fault"]:
                d = f["delay"]
                rows.setdefault(det, []).append(
                    {
                        "world": g["world"],
                        "regime": g.get("regime"),
                        "fault": f["id"],
                        "type": f["type"],
                        "detected": bool(f["detected"]),
                        "caught": bool(f["detected"]) and d == d and d <= H1_HOURS,
                        "delay": d,
                    }
                )
    return rows


def _det_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    delays = [r["delay"] for r in rows if r["detected"]]
    return {
        f"caught_within_{H1_HOURS}h": _share(sum(r["caught"] for r in rows), len(rows)),
        "detected": _share(sum(r["detected"] for r in rows), len(rows)),
        "median_delay_hours": float(np.median(delays)) if delays else None,
    }


def _split(rows, key, fn) -> dict[str, Any]:
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(str(r[key]), []).append(r)
    return {k: fn(v) for k, v in sorted(groups.items())}


def _paired(rows_a, rows_b, field, n_boot) -> dict[str, Any] | None:
    """b minus a on the rows both have, resampling whole worlds."""
    a = {(r["world"], r["fault"]): r for r in rows_a}
    b = {(r["world"], r["fault"]): r for r in rows_b}
    keys = sorted(set(a) & set(b))
    if not keys:
        return None
    va = np.array([float(a[k][field]) for k in keys])
    vb = np.array([float(b[k][field]) for k in keys])
    clusters = np.array([k[0] for k in keys])
    res = paired_bootstrap(lambda i: (va[i].mean(), vb[i].mean()), clusters, n_boot=n_boot)
    return {**res.to_dict(), "n_faults": len(keys)}


def _attribution_rows(grades: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    rows: dict[str, list[dict[str, Any]]] = {}
    for g in grades:
        for who, att in g["attribution"].items():
            for r in att["rows"]:
                rows.setdefault(who, []).append(
                    {
                        "world": g["world"],
                        "regime": g.get("regime"),
                        "fault": r["fault"],
                        "type": r["type"],
                        "top1": bool(r["top1"]),
                        "top3": bool(r["top3"]),
                        "type_right": bool(r["type_right"]),
                    }
                )
    return rows


def _att_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(rows)
    return {k: _share(sum(r[k] for r in rows), n) for k in ("top1", "top3", "type_right")}


def _fmt(s: dict[str, Any]) -> str:
    if s["share"] is None:
        return "no faults"
    lo, hi = s["ci95"]
    return f"{s['k']} of {s['n']} ({s['share']:.3f}, 95% CI {lo:.3f} to {hi:.3f})"


def pool(grades: list[dict[str, Any]], n_boot: int = 2000) -> dict[str, Any]:
    weeks = sum(g["eval_hours"] for g in grades) / 168.0
    det_rows = _detection_rows(grades)
    detection = {}
    for det, rows in det_rows.items():
        fa = sum(g["detection"][det]["false_alarms"] for g in grades)
        fi = sum(g["detection"][det]["false_incidents"] for g in grades)
        detection[det] = {
            "overall": _det_stats(rows),
            "false_alarms_per_week": fa / weeks if weeks else None,
            "false_incidents_per_week": fi / weeks if weeks else None,
            "by_type": _split(rows, "type", _det_stats),
            "by_regime": _split(rows, "regime", _det_stats),
        }
    h1 = {}
    if "TSFM" in det_rows:
        for other in sorted(set(det_rows) - {"TSFM"}):
            h1[f"TSFM minus {other}"] = _paired(det_rows[other], det_rows["TSFM"], "caught", n_boot)
    att_rows = _attribution_rows(grades)
    attribution = {
        who: {
            "overall": _att_stats(rows),
            "by_type": _split(rows, "type", _att_stats),
            "by_regime": _split(rows, "regime", _att_stats),
        }
        for who, rows in att_rows.items()
    }
    h2 = None
    if "agent" in att_rows and "control" in att_rows:
        h2 = _paired(att_rows["control"], att_rows["agent"], "top1", n_boot)
    costs = [c for g in grades for c in g.get("agent_costs", [])]
    agent_cost = (
        {
            "incidents": len(costs),
            "total_usd": float(sum(costs)),
            "median_usd_per_incident": float(np.median(costs)),
        }
        if costs
        else None
    )
    modes = sorted({g.get("budget_mode") for g in grades if g.get("budget_mode")})
    text = [f"{NOTE} Worlds: {len(grades)}. Budget counted {', '.join(modes) or 'unknown'}."]
    for det, d in detection.items():
        caught = _fmt(d["overall"][f"caught_within_{H1_HOURS}h"])
        text.append(
            f"H1 {det}: caught within {H1_HOURS} h {caught}"
            f", false alarms per week {d['false_alarms_per_week']:.2f}"
        )
    for name, r in h1.items():
        if r:
            text.append(
                f"H1 {name}: {r['diff']:+.3f} (95% CI {r['ci_low']:+.3f} to {r['ci_high']:+.3f}, "
                f"{r['n_clusters']} worlds)"
            )
    for who, a in attribution.items():
        text.append(f"H2 {who}: top-1 {_fmt(a['overall']['top1'])}")
    if h2:
        text.append(
            f"H2 agent minus control top-1: {h2['diff']:+.3f} (95% CI {h2['ci_low']:+.3f} to "
            f"{h2['ci_high']:+.3f}, {h2['n_faults']} faults, {h2['n_clusters']} worlds)"
        )
    if agent_cost:
        text.append(
            f"H2 agent cost: USD {agent_cost['total_usd']:.2f} over {agent_cost['incidents']} "
            f"incidents, median USD {agent_cost['median_usd_per_incident']:.4f} per incident"
        )
    return {
        "note": NOTE,
        "worlds": [g["world"] for g in grades],
        "evaluation_weeks": weeks,
        "detection": detection,
        "h1": h1,
        "attribution": attribution,
        "h2_agent_minus_control_top1": h2,
        "agent_cost": agent_cost,
        "headline_text": text,
    }
