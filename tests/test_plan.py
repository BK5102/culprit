"""Test plans: placeholders block sealing, worlds expand per regime and seed, and the full
sealed path (seal, commit, sealed run with or without the agent, evaluate) works on tiny worlds.

The agent in the sealed run uses the fake backend from test_agent_cli (no live call).
"""

from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest
import yaml
from test_agent_cli import FakeBackend
from worlds import tiny_config

from culprit.agent import run as agent_run
from culprit.cli import main
from culprit.config import load_config
from culprit.plan import DEV_SEEDS, PlanError, expand_worlds, placeholders, problems

ROOT = Path(__file__).resolve().parents[1]
DRAFT = ROOT / "configs" / "test.yaml"


def filled_plan(**over) -> dict:
    """A tiny, fully chosen plan (not the owner's choices; test values only)."""
    cfg = tiny_config(faults={"types": ["issuer_outage", "extra_verification"]})
    cfg["name"] = "plan"
    cfg["evaluate"]["role"] = "test"
    cfg["budget"]["mode"] = "per_incident"
    cfg["detect"]["detectors"] = ["A2", "TSFM"]
    cfg["detect"]["tsfm"]["adapter"] = "fake"
    cfg["agent"]["max_total_cost_usd"] = 5.0
    cfg["agent"]["max_tokens"] = 1000
    cfg["test"] = {
        "agent": True,
        "seeds": [900001, 900002],
        "regimes": {"base": {}, "second": {"world": {"approval": {"drift_sd": 0.10}}}},
    }
    for k, v in over.items():
        cfg[k] = v
    return cfg


def test_the_plan_has_every_owner_choice_and_no_live_agent():
    """Owner decisions of 2026-11-21 and 2026-11-22 (D13, D16): nothing open, no agent."""
    cfg = load_config(DRAFT)
    assert placeholders(cfg) == []
    assert problems(cfg) == []
    assert cfg["test"]["agent"] is False and cfg["agent"]["max_total_cost_usd"] is None
    assert cfg["budget"]["mode"] == "per_incident"
    assert cfg["agent"]["max_tokens"] == 4000 and cfg["agent"]["max_cost_usd"] == 1.0
    assert len(cfg["test"]["seeds"]) == 5 and not set(cfg["test"]["seeds"]) & DEV_SEEDS
    assert cfg["test"]["regimes"]["second"]["world"]["approval"]["drift_sd"] == 0.10
    # The held-out type is injected in the test worlds and only there.
    assert "extra_verification" in cfg["world"]["faults"]["types"]
    assert cfg["world"]["holdout_fault_types"] == ["extra_verification"]
    for dev in ("small.yaml", "full.yaml"):
        dev_cfg = load_config(ROOT / "configs" / dev)
        assert "extra_verification" not in dev_cfg["world"]["faults"]["types"]


def test_an_unfinished_plan_cannot_be_validated_simulated_or_sealed(capsys, tmp_path):
    raw = yaml.safe_load(DRAFT.read_text(encoding="utf-8"))
    raw["test"]["agent"] = True
    raw["agent"]["max_total_cost_usd"] = "PLACEHOLDER: total USD"
    unfinished = tmp_path / "unfinished.yaml"
    unfinished.write_text(yaml.safe_dump(raw), encoding="utf-8")
    assert main(["validate", str(unfinished)]) == 1
    assert "agent.max_total_cost_usd is a placeholder" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="not ready to seal"):
        main(["seal", str(unfinished)])
    # Placeholder seeds must still stop `simulate` before any test world is built.
    raw = yaml.safe_load(DRAFT.read_text(encoding="utf-8"))
    raw["test"]["seeds"] = "PLACEHOLDER: list of new integer seeds"
    unseeded = tmp_path / "test.yaml"
    unseeded.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(SystemExit, match="test.seeds is still a placeholder"):
        main(["simulate", str(unseeded)])


def test_a_filled_plan_is_ready_and_expands_per_regime_and_seed():
    cfg = filled_plan()
    assert problems(cfg) == []
    worlds = expand_worlds(cfg)
    assert [(w["name"], w["seed"]) for w in worlds] == [
        ("plan-base", 900001),
        ("plan-base", 900002),
        ("plan-second", 900001),
        ("plan-second", 900002),
    ]
    assert worlds[0]["world"]["approval"]["drift_sd"] == 0.05
    assert worlds[2]["world"]["approval"]["drift_sd"] == 0.10
    assert all("extra_verification" in w["world"]["faults"]["types"] for w in worlds)
    # A development config is its own single world.
    assert expand_worlds(tiny_config()) == [tiny_config()]


@pytest.mark.parametrize(
    "mutate, problem",
    [
        (lambda c: c["test"].update(seeds=[sorted(DEV_SEEDS)[0], 900003]), "already used"),
        (lambda c: c["test"].update(seeds=[900001, 900001]), "repeats"),
        (lambda c: c["test"].update(seeds=[]), "non-empty"),
        (lambda c: c["test"].update(regimes={"base": {}}), "at least two regimes"),
        (lambda c: c["test"]["regimes"].update(second={"budget": {"mode": "per_series"}}), "world"),
        (lambda c: c["world"]["faults"].update(types=["issuer_outage"]), "not injected"),
        (lambda c: c["budget"].update(mode="per_page"), "budget.mode"),
        (lambda c: c["agent"].update(max_total_cost_usd=None), "max_total_cost_usd"),
        (lambda c: c["agent"].update(max_total_cost_usd=0), "max_total_cost_usd"),
        (lambda c: c["evaluate"].update(role="dev"), "role"),
        (
            lambda c: c["test"]["regimes"].update(
                second={"world": {"faults": {"types": ["issuer_outage"]}}}
            ),
            "drops a held-out",
        ),
    ],
)
def test_validator_refuses_plans_that_break_the_rules(mutate, problem):
    cfg = filled_plan()
    mutate(cfg)
    found = problems(cfg)
    assert any(problem in p for p in found), found


def test_regime_placeholder_blocks_expansion():
    cfg = filled_plan()
    cfg["test"]["regimes"]["second"] = "PLACEHOLDER: later"
    with pytest.raises(PlanError, match="placeholder"):
        expand_worlds(cfg)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def sealed_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    (repo / ".gitignore").write_text("data/\nartifacts/\n", encoding="utf-8")
    cfg = filled_plan()
    cfg["paths"] = {
        "data_dir": str(repo / "data"),
        "artifacts_dir": str(repo / "artifacts"),
        "lock_dir": str(repo / "locks"),
    }
    cfg["agent"]["cassette_dir"] = str(repo / "cassettes")
    path = repo / "plan.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    git(repo, "add", ".")
    git(repo, "commit", "-q", "-m", "plan")
    fake = FakeBackend()
    monkeypatch.setattr(agent_run, "live_llm", lambda a: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    return repo, path, fake


def test_full_sealed_path_on_a_tiny_plan(sealed_repo, capsys):
    repo, path, fake = sealed_repo
    assert main(["validate", str(path)]) == 0
    assert main(["simulate", str(path)]) == 0
    with pytest.raises(SystemExit, match="only inside"):
        main(["detect", str(path)])  # no peeking at test worlds before the sealed run
    assert main(["seal", str(path), "--note", "test plan"]) == 0
    with pytest.raises(SystemExit, match="not committed"):
        main(["run", str(path), "--sealed", "r1"])  # lock not committed yet
    git(repo, "add", "locks")
    git(repo, "commit", "-q", "-m", "lock")
    assert main(["run", str(path), "--sealed", "r1"]) == 0
    assert fake.calls > 0
    assert (repo / "cassettes" / "spend-plan.jsonl").exists()
    assert not (repo / "cassettes" / "spend-dev.jsonl").exists()
    assert main(["evaluate", str(path), "--run-id", "r1"]) == 0
    summary = json.loads((repo / "artifacts" / "plan" / "summary.json").read_text("utf-8"))
    assert len(summary["worlds"]) == 4
    assert set(summary["detection"]) == {"A2", "TSFM"}
    assert "TSFM minus A2" in summary["h1"]
    assert set(summary["attribution"]) == {"control", "agent"}
    assert summary["h2_agent_minus_control_top1"] is not None
    assert summary["h2_agent_minus_control_top1"]["n_clusters"] >= 1
    assert set(summary["detection"]["A2"]["by_regime"]) == {"base", "second"}
    text = capsys.readouterr().out
    assert "H1 TSFM" in text and "H2 agent minus control" in text
    uses = list((repo / "locks").glob("*.uses.jsonl"))[0].read_text(encoding="utf-8")
    assert '"started"' in uses and '"finished"' in uses


def test_a_sealed_run_without_the_agent_makes_no_call_and_reports_the_control_only(
    sealed_repo, monkeypatch, capsys
):
    """The owner's plan (D16): no key needed, no spend log, H2a only."""
    repo, path, fake = sealed_repo
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["test"]["agent"] = False
    cfg["agent"]["max_total_cost_usd"] = None
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    git(repo, "commit", "-q", "-am", "no agent")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert main(["validate", str(path)]) == 0
    assert main(["simulate", str(path)]) == 0
    assert main(["seal", str(path)]) == 0
    git(repo, "add", "locks")
    git(repo, "commit", "-q", "-m", "lock")
    assert main(["run", str(path), "--sealed", "r4"]) == 0
    assert fake.calls == 0
    assert not (repo / "cassettes").exists()
    assert main(["evaluate", str(path), "--run-id", "r4"]) == 0
    summary = json.loads((repo / "artifacts" / "plan" / "summary.json").read_text("utf-8"))
    assert set(summary["attribution"]) == {"control"}
    assert summary["h2_agent_minus_control_top1"] is None
    assert summary["agent_cost"] is None
    assert "H2 control: top-1" in capsys.readouterr().out


def test_a_changed_agent_prompt_needs_a_new_lock(sealed_repo, monkeypatch):
    repo, path, _ = sealed_repo
    main(["simulate", str(path)])
    main(["seal", str(path)])
    git(repo, "add", "locks")
    git(repo, "commit", "-q", "-m", "lock")
    import culprit.agent.investigator as inv

    monkeypatch.setattr(inv, "SYSTEM", inv.SYSTEM + "\nBe bold.")
    with pytest.raises(SystemExit, match="no lock"):
        main(["run", str(path), "--sealed", "r2"])


def test_sealed_run_refuses_to_start_without_the_agent_key(sealed_repo, monkeypatch):
    repo, path, _ = sealed_repo
    main(["simulate", str(path)])
    main(["seal", str(path)])
    git(repo, "add", "locks")
    git(repo, "commit", "-q", "-m", "lock")
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        main(["run", str(path), "--sealed", "r3"])
    assert not list((repo / "locks").glob("*.uses.jsonl"))  # no attempt was recorded


def test_fit_check_takes_a_regime_but_never_test_seeds(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "check_data_fit", ROOT / "scripts" / "check_data_fit.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    cfg = copy.deepcopy(filled_plan())
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    with pytest.raises(SystemExit, match="never runs on test seeds"):
        mod.main([str(path), "--regime", "second", "--seeds", "900001"])
