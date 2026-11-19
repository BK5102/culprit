"""Separate detection from attribution for the no-LLM control on one development world.

    uv run python scripts/diagnose_control.py configs/full.yaml

Simulates the config's world in memory, then grades the control twice
(methodology M47):

- detector alerts: the control investigates the incidents of its configured
  detector (A2 by default), as in `culprit attribute`, for both budget
  counting units (M42), with only that detector run;
- oracle alerts: one incident per fault, paged at the fault's true start plus
  persistence minus one (`culprit.evaluate.oracle`), so every page is on time
  and real and what is left is attribution alone.

It also reports how many investigation windows the culprit segment had, since
a culprit backed by one or two payments is the sign of the degenerate
variance described in L27. Development numbers from one seed, never results.
It refuses a config whose role is "test". Output also goes to
artifacts/<name>-seed<seed>/control-diagnosis.json with provenance.

All data is simulated.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import numpy as np
from cleanroom.provenance import stamp

from culprit.config import artifacts_dir, load_config
from culprit.detect.run import run_detection
from culprit.evaluate.grade import grade
from culprit.evaluate.oracle import oracle_attribution, oracle_incidents
from culprit.investigate.control import run_control
from culprit.sim.build import simulate

MODES = ("per_series", "per_incident")


def _thin(atts: list[dict], limit: float = 10.0) -> int:
    """Culprits whose investigation window held fewer than `limit` payment attempts."""
    return sum(1 for a in atts if a["culprit"] is not None and a["evidence"]["attempts"] < limit)


def diagnose(config: dict) -> dict:
    if config["evaluate"]["role"] != "dev":
        raise SystemExit("control diagnosis runs on development worlds only")
    sim = simulate(config)
    world = sim.observed
    lo, hi = world.timeline.window_hours("evaluation")
    faults = sim.answer_key["faults"]
    source = config["control"]["detector"]
    out = {
        "world": sim.answer_key["world"],
        "dataset_hash": world.meta["dataset_hash"],
        "control": config["control"],
        "faults": len(faults),
        "detector_alerts": {},
    }
    for mode in MODES:
        cfg = copy.deepcopy(config)
        cfg["budget"]["mode"] = mode
        cfg["detect"]["detectors"] = [source]
        t0 = time.perf_counter()
        panel, results, _ = run_detection(world, cfg)
        r = results[source]
        alarms = {source: [{"node": panel.keys[a.series], "hour": a.hour} for a in r.alarms]}
        incidents = {source: [i.to_dict(panel.keys) for i in r.incidents]}
        atts = [
            {**a.to_dict(), "source_detector": source} for a in run_control(world, r.incidents, cfg)
        ]
        g = grade(
            sim.answer_key, world.segments, hi - lo, alarms, incidents, {"control": atts}, cfg
        )
        c = g["attribution"]["control"]
        out["detector_alerts"][mode] = {
            "incidents": len(atts),
            "faults_detected": round(g["detection"][source]["detection_rate"] * len(faults)),
            "thin_culprits": _thin(atts),
            **c,
            "seconds": round(time.perf_counter() - t0, 1),
        }
    t0 = time.perf_counter()
    k = int(config["budget"]["persistence_hours"])
    incs = oracle_incidents(faults, k)
    atts = [a.to_dict() for a in run_control(world, incs, config)]
    o = oracle_attribution(faults, atts)
    o["thin_culprits"] = _thin(atts)
    o["median_culprit_attempts"] = (
        float(np.median([r["culprit_attempts"] for r in o["rows"]])) if o["rows"] else None
    )
    o["seconds"] = round(time.perf_counter() - t0, 1)
    out["oracle_alerts"] = o
    return out


def _f(x) -> str:
    return "n/a" if x is None else f"{x:.3f}"


def table(result: dict) -> str:
    lines = [
        f"Development only, one seed, simulated: {result['world']}, {result['faults']} faults",
        "",
        "| Alerts | Incidents | Faults investigated | Top-1 | Top-3 | Fault type | "
        "Culprits under 10 attempts |",
        "|---|---|---|---|---|---|---|",
    ]
    for mode, m in result["detector_alerts"].items():
        lines.append(
            f"| detector, {mode} | {m['incidents']} | {m['investigated_faults']} | "
            f"{_f(m['top1'])} | {_f(m['top3'])} | {_f(m['fault_type_accuracy'])} | "
            f"{m['thin_culprits']} |"
        )
    o = result["oracle_alerts"]
    lines.append(
        f"| oracle | {o['investigated_faults']} | {o['investigated_faults']} | {_f(o['top1'])} | "
        f"{_f(o['top3'])} | {_f(o['fault_type_accuracy'])} | {o['thin_culprits']} |"
    )
    lines += ["", "Oracle top-1 by fault type:"]
    for t, v in o["by_type"].items():
        lines.append(f"  {t}: {_f(v['top1'])} of {v['n']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config")
    args = ap.parse_args(argv)
    config = load_config(args.config)
    result = diagnose(config)
    result["provenance"] = stamp(config, {}, packages=("culprit", "cleanroom", "numpy"))
    result["note"] = "Simulated data. Development numbers from one seed, not a result."
    path = artifacts_dir(config) / "control-diagnosis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    print(table(result))
    print(f"\nwritten {Path(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
