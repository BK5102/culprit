"""The budget-mode comparison runs both modes on a development world and refuses test ones."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from worlds import tiny_config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_budget_modes.py"


def load_script():
    spec = importlib.util.spec_from_file_location("compare_budget_modes", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_both_modes_are_compared_on_the_same_world():
    mod = load_script()
    out = mod.compare(tiny_config())
    assert set(out["modes"]) == {"per_series", "per_incident"}
    for mode, m in out["modes"].items():
        for cal in m["calibration"].values():
            assert cal["mode"] == mode and cal["budget_rate"] <= 2.0
    for name in out["modes"]["per_series"]["calibration"]:
        ser = out["modes"]["per_series"]["calibration"][name]["threshold"]
        inc = out["modes"]["per_incident"]["calibration"][name]["threshold"]
        assert inc <= ser  # counting incidents can only loosen the threshold


def test_comparison_refuses_a_test_world():
    mod = load_script()
    cfg = tiny_config()
    cfg["evaluate"]["role"] = "test"
    with pytest.raises(SystemExit, match="development"):
        mod.compare(cfg)
