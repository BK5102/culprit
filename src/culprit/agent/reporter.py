"""The incident report: a fixed template, every number inserted by code (FR15, M37).

Sections: what changed, where, since when, likely cause, confidence, evidence,
what to check next. "What changed" comes straight from the ledger's
query_slice call on the culprit; evidence sentences are the investigator's
claim texts with each {n} placeholder replaced by the cited ledger value. The
report says on its first lines that it is an investigation, not a decision,
and that the data is simulated (CLAUDE.md rule 8).
"""

from __future__ import annotations

from typing import Any

from culprit.agent.tools import ToolBox
from culprit.segments import from_arg, node_key

HEADER = "**Investigation, not a decision.** Simulated data; no real payments."


def fmt(field_name: str, value: float) -> str:
    """Rates as percentages, ratios and z with two decimals, counts as whole numbers."""
    leaf = field_name.rsplit(".", 1)[-1]
    if value != value:  # NaN
        return "not available"
    if "rate" in leaf or leaf in ("low", "high", "change"):
        return f"{100 * value:.2f}%"
    if leaf in ("z", "ratio"):
        return f"{value:.2f}"
    if "latency" in leaf:
        return f"{value:.0f} ms"
    return f"{value:,.0f}"


def fill(text: str, cites: list[dict[str, Any]], tools: ToolBox) -> str:
    out = text
    for i, c in enumerate(cites):
        value = tools.lookup(c["call_id"], c["field"])
        out = out.replace("{" + str(i) + "}", fmt(c["field"], value))
    return out


def render(hypothesis: dict[str, Any], tools: ToolBox, incident_id: str) -> str:
    culprit = from_arg(hypothesis["culprit"])
    key = node_key(culprit)
    tl = tools.world.timeline
    lines = [f"# Incident {incident_id}: {key}", "", HEADER, ""]
    query = next(
        (
            c
            for c in reversed(tools.ledger)
            if c.name == "query_slice" and c.output["segment"] == key
        ),
        None,
    )
    lines.append("## What changed")
    if query is not None:
        n = query.numbers
        missing = fmt("missing_approvals", n["missing_approvals"])
        lines.append(
            f"Over the last {query.output['hours']} hours (tool call {query.call_id}), "
            f"the approval rate of {key} was {fmt('rate', n['rate'])} against an expected "
            f"{fmt('expected_rate', n['expected_rate'])}: {missing} missing approvals, "
            f"z = {fmt('z', n['z'])}."
        )
    lines += [
        "",
        "## Where",
        key,
        "",
        "## Since when",
        f"Hour {hypothesis['since_hour']} ({tl.time(hypothesis['since_hour']).isoformat()}), as "
        "estimated by the investigator.",
        "",
        "## Likely cause",
        hypothesis["fault_type"].replace("_", " "),
        "",
        "## Confidence",
        hypothesis["confidence"],
        "",
        "## Evidence",
    ]
    for claim in hypothesis["claims"]:
        cited = ", ".join(c["call_id"] for c in claim["cites"])
        lines.append(f"- {fill(claim['text'], claim['cites'], tools)} (from {cited})")
    lines += ["", "## What to check next"]
    lines += [f"- {x}" for x in hypothesis.get("next_checks") or ["(none given)"]]
    return "\n".join(lines) + "\n"
