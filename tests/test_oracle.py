"""Oracle alerts (development only): one on-time page per fault, graded on its own incident."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from worlds import tiny_config

from culprit.evaluate.oracle import oracle_attribution, oracle_incidents

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "diagnose_control.py"

FAULTS = [
    {"id": "F0", "type": "issuer_outage", "target_key": "issuer=C0-I0", "start_hour": 100},
    {"id": "F1", "type": "gateway_degradation", "target_key": "gateway=G1", "start_hour": 101},
]


def test_oracle_pages_at_the_earliest_hour_the_alarm_rule_allows():
    incs = oracle_incidents(FAULTS, persistence=2)
    assert [i.first_hour for i in incs] == [101, 102]
    assert [i.id for i in incs] == ["oracle-F0", "oracle-F1"]


def _att(inc, culprit, top3, ftype):
    return {
        "incident_id": inc,
        "culprit": culprit,
        "top3": top3,
        "fault_type": ftype,
        "evidence": {"attempts": 50.0},
    }


def test_each_fault_is_graded_on_its_own_incident_even_when_faults_overlap():
    atts = [
        _att("oracle-F0", "issuer=C0-I0", ["issuer=C0-I0"], "issuer_outage"),
        _att("oracle-F1", "issuer=C0-I0", ["issuer=C0-I0", "gateway=G1"], "issuer_outage"),
    ]
    out = oracle_attribution(FAULTS, atts)
    assert out["investigated_faults"] == 2
    assert out["top1"] == 0.5 and out["top3"] == 1.0 and out["fault_type_accuracy"] == 0.5
    assert out["by_type"]["gateway_degradation"]["top1"] == 0.0


def _script():
    spec = importlib.util.spec_from_file_location("diagnose_control", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_diagnosis_runs_detector_and_oracle_alerts_on_a_development_world():
    out = _script().diagnose(tiny_config())
    assert set(out["detector_alerts"]) == {"per_series", "per_incident"}
    assert out["oracle_alerts"]["investigated_faults"] == out["faults"]


def test_diagnosis_refuses_a_test_world():
    cfg = tiny_config()
    cfg["evaluate"]["role"] = "test"
    with pytest.raises(SystemExit, match="development"):
        _script().diagnose(cfg)
