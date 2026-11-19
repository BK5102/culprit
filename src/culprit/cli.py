"""Command line: simulate a world, detect, attribute, and grade (methodology M41).

    culprit simulate CONFIG     build the world: data/worlds/<name>-seed<seed>/
    culprit detect CONFIG       detectors at an equal false-alarm budget -> artifacts/.../detect/
    culprit attribute CONFIG    the no-LLM control on the configured detector's incidents
    culprit agent CONFIG --incident N | --all [--record]   the LLM investigator on the same
                                incidents, replaying cassettes (default) or recording new ones
    culprit evaluate CONFIG     grade a development world against its answer key
    culprit validate CONFIG     test plans: list every placeholder or problem left before sealing
    culprit seal CONFIG         test plans: lock the plan and seal every world's key (commit both)
    culprit run CONFIG --sealed RUN_ID   test plans: detect, attribute and (if test.agent) the
                                agent on every world, as one sealed run
    culprit evaluate CONFIG --run-id RUN_ID   test plans: grade after the sealed run finished

A development config is one world. A test plan (configs/test.yaml) names
several worlds through `test.seeds` and `test.regimes` (culprit/plan.py);
every command runs on each of them, and the plan is what gets locked.

Every output file carries provenance (config hash, git commit, dataset hash,
package versions). All data is simulated.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path
from typing import Any

from cleanroom.guard import SealedRunError, sealed_run
from cleanroom.lock import LockMissingError, seal
from cleanroom.provenance import config_hash, stamp
from cleanroom.vault import VaultError, seal_answer_key

from culprit.config import artifacts_dir, load_config, world_dir
from culprit.detect.budget import Alarm, Incident
from culprit.detect.run import run_detection
from culprit.investigate.control import run_control
from culprit.plan import PlanError, combined_data_hash, dev_seeds, expand_worlds, is_plan, problems
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


def _worlds(config: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return expand_worlds(config)
    except PlanError as err:
        raise SystemExit(str(err)) from err


def _dev_only(config: dict[str, Any], what: str) -> None:
    if config["evaluate"]["role"] == "test":
        raise SystemExit(
            f"{what} on test worlds runs only inside `culprit run CONFIG --sealed RUN_ID`, "
            "after the plan is sealed and committed"
        )


def _load(w: dict[str, Any]):
    if not (world_dir(w) / OBSERVED_DIR).exists():
        raise SystemExit(f"missing world {world_dir(w)}; run `culprit simulate` first")
    return load_observed(world_dir(w))


def lock_config(config: dict[str, Any]) -> dict[str, Any]:
    """What a test plan's lock covers: the plan plus the hash of the agent's fixed prompt."""
    from culprit.agent.investigator import prompt_sha256

    out = copy.deepcopy(config)
    out["agent_prompt_sha256"] = prompt_sha256(config["agent"]["max_tool_calls"])
    return out


def cmd_simulate(config: dict[str, Any], args) -> int:
    from culprit.sim.build import simulate, write_world

    for w in _worlds(config):
        t0 = time.perf_counter()
        result = simulate(w)
        out = write_world(result, world_dir(w))
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


def _incidents(config: dict[str, Any]) -> tuple[str, list[Incident], dict[int, str]]:
    """The investigated detector's incidents, rebuilt from the detect step's files."""
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
    return name, objs, {v: k for k, v in series.items()}


def _attribute(config: dict[str, Any], world) -> list[dict[str, Any]]:
    name, objs, _ = _incidents(config)
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
    _dev_only(config, "detect")
    for w in _worlds(config):
        _detect(w, _load(w))
    return 0


def cmd_attribute(config: dict[str, Any], args) -> int:
    _dev_only(config, "attribute")
    for w in _worlds(config):
        _attribute(w, _load(w))
    return 0


def _agent(config: dict[str, Any], world, which: str | None, record: bool) -> dict[str, Any]:
    from culprit.agent.run import AgentSetupError, run_agent, select_incidents, summary

    name, objs, keys = _incidents(config)
    out_path = artifacts_dir(config) / "agent" / "agent.json"
    try:
        chosen = select_incidents(objs, which)
        t0 = time.perf_counter()
        rows, reports = run_agent(
            world, chosen, keys, config, world_dir(config).name, record=record
        )
    except AgentSetupError as err:
        raise SystemExit(str(err)) from err
    # A single-incident run updates that incident's row and keeps the others.
    previous = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    by_id = {r["incident_id"]: r for r in previous.get("attributions", [])}
    by_id.update({r["incident_id"]: r for r in rows})
    all_rows = [by_id.get(i.id) for i in objs if i.id in by_id]
    for inc_id, text in reports.items():
        p = out_path.parent / "reports" / f"{inc_id}.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    result = {
        "provenance": _provenance(config, world),
        "source_detector": name,
        "summary": summary(all_rows, config),
        "attributions": all_rows,
        "seconds": round(time.perf_counter() - t0, 2),
    }
    _write(out_path, result)
    for r in rows:
        print(
            f"{r['incident_id']}: {r['status']}  culprit {r['culprit']}  {r['fault_type']}  "
            f"USD {r.get('cost_usd', 0.0):.4f}"
        )
    s = result["summary"]
    print(
        f"agent ({'record' if record else 'replay'}): {len(rows)} incidents, "
        f"{s['accepted']} of {s['incidents']} accepted by the critic in {out_path}"
    )
    return result


def cmd_agent(config: dict[str, Any], args) -> int:
    if args.incident is None and not args.all:
        raise SystemExit("agent needs --incident N (index or id) or --all")
    _dev_only(config, "agent")
    for w in _worlds(config):
        _agent(w, _load(w), None if args.all else args.incident, args.record)
    return 0


def cmd_validate(config: dict[str, Any], args) -> int:
    found = problems(config, dev_seeds(Path(args.config).parent))
    if found:
        print(f"{args.config} is not ready to seal:")
        for p in found:
            print(f"- {p}")
        return 1
    names = [world_dir(w).name for w in _worlds(config)]
    print(f"{args.config} is ready to seal: {len(names)} worlds ({', '.join(names)}).")
    return 0


def _data_hashes(worlds: list[dict[str, Any]]) -> tuple[list[Any], dict[str, str]]:
    observed = [_load(w) for w in worlds]
    hashes = {
        world_dir(w).name: o.meta["dataset_hash"] for w, o in zip(worlds, observed, strict=True)
    }
    return observed, hashes


def cmd_seal(config: dict[str, Any], args) -> int:
    from culprit.evaluate.grade import sealed_vault_path
    from culprit.sim.build import answer_key_path

    if config["evaluate"]["role"] != "test":
        raise SystemExit("seal is for test worlds (evaluate.role: test)")
    found = problems(config, dev_seeds(Path(args.config).parent)) if is_plan(config) else []
    if found:
        raise SystemExit("not ready to seal:\n" + "\n".join(f"- {p}" for p in found))
    worlds = _worlds(config)
    _, hashes = _data_hashes(worlds)
    lock = seal(
        lock_config(config),
        config["paths"]["lock_dir"],
        note=args.note,
        data_sha256=combined_data_hash(hashes),
    )
    print(f"lock {lock.path}")
    for w in worlds:
        vault = seal_answer_key(
            answer_key_path(world_dir(w)),
            vault_path=sealed_vault_path(config, world_dir(w).name),
            note=args.note,
        )
        print(f"vault record {vault.record_path}")
    print("Commit the lock and every vault record before the sealed run.")
    return 0


def cmd_run(config: dict[str, Any], args) -> int:
    if not args.sealed:
        raise SystemExit("run needs --sealed RUN_ID (use detect and attribute for development)")
    if config["evaluate"]["role"] != "test":
        raise SystemExit("run --sealed is for test worlds (evaluate.role: test)")
    worlds = _worlds(config)
    with_agent = is_plan(config) and bool(config["test"].get("agent", True))
    if with_agent:
        from culprit.agent.run import AgentSetupError, check_record_setup

        try:
            check_record_setup(config["agent"])  # before the run starts, so no attempt is wasted
        except AgentSetupError as err:
            raise SystemExit(str(err)) from err
    observed, hashes = _data_hashes(worlds)
    locked = lock_config(config)
    with sealed_run(
        locked, config["paths"]["lock_dir"], args.sealed, data_sha256=combined_data_hash(hashes)
    ) as run:
        for w, world in zip(worlds, observed, strict=True):
            _detect(w, world)
            _attribute(w, world)
            if with_agent:
                _agent(w, world, None, record=True)
        run.finish(config_hash=config_hash(locked), worlds=sorted(hashes))
    print("Sealed run finished. Commit the lock's uses file (and any new cassettes) next.")
    return 0


def _evaluate_world(w: dict[str, Any], run_id: str | None, locked: dict[str, Any] | None):
    from culprit.evaluate.grade import dev_answer_key, grade, sealed_answer_key

    world = _load(w)
    a_dir = artifacts_dir(w)
    alarms = _read(a_dir / "detect" / "alarms.json")
    incidents = _read(a_dir / "detect" / "incidents.json")
    control = _read(a_dir / "attribute" / "control.json")["attributions"]
    investigators = {"control": control}
    agent_path = a_dir / "agent" / "agent.json"
    agent = json.loads(agent_path.read_text(encoding="utf-8")) if agent_path.exists() else None
    if agent is not None:
        investigators["agent"] = agent["attributions"]
    if run_id:
        key = sealed_answer_key(world_dir(w), locked, run_id)
    else:
        key = dev_answer_key(world_dir(w), w)
    lo, hi = world.timeline.window_hours("evaluation")
    result = grade(key, world.segments, hi - lo, alarms, incidents, investigators, w)
    if agent is not None:
        result["agent_cost"] = agent["summary"]
        result["agent_costs"] = [
            r.get("cost_usd", 0.0) for r in agent["attributions"] if r["status"] != "not_run"
        ]
    result["provenance"] = _provenance(w, world)
    result["role"] = w["evaluate"]["role"]
    result["regime"] = (w.get("test") or {}).get("regime")
    result["eval_hours"] = hi - lo
    _write(a_dir / "evaluate" / "grade.json", result)
    print(f"{NOTE} Role: {result['role']}. World {world_dir(w).name}.")
    for name, m in result["detection"].items():
        print(
            f"{name:5s} detected {m['detection_rate']}  within 6h {m['caught_within_6h']}  "
            f"false alarms per week {m['false_alarms_per_week']:.2f}  "
            f"false incidents per week {m['false_incidents_per_week']:.2f}"
        )
    for who, att in result["attribution"].items():
        print(
            f"{who} top-1 {att['top1']}  top-3 {att['top3']}  "
            f"fault type {att['fault_type_accuracy']}  ({att['investigated_faults']} faults)"
        )
    if agent is not None:
        c = agent["summary"]
        print(
            f"agent cost: USD {c['total_cost_usd']:.4f}, median per incident {c['median_cost_usd']}"
        )
    return result


def cmd_evaluate(config: dict[str, Any], args) -> int:
    from culprit.evaluate.pooled import pool

    locked = lock_config(config) if args.run_id else None
    grades = [_evaluate_world(w, args.run_id, locked) for w in _worlds(config)]
    if is_plan(config):
        summary = pool(grades, n_boot=int(config["evaluate"].get("n_boot", 2000)))
        summary["run_id"] = args.run_id
        summary["plan_config_hash"] = config_hash(locked or lock_config(config))
        out = Path(config["paths"]["artifacts_dir"]) / config["name"] / "summary.json"
        _write(out, summary)
        print(f"pooled over {len(grades)} worlds: {out}")
        for line in summary["headline_text"]:
            print(line)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="culprit", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    commands = ("simulate", "detect", "attribute", "agent", "evaluate", "validate", "seal", "run")
    for name in commands:
        p = sub.add_parser(name)
        p.add_argument("config")
        if name == "agent":
            p.add_argument("--incident", default=None, help="index in the incident list, or an id")
            p.add_argument("--all", action="store_true", help="every incident of the world")
            p.add_argument(
                "--record",
                action="store_true",
                help="live, billed calls where no cassette exists (needs ANTHROPIC_API_KEY)",
            )
        if name == "evaluate":
            p.add_argument("--run-id", default=None)
        if name == "seal":
            p.add_argument("--note", default="")
        if name == "run":
            p.add_argument("--sealed", default=None)
    args = ap.parse_args(argv)
    config = load_config(args.config)
    handler = {
        "simulate": cmd_simulate,
        "detect": cmd_detect,
        "attribute": cmd_attribute,
        "agent": cmd_agent,
        "evaluate": cmd_evaluate,
        "validate": cmd_validate,
        "seal": cmd_seal,
        "run": cmd_run,
    }[args.cmd]
    try:
        return handler(config, args)
    except (SealedRunError, LockMissingError, VaultError) as err:
        # The Cleanroom refused: no lock, uncommitted records, or a run not finished.
        raise SystemExit(f"refused: {err}") from err


if __name__ == "__main__":
    sys.exit(main())
