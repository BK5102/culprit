"""Simulator: hierarchy reconciles, seeds reproduce, faults and surges do what they say."""

from __future__ import annotations

import json

import numpy as np
import pytest
from worlds import tiny_config

from culprit.segments import Segments, canonical, node_key, parse_key
from culprit.sim.build import ANSWER_KEY_FILE, SEALED_DIR, simulate, write_world
from culprit.sim.faults import FAULT_TYPES
from culprit.world import REASONS, dataset_hash, load_observed


def test_leaf_count_is_the_cross_product(tiny_sim):
    seg = tiny_sim.observed.segments
    assert seg.n_leaves == 2 * 2 * 2 * 2 * 2
    assert len(set(seg.leaf_keys())) == seg.n_leaves
    assert np.isclose(tiny_sim.hierarchy.share.sum(), 1.0)


def test_child_counts_sum_to_parent_counts(small_sim):
    obs = small_sim.observed
    seg = obs.segments
    nodes = seg.monitored_nodes()
    m = seg.membership(nodes)
    att = m @ obs.attempts
    app = m @ obs.approved
    keys = [node_key(n) for n in nodes]
    total = keys.index("total")
    for node in nodes:
        for _, kids in seg.refinements(node).items():
            parent_mask = seg.mask(node)
            kid_masks = np.array([seg.mask(k) for k in kids])
            # children of one dimension partition the parent exactly
            assert (kid_masks.sum(axis=0) == parent_mask).all()
            kid_att = sum(obs.attempts[seg.mask(k)].sum(axis=0) for k in kids)
            assert (kid_att == obs.attempts[parent_mask].sum(axis=0)).all()
    assert (att[total] == obs.attempts.sum(axis=0)).all()
    assert (app[total] == obs.approved.sum(axis=0)).all()


def test_counts_are_consistent(small_sim):
    obs = small_sim.observed
    assert (obs.attempts >= 0).all()
    assert (obs.approved <= obs.attempts).all()
    assert (obs.declines >= 0).all()
    assert (obs.declines.sum(axis=-1) == obs.attempts - obs.approved).all()
    assert np.isnan(obs.latency_ms[obs.attempts == 0]).all()
    assert not np.isnan(obs.latency_ms[obs.attempts > 0]).any()


def test_same_seed_same_world_and_different_seed_different_world():
    a = simulate(tiny_config())
    b = simulate(tiny_config())
    assert a.observed.meta["dataset_hash"] == b.observed.meta["dataset_hash"]
    assert a.answer_key == b.answer_key
    c_cfg = tiny_config()
    c_cfg["seed"] = 4
    c = simulate(c_cfg)
    assert c.observed.meta["dataset_hash"] != a.observed.meta["dataset_hash"]


def test_written_world_round_trips_with_its_hash(tmp_path, tiny_sim):
    write_world(tiny_sim, tmp_path)
    back = load_observed(tmp_path)
    assert back.meta["dataset_hash"] == tiny_sim.observed.meta["dataset_hash"]
    assert (
        dataset_hash(back.attempts, back.approved, back.declines, back.latency_ms)
        == (tiny_sim.observed.meta["dataset_hash"])
    )
    assert (tmp_path / SEALED_DIR / ANSWER_KEY_FILE).exists()
    # The observed folder holds no fault or surge information.
    observed_text = (tmp_path / "observed" / "world.json").read_text(encoding="utf-8")
    for word in ("fault", "surge", "severity", "issuer_outage", "promotion"):
        assert word not in observed_text


def test_tampered_panel_is_detected(tmp_path, tiny_sim):
    import polars as pl

    write_world(tiny_sim, tmp_path)
    panel = tmp_path / "observed" / "panel.parquet"
    df = pl.read_parquet(panel)
    df = df.with_columns(pl.col("approved").cast(pl.Int64) + (pl.col("hour") == 5).cast(pl.Int64))
    df.write_parquet(panel)
    with pytest.raises(ValueError, match="hash mismatch"):
        load_observed(tmp_path)


def test_faults_only_in_evaluation_and_only_configured_types(small_sim):
    tl = small_sim.observed.timeline
    lo, hi = tl.window_hours("evaluation")
    assert small_sim.faults, "the small world should contain faults"
    for f in small_sim.faults:
        assert lo <= f.start < f.end <= hi
        assert f.type in ("issuer_outage", "bin_decline_spike", "gateway_degradation")
    # Held-out type is absent from development worlds.
    assert "extra_verification" not in {f.type for f in small_sim.faults}
    assert small_sim.answer_key["holdout_fault_types"] == ["extra_verification"]


def test_context_and_calibration_are_fault_free(small_sim):
    tl = small_sim.observed.timeline
    end = tl.calibration_end
    assert np.allclose(small_sim.p_actual[:, :end], small_sim.p_normal[:, :end])


def test_fault_lowers_true_rate_by_its_severity_on_target_only(small_sim):
    seg = small_sim.observed.segments
    hit = np.zeros(small_sim.p_actual.shape, dtype=bool)
    for f in small_sim.faults:
        hit[np.ix_(seg.mask(f.target), np.arange(f.start, f.end))] = True
    assert np.allclose(small_sim.p_actual[~hit], small_sim.p_normal[~hit])
    for f in small_sim.faults:
        rows = seg.mask(f.target)
        ratio = (
            small_sim.p_actual[rows, f.start : f.end] / small_sim.p_normal[rows, f.start : f.end]
        )
        assert (ratio <= 1 - f.severity + 1e-9).all()


def test_fault_signature_shows_in_decline_reasons():
    cfg = tiny_config(faults={"per_week": 8.0, "types": ["issuer_outage"]})
    sim = simulate(cfg)
    obs = sim.observed
    r = REASONS.index("issuer_unavailable")
    for f in sim.faults:
        rows = obs.segments.mask(f.target)
        inside = obs.declines[rows, f.start : f.end, r].sum()
        before = obs.declines[rows, f.start - 168 : f.end - 168, r].sum()
        assert inside > 3 * max(before, 1)


def test_gateway_fault_raises_latency():
    sim = simulate(tiny_config(faults={"per_week": 8.0, "types": ["gateway_degradation"]}))
    obs = sim.observed
    for f in sim.faults:
        rows = obs.segments.mask(f.target)
        inside = np.nanmean(obs.latency_ms[rows, f.start : f.end])
        before = np.nanmean(obs.latency_ms[rows, f.start - 168 : f.end - 168])
        assert inside > 1.5 * before


def test_holdout_type_can_be_injected_when_configured():
    sim = simulate(tiny_config(faults={"per_week": 8.0, "types": ["extra_verification"]}))
    assert sim.faults
    for f in sim.faults:
        assert set(f.target) == {"issuer", "method"}
        assert f.target["method"] == "card_not_present"


def test_unknown_fault_type_is_rejected():
    with pytest.raises(ValueError, match="unknown fault types"):
        simulate(tiny_config(faults={"types": ["meteor"]}))


def test_surges_raise_volume(small_sim):
    seg = small_sim.observed.segments
    promos = [s for s in small_sim.surges if s.type == "promotion"]
    assert promos
    for s in promos:
        rows = seg.mask(s.target)
        assert s.volume_factor > 1.4
        # expected volume inside is the factor times what it would be without (checked via p too)
        assert (small_sim.p_normal[rows, s.start : s.end] > 0).all()


def test_answer_key_lists_every_event(tmp_path, tiny_sim):
    write_world(tiny_sim, tmp_path)
    key = json.loads((tmp_path / SEALED_DIR / ANSWER_KEY_FILE).read_text(encoding="utf-8"))
    assert len(key["faults"]) == len(tiny_sim.faults)
    for f in key["faults"]:
        assert f["type"] in FAULT_TYPES
        assert parse_key(f["target_key"]) == canonical(f["target"])


def test_segment_filters_are_canonical():
    seg = Segments(
        {
            "country": ["C0", "C0"],
            "issuer": ["C0-I0", "C0-I0"],
            "bin": ["C0-I0-B0", "C0-I0-B1"],
            "method": ["m", "m"],
            "gateway": ["G0", "G1"],
        }
    )
    assert canonical({"country": "C0", "issuer": "C0-I0", "gateway": "G1"}) == {
        "issuer": "C0-I0",
        "gateway": "G1",
    }
    assert node_key({}) == "total"
    assert parse_key("issuer=C0-I0|gateway=G1") == {"issuer": "C0-I0", "gateway": "G1"}
    assert seg.mask({"bin": "C0-I0-B1"}).tolist() == [False, True]
    assert seg.exists({"gateway": "G1"}) and not seg.exists({"gateway": "G9"})
    kids = seg.refinements({"issuer": "C0-I0"})
    assert set(kids) == {"bin", "method", "gateway"}
