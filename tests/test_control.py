"""The deterministic control: contribution, drill-down, fault typing, past-only investigation."""

from __future__ import annotations

import numpy as np
import pytest
from worlds import tiny_config

from culprit.config import make_config
from culprit.detect.budget import Alarm, Incident
from culprit.investigate.contribution import leaf_window, node_stats
from culprit.investigate.control import investigate_incident
from culprit.investigate.drilldown import DrillSettings, drill_down
from culprit.investigate.fault_typing import classify, signals
from culprit.segments import node_key
from culprit.sim.build import simulate
from culprit.sim.faults import FAULT_TYPES

CONTROL = make_config()["control"]


def quiet_world(**overrides):
    cfg = tiny_config(
        faults={"per_week": 0.0}, surges={"promotions_per_week": 0.0, "paydays_per_week": 0.0}
    )
    for k, v in overrides.items():
        cfg["world"][k] = {**cfg["world"].get(k, {}), **v}
    return simulate(cfg).observed


def inject(world, target, t0, hours, keep):
    rows = world.segments.mask(target)
    block = np.ix_(rows, np.arange(t0, t0 + hours))
    world.approved[block] = np.floor(world.approved[block] * keep).astype(np.int64)


@pytest.mark.parametrize(
    "target",
    [
        {"issuer": "C0-I1"},
        {"bin": "C1-I0-B1"},
        {"gateway": "G1"},
        {"issuer": "C1-I1", "method": "card_not_present"},
    ],
)
def test_drill_down_finds_an_injected_drop(target):
    world = quiet_world()
    t0 = world.timeline.calibration_end + 30
    inject(world, target, t0, 6, 0.6)
    lw = leaf_window(world, t0, t0 + 6)
    result = drill_down(world, lw, DrillSettings())
    assert result.culprit == target, result.ranked(5)
    assert result.ranked(3)[0] == result.culprit_key


def test_contribution_counts_rate_changes_not_volume():
    world = quiet_world()
    t0 = world.timeline.calibration_end + 30
    rows = world.segments.mask({"country": "C1"})
    block = np.ix_(rows, np.arange(t0, t0 + 6))
    # Triple volume at the same rate: no missing approvals should appear.
    world.attempts[block] *= 3
    world.approved[block] *= 3
    lw = leaf_window(world, t0, t0 + 6)
    s = node_stats(world, lw, {"country": "C1"})
    assert abs(s.z) < 4
    assert drill_down(world, lw, DrillSettings()).culprit is None


def test_no_drop_means_no_culprit():
    world = quiet_world()
    t0 = world.timeline.calibration_end + 30
    lw = leaf_window(world, t0, t0 + 6)
    assert drill_down(world, lw, DrillSettings()).culprit is None


@pytest.mark.parametrize(
    "ftype", ["issuer_outage", "bin_decline_spike", "gateway_degradation", "extra_verification"]
)
def test_control_names_segment_and_type_of_strong_simulated_faults(ftype):
    cfg = tiny_config(
        weeks={"context": 3, "calibration": 1, "evaluation": 6},
        volume={"mean_attempts_per_hour": 40000},
        faults={"per_week": 1.5 if ftype == "extra_verification" else 3.0, "types": [ftype]},
        surges={"promotions_per_week": 0.0, "paydays_per_week": 0.0},
    )
    sim = simulate(cfg)
    floor = 0.4 * FAULT_TYPES[ftype].severity[1]  # the top 60% of the type's range
    strong = [f for f in sim.faults if f.severity >= floor and f.end - f.start >= 3]
    lone = [
        f
        for f in strong
        if not any(g is not f and g.start < f.end + 6 and f.start < g.end for g in sim.faults)
    ]
    assert lone, "the test world should contain an isolated strong fault"
    right_segment = right_type = 0
    control = {**CONTROL, "lookback_hours": 6}  # a window that covers up to 6 fault hours
    for f in lone:
        hour = min(f.start + 5, f.end - 1)
        inc = Incident("t", hour, hour, [Alarm(0, hour, 9.0)])
        att = investigate_incident(sim.observed, inc, control)
        right_segment += att.culprit == node_key(f.target)
        right_type += att.fault_type == ftype
    # Strong, isolated faults: the control should get most of them, not necessarily all.
    assert right_segment >= 0.75 * len(lone), (right_segment, len(lone))
    assert right_type >= 0.75 * len(lone), (right_type, len(lone))


def test_promotion_is_typed_as_no_fault():
    cfg = tiny_config(
        faults={"per_week": 0.0}, surges={"promotions_per_week": 8.0, "paydays_per_week": 0.0}
    )
    sim = simulate(cfg)
    world = sim.observed
    big = [
        s for s in sim.surges if s.logit_shift < -0.25 and s.start > 700 and s.end - s.start >= 6
    ]
    assert big
    s = big[0]
    sig = signals(world, s.target, s.start, s.start + 4)
    assert sig.dominant_reason == "insufficient_funds"
    assert classify(sig) == "no_fault"


def test_investigation_uses_only_data_up_to_the_alarm():
    world = quiet_world()
    t0 = world.timeline.calibration_end + 30
    inject(world, {"issuer": "C0-I1"}, t0, 6, 0.6)
    inc = Incident("t", t0 + 2, t0 + 2, [Alarm(0, t0 + 2, 9.0)])
    a1 = investigate_incident(world, inc, CONTROL)
    world.approved[:, t0 + 3 :] = 0  # wreck everything after the alarm hour
    world.attempts[:, t0 + 3 :] = 1
    a2 = investigate_incident(world, inc, CONTROL)
    assert a1.to_dict() == a2.to_dict()


def thin_leaf_with_one_decline(world, t0):
    """Make one leaf thin (1 attempt an hour, all approved before t0), then decline once at t0.

    This is the full world's L27 failure in miniature: a pooled rate of exactly 1
    from a handful of past attempts (methodology M48).
    """
    leaf = int(np.flatnonzero(world.segments.mask({"country": "C1"}))[0])
    world.attempts[leaf, :] = 1
    world.approved[leaf, :] = 1
    world.declines[leaf, :, :] = 0
    world.approved[leaf, t0] = 0
    world.declines[leaf, t0, 0] = 1
    return leaf


def test_a_thin_leaf_with_a_spotless_past_does_not_get_a_huge_z():
    world = quiet_world()
    t0 = world.timeline.calibration_end + 30
    leaf = thin_leaf_with_one_decline(world, t0)
    lw = leaf_window(world, t0 - 2, t0 + 1)
    z = lw.missing[leaf] / np.sqrt(lw.variance[leaf])
    # One decline in 3 attempts after 4 of 4 past approvals at each hour is not a 500-sigma event.
    assert z < 4, z


def test_a_thin_leaf_does_not_hide_a_real_drop():
    world = quiet_world()
    t0 = world.timeline.calibration_end + 30
    inject(world, {"issuer": "C0-I1"}, t0 - 2, 3, 0.6)
    thin_leaf_with_one_decline(world, t0)
    lw = leaf_window(world, t0 - 2, t0 + 1)
    result = drill_down(world, lw, DrillSettings())
    assert result.culprit == {"issuer": "C0-I1"}, result.ranked(5)
