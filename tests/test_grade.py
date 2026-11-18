"""Grading: hand-checked metrics, and the answer key opens only the way it should."""

from __future__ import annotations

import json

import pytest
from cleanroom.guard import sealed_run
from cleanroom.lock import seal
from cleanroom.vault import VaultError, seal_answer_key
from worlds import tiny_config

from culprit.evaluate.grade import dev_answer_key, sealed_answer_key, sealed_vault_path
from culprit.evaluate.metrics import attribution_metrics, detection_metrics
from culprit.segments import Segments
from culprit.sim.build import answer_key_path, simulate, write_world

SEG = Segments(
    {
        "country": ["C0", "C0", "C1", "C1"],
        "issuer": ["C0-I0", "C0-I0", "C1-I0", "C1-I0"],
        "bin": ["C0-I0-B0", "C0-I0-B0", "C1-I0-B0", "C1-I0-B0"],
        "method": ["m", "m", "m", "m"],
        "gateway": ["G0", "G1", "G0", "G1"],
    }
)
FAULT = {
    "id": "F0",
    "type": "issuer_outage",
    "target": {"issuer": "C0-I0"},
    "target_key": "issuer=C0-I0",
    "start_hour": 100,
    "end_hour": 104,  # hours 100 to 103
}
SURGE = {
    "id": "S0",
    "type": "promotion",
    "target": {"country": "C1"},
    "start_hour": 200,
    "end_hour": 206,
}


def test_detection_metrics_by_hand():
    alarms = [
        {"node": "issuer=C0-I0", "hour": 99},  # before the fault: false
        {"node": "country=C0", "hour": 102},  # overlaps the fault's leaves: detects, delay 2
        {"node": "gateway=G0", "hour": 103},  # gateway G0 includes a C0-I0 leaf: matched
        {"node": "country=C1", "hour": 101},  # wrong place: false
        {"node": "country=C1", "hour": 203},  # during the surge: false, a surge trap
        {"node": "issuer=C0-I0", "hour": 106},  # 3 hours after the end, within tolerance 6
    ]
    m = detection_metrics(alarms, [FAULT], [SURGE], SEG, eval_hours=336, tolerance=6)
    assert m["per_fault"][0]["detected"] and m["per_fault"][0]["delay"] == 2.0
    assert m["false_alarms"] == 3
    assert m["false_alarms_per_week"] == pytest.approx(1.5)
    assert m["false_alarms_on_surges"] == 1
    assert m["caught_within_2h"] == 1.0 and m["detection_rate"] == 1.0


def test_attribution_metrics_by_hand():
    incidents = [
        {"id": "I0", "alarms": [{"node": "country=C0", "hour": 102}]},
        {"id": "I1", "alarms": [{"node": "country=C1", "hour": 203}]},
    ]
    atts = [
        {
            "incident_id": "I0",
            "culprit": "bin=C0-I0-B0",
            "top3": ["bin=C0-I0-B0", "issuer=C0-I0"],
            "fault_type": "issuer_outage",
        },
        {
            "incident_id": "I1",
            "culprit": "country=C1",
            "top3": ["country=C1"],
            "fault_type": "no_fault",
        },
    ]
    m = attribution_metrics(incidents, atts, [FAULT], [SURGE], SEG, tolerance=6)
    assert m["top1"] == 0.0 and m["top3"] == 1.0 and m["fault_type_accuracy"] == 1.0
    assert m["surge_incidents"] == 1 and m["surge_incidents_blamed"] == 0


@pytest.fixture()
def written_world(tmp_path):
    cfg = tiny_config()
    cfg["paths"] = {
        "data_dir": str(tmp_path / "data"),
        "artifacts_dir": str(tmp_path / "art"),
        "lock_dir": str(tmp_path / "locks"),
    }
    world_dir = tmp_path / "data" / "tiny-seed3"
    write_world(simulate(cfg), world_dir)
    return cfg, world_dir


def test_dev_key_opens_after_its_checksum_is_checked(written_world):
    cfg, world_dir = written_world
    key = dev_answer_key(world_dir, cfg)
    assert key["faults"] and key["world"] == "tiny-seed3"


def test_dev_key_refuses_a_changed_file(written_world):
    cfg, world_dir = written_world
    path = answer_key_path(world_dir)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["faults"] = []
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(VaultError, match="changed"):
        dev_answer_key(world_dir, cfg)


def test_test_role_never_opens_through_the_dev_path(written_world):
    cfg, world_dir = written_world
    cfg["evaluate"]["role"] = "test"
    with pytest.raises(VaultError):
        dev_answer_key(world_dir, cfg)


def test_sealed_key_opens_only_after_a_finished_sealed_run(written_world):
    cfg, world_dir = written_world
    cfg["evaluate"]["role"] = "test"
    seal(cfg, cfg["paths"]["lock_dir"], note="test")
    vault_path = sealed_vault_path(cfg, world_dir.name)
    seal_answer_key(answer_key_path(world_dir), vault_path=vault_path)
    with pytest.raises(VaultError, match="not recorded"):
        sealed_answer_key(world_dir, cfg, "run-1", allow_untracked_for_tests=True)
    lock_dir = cfg["paths"]["lock_dir"]
    with (
        sealed_run(cfg, lock_dir, "run-1", allow_untracked_lock_for_tests=True),
        pytest.raises(VaultError, match="has not finished"),
    ):
        sealed_answer_key(world_dir, cfg, "run-1", allow_untracked_for_tests=True)
    key = sealed_answer_key(world_dir, cfg, "run-1", allow_untracked_for_tests=True)
    assert key["world"] == "tiny-seed3"
    releases = vault_path.with_name(world_dir.name + ".releases.jsonl")
    assert releases.exists() and "run-1" in releases.read_text(encoding="utf-8")


def test_sealed_key_needs_git_tracking_outside_tests(written_world):
    cfg, world_dir = written_world
    seal(cfg, cfg["paths"]["lock_dir"])
    seal_answer_key(answer_key_path(world_dir), vault_path=sealed_vault_path(cfg, world_dir.name))
    with pytest.raises(VaultError, match="not committed"):
        sealed_answer_key(world_dir, cfg, "run-1")
