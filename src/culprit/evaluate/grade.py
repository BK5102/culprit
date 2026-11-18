"""Grading: the only module that reads the answer key (CLAUDE.md rule 1, methodology M39).

Two ways in, both after the run's outputs exist:

- Development worlds (`evaluate.role: dev`): the key is read only after its
  sha256 is checked against the Cleanroom vault record written when the world
  was built, and never for a config whose role is "test".
- Sealed test worlds (`evaluate.role: test`): the key is released only by
  `cleanroom.vault.release_answer_key`, which requires a valid lock committed
  to git, a vault record committed to git (`culprit seal` writes it under
  locks/vaults/), a sealed run recorded as finished, and an unchanged key.
  Every release is logged next to the vault record.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from cleanroom.lock import require_lock
from cleanroom.vault import VaultError, load_vault, release_answer_key

from culprit.evaluate.metrics import attribution_metrics, detection_metrics
from culprit.segments import Segments
from culprit.sim.build import ANSWER_KEY_FILE, SEALED_DIR

VAULT_SUFFIX = ".vault.json"


def sealed_vault_path(config: dict[str, Any], world_name: str) -> Path:
    return Path(config["paths"]["lock_dir"]) / "vaults" / f"{world_name}{VAULT_SUFFIX}"


def dev_answer_key(world_dir: str | Path, config: dict[str, Any]) -> dict[str, Any]:
    if config["evaluate"].get("role", "dev") != "dev":
        raise VaultError("a test world's key opens only through a finished sealed run")
    key = Path(world_dir) / SEALED_DIR / ANSWER_KEY_FILE
    vault = load_vault(key.with_name(key.name + VAULT_SUFFIX))
    data = key.read_bytes()
    if hashlib.sha256(data).hexdigest() != vault.sha256:
        raise VaultError(f"answer key {key} changed since the world was built")
    return json.loads(data)


def sealed_answer_key(
    world_dir: str | Path,
    config: dict[str, Any],
    run_id: str,
    allow_untracked_for_tests: bool = False,
) -> dict[str, Any]:
    world_name = Path(world_dir).name
    lock = require_lock(config, config["paths"]["lock_dir"])
    data = release_answer_key(
        sealed_vault_path(config, world_name),
        lock.path,
        lock.uses_path,
        run_id,
        allow_untracked_for_tests=allow_untracked_for_tests,
    )
    return json.loads(data)


def grade(
    key: dict[str, Any],
    segments: Segments,
    eval_hours: int,
    detection: dict[str, list[dict[str, Any]]],
    incidents: dict[str, list[dict[str, Any]]],
    attributions: dict[str, list[dict[str, Any]]],
    config: dict[str, Any],
) -> dict[str, Any]:
    """Score saved outputs against the key. Inputs are plain dicts from the run's files."""
    tol = float(config["evaluate"]["match_grace_hours"])
    faults, surges = key["faults"], key["surges"]
    out: dict[str, Any] = {
        "world": key["world"],
        "world_hash": key["world_hash"],
        "holdout_fault_types": key["holdout_fault_types"],
        "detection": {
            name: detection_metrics(alarms, faults, surges, segments, eval_hours, tol)
            for name, alarms in detection.items()
        },
        "attribution": {},
    }
    for name, atts in attributions.items():
        source = atts[0]["source_detector"] if atts else None
        incs = incidents.get(source, []) if source else []
        out["attribution"][name] = attribution_metrics(incs, atts, faults, surges, segments, tol)
    return out
