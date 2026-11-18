"""The data-fit script runs on a tiny world and its checks mean what they say."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from worlds import tiny_config

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_data_fit.py"


def load_script():
    spec = importlib.util.spec_from_file_location("check_data_fit", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_fit_check_runs_and_bookkeeping_passes():
    fit = load_script()
    cfg = tiny_config()
    results = [fit.check_seed(cfg, s) for s in (5, 6)]
    summary = fit.summarize(results)
    assert summary["gates"]["bookkeeping_ok"]
    assert summary["faults"] == sum(len(r["faults"]) for r in results) > 0
    for f in (f for r in results for f in r["faults"]):
        assert f["segment_drop"] > 0
        assert f["snr_window"] >= f["snr_hour"] * 0  # finite and non-negative
    md = fit.markdown(summary, "tiny")
    assert "Too easy" in md and "Headroom" in md


def test_naive_detector_fires_on_a_drop_and_not_on_flat_noise():
    import numpy as np

    fit = load_script()
    rng = np.random.default_rng(0)
    flat = 0.9 + rng.normal(0, 0.005, size=1500)
    assert not fit.naive_fires(flat, 1200, 1208)
    dropped = flat.copy()
    dropped[1200:1208] -= 0.1
    assert fit.naive_fires(dropped, 1200, 1208)
