"""`culprit agent`: replay cassettes, record new ones through a fake backend, and hard spend caps.

No test makes a live call. "Record" tests swap the live backend for a fake
that serves the hand-written cassette's responses, so the recording, the spend
log and the caps are exercised without a network or a key.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
import yaml
from worlds import tiny_config

from culprit.agent import run as agent_run
from culprit.agent.llm import PRICES, cost_usd, response_cost
from culprit.cli import main

HANDWRITTEN = json.loads(
    (Path(__file__).parent / "cassettes" / "issuer_outage_handwritten.json").read_text(
        encoding="utf-8"
    )
)
FIRST_ALARM = re.compile(r"First alarm at hour (\d+)")


def scripted_response(messages: list[dict]) -> dict:
    """The hand-written exchange for this point of the conversation, since_hour fitted."""
    turn = sum(1 for m in messages if m["role"] == "assistant")
    resp = copy.deepcopy(HANDWRITTEN[turn]["response"])
    first = int(FIRST_ALARM.search(messages[0]["content"]).group(1))
    for block in resp["content"]:
        if block.get("name") == "submit_hypothesis":
            block["input"]["since_hour"] = first - 1
    return resp


class FakeBackend:
    """Stands in for AnthropicLLM. Counts calls; never touches the network."""

    def __init__(self):
        self.calls = 0

    def create(self, *, system, messages, tools):
        self.calls += 1
        return scripted_response(messages)


def handwritten_cassette(first_hour: int) -> list[dict]:
    out = []
    for i, entry in enumerate(HANDWRITTEN):
        e = copy.deepcopy(entry)
        for block in e["response"]["content"]:
            if block.get("name") == "submit_hypothesis":
                block["input"]["since_hour"] = first_hour - 1
        out.append(e if i else {**e, "note": "hand-written test fixture, not a recording"})
    return out


@pytest.fixture()
def world(tmp_path):
    cfg = tiny_config()
    cfg["budget"]["mode"] = "per_incident"  # more incidents in a one-week evaluation window
    cfg["detect"]["detectors"] = ["A2"]  # the investigated detector; keeps the fixture fast
    cfg["agent"]["cassette_dir"] = str(tmp_path / "cassettes")
    cfg["agent"]["max_tokens"] = 1000
    cfg["paths"] = {
        "data_dir": str(tmp_path / "data"),
        "artifacts_dir": str(tmp_path / "artifacts"),
        "lock_dir": str(tmp_path / "locks"),
    }
    path = tmp_path / "tiny.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    assert main(["simulate", str(path)]) == 0
    assert main(["detect", str(path)]) == 0
    assert main(["attribute", str(path)]) == 0
    art = tmp_path / "artifacts" / "tiny-seed3"
    incidents = json.loads((art / "detect" / "incidents.json").read_text(encoding="utf-8"))["A2"]
    assert len(incidents) >= 3, "the fixture world needs a few incidents"
    return path, cfg, art, incidents, tmp_path


def set_agent(path: Path, **kw) -> None:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg["agent"].update(kw)
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")


def test_replay_one_incident_then_grade_it_next_to_the_control(world, capsys):
    path, cfg, art, incidents, tmp = world
    inc = incidents[0]
    cdir = Path(cfg["agent"]["cassette_dir"]) / "tiny-seed3"
    cdir.mkdir(parents=True)
    (cdir / f"{inc['id']}.json").write_text(
        json.dumps(handwritten_cassette(inc["first_hour"])), encoding="utf-8"
    )
    assert main(["agent", str(path), "--incident", "0"]) == 0
    out = json.loads((art / "agent" / "agent.json").read_text(encoding="utf-8"))
    (row,) = out["attributions"]
    assert row["status"] == "submitted" and row["critic_ok"]
    assert row["culprit"] == "issuer=C0-I1" and row["fault_type"] == "issuer_outage"
    assert row["cost_usd"] == pytest.approx(cost_usd("claude-opus-5-5", row["usage"]))
    report = (art / "agent" / "reports" / f"{inc['id']}.md").read_text(encoding="utf-8")
    assert "Investigation, not a decision" in report and "Simulated data" in report
    assert out["provenance"]["dataset_hash"] and out["summary"]["prompt_sha256"]

    # Batch replay: incidents without a cassette are recorded as not run, never guessed.
    assert main(["agent", str(path), "--all"]) == 0
    out = json.loads((art / "agent" / "agent.json").read_text(encoding="utf-8"))
    statuses = [r["status"] for r in out["attributions"]]
    assert statuses[0] == "submitted" and set(statuses[1:]) == {"not_run"}
    assert len(statuses) == len(incidents)

    assert main(["evaluate", str(path)]) == 0
    graded = json.loads((art / "evaluate" / "grade.json").read_text(encoding="utf-8"))
    assert set(graded["attribution"]) == {"control", "agent"}
    assert graded["agent_cost"]["incidents"] == len(incidents)
    assert "agent top-1" in capsys.readouterr().out


def test_agent_needs_a_choice_of_incidents(world):
    path, *_ = world
    with pytest.raises(SystemExit, match="--incident"):
        main(["agent", str(path)])
    with pytest.raises(SystemExit, match="does not exist"):
        main(["agent", str(path), "--incident", "999"])


def test_record_refuses_without_a_key_or_a_total_cap(world, monkeypatch):
    path, *_ = world
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="ANTHROPIC_API_KEY"):
        main(["agent", str(path), "--all", "--record"])
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    with pytest.raises(SystemExit, match="max_total_cost_usd"):
        main(["agent", str(path), "--all", "--record"])


def test_record_saves_cassettes_that_replay_identically(world, monkeypatch):
    path, cfg, art, incidents, _ = world
    fake = FakeBackend()
    monkeypatch.setattr(agent_run, "live_llm", lambda a: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    set_agent(path, max_total_cost_usd=10.0)
    assert main(["agent", str(path), "--all", "--record"]) == 0
    recorded = json.loads((art / "agent" / "agent.json").read_text(encoding="utf-8"))
    assert fake.calls == 3 * len(incidents)
    root = Path(cfg["agent"]["cassette_dir"])
    log = (root / "spend-dev.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == fake.calls
    for inc in incidents:
        entries = json.loads((root / "tiny-seed3" / f"{inc['id']}.json").read_text("utf-8"))
        assert all(e["request_digest"] not in (None, "any") for e in entries)

    # Recording again replays every saved cassette: no new calls, no new spend.
    assert main(["agent", str(path), "--all", "--record"]) == 0
    assert fake.calls == 3 * len(incidents)
    # Plain replay (no key needed) gives the same rows.
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    assert main(["agent", str(path), "--all"]) == 0
    replayed = json.loads((art / "agent" / "agent.json").read_text(encoding="utf-8"))
    keep = ("incident_id", "status", "culprit", "fault_type", "cost_usd", "tool_calls")
    assert [{k: r[k] for k in keep} for r in replayed["attributions"]] == [
        {k: r[k] for k in keep} for r in recorded["attributions"]
    ]


def test_total_cap_stops_the_run_and_holds_across_runs(world, monkeypatch):
    path, cfg, art, incidents, _ = world
    fake = FakeBackend()
    monkeypatch.setattr(agent_run, "live_llm", lambda a: fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    cap = 0.06  # room for about one incident at max_tokens 1000 with the fixture's usage
    set_agent(path, max_total_cost_usd=cap)
    assert main(["agent", str(path), "--all", "--record"]) == 0
    rows = json.loads((art / "agent" / "agent.json").read_text(encoding="utf-8"))["attributions"]
    root = Path(cfg["agent"]["cassette_dir"])
    ledger = agent_run.SpendLedger(root / "spend-dev.jsonl", cap)
    assert 0 < ledger.spent() <= cap
    stopped = [r for r in rows if r["status"] == "total_cap"]
    assert stopped and rows[0]["status"] == "submitted"
    for r in stopped:
        assert not (root / "tiny-seed3" / f"{r['incident_id']}.json").exists()
        assert not (root / "tiny-seed3" / f"{r['incident_id']}.json.partial").exists()

    # A second run under the same cap spends nothing more: the log carries the total.
    calls = fake.calls
    assert main(["agent", str(path), "--all", "--record"]) == 0
    assert ledger.spent() <= cap
    assert fake.calls == calls


def test_per_incident_cap_is_checked_before_each_call(world):
    from culprit.agent.investigator import Investigator
    from culprit.agent.llm import CassetteLLM
    from culprit.cli import _incidents
    from culprit.config import load_config, world_dir
    from culprit.world import load_observed

    path, cfg, art, incidents, tmp = world
    config = load_config(path)
    _, objs, keys = _incidents(config)
    world_obs = load_observed(world_dir(config))
    cas = tmp / "one.json"
    cas.write_text(json.dumps(handwritten_cassette(objs[0].first_hour)), encoding="utf-8")
    probe = Investigator(CassetteLLM(cas), max_tokens=1000, max_cost_usd=1.0)
    full = probe.run(world_obs, objs[0], keys)
    assert full.status == "submitted" and full.llm_calls == 3
    # Under a cap below what the whole investigation cost, the loop stops before the call
    # whose worst case could pass the cap, so the incident never spends more than its cap.
    cap = full.cost_usd / 2
    result = Investigator(CassetteLLM(cas), max_tokens=1000, max_cost_usd=cap).run(
        world_obs, objs[0], keys
    )
    assert result.status == "cost_cap" and result.report is None
    assert result.llm_calls < 3 and result.cost_usd <= cap


def test_unknown_or_fallback_models_are_priced_at_least_as_high():
    usage = {"input_tokens": 1000, "output_tokens": 1000}
    top = max(PRICES.values(), key=lambda p: p[1])
    assert cost_usd("some-new-model", usage) == pytest.approx((top[0] + top[1]) * 1000 / 1e6)
    resp = {"model": "claude-fable-5-2", "usage": usage}
    assert response_cost("claude-opus-5-5", resp) == pytest.approx(
        cost_usd("claude-fable-5-2", usage)
    )
