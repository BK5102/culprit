"""The agent's read-only tools (CLAUDE.md agent safety rules; methodology M33, M34).

Allow-list: `query_slice`, `forecast`, `decline_reasons`, `latency`. Each one
reads a copy of the observed world cut at the investigation time (`as_of`),
so no tool can see later hours, and nothing here can reach the answer key
(the import-graph test in tests/test_sealed.py covers this module). There are
no write tools, no shell and no network.

Every call gets an id (c1, c2, ...) and goes into a ledger with a flat table
of the numbers it returned, such as `rate` or `issuer=C0-I1.missing_approvals`.
The agent cites numbers by (call id, field); the critic checks the citations
against this ledger, and the reporter copies values from it.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from culprit.investigate.contribution import leaf_window, node_stats
from culprit.investigate.fault_typing import signals
from culprit.segments import DIMS, GEO, canonical, from_arg, geo_level, node_key
from culprit.world import REASONS, ObservedWorld

TOOL_NAMES = ("query_slice", "forecast", "decline_reasons", "latency")
MAX_HOURS = 48
MAX_CHILDREN = 30


class ToolError(ValueError):
    """A tool call was invalid (unknown tool, unknown segment, bad arguments)."""


class ToolBudgetExceeded(RuntimeError):
    """The hard cap on tool calls for this incident was reached."""


def _num(x: float) -> float:
    x = float(x)
    return round(x, 4) if math.isfinite(x) else float("nan")


@dataclass
class ToolCall:
    call_id: str
    name: str
    args: dict[str, Any]
    output: dict[str, Any]
    numbers: dict[str, float] = field(default_factory=dict)


# One key string, in the same form tool output uses. Five nullable fields per tool made 27
# union-typed parameters, over the live API's strict-schema limit of 16 (methodology M51).
SEGMENT_SCHEMA = {
    "type": "string",
    "description": "Segment key as tool output writes it, e.g. issuer=C0-I1|method=card or "
    "gateway=G2; 'total' for everything. Dimensions: " + ", ".join(DIMS) + ".",
}


def _spec(name: str, description: str, extra: dict[str, Any]) -> dict[str, Any]:
    props = {"segment": SEGMENT_SCHEMA, "hours": {"type": "integer"}, **extra}
    return {
        "name": name,
        "description": description,
        "input_schema": {
            "type": "object",
            "properties": props,
            "required": list(props),
            "additionalProperties": False,
        },
    }


TOOL_SPECS = [
    _spec(
        "query_slice",
        "Attempts, approvals, approval rate, expected rate from the same hours of earlier weeks "
        "(drift adjusted), missing approvals and z over the last `hours` hours for a segment. "
        "With `breakdown` set to a dimension, also returns the same numbers for each child.",
        # A choice of dimension or null. Strict tool schemas reject an enum under a type list
        # (live API 400, 2026-11-21), so the two options are separate anyOf branches.
        {"breakdown": {"anyOf": [{"type": "string", "enum": list(DIMS)}, {"type": "null"}]}},
    ),
    _spec(
        "forecast",
        "Hour by hour for the last `hours` hours: actual rate, expected rate, and a 90% "
        "binomial band around the expected rate.",
        {},
    ),
    _spec(
        "decline_reasons",
        "Each decline reason's rate per attempt over the last `hours` hours, the same hours of "
        "the previous 4 weeks, and the change.",
        {},
    ),
    _spec(
        "latency",
        "Mean latency in ms over the last `hours` hours, the same hours of the previous 4 weeks, "
        "and their ratio.",
        {},
    ),
]


class ToolBox:
    def __init__(self, world: ObservedWorld, as_of: int, max_calls: int, weeks: int = 4):
        if as_of > world.n_hours_seen:
            raise ValueError("as_of is beyond the data")
        self._world = world.until(as_of)
        self.as_of = as_of
        self.max_calls = max_calls
        self.weeks = weeks
        self.ledger: list[ToolCall] = []

    @property
    def world(self) -> ObservedWorld:
        """The observed world as visible at `as_of` (read-only use only)."""
        return self._world

    # --- dispatch
    def call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            raise ToolError(f"unknown tool {name!r}; allowed: {', '.join(TOOL_NAMES)}")
        if len(self.ledger) >= self.max_calls:
            raise ToolBudgetExceeded(f"tool-call budget of {self.max_calls} reached")
        segment = self._segment(args.get("segment"))
        hours = int(args.get("hours") or 6)
        if not 1 <= hours <= MAX_HOURS:
            raise ToolError(f"hours must be between 1 and {MAX_HOURS}")
        start = max(0, self.as_of - hours)
        fn = getattr(self, f"_{name}")
        output, numbers = fn(segment, start, args)
        call_id = f"c{len(self.ledger) + 1}"
        output = {"call_id": call_id, "segment": node_key(segment), "hours": hours, **output}
        self.ledger.append(ToolCall(call_id, name, dict(args), output, numbers))
        return output

    def _segment(self, raw: str | dict[str, Any]) -> dict[str, str]:
        try:
            f = from_arg(raw)
        except (KeyError, ValueError) as err:
            raise ToolError(str(err)) from err
        if f and not self._world.segments.exists(f):
            raise ToolError(f"no such segment {node_key(f)!r}")
        return f

    def _children(self, f: dict[str, str], dim: str) -> list[dict[str, str]]:
        """Split f by any dimension it does not already fix (deeper geography allowed)."""
        seg = self._world.segments
        if dim in f or (dim in GEO and GEO.index(dim) < geo_level(f)):
            raise ToolError(f"segment {node_key(f)!r} cannot be split by {dim}")
        values = sorted(set(seg.cols[dim][seg.mask(f)].tolist()))
        return [canonical({**f, dim: v}) for v in values]

    # --- tools
    def _stats(self, f, lw) -> dict[str, float]:
        s = node_stats(self._world, lw, f)
        return {
            "attempts": _num(s.attempts),
            "approved": _num(s.approved),
            "rate": _num(s.rate),
            "expected_rate": _num(s.expected_rate),
            "missing_approvals": _num(s.missing),
            "z": _num(s.z),
        }

    def _query_slice(self, f, start, args):
        lw = leaf_window(self._world, start, self.as_of, self.weeks)
        top = self._stats(f, lw)
        out: dict[str, Any] = dict(top)
        numbers = dict(top)
        dim = args.get("breakdown")
        if dim is not None:
            if dim not in DIMS:
                raise ToolError(f"breakdown must be one of {DIMS}")
            kids = self._children(f, dim)
            rows = sorted(
                ({"segment": node_key(k), **self._stats(k, lw)} for k in kids),
                key=lambda r: -r["missing_approvals"],
            )[:MAX_CHILDREN]
            out["children"] = rows
            for r in rows:
                for k, v in r.items():
                    if k != "segment":
                        numbers[f"{r['segment']}.{k}"] = v
        return out, numbers

    def _forecast(self, f, start, args):
        m = self._world.segments.mask(f)
        rows, numbers = [], {}
        for h in range(start, self.as_of):
            lw = leaf_window(self._world, h, h + 1, self.weeks)
            n = float(lw.attempts[m].sum())
            p = float(lw.expected[m].sum() / n) if n else float("nan")
            band = 1.645 * math.sqrt(p * (1 - p) / n) if n and math.isfinite(p) else float("nan")
            actual = float(lw.approved[m].sum() / n) if n else float("nan")
            row = {
                "hour": h,
                "time": self._world.timeline.time(h).isoformat(),
                "actual_rate": _num(actual),
                "expected_rate": _num(p),
                "low": _num(p - band),
                "high": _num(p + band),
            }
            rows.append(row)
            for k in ("actual_rate", "expected_rate", "low", "high"):
                numbers[f"h{h}.{k}"] = row[k]
        return {"rows": rows}, numbers

    def _decline_reasons(self, f, start, args):
        sig = signals(self._world, f, start, self.as_of, self.weeks)
        rows, numbers = [], {}
        for r in REASONS:
            row = {
                "reason": r,
                "rate_now": _num(sig.reason_rate_now[r]),
                "rate_before": _num(sig.reason_rate_before[r]),
                "change": _num(sig.reason_rise[r]),
            }
            rows.append(row)
            for k in ("rate_now", "rate_before", "change"):
                numbers[f"{r}.{k}"] = row[k]
        return {"reasons": rows}, numbers

    def _latency(self, f, start, args):
        sig = signals(self._world, f, start, self.as_of, self.weeks)
        out = {
            "latency_ms_now": _num(sig.latency_now),
            "latency_ms_before": _num(sig.latency_before),
            "ratio": _num(sig.latency_ratio),
        }
        return out, dict(out)

    # --- helpers for the critic and reporter
    def lookup(self, call_id: str, field_name: str) -> float:
        """A cited number: a ledger name (``z``, ``h1042.actual_rate``) or a path into the
        call's output as the model sees it (``children[0].z``, ``rows[4].actual_rate``)."""
        for c in self.ledger:
            if c.call_id == call_id:
                if field_name in c.numbers:
                    return c.numbers[field_name]
                value = _resolve_path(c.output, field_name)
                if value is None:
                    raise KeyError(f"{call_id} has no number {field_name!r}")
                return value
        raise KeyError(f"no tool call {call_id!r}")

    def queried_segments(self, tool: str = "query_slice") -> set[str]:
        out = set()
        for c in self.ledger:
            if c.name == tool:
                out.add(c.output["segment"])
                out |= {r["segment"] for r in c.output.get("children", [])}
        return out


_PATH_PART = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)(?:\[(\d+)\])?$")


def _resolve_path(output: Any, path: str) -> float | None:
    """The number at a dotted path such as ``children[0].z`` in a tool output, or None.

    Added 2026-11-21 (methodology M51): the first live run cited numbers this way, which the
    prompt allowed ("field from tool output") but the ledger names did not cover.
    """
    node = output
    for part in path.split("."):
        m = _PATH_PART.match(part)
        if m is None or not isinstance(node, dict) or m.group(1) not in node:
            return None
        node = node[m.group(1)]
        if m.group(2) is not None:
            i = int(m.group(2))
            if not isinstance(node, list) or i >= len(node):
                return None
            node = node[i]
    if isinstance(node, bool) or not isinstance(node, int | float):
        return None
    return float(node)
