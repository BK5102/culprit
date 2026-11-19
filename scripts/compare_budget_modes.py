"""Compare the two ways of counting the false-alarm budget on one development world.

    uv run python scripts/compare_budget_modes.py configs/small.yaml

For `budget.mode` per_series and per_incident (methodology M27, M42), this
simulates the config's world in memory, runs the detectors and the no-LLM
control, grades them against the world's answer key, and prints one table.
It is a development check to help the owner choose the mode before the lock:
the numbers are development numbers from one seed, never results. It refuses
a config whose role is "test". Output also goes to
artifacts/<name>-seed<seed>/budget-modes.json with provenance.

All data is simulated.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

from cleanroom.provenance import stamp

from culprit.config import artifacts_dir, load_config
from culprit.detect.run import run_detection
from culprit.evaluate.grade import grade
from culprit.investigate.control import run_control
from culprit.sim.build import simulate

MODES = ("per_series", "per_incident")


def compare(config: dict) -> dict:
    if config["evaluate"]["role"] != "dev":
        raise SystemExit("budget comparisons run on development worlds only")
    sim = simulate(config)
    world = sim.observed
    lo, hi = world.timeline.window_hours("evaluation")
    out = {
        "world": sim.answer_key["world"],
        "dataset_hash": world.meta["dataset_hash"],
        "modes": {},
    }
    for mode in MODES:
        cfg = copy.deepcopy(config)
        cfg["budget"]["mode"] = mode
        t0 = time.perf_counter()
        panel, results, _ = run_detection(world, cfg)
        alarms = {
            n: [{"node": panel.keys[a.series], "hour": a.hour} for a in r.alarms]
            for n, r in results.items()
        }
        incidents = {n: [i.to_dict(panel.keys) for i in r.incidents] for n, r in results.items()}
        source = cfg["control"]["detector"]
        atts = [
            {**a.to_dict(), "source_detector": source}
            for a in run_control(world, results[source].incidents, cfg)
        ]
        g = grade(
            sim.answer_key, world.segments, hi - lo, alarms, incidents, {"control": atts}, cfg
        )
        out["modes"][mode] = {
            "calibration": {n: r.threshold.to_dict() for n, r in results.items()},
            "detection": {
                n: {k: v for k, v in m.items() if k != "per_fault"}
                for n, m in g["detection"].items()
            },
            "control": {k: v for k, v in g["attribution"]["control"].items() if k != "rows"},
            "seconds": round(time.perf_counter() - t0, 1),
        }
    return out


def table(result: dict) -> str:
    lines = [
        f"Development only, one seed, simulated: {result['world']}",
        "",
        "| Mode | Detector | Threshold | Calib. alarms | Calib. incidents | Faults caught | "
        "Within 6 h | Eval. false alarms / wk | Eval. false incidents / wk |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for mode, m in result["modes"].items():
        for n, d in m["detection"].items():
            c = m["calibration"][n]
            caught = round(d["detection_rate"] * d["faults"]) if d["faults"] else 0
            lines.append(
                f"| {mode} | {n} | {c['threshold']:.3f} | {c['n_alarms']} | {c['n_incidents']} | "
                f"{caught} of {d['faults']} | {d['caught_within_6h']:.3f} | "
                f"{d['false_alarms_per_week']:.2f} | {d['false_incidents_per_week']:.2f} |"
            )
    lines += ["", "| Mode | Control incidents | Faults investigated | Top-1 | Top-3 | Fault type |"]
    lines.append("|---|---|---|---|---|---|")
    for mode, m in result["modes"].items():
        c = m["control"]
        lines.append(
            f"| {mode} | {m['n_control_incidents']} | {c['investigated_faults']} | {c['top1']} | "
            f"{c['top3']} | {c['fault_type_accuracy']} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("config")
    args = ap.parse_args(argv)
    config = load_config(args.config)
    result = compare(config)
    for m in result["modes"].values():
        src = config["control"]["detector"]
        m["n_control_incidents"] = m["detection"][src]["incidents"]
    result["provenance"] = stamp(config, {}, packages=("culprit", "cleanroom", "numpy"))
    result["note"] = "Simulated data. Development numbers from one seed, not a result."
    path = artifacts_dir(config) / "budget-modes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, default=float), encoding="utf-8")
    print(table(result))
    print(f"\nwritten {Path(path)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
