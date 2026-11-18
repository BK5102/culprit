"""Configs: YAML files merged over code defaults, hashed after merging.

The hash is taken over the merged config, so changing a default in code
changes the hash of every config that relies on it (methodology M41).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml
from cleanroom.provenance import config_hash

DEFAULTS: dict[str, Any] = {
    "name": "unnamed",
    "seed": 0,
    "world": {
        "start": "2026-01-05T00:00:00",  # a Monday; the calendar is simulated
        "weeks": {"context": 4, "calibration": 2, "evaluation": 2},
        "hierarchy": {
            "countries": 2,
            "issuers_per_country": 3,
            "bins_per_issuer": 2,
            "methods": ["card_not_present", "card_present"],
            "gateways": 4,
            "share_concentration": 1.0,
        },
        "volume": {
            "mean_attempts_per_hour": 20000,
            "max_timezone_offset": 6,
            "day_noise_sd": 0.08,
            "leaf_day_noise_sd": 0.10,
            "holidays": [{"day": 17, "factor": 0.6}],
        },
        "approval": {
            "base_rate": 0.87,
            "country_sd": 0.25,
            "issuer_sd": 0.35,
            "bin_sd": 0.30,
            "method_sd": 0.30,
            "gateway_sd": 0.10,
            "leaf_sd": 0.15,
            "hour_amplitude": 0.15,
            "drift_phi": 0.9,
            "drift_sd": 0.05,
        },
        "signals": {
            "reason_concentration": 50.0,
            "latency_base_ms": [250, 600],
            "latency_load": 0.15,
            "latency_noise": 0.25,
        },
        "surges": {"promotions_per_week": 2.0, "paydays_per_week": 1.0},
        "faults": {
            "per_week": 5.0,
            "types": ["issuer_outage", "bin_decline_spike", "gateway_degradation"],
        },
        "holdout_fault_types": ["extra_verification"],
    },
    "detect": {
        "detectors": ["A", "A2", "B"],
        "scale_window_hours": 672,
        "baseline_weeks": 4,
        "cusum_k": 0.5,
        "b_level_alpha": 0.05,
        "tsfm": {
            "adapter": None,
            "context_hours": 512,
            "horizon_hours": 24,
            "quantiles": [0.1, 0.5, 0.9],
        },
    },
    "budget": {
        "false_alarms_per_week": 2.0,
        "persistence_hours": 2,
        "group_gap_hours": 6,
        "min_series_attempts": 0,
    },
    "control": {
        "detector": "A2",
        "lookback_hours": 6,
        "min_share": 0.6,
        "min_excess": 0.1,
        "min_z": 3.0,
        "max_depth": 4,
    },
    "agent": {"max_tool_calls": 12, "max_cost_usd": 0.50},
    "evaluate": {"match_grace_hours": 6, "average_ticket_usd": 50.0},
    "paths": {"data_dir": "data/worlds", "artifacts_dir": "artifacts", "lock_dir": "locks"},
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_config(path: str | Path) -> dict[str, Any]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return deep_merge(DEFAULTS, raw)


def make_config(**overrides: Any) -> dict[str, Any]:
    """Defaults plus overrides, for tests and scripts."""
    return deep_merge(DEFAULTS, overrides)


def world_hash(config: dict[str, Any]) -> str:
    """Hash of the settings that define the simulated world (seed included)."""
    return config_hash({"seed": config["seed"], "world": config["world"]})


def world_dir(config: dict[str, Any]) -> Path:
    return Path(config["paths"]["data_dir"]) / f"{config['name']}-seed{config['seed']}"


def artifacts_dir(config: dict[str, Any]) -> Path:
    return Path(config["paths"]["artifacts_dir"]) / f"{config['name']}-seed{config['seed']}"
