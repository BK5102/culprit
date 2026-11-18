"""The LLM investigator: a tool-use loop with a hard tool-call budget and a cost cap (M35).

One incident in, one hypothesis out. The loop sends the incident brief and the
four read-only tools plus `submit_hypothesis`, runs each requested tool
through the `ToolBox` (cut at the investigation time), and stops when the
model submits, when the tool-call budget or cost cap is hit, or after a
maximum number of turns. The critic then checks the hypothesis, and only an
accepted hypothesis gets a report. Orchestrator, investigator and hypothesis
writer from PLAN.md are one loop here for v0.1; splitting them is future work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from culprit.agent import critic, reporter
from culprit.agent.llm import LLM, MODEL, cost_usd
from culprit.agent.tools import TOOL_SPECS, ToolBox, ToolBudgetExceeded, ToolError
from culprit.detect.budget import Incident
from culprit.investigate.fault_typing import FAULT_LABELS
from culprit.segments import DIMS
from culprit.world import ObservedWorld

SYSTEM = """You investigate drops in payment approval rates on a simulated payment system.
An alarm fired; find the one segment that best explains the drop and its likely cause.

Rules:
- You can only read data through the tools. They are read-only and see nothing after the alarm.
- You have a hard budget of {max_calls} tool calls. Spend them on narrowing down.
- Segments filter on country, issuer, bin, method, gateway (ids like C0, C0-I1, C0-I1-B0, G2).
- Finish by calling submit_hypothesis exactly once.
- Never type a number into claim text. Write placeholders {{0}}, {{1}}, ... and put the matching
  citations (call_id and field from tool output) in `cites`, in the same order. Code inserts the
  numbers. Claims with typed numbers or citations not in tool output are rejected.
- This is an investigation, not a decision. Say what to check next."""

SUBMIT_SPEC = {
    "name": "submit_hypothesis",
    "description": "Submit the final hypothesis: culprit segment, cause, and cited evidence.",
    "input_schema": {
        "type": "object",
        "properties": {
            "culprit": {
                "type": "object",
                "properties": {k: {"type": ["string", "null"]} for k in DIMS},
                "required": list(DIMS),
                "additionalProperties": False,
            },
            "fault_type": {"type": "string", "enum": list(FAULT_LABELS)},
            "since_hour": {"type": "integer"},
            "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string"},
                        "cites": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "call_id": {"type": "string"},
                                    "field": {"type": "string"},
                                    "value": {"type": ["number", "null"]},
                                },
                                "required": ["call_id", "field", "value"],
                                "additionalProperties": False,
                            },
                        },
                    },
                    "required": ["text", "cites"],
                    "additionalProperties": False,
                },
            },
            "next_checks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["culprit", "fault_type", "since_hour", "confidence", "claims", "next_checks"],
        "additionalProperties": False,
    },
}


@dataclass
class InvestigationResult:
    incident_id: str
    status: str  # submitted, budget_exceeded, cost_cap, no_answer, max_turns
    hypothesis: dict[str, Any] | None
    verdict: critic.Verdict | None
    report: str | None
    tool_calls: int
    cost_usd: float
    turns: int
    usage: dict[str, int] = field(default_factory=dict)


def brief(incident: Incident, keys: list[str], world: ObservedWorld) -> str:
    alarms = sorted(incident.alarms, key=lambda a: -a.score)[:10]
    lines = [
        f"Incident {incident.id}. First alarm at hour {incident.first_hour} "
        f"({world.timeline.time(incident.first_hour).isoformat()}).",
        "Alarmed series (strongest first):",
    ]
    lines += [f"- {keys[a.series]} at hour {a.hour}" for a in alarms]
    return "\n".join(lines)


class Investigator:
    def __init__(
        self,
        llm: LLM,
        max_tool_calls: int = 12,
        max_cost_usd: float = 0.50,
        max_turns: int = 20,
        model: str = MODEL,
    ):
        self.llm = llm
        self.max_tool_calls = max_tool_calls
        self.max_cost_usd = max_cost_usd
        self.max_turns = max_turns
        self.model = model

    def run(self, world: ObservedWorld, incident: Incident, keys: list[str]) -> InvestigationResult:
        tools = ToolBox(world, incident.first_hour + 1, self.max_tool_calls)
        system = SYSTEM.format(max_calls=self.max_tool_calls)
        specs = [*TOOL_SPECS, SUBMIT_SPEC]
        messages: list[dict[str, Any]] = [{"role": "user", "content": brief(incident, keys, world)}]
        usage = {"input_tokens": 0, "output_tokens": 0}
        cost, status, hypothesis, turns = 0.0, "max_turns", None, 0
        for turns in range(1, self.max_turns + 1):  # noqa: B007 - turns is reported
            resp = self.llm.create(system=system, messages=messages, tools=specs)
            for k in usage:
                usage[k] += int(resp.get("usage", {}).get(k, 0))
            cost = cost_usd(resp.get("model", self.model), usage)
            messages.append({"role": "assistant", "content": resp["content"]})
            if cost > self.max_cost_usd:
                status = "cost_cap"
                break
            uses = [b for b in resp["content"] if b.get("type") == "tool_use"]
            if not uses:
                status = "no_answer"
                break
            results = []
            for u in uses:
                if u["name"] == "submit_hypothesis":
                    hypothesis = u["input"]
                    results.append({"type": "tool_result", "tool_use_id": u["id"], "content": "ok"})
                    continue
                try:
                    out = tools.call(u["name"], u["input"])
                    content, is_error = json.dumps(out), False
                except ToolBudgetExceeded as err:
                    content, is_error, status = str(err), True, "budget_exceeded"
                except ToolError as err:
                    content, is_error = str(err), True
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": u["id"],
                        "content": content,
                        "is_error": is_error,
                    }
                )
            if hypothesis is not None:
                status = "submitted"
                break
            if status == "budget_exceeded":
                break
            messages.append({"role": "user", "content": results})
        verdict = critic.check(hypothesis, tools) if hypothesis is not None else None
        report = (
            reporter.render(hypothesis, tools, incident.id)
            if verdict is not None and verdict.ok
            else None
        )
        return InvestigationResult(
            incident.id, status, hypothesis, verdict, report, len(tools.ledger), cost, turns, usage
        )
