"""Tool schemas must be valid for strict tool use on the live API (methodology M51)."""

from culprit.agent.investigator import SUBMIT_SPEC
from culprit.agent.tools import TOOL_SPECS


def _walk(node, path="$"):
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk(v, f"{path}[{i}]")


def test_no_enum_under_a_type_list():
    """The live API rejects an enum whose node declares a list of types (400, 2026-11-21)."""
    for spec in [*TOOL_SPECS, SUBMIT_SPEC]:
        for path, node in _walk(spec["input_schema"], spec["name"]):
            if "enum" in node:
                assert isinstance(node.get("type"), str), path
                assert None not in node["enum"], path


def test_every_object_forbids_extra_properties():
    """Strict mode needs additionalProperties: false on every object."""
    for spec in [*TOOL_SPECS, SUBMIT_SPEC]:
        for path, node in _walk(spec["input_schema"], spec["name"]):
            if node.get("type") == "object":
                assert node.get("additionalProperties") is False, path


def test_breakdown_accepts_a_dimension_or_null():
    query = next(s for s in TOOL_SPECS if s["name"] == "query_slice")
    branches = query["input_schema"]["properties"]["breakdown"]["anyOf"]
    assert {"type": "null"} in branches
    assert any(b.get("type") == "string" and "issuer" in b["enum"] for b in branches)


def test_citation_paths_resolve_into_tool_output():
    """The critic accepts a path into the output as the model saw it (M51)."""
    from culprit.agent.tools import _resolve_path

    out = {
        "z": -3.5,
        "children": [{"segment": "issuer=C0-I1", "z": -4.0, "missing_approvals": 12}],
        "rows": [{"hour": 1042, "actual_rate": 0.81}],
    }
    assert _resolve_path(out, "z") == -3.5
    assert _resolve_path(out, "children[0].z") == -4.0
    assert _resolve_path(out, "children[0].missing_approvals") == 12.0
    assert _resolve_path(out, "rows[0].actual_rate") == 0.81
    for bad in ("children[1].z", "children[0].segment", "children.z", "rows[0]", "nope", "z[0]"):
        assert _resolve_path(out, bad) is None, bad
