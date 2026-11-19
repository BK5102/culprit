"""Command line: simulate a world, detect, attribute, and grade (methodology M41).

    culprit simulate CONFIG     build the world: data/worlds/<name>-seed<seed>/
    culprit detect CONFIG       detectors at an equal false-alarm budget -> artifacts/.../detect/
    culprit attribute CONFIG    the no-LLM control on the configured detector's incidents
    culprit evaluate CONFIG     grade a development world against its answer key
    culprit seal CONFIG         test worlds: lock the config and seal the key (commit both)
    culprit run CONFIG --sealed RUN_ID   test worlds: detect + attribute as one sealed run
    culprit evaluate CONFIG --run-id RUN_ID   test worlds: grade after the sealed run finished

Every output file carries provenance (config hash, git commit, dataset hash,
package versions). All data is simulated.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from cleanroom.guard import sealed_run
from cleanroom.lock import seal
from cleanroom.provenance import config_hash, stamp
from cleanroom.vault import seal_answer_key

from culprit.config import artifacts_dir, load_config, world_dir
from culprit.detect.budget import Alarm, Incident
from culprit.detect.run import run_detection
from culprit.investigate.control import run_control
from culprit.world import OBSERVED_DIR, PANEL_FILE, load_observed

PACKAGES = ("culprit", "cleanroom", "numpy", "polars", "statsmodels", "scipy")
NOTE = "Simulated data. No real payments."


def _write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=float), encoding="utf-8")


def _read(path: Path) -> Any:
    if not path.exists():
        raise SystemExit(f"missing {path}; run the earlier step first")
    return json.loads(path.read_text(encoding="utf-8"))


def _provenance(config: dict[str, Any], world) -> dict[str, Any]:
    panel = world_dir(config) / OBSERVED_DIR / PANEL_FILE
    out = stamp(config, {"panel": panel}, packages=PACKAGES)
    out["dataset_hash"] = world.meta["dataset_hash"]
    out["note"] = NOTE
    return out


def cmd_simulate(config: dict[str, Any], args) -> int:
    from culprit.sim.build import simulate, write_world

    t0 = time.perf_counter()
    result = simulate(config)
    out = write_world(result, world_dir(config))
    obs = result.observed
    print(
        f"{NOTE}\nworld {out}: {obs.segments.n_leaves} leaf segments x "
        f"{obs.timeline.n_hours} hours, dataset hash {obs.meta['dataset_hash'][:12]}, "
        f"{time.perf_counter() - t0:.1f} s"
    )
    return 0


def _detect(config: dict[str, Any], world) -> dict[str, Any]:
    t0 = time.perf_counter()
    panel, results, skipped = run_detection(world, config)
    d = artifacts_dir(config) / "detect"
    _write(
        d / "alarms.json",
        {
            n: [
                {"node": panel.keys[a.series], "series": a.series, "hour": a.hour, "score": a.score}
                for a in r.alarms
            ]
            for n, r in results.items()
        },
    )
    _write(
        d / "incidents.json",
        {n: [i.to_dict(panel.keys) for i in r.incidents] for n, r in results.items()},
    )
    summary = {
        "provenance": _provenance(config, world),
        "series": len(panel.keys),
        "budget": config["budget"],
        "detectors": [r.summary(panel.keys) for r in results.values()],
        "skipped": skipped,
        "seconds": round(time.perf_counter() - t0, 2),
    }
    _write(d / "summary.json", summary)
    b = config["budget"]
    print(f"budget: {b['false_alarms_per_week']} false alarms per week, counted {b['mode']}")
    for r in results.values():
        print(
            f"{r.name:5s} threshold {r.threshold.threshold:8.3f}  calibration alarms "
            f"{r.threshold.n_alarms} ({r.threshold.n_incidents} incidents)  evaluation alarms "
            f"{len(r.alarms):4d}  incidents {len(r.incidents):3d}  {r.seconds:.1f} s"
        )
    for s in skipped:
        print(f"skipped: {s}")
    return summary


def _attribute(config: dict[str, Any], world) -> list[dict[str, Any]]:
    name = config["control"]["detector"]
    incidents = _read(artifacts_dir(config) / "detect" / "incidents.json").get(name)
    if incidents is None:
        raise SystemExit(f"detector {name!r} has no incidents file; is it in detect.detectors?")
    alarms = _read(artifacts_dir(config) / "detect" / "alarms.json")[name]
    series = {a["node"]: a["series"] for a in alarms}
    objs = [
        Incident(
            i["id"],
            i["first_hour"],
            i["last_hour"],
            [Alarm(series[a["node"]], a["hour"], a["score"]) for a in i["alarms"]],
        )
        for i in incidents
    ]
    t0 = time.perf_counter()
    atts = [{**a.to_dict(), "source_detector": name} for a in run_control(world, objs, config)]
    _write(
        artifacts_dir(config) / "attribute" / "control.json",
        {
            "provenance": _provenance(config, world),
            "attributions": atts,
            "seconds": round(time.perf_counter() - t0, 2),
        },
    )
    print(
        f"control: {len(atts)} incidents from detector {name} investigated "
        f"in {time.perf_counter() - t0:.1f} s"
    )
    return atts


def cmd_detect(config: dict[str, Any], args) -> int:
    _detect(config, load_observed(world_dir(config)))
    return 0


def cmd_attribute(config: dict[str, Any], args) -> int:
    _attribute(config, load_observed(world_dir(config)))
    return 0


def cmd_seal(config: dict[str, Any], args) -> int:
    from culprit.evaluate.grade import sealed_vault_path
    from culprit.sim.build import answer_key_path

    if config["evaluate"]["role"] != "test":
        raise SystemExit("seal is for test worlds (evaluate.role: test)")
    world = load_observed(world_dir(config))
    lock = seal(
        config, config["paths"]["lock_dir"], note=args.note, data_sha256=world.meta["dataset_hash"]
    )
    vault = seal_answer_key(
        answer_key_path(world_dir(config)),
        vault_path=sealed_vault_path(config, world_dir(config).name),
        note=args.note,
    )
    print(f"lock {lock.path}\nvault record {vault.record_path}\nCommit both before the sealed run.")
    return 0


def cmd_run(config: dict[str, Any], args) -> int:
    if not args.sealed:
        raise SystemExit("run needs --sealed RUN_ID (use detect and attribute for development)")
    world = load_observed(world_dir(config))
    with sealed_run(
        config, config["paths"]["lock_dir"], args.sealed, data_sha256=world.meta["dataset_hash"]
    ) as run:
        _detect(config, world)
        _attribute(config, world)
        run.finish(config_hash=config_hash(config))
    return 0


def cmd_evaluate(config: dict[str, Any], args) -> int:
    from culprit.evaluate.grade import dev_answer_key, grade, sealed_answer_key

    world = load_observed(world_dir(config))
    a_dir = artifacts_dir(config)
    alarms = _read(a_dir / "detect" / "alarms.json")
    incidents = _read(a_dir / "detect" / "incidents.json")
    control = _read(a_dir / "attribute" / "control.json")["attributions"]
    if args.run_id:
        key = sealed_answer_key(world_dir(config), config, args.run_id)
    else:
        key = dev_answer_key(world_dir(config), config)
    lo, hi = world.timeline.window_hours("evaluation")
    result = grade(key, world.segments, hi - lo, alarms, incidents, {"control": control}, config)
    result["provenance"] = _provenance(config, world)
    result["role"] = config["evaluate"]["role"]
    _write(a_dir / "evaluate" / "grade.json", result)
    print(f"{NOTE} Role: {result['role']}.")
    for name, m in result["detection"].items():
        print(
            f"{name:5s} detected {m['detection_rate']}  within 6h {m['caught_within_6h']}  "
            f"false alarms per week {m['false_alarms_per_week']:.2f}  "
            f"false incidents per week {m['false_incidents_per_week']:.2f}"
        )
    att = result["attribution"]["control"]
    print(
        f"control top-1 {att['top1']}  top-3 {att['top3']}  "
        f"fault type {att['fault_type_accuracy']}  ({att['investigated_faults']} faults)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="culprit", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("simulate", "detect", "attribute", "evaluate", "seal", "run"):
        p = sub.add_parser(name)
        p.add_argument("config")
        if name == "evaluate":
            p.add_argument("--run-id", default=None)
        if name == "seal":
            p.add_argument("--note", default="")
        if name == "run":
            p.add_argument("--sealed", default=None)
    args = ap.parse_args(argv)
    config = load_config(args.config)
    return {
        "simulate": cmd_simulate,
        "detect": cmd_detect,
        "attribute": cmd_attribute,
        "evaluate": cmd_evaluate,
        "seal": cmd_seal,
        "run": cmd_run,
    }[args.cmd](config, args)


if __name__ == "__main__":
    sys.exit(main())
