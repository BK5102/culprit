"""Detectors: past-only scores, equal alarm budget, and they catch an obvious fault."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest
from cleanroom.pastonly import assert_past_only
from worlds import tiny_config

from culprit.detect.base import robust_scale_by_day
from culprit.detect.binomial import BinomialCusum
from culprit.detect.budget import alarms, calibrate, group_incidents
from culprit.detect.classical import MSTLDetector
from culprit.detect.run import run_detection
from culprit.detect.seasonal_naive import SeasonalNaive
from culprit.detect.tsfm import (
    MODEL_ID,
    REVISION,
    FakeForecaster,
    TSFMDetector,
    make_forecaster,
)
from culprit.panel import node_panel
from culprit.sim.build import simulate

DETECTORS = {
    "A": lambda: SeasonalNaive(),
    "A2": lambda: BinomialCusum(),
    "A2-cusum": lambda: BinomialCusum(mode="cusum"),
    "B": lambda: MSTLDetector(),
    "TSFM-fake": lambda: TSFMDetector(FakeForecaster(), context_hours=336, horizon=24),
}


@pytest.fixture(scope="module")
def few_series(tiny_sim):
    world = tiny_sim.observed
    seg = world.segments
    nodes = [{}, {"country": "C0"}, {"issuer": "C0-I1"}, {"gateway": "G1"}, seg.leaf_filter(3)]
    panel = node_panel(world, nodes)
    return panel, world.timeline


def long_frame(panel) -> pl.DataFrame:
    n, t = panel.attempts.shape
    return pl.DataFrame(
        {
            "row_id": np.arange(n * t),
            "series": np.repeat(np.arange(n), t),
            "t": np.tile(np.arange(t), n),
            "attempts": panel.attempts.ravel(),
            "approved": panel.approved.ravel(),
        }
    )


def make_builder(det, start: int):
    def build(df: pl.DataFrame) -> pl.DataFrame:
        n = int(df["series"].max()) + 1
        t = int(df["t"].max()) + 1
        att = np.zeros((n, t))
        app = np.zeros((n, t))
        s_idx, t_idx = df["series"].to_numpy(), df["t"].to_numpy()
        att[s_idx, t_idx] = df["attempts"].to_numpy()
        app[s_idx, t_idx] = df["approved"].to_numpy()
        scores = det.score(att, app, start)
        return pl.DataFrame({"row_id": df["row_id"], "score": scores[s_idx, t_idx]})

    return build


@pytest.mark.parametrize("name", sorted(DETECTORS))
def test_scores_use_only_the_past(name, few_series):
    panel, tl = few_series
    df = long_frame(panel)
    start = tl.context_end
    rng = np.random.default_rng(1)
    scored = df.filter(pl.col("t") >= start)["row_id"].to_numpy()
    probes = rng.choice(scored, size=6, replace=False).tolist()
    probes.append(int(df.filter((pl.col("t") == start) & (pl.col("series") == 0))["row_id"][0]))
    assert_past_only(make_builder(DETECTORS[name](), start), df, "t", "row_id", probe_ids=probes)


def test_past_only_check_catches_a_detector_that_peeks():
    class Peeker:
        name = "peek"

        def score(self, attempts, approved, start):
            r = approved / np.maximum(attempts, 1)
            out = np.zeros(r.shape)
            out[:, :-1] = r[:, 1:]  # uses the next hour
            out[:, :start] = np.nan
            return out

    rng = np.random.default_rng(0)
    att = rng.integers(50, 100, size=(2, 400)).astype(float)
    app = np.floor(att * rng.uniform(0.8, 0.95, size=att.shape))

    class P:
        attempts, approved = att, app

    df = long_frame(P)
    probes = df.filter(pl.col("t") == 300)["row_id"].to_list()
    with pytest.raises(AssertionError):
        assert_past_only(make_builder(Peeker(), 200), df, "t", "row_id", probe_ids=probes)


def test_scores_are_nan_before_start_and_finite_after(few_series):
    panel, tl = few_series
    for make in DETECTORS.values():
        s = make().score(panel.attempts, panel.approved, tl.context_end)
        assert np.isnan(s[:, : tl.context_end]).all()
        assert np.isfinite(s[:, tl.context_end :]).all()


def test_robust_scale_never_sees_its_own_day():
    x = np.zeros((1, 200))
    x[0, 100:] = np.arange(100)  # values start changing at hour 100
    s1 = robust_scale_by_day(x, 96, window=48)
    x2 = x.copy()
    x2[0, 96:120] = 1000.0  # change the day being scaled
    s2 = robust_scale_by_day(x2, 96, window=48)
    assert np.allclose(s1[0, 96:120], s2[0, 96:120])


def test_calibration_uses_only_the_calibration_window(few_series):
    panel, tl = few_series
    s = SeasonalNaive().score(panel.attempts, panel.approved, tl.context_end)
    cal = (tl.context_end, tl.calibration_end)
    t1 = calibrate(s, cal, 2.0, 2)
    s2 = s.copy()
    s2[:, tl.calibration_end :] += 100.0
    assert calibrate(s2, cal, 2.0, 2).threshold == t1.threshold


def test_every_detector_meets_the_same_budget_on_calibration():
    cfg = tiny_config()
    cfg["detect"]["detectors"] = ["A", "A2", "B", "TSFM"]
    world = simulate(cfg).observed
    _, results, skipped = run_detection(world, cfg, forecaster=FakeForecaster())
    assert not skipped
    weeks = (world.timeline.calibration_end - world.timeline.context_end) / 168
    for r in results.values():
        assert r.threshold.n_alarms <= cfg["budget"]["false_alarms_per_week"] * weeks
        assert r.threshold.alarm_rate <= cfg["budget"]["false_alarms_per_week"]
        assert all(a.hour >= world.timeline.calibration_end for a in r.alarms)


def test_detectors_catch_a_big_issuer_outage_quickly():
    # No faults and no surges, so the calibration budget is not spent on promotions.
    cfg = tiny_config(faults={"per_week": 0.0}, surges={"promotions_per_week": 0.0})
    sim = simulate(cfg)
    world = sim.observed
    # Inject a clear outage by hand on the observed counts: issuer C0-I0 loses 40% of approvals.
    seg = world.segments
    rows = seg.mask({"issuer": "C0-I0"})
    t0 = world.timeline.calibration_end + 40
    world.approved[np.ix_(rows, np.arange(t0, t0 + 6))] = (
        world.approved[np.ix_(rows, np.arange(t0, t0 + 6))] * 0.6
    ).astype(np.int64)
    cfg["detect"]["detectors"] = ["A", "A2", "B", "TSFM"]
    panel, results, _ = run_detection(world, cfg, forecaster=FakeForecaster())
    issuer = panel.index("issuer=C0-I0")
    for name, r in results.items():
        hits = [a for a in r.alarms if a.series == issuer and t0 <= a.hour <= t0 + 6]
        assert hits, f"{name} missed an obvious outage"
        assert hits[0].hour - t0 <= cfg["budget"]["persistence_hours"] + 1


def test_alarm_rule_fires_once_per_run_and_incidents_group():
    s = np.full((2, 30), 0.0)
    s[0, 5:9] = 5.0  # one run of 4 hours
    s[1, 7:9] = 5.0  # another series, overlapping in time
    s[0, 20:22] = 5.0
    found = alarms(s, 1.0, 2, (0, 30), 0)
    assert [(a.series, a.hour) for a in found] == [(0, 6), (1, 8), (0, 21)]
    inc = group_incidents(found, gap=6)
    assert [len(i.alarms) for i in inc] == [2, 1]


def test_tsfm_module_pins_chronos_bolt_and_imports_no_torch():
    assert MODEL_ID == "amazon/chronos-bolt-tiny"
    assert REVISION == "a0e552de83495b5c28c14c71c374f3e33280b340"
    assert make_forecaster(None) is None
    assert isinstance(make_forecaster("fake"), FakeForecaster)
    with pytest.raises(ValueError):
        make_forecaster("nope")
    import culprit.detect.tsfm as tsfm_mod

    with open(tsfm_mod.__file__, encoding="utf-8") as f:
        before_adapter = f.read().split("class ChronosBoltForecaster")[0]
    assert "import torch" not in before_adapter


def test_fake_forecaster_quantiles_are_ordered():
    rng = np.random.default_rng(0)
    ctx = [0.9 + rng.normal(0, 0.01, 400), np.full(400, np.nan)]
    ctx[1][::3] = 0.8
    fc = FakeForecaster().forecast(ctx, 24, (0.1, 0.5, 0.9))
    assert fc.shape == (2, 24, 3)
    assert (np.diff(fc, axis=-1) >= 0).all()
    assert np.isfinite(fc).all()
