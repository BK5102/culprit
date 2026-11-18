"""The CLI runs the small config end to end on CPU in under a minute, with provenance."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
import yaml

from culprit.cli import main

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def small_config(tmp_path):
    cfg = yaml.safe_load((ROOT / "configs" / "small.yaml").read_text(encoding="utf-8"))
    cfg["paths"] = {
        "data_dir": str(tmp_path / "data"),
        "artifacts_dir": str(tmp_path / "artifacts"),
        "lock_dir": str(tmp_path / "locks"),
    }
    path = tmp_path / "small.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path, tmp_path


def test_small_config_end_to_end_under_a_minute(small_config, capsys):
    path, tmp = small_config
    t0 = time.perf_counter()
    for cmd in ("simulate", "detect", "attribute", "evaluate"):
        assert main([cmd, str(path)]) == 0
    elapsed = time.perf_counter() - t0
    assert elapsed < 60, f"small config took {elapsed:.1f} s"
    out = tmp / "artifacts" / "small-seed7"
    summary = json.loads((out / "detect" / "summary.json").read_text(encoding="utf-8"))
    assert {d["detector"] for d in summary["detectors"]} == {"A", "A2", "B"}
    for d in summary["detectors"]:
        assert d["threshold"]["alarm_rate"] <= 2.0
    prov = summary["provenance"]
    assert prov["config_hash"] and prov["dataset_hash"] and "git" in prov
    assert "Simulated" in prov["note"]
    graded = json.loads((out / "evaluate" / "grade.json").read_text(encoding="utf-8"))
    assert graded["role"] == "dev" and set(graded["detection"]) == {"A", "A2", "B"}
    assert "Simulated data" in capsys.readouterr().out


def test_sealed_commands_refuse_development_use(small_config):
    path, _ = small_config
    main(["simulate", str(path)])
    with pytest.raises(SystemExit, match="test worlds"):
        main(["seal", str(path)])
    with pytest.raises(SystemExit, match="--sealed"):
        main(["run", str(path)])


def test_attribute_before_detect_says_what_is_missing(small_config):
    path, _ = small_config
    main(["simulate", str(path)])
    with pytest.raises(SystemExit, match="run the earlier step first"):
        main(["attribute", str(path)])
