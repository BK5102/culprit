"""Agent layer: read-only tools, budgets, critic, reporter, cassettes (no live LLM calls)."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pytest
from worlds import tiny_config

from culprit.agent import critic, reporter
from culprit.agent.investigator import Investigator
from culprit.agent.llm import CassetteLLM, cost_usd, request_digest
from culprit.agent.tools import TOOL_NAMES, TOOL_SPECS, ToolBox, ToolBudgetExceeded, ToolError
from culprit.detect.budget import Alarm, Incident
from culprit.sim.build import simulate

CASSETTE = Path(__file__).parent / "cassettes" / "issuer_outage_handwritten.json"
NULL_SEG = {"country": None, "issuer": None, "bin": None, "method": None, "gateway": None}


@pytest.fixture()
def outage_world():
    cfg = tiny_config(
        faults={"per_week": 0.0}, surges={"promotions_per_week": 0.0, "paydays_per_week": 0.0}
    )
    world = simulate(cfg).observed
    t0 = world.timeline.calibration_end + 30
    assert t0 == 702  # the cassette's since_hour refers to this hour
    rows = world.segments.mask({"issuer": "C0-I1"})
    block = np.ix_(rows, np.arange(t0, t0 + 6))
    world.approved[block] = np.floor(world.approved[block] * 0.6).astype(np.int64)
    incident = Incident("I-test", t0 + 2, t0 + 2, [Alarm(0, t0 + 2, 9.0)])
    keys = [f"series{i}" for i in range(5)]
    return world, incident, keys


def seg(**kw):
    return {**NULL_SEG, **kw}


def test_only_the_four_read_only_tools_exist():
    assert TOOL_NAMES == ("query_slice", "forecast", "decline_reasons", "latency")
    assert [s["name"] for s in TOOL_SPECS] == list(TOOL_NAMES)
    for spec in TOOL_SPECS:
        schema = spec["input_schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_tools_see_nothing_after_the_investigation_time(outage_world):
    world, incident, _ = outage_world
    as_of = incident.first_hour + 1
    args = {"segment": seg(issuer="C0-I1"), "hours": 3, "breakdown": "bin"}
    before = [ToolBox(world, as_of, 10).call(n, args) for n in TOOL_NAMES]
    wrecked = copy.deepcopy(world)
    wrecked.approved[:, as_of:] = 0
    wrecked.latency_ms[:, as_of:] = 99999.0
    after = [ToolBox(wrecked, as_of, 10).call(n, args) for n in TOOL_NAMES]
    assert json.dumps(before, default=str) == json.dumps(after, default=str)


def test_tools_reject_unknown_tools_segments_and_overspending(outage_world):
    world, incident, _ = outage_world
    tb = ToolBox(world, incident.first_hour + 1, max_calls=2)
    with pytest.raises(ToolError):
        tb.call("write_file", {})
    with pytest.raises(ToolError):
        tb.call("query_slice", {"segment": seg(issuer="NOPE"), "hours": 3, "breakdown": None})
    tb.call("latency", {"segment": NULL_SEG, "hours": 3})
    tb.call("latency", {"segment": NULL_SEG, "hours": 3})
    with pytest.raises(ToolBudgetExceeded):
        tb.call("latency", {"segment": NULL_SEG, "hours": 3})
    assert [c.call_id for c in tb.ledger] == ["c1", "c2"]


def test_cassette_investigation_end_to_end(outage_world):
    world, incident, keys = outage_world
    inv = Investigator(CassetteLLM(CASSETTE), max_tool_calls=12, max_cost_usd=0.50)
    result = inv.run(world, incident, keys)
    assert result.status == "submitted"
    assert result.verdict is not None and result.verdict.ok, result.verdict.problems
    assert result.tool_calls == 3
    assert result.cost_usd == pytest.approx(cost_usd("claude-opus-5-5", result.usage))
    report = result.report
    assert report.startswith("# Incident I-test: issuer=C0-I1")
    assert "Investigation, not a decision" in report and "Simulated data" in report
    # Every number in the evidence came from the ledger through the reporter.
    tb = ToolBox(world, incident.first_hour + 1, 12)
    tb.call("query_slice", {"segment": NULL_SEG, "hours": 3, "breakdown": "issuer"})
    out = tb.call("query_slice", {"segment": seg(issuer="C0-I1"), "hours": 3, "breakdown": None})
    assert reporter.fmt("rate", out["rate"]) in report
    assert reporter.fmt("expected_rate", out["expected_rate"]) in report


def hypothesis_and_tools(outage_world):
    world, incident, _ = outage_world
    tb = ToolBox(world, incident.first_hour + 1, 12)
    tb.call("query_slice", {"segment": seg(issuer="C0-I1"), "hours": 3, "breakdown": None})
    hyp = {
        "culprit": seg(issuer="C0-I1"),
        "fault_type": "issuer_outage",
        "since_hour": 702,
        "confidence": "high",
        "claims": [{"text": "Rate {0}.", "cites": [{"call_id": "c1", "field": "rate"}]}],
        "next_checks": [],
    }
    return hyp, tb


def test_critic_accepts_a_clean_hypothesis(outage_world):
    hyp, tb = hypothesis_and_tools(outage_world)
    assert critic.check(hyp, tb).ok


@pytest.mark.parametrize(
    "mutate, problem",
    [
        (lambda h: h["claims"][0].update(text="Rate fell to 61.2%."), "types a number"),
        (lambda h: h["claims"][0]["cites"][0].update(value=0.123), "is not the tool output"),
        (lambda h: h["claims"][0]["cites"][0].update(call_id="c9"), "no tool call"),
        (lambda h: h["claims"][0]["cites"][0].update(field="made_up"), "has no number"),
        (lambda h: h.update(culprit=seg(issuer="C1-I0")), "never examined"),
        (lambda h: h.update(culprit=seg(issuer="ZZ")), "does not exist"),
        (lambda h: h.update(fault_type="aliens"), "fault_type"),
        (lambda h: h.update(since_hour=9999), "since_hour"),
        (lambda h: h.update(claims=[]), "no claims"),
        (lambda h: h["claims"][0].update(text="Rate {0} and {1}."), "placeholder"),
    ],
)
def test_critic_rejects_unsupported_claims(outage_world, mutate, problem):
    hyp, tb = hypothesis_and_tools(outage_world)
    mutate(hyp)
    verdict = critic.check(hyp, tb)
    assert not verdict.ok
    assert any(problem in p for p in verdict.problems), verdict.problems


def test_critic_allows_segment_ids_in_text(outage_world):
    hyp, tb = hypothesis_and_tools(outage_world)
    hyp["claims"][0]["text"] = "Issuer C0-I1 on G1 approved {0}."
    assert critic.check(hyp, tb).ok


def test_cost_cap_stops_the_loop(outage_world):
    world, incident, keys = outage_world
    result = Investigator(CassetteLLM(CASSETTE), max_cost_usd=0.001).run(world, incident, keys)
    assert result.status == "cost_cap" and result.report is None


def test_tool_budget_stops_the_loop(outage_world):
    world, incident, keys = outage_world
    result = Investigator(CassetteLLM(CASSETTE), max_tool_calls=1).run(world, incident, keys)
    assert result.status == "budget_exceeded"
    assert result.tool_calls == 1 and result.report is None


def test_replay_refuses_a_changed_request(tmp_path):
    system, messages = "s", [{"role": "user", "content": "hi"}]
    path = tmp_path / "c.json"
    path.write_text(
        json.dumps(
            [{"request_digest": request_digest(system, messages, []), "response": {"content": []}}]
        ),
        encoding="utf-8",
    )
    assert CassetteLLM(path).create(system=system, messages=messages, tools=[]) == {"content": []}
    with pytest.raises(RuntimeError, match="differs"):
        CassetteLLM(path).create(system="changed", messages=messages, tools=[])


def test_agent_package_never_imports_the_anthropic_sdk_at_module_level():
    import culprit.agent.llm as llm_mod

    text = Path(llm_mod.__file__).read_text(encoding="utf-8")
    top = text.split("class AnthropicLLM")[0]
    assert "import anthropic" not in top
