"""Test plans: one config that names several sealed worlds, and the checks before sealing (M45).

A development config describes one world (its `name` and `seed`). A test plan
adds a `test` section:

    test:
      seeds: [s1, s2, ...]          # one world per seed and regime
      regimes:
        base: {}                    # the development settings
        second: {world: {...}}      # overrides merged over the plan (simulator settings only)

`expand_worlds` turns a plan into one ordinary config per (regime, seed),
named `<name>-<regime>` with that seed, so every command works per world as
before. The plan itself (not the per-world configs) is what gets locked.

Owner choices that are still open are written as strings that start with
PLACEHOLDER. `problems(config)` lists every one and every other reason the
plan is not ready; `culprit validate` prints them and `culprit seal` refuses
while any remain.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from culprit.config import deep_merge, load_config
from culprit.detect.budget import BUDGET_MODES

PLACEHOLDER = "PLACEHOLDER"
# Seeds already used for development anywhere in this repo (configs, tests, the
# data-fit check, docs; 301 to 303 are reserved for the second regime's fit check).
# A test seed must be new (methodology M45).
DEV_SEEDS = frozenset({3, 7, 11, 17, 101, 102, 103, 104, 105, 201, 301, 302, 303})


class PlanError(ValueError):
    """The plan cannot be expanded or sealed as written."""


def placeholders(obj: Any, path: str = "") -> list[str]:
    """Dotted paths of every value that is still a PLACEHOLDER string."""
    if isinstance(obj, str):
        return [path] if obj.strip().startswith(PLACEHOLDER) else []
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in placeholders(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, list):
        return [p for i, v in enumerate(obj) for p in placeholders(v, f"{path}[{i}]")]
    return []


def is_plan(config: dict[str, Any]) -> bool:
    return bool(config.get("test"))


def regime_config(config: dict[str, Any], regime: str) -> dict[str, Any]:
    """The plan with one regime's overrides merged in (no seed change)."""
    regimes = (config.get("test") or {}).get("regimes")
    if not isinstance(regimes, dict) or regime not in regimes:
        raise PlanError(f"no regime {regime!r} in test.regimes")
    over = regimes[regime]
    if placeholders(over) or not isinstance(over, dict):
        raise PlanError(f"regime {regime!r} is still a placeholder")
    out = deep_merge(config, over)
    out["name"] = f"{config['name']}-{regime}"
    return out


def expand_worlds(config: dict[str, Any]) -> list[dict[str, Any]]:
    """One config per world. A development config is its own single world."""
    if not is_plan(config):
        return [config]
    t = config["test"]
    if placeholders(t.get("seeds")) or not isinstance(t.get("seeds"), list):
        raise PlanError("test.seeds is still a placeholder; choose the test seeds first")
    out = []
    for regime in t["regimes"]:
        base = regime_config(config, regime)
        for seed in t["seeds"]:
            w = dict(base)
            w["seed"] = int(seed)
            w["test"] = {"regime": regime, "plan": config["name"]}
            out.append(w)
    return out


def combined_data_hash(dataset_hashes: dict[str, str]) -> str:
    """One checksum over every world's dataset hash, pinned in the plan's lock."""
    payload = json.dumps(sorted(dataset_hashes.items()))
    return hashlib.sha256(payload.encode()).hexdigest()


def dev_seeds(config_dir: str | Path = "configs") -> set[int]:
    seeds = set(DEV_SEEDS)
    for p in Path(config_dir).glob("*.yaml"):
        cfg = load_config(p)
        if cfg["evaluate"]["role"] == "dev" and isinstance(cfg.get("seed"), int):
            seeds.add(cfg["seed"])
    return seeds


def problems(config: dict[str, Any], known_dev_seeds: set[int] | None = None) -> list[str]:
    """Every reason this plan cannot be sealed yet. Empty means ready."""
    out = [f"{p} is a placeholder (owner's choice)" for p in placeholders(config)]
    if config["evaluate"]["role"] != "test":
        out.append("evaluate.role must be 'test' for a sealed plan")
    if not is_plan(config):
        out.append("a sealed plan needs a test section with seeds and regimes")
        return out
    t = config["test"]
    seeds = t.get("seeds")
    if isinstance(seeds, list):
        if not seeds or not all(isinstance(s, int) and s >= 0 for s in seeds):
            out.append("test.seeds must be a non-empty list of non-negative integers")
        elif len(set(seeds)) != len(seeds):
            out.append("test.seeds has repeats")
        else:
            used = sorted(set(seeds) & (known_dev_seeds or set(DEV_SEEDS)))
            if used:
                out.append(f"test.seeds {used} were already used in development")
    regimes = t.get("regimes")
    if not isinstance(regimes, dict) or len(regimes) < 2:
        out.append("test.regimes needs at least two regimes (CLAUDE.md rule 9)")
    else:
        for name, over in regimes.items():
            if isinstance(over, dict) and set(over) - {"world"}:
                out.append(f"regime {name!r} may only override world settings")
        if all(isinstance(v, dict) for v in regimes.values()) and not any(
            v.get("world") for v in regimes.values()
        ):
            out.append("no regime changes any simulator setting")
    mode = config["budget"].get("mode")
    if mode not in BUDGET_MODES and not placeholders(mode):
        out.append(f"budget.mode must be one of {BUDGET_MODES}")
    held = config["world"]["holdout_fault_types"]
    if not held:
        out.append("world.holdout_fault_types is empty (CLAUDE.md rule 9)")
    types = config["world"]["faults"]["types"]
    if isinstance(types, list):
        missing = [h for h in held if h not in types]
        if missing:
            out.append(f"held-out fault types {missing} are not injected in world.faults.types")
    dets = config["detect"]["detectors"]
    if "TSFM" in dets and not config["detect"]["tsfm"].get("adapter"):
        out.append("TSFM is listed but detect.tsfm.adapter is not set")
    cap = config["agent"].get("max_total_cost_usd")
    if (
        t.get("agent", True)
        and not placeholders(cap)
        and not (isinstance(cap, int | float) and cap > 0)
    ):
        out.append("agent.max_total_cost_usd must be a positive number for the sealed agent run")
    if not out and isinstance(regimes, dict):
        for name in regimes:
            w = regime_config(config, name)["world"]
            if [h for h in held if h not in w["faults"]["types"]]:
                out.append(f"regime {name!r} drops a held-out fault type")
    return out
