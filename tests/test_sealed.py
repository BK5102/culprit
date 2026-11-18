"""The answer key is sealed: no detector, control or agent code has a path to it.

Three checks (CLAUDE.md rule 1, methodology M18):

1. Import graph. Every module the detectors, the deterministic control or the
   agent can import (directly or through other culprit modules) is collected.
   None of them may be `culprit.sim` (which writes the key) or
   `culprit.evaluate` (which reads it).
2. Text. Outside the writer and the grader, no source file names the sealed
   folder or the key file, and restricted modules do no dynamic imports.
3. Runtime. `load_observed` works on a world whose sealed folder is deleted,
   and the observed files contain no fault information (see test_simulator).
   The full pipeline version of this check is in test_pipeline.py.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
PKG = SRC / "culprit"
RESTRICTED_PREFIXES = (
    "culprit.detect",
    "culprit.investigate",
    "culprit.agent",
    "culprit.world",
    "culprit.segments",
    "culprit.config",
    "culprit.panel",
)
FORBIDDEN_PREFIXES = ("culprit.sim", "culprit.evaluate")
KEY_READERS = {"culprit.sim.build", "culprit.evaluate.grade"}


def module_name(path: Path) -> str:
    rel = path.relative_to(SRC).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


MODULES = {module_name(p): p for p in PKG.rglob("*.py")}


def culprit_imports(name: str) -> set[str]:
    tree = ast.parse(MODULES[name].read_text(encoding="utf-8"))
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names if a.name.startswith("culprit")}
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                raise AssertionError(f"{name} uses a relative import; use absolute imports")
            mod = node.module or ""
            if mod.startswith("culprit"):
                out.add(mod)
                # `from culprit.x import y` may import submodule culprit.x.y
                out |= {f"{mod}.{a.name}" for a in node.names if f"{mod}.{a.name}" in MODULES}
    # Importing a.b.c also runs a and a.b
    with_parents = set()
    for m in out:
        parts = m.split(".")
        with_parents |= {".".join(parts[: i + 1]) for i in range(len(parts))}
    return {m for m in with_parents if m in MODULES}


def closure(name: str) -> set[str]:
    seen, todo = set(), [name]
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        todo += list(culprit_imports(m) - seen)
    return seen


def restricted_modules() -> list[str]:
    return sorted(m for m in MODULES if m.startswith(RESTRICTED_PREFIXES))


def test_there_are_restricted_modules_to_check():
    names = restricted_modules()
    assert "culprit.world" in names and "culprit.segments" in names


@pytest.mark.parametrize("name", restricted_modules())
def test_restricted_module_cannot_reach_the_simulator_or_grader(name):
    reach = closure(name)
    bad = sorted(m for m in reach if m.startswith(FORBIDDEN_PREFIXES))
    assert not bad, f"{name} can import {bad}, which has a path to the answer key"


@pytest.mark.parametrize("name", restricted_modules())
def test_restricted_module_does_no_dynamic_imports(name):
    text = MODULES[name].read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            called = fn.id if isinstance(fn, ast.Name) else getattr(fn, "attr", "")
            assert called not in ("__import__", "import_module"), f"{name} imports dynamically"


@pytest.mark.parametrize("name", sorted(MODULES))
def test_only_writer_and_grader_name_the_key(name):
    if name in KEY_READERS:
        return
    text = MODULES[name].read_text(encoding="utf-8")
    for token in ("ANSWER_KEY_FILE", "SEALED_DIR", "answer_key.json", '"sealed"', "'sealed'"):
        assert token not in text, f"{name} mentions {token}"


def test_import_graph_checker_catches_a_leak(tmp_path, monkeypatch):
    """The checker itself works: a fake agent module importing the grader is flagged."""
    fake = tmp_path / "culprit" / "agent" / "leaky.py"
    fake.parent.mkdir(parents=True)
    fake.write_text("from culprit.evaluate.grade import load_answer_key\n", encoding="utf-8")
    monkeypatch.setitem(MODULES, "culprit.agent.leaky", fake)
    reach = closure("culprit.agent.leaky")
    assert "culprit.evaluate.grade" in reach or "culprit.evaluate" in reach


def test_observed_world_loads_without_the_sealed_folder(tmp_path, tiny_sim):
    import shutil

    from culprit.sim.build import SEALED_DIR, write_world
    from culprit.world import load_observed

    write_world(tiny_sim, tmp_path)
    shutil.rmtree(tmp_path / SEALED_DIR)
    world = load_observed(tmp_path)
    assert world.attempts.sum() == tiny_sim.observed.attempts.sum()
