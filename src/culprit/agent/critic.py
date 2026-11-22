"""The critic: deterministic checks on a hypothesis before any report is written (M36).

A hypothesis is what the investigator submits:

    {"culprit": {segment filter}, "fault_type": str, "since_hour": int,
     "confidence": "low" | "medium" | "high",
     "claims": [{"text": "Approval rate fell to {0} against an expected {1}.",
                 "cites": [{"call_id": "c2", "field": "rate", "value": null}, ...]}],
     "next_checks": [str, ...]}

Numbers never appear in claim text; the text holds placeholders {0}, {1}, ...
that point at its citations, and the reporter fills them from the tool ledger
(CLAUDE.md rule 7). The critic rejects a hypothesis when:

- the culprit segment does not exist, or was never looked at with query_slice,
- the fault type or confidence is not one of the allowed values,
- since_hour is after the investigation time,
- there are no claims, a claim cites nothing, a citation points at a call or
  field that is not in the ledger, or a cited value differs from the ledger,
- claim text contains a digit outside a placeholder (segment ids such as
  C0-I1 are allowed), or a placeholder has no matching citation.

An LLM review of whether the evidence supports the claim is planned as a
second stage (PLAN.md Day 25) and is not built yet.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from culprit.agent.tools import ToolBox
from culprit.investigate.fault_typing import FAULT_LABELS
from culprit.segments import from_arg, node_key

CONFIDENCE = ("low", "medium", "high")
PLACEHOLDER = re.compile(r"\{(\d+)\}")
SEGMENT_ID = re.compile(r"\b(?:C\d+(?:-I\d+(?:-B\d+)?)?|G\d+)\b")


@dataclass
class Verdict:
    ok: bool
    problems: list[str] = field(default_factory=list)


def _same(a: float, b: float) -> bool:
    if math.isnan(a) and math.isnan(b):
        return True
    return math.isclose(a, b, rel_tol=1e-6, abs_tol=1e-9)


def check(hypothesis: dict[str, Any], tools: ToolBox) -> Verdict:
    problems: list[str] = []
    seg = tools.world.segments
    try:
        culprit = from_arg(hypothesis.get("culprit"))
    except (KeyError, ValueError) as err:
        culprit = None
        problems.append(f"culprit is not a valid segment: {err}")
    if culprit is not None:
        if not culprit or not seg.exists(culprit):
            problems.append(f"culprit segment {node_key(culprit)} does not exist")
        elif node_key(culprit) not in tools.queried_segments():
            problems.append(f"culprit {node_key(culprit)} was never examined with query_slice")
    if hypothesis.get("fault_type") not in FAULT_LABELS:
        problems.append(f"fault_type must be one of {FAULT_LABELS}")
    if hypothesis.get("confidence") not in CONFIDENCE:
        problems.append(f"confidence must be one of {CONFIDENCE}")
    since = hypothesis.get("since_hour")
    if not isinstance(since, int) or since >= tools.as_of or since < 0:
        problems.append("since_hour must be an hour before the investigation time")
    claims = hypothesis.get("claims") or []
    if not claims:
        problems.append("there are no claims")
    for i, claim in enumerate(claims):
        cites = claim.get("cites") or []
        text = claim.get("text") or ""
        if not cites:
            problems.append(f"claim {i} cites no tool output")
        for j, c in enumerate(cites):
            try:
                value = tools.lookup(c.get("call_id", ""), c.get("field", ""))
            except KeyError as err:
                problems.append(f"claim {i} citation {j}: {err.args[0]}")
                continue
            given = c.get("value")
            if given is not None and not _same(float(given), value):
                problems.append(
                    f"claim {i} citation {j}: value {given} is not the tool output {value}"
                )
        refs = {int(n) for n in PLACEHOLDER.findall(text)}
        if any(r >= len(cites) for r in refs):
            problems.append(f"claim {i} has a placeholder with no citation")
        bare = SEGMENT_ID.sub("", PLACEHOLDER.sub("", text))
        if re.search(r"\d", bare):
            problems.append(f"claim {i} types a number into its text; cite it with a placeholder")
    return Verdict(not problems, problems)
