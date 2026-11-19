"""Run the LLM investigator over a world's incidents, from cassettes or live (M43, M44).

One cassette per incident, at `<agent.cassette_dir>/<world>/<incident id>.json`.

- Replay (the default): an incident with a cassette is replayed, and the
  replay checks every request against the recording, so a changed prompt,
  tool or world fails loudly. An incident without one is "not_run".
- Record (`--record`): incidents with a cassette are still replayed (free);
  the others call Claude live and save a new cassette. Needs ANTHROPIC_API_KEY
  in the environment and a total cap (`agent.max_total_cost_usd`) in the
  config; it refuses to start without either.

Spend: every live response is appended, with its cost, to an append-only log
`<agent.cassette_dir>/spend.jsonl`. The log's sum is what has been spent
across all record runs, so the total cap holds across runs, not just within
one. Before every live call the investigator checks that the log's sum plus
the worst case of that call stays within the total cap, and that the
incident's own spend plus the worst case stays within the per-incident cap
(`agent.max_cost_usd`). A cassette is saved only for an incident that ended
on its own terms; one cut off by the total cap is discarded (its spend stays
in the log) and is recorded live again on the next run.

Every incident the agent was asked to investigate gets an attribution row,
including "not_run" and rejected ones (culprit None), so an incident the agent
skipped or got wrong counts as a miss against it when graded. Nothing here
reads the answer key (tests/test_sealed.py).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from culprit.agent.investigator import InvestigationResult, Investigator, prompt_sha256
from culprit.agent.llm import LLM, MODEL, AgentRefusedError, CassetteLLM, response_cost
from culprit.detect.budget import Incident
from culprit.segments import canonical, node_key
from culprit.world import ObservedWorld

SPEND_LOG = "spend.jsonl"
PARTIAL = ".partial"


class AgentSetupError(RuntimeError):
    """The agent cannot run as asked (missing key, missing cap, unknown incident)."""


class SpendLedger:
    """Append-only log of every billed response; its sum is the total spent."""

    def __init__(self, path: str | Path, cap_total: float | None):
        self.path = Path(path)
        self.cap_total = cap_total

    def spent(self) -> float:
        if not self.path.exists():
            return 0.0
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return float(sum(json.loads(x)["cost_usd"] for x in lines if x.strip()))

    def allows(self, worst_case: float) -> bool:
        return self.cap_total is not None and self.spent() + worst_case <= self.cap_total

    def record(self, **entry: Any) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        entry = {"utc": datetime.now(UTC).isoformat(), **entry}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, default=str) + "\n")


class MeteredLLM:
    """Wraps a live backend and logs the cost of every response it returns."""

    def __init__(self, backend: LLM, ledger: SpendLedger, model: str, **details: Any):
        self.backend = backend
        self.ledger = ledger
        self.model = model
        self.details = details

    def create(self, *, system, messages, tools):
        resp = self.backend.create(system=system, messages=messages, tools=tools)
        self.ledger.record(
            model=resp.get("model", self.model),
            usage=resp.get("usage", {}),
            cost_usd=response_cost(self.model, resp),
            **self.details,
        )
        return resp


def live_llm(agent_cfg: dict[str, Any]) -> LLM:  # pragma: no cover - live calls are never tested
    from culprit.agent.llm import AnthropicLLM

    return AnthropicLLM(
        model=agent_cfg["model"], effort=agent_cfg["effort"], max_tokens=agent_cfg["max_tokens"]
    )


def check_record_setup(agent_cfg: dict[str, Any]) -> None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise AgentSetupError(
            "--record makes live, billed calls and needs ANTHROPIC_API_KEY in the environment "
            "(never in git)"
        )
    cap = agent_cfg.get("max_total_cost_usd")
    if cap is None or not cap > 0:
        raise AgentSetupError(
            "--record needs a total spend cap: set agent.max_total_cost_usd (USD) in the config, "
            "and review agent.max_cost_usd (per incident)"
        )


def select_incidents(incidents: list[Incident], which: str | None) -> list[Incident]:
    """`which` is None (all), an index into the list, or an incident id."""
    if which is None:
        return list(incidents)
    if which.isdigit():
        i = int(which)
        if not 0 <= i < len(incidents):
            raise AgentSetupError(f"incident {i} does not exist; there are {len(incidents)}")
        return [incidents[i]]
    found = [x for x in incidents if x.id == which]
    if not found:
        raise AgentSetupError(f"no incident with id {which!r}")
    return found


def attribution(
    result: InvestigationResult | None, incident: Incident, source: str, cassette: Path
) -> dict[str, Any]:
    """The row the grader reads, in the same shape as the control's."""
    row: dict[str, Any] = {
        "incident_id": incident.id,
        "investigator": "agent",
        "source_detector": source,
        "as_of_hour": incident.first_hour + 1,
        "cassette": cassette.as_posix(),
        "status": "not_run",
        "culprit": None,
        "top3": [],
        "fault_type": "unknown",
    }
    if result is None:
        return row
    accepted = result.verdict is not None and result.verdict.ok
    hyp = result.hypothesis or {}
    culprit = None
    if accepted:
        culprit = node_key(canonical({k: v for k, v in hyp["culprit"].items() if v is not None}))
    row.update(
        status=result.status,
        critic_ok=accepted,
        critic_problems=result.verdict.problems if result.verdict else [],
        culprit=culprit,
        top3=[culprit] if culprit else [],
        fault_type=hyp.get("fault_type", "unknown") if accepted else "unknown",
        confidence=hyp.get("confidence") if accepted else None,
        tool_calls=result.tool_calls,
        llm_calls=result.llm_calls,
        turns=result.turns,
        cost_usd=result.cost_usd,
        usage=result.usage,
        models=result.models,
    )
    return row


def run_agent(
    world: ObservedWorld,
    incidents: list[Incident],
    keys: list[str],
    config: dict[str, Any],
    world_name: str,
    record: bool = False,
    backend_factory: Callable[[dict[str, Any]], LLM] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Investigate `incidents`; returns (attribution rows, {incident id: report markdown})."""
    a = config["agent"]
    source = config["control"]["detector"]
    root = Path(a["cassette_dir"])
    ledger = SpendLedger(root / SPEND_LOG, a.get("max_total_cost_usd"))
    if record:
        check_record_setup(a)
    factory = backend_factory or live_llm
    backend: LLM | None = None
    rows: list[dict[str, Any]] = []
    reports: dict[str, str] = {}
    for inc in incidents:
        path = root / world_name / f"{inc.id}.json"
        partial = path.with_name(path.name + PARTIAL)
        guard = None
        if path.exists():
            llm: LLM = CassetteLLM(path)
        elif record:
            backend = backend or factory(a)
            metered = MeteredLLM(backend, ledger, a["model"], world=world_name, incident=inc.id)
            llm = CassetteLLM(partial, mode="record", backend=metered)
            guard = ledger.allows
        else:
            rows.append(attribution(None, inc, source, path))
            continue
        inv = Investigator(
            llm,
            max_tool_calls=a["max_tool_calls"],
            max_cost_usd=a["max_cost_usd"],
            max_turns=a["max_turns"],
            model=a["model"],
            max_tokens=a["max_tokens"],
            total_guard=guard,
        )
        try:
            result = inv.run(world, inc, keys)
        except AgentRefusedError as err:
            row = attribution(None, inc, source, path)
            row.update(status="refused", detail=str(err))
            rows.append(row)
            partial.unlink(missing_ok=True)
            continue
        if guard is not None:
            if result.status == "total_cap":
                partial.unlink(missing_ok=True)
            elif partial.exists():
                partial.replace(path)
            elif result.llm_calls == 0:  # stopped before any call: nothing to replay
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("[]", encoding="utf-8")
        rows.append(attribution(result, inc, source, path))
        if result.report:
            reports[inc.id] = result.report
    return rows, reports


def summary(rows: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    a = config["agent"]
    ran = [r for r in rows if r["status"] != "not_run"]
    costs = sorted(r.get("cost_usd", 0.0) for r in ran)
    statuses: dict[str, int] = {}
    for r in rows:
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    return {
        "model": a["model"],
        "default_model": MODEL,
        "prompt_sha256": prompt_sha256(a["max_tool_calls"]),
        "incidents": len(rows),
        "statuses": statuses,
        "accepted": sum(1 for r in rows if r.get("critic_ok")),
        "total_cost_usd": float(sum(costs)),
        "median_cost_usd": float(costs[len(costs) // 2]) if costs else None,
        "settings": {
            k: a[k] for k in ("max_tool_calls", "max_cost_usd", "max_turns", "max_tokens", "effort")
        },
        "note": "Simulated data. Cassette replays cost nothing; costs are those recorded.",
    }
