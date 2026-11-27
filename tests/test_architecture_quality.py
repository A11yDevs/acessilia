"""The instrumentation behind #656's architectural baseline (PR 1).

The baseline JSON is a snapshot, not a ratchet; PR 5 decides which measures
become CI guards. These tests cover the parsers and the committed baseline's
shape, not a full re-scan of the repository (which the script's CLI performs).
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from scripts import architecture_quality as quality

REPO_ROOT = Path(__file__).resolve().parents[1]
BASELINE_PATH = REPO_ROOT / "docs" / "architecture" / "quality-baseline.json"


def test_component_of_maps_every_scanned_root() -> None:
    expected = {
        "libs/core/src/acessilia_core/pipeline/fusion.py": "core",
        "libs/sdk/src/acessilia_sdk/cli.py": "sdk",
        "libs/docstruct/src/docstruct/canonical.py": "docstruct",
        "backend/api/worker.py": "backend",
        "frontend/telegram/bot.py": "frontend",
        "scripts/architecture_quality.py": None,
        "tests/test_architecture_quality.py": None,
    }
    for path, component in expected.items():
        assert quality._component_of(path) == component


def test_imported_components_maps_absolute_and_relative_imports() -> None:
    tree = ast.parse(
        "import acessilia_core as core\n"
        "from docstruct.fusion import payload\n"
        "from .. import sibling\n"
        "from backend.api import routes\n"
        "import httpx\n"
    )

    assert quality._imported_components(tree, "sdk") == {
        "core",
        "docstruct",
        "sdk",
        "backend",
    }


def _record(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    parents: dict[ast.AST, ast.AST],
) -> quality.FunctionRecord:
    return quality.FunctionRecord(
        component="core",
        path="core/sample.py",
        qualname=quality._qualname(node, parents),
        lines=(node.end_lineno or node.lineno) - node.lineno + 1,
        complexity=quality.complexity(node),
        fingerprint=quality._fingerprint(node),
    )


def test_duplicate_groups_find_structurally_equal_functions() -> None:
    tree = ast.parse(
        "def first(values):\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        if value:\n"
        "            total += value\n"
        "    return total\n"
        "\n"
        "def second(items):\n"
        "    count = 1\n"
        "    for item in items:\n"
        "        if item:\n"
        "            count += item\n"
        "    return count\n"
        "\n"
        "def different(values):\n"
        "    return len(values)\n"
    )
    parents = quality._parents(tree)
    records = [
        _record(node, parents)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    groups, totals = quality._duplicate_groups(records)

    assert [group["size"] for group in groups] == [2]
    assert totals == {"groups": 1, "functions_in_groups": 2, "lines_in_groups": 12}
    assert {function["qualname"] for function in groups[0]["functions"]} == {
        "first",
        "second",
    }


def test_duplicate_groups_can_span_components() -> None:
    tree = ast.parse(
        "def first(values):\n"
        "    total = 0\n"
        "    for value in values:\n"
        "        total += value\n"
        "    return total\n"
        "\n"
        "def second(items):\n"
        "    count = 0\n"
        "    for item in items:\n"
        "        count += item\n"
        "    return count\n"
    )
    parents = quality._parents(tree)
    records = [
        replace(record, component=component, path=path)
        for record, component, path in zip(
            (
                _record(node, parents)
                for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ),
            ("core", "sdk"),
            ("core/sample.py", "sdk/sample.py"),
        )
    ]

    groups, totals = quality._duplicate_groups(records)

    assert totals["groups"] == 1
    assert {function["component"] for function in groups[0]["functions"]} == {
        "core",
        "sdk",
    }


def test_a_trivial_function_has_no_duplicate_fingerprint() -> None:
    node = cast(
        ast.FunctionDef,
        ast.parse("def tiny(value):\n    return value\n").body[0],
    )
    assert quality._fingerprint(node) is None


def test_a_multiline_one_statement_forwarding_wrapper_is_a_duplicate() -> None:
    """#749: one-statement bodies are fingerprinted once they clear the size floor."""
    tree = ast.parse(
        "async def transcribe_region_result(\n"
        "    self,\n"
        "    candidates: list[str],\n"
        "    file_path: Path | None = None,\n"
        "    artifact_id: str | None = None,\n"
        "    *,\n"
        "    use_remote_cache: bool | None = None,\n"
        ") -> RegionTranscription:\n"
        '    """Typed published result."""\n'
        "    return read_document(\n"
        "        await self.transcribe_region(\n"
        "            candidates=candidates,\n"
        "            file_path=file_path,\n"
        "            artifact_id=artifact_id,\n"
        "            use_remote_cache=use_remote_cache,\n"
        "        ),\n"
        "        RegionTranscription,\n"
        "    )\n"
        "\n"
        "async def text_spans_result(\n"
        "    self,\n"
        "    spans: list[str],\n"
        "    source_path: Path | None = None,\n"
        "    source_id: str | None = None,\n"
        "    *,\n"
        "    remote_cache: bool | None = None,\n"
        ") -> TextSpans:\n"
        '    """Typed published result."""\n'
        "    return read_document(\n"
        "        await self.text_spans(\n"
        "            spans=spans,\n"
        "            source_path=source_path,\n"
        "            source_id=source_id,\n"
        "            remote_cache=remote_cache,\n"
        "        ),\n"
        "        TextSpans,\n"
        "    )\n"
    )
    parents = quality._parents(tree)
    records = [
        _record(node, parents)
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]

    assert all(record.fingerprint is not None for record in records)
    groups, totals = quality._duplicate_groups(records)

    assert [group["size"] for group in groups] == [2]
    assert totals["groups"] == 1
    assert {function["qualname"] for function in groups[0]["functions"]} == {
        "transcribe_region_result",
        "text_spans_result",
    }


def test_collapsing_a_forwarder_to_one_statement_keeps_its_group() -> None:
    """Inlining the temporary must not lower the duplicate total (#749).

    The two-statement forwarder still has the same forwarding shape after the
    collapse, and it stays above the whole-function node floor.
    """
    two_statement = (
        "async def first(self):\n"
        "    result = await self.raw_call(\n"
        "        first=1, second=2, third=3, fourth=4\n"
        "    )\n"
        "    return read_result(result, Model)\n"
        "async def second(self):\n"
        "    result = await self.other_call(\n"
        "        first=1, second=2, third=3, fourth=4\n"
        "    )\n"
        "    return read_result(result, Model)\n"
    )
    one_statement = (
        "async def first(self):\n"
        "    return read_result(\n"
        "        await self.raw_call(first=1, second=2, third=3, fourth=4),\n"
        "        Model,\n"
        "    )\n"
        "async def second(self):\n"
        "    return read_result(\n"
        "        await self.other_call(first=1, second=2, third=3, fourth=4),\n"
        "        Model,\n"
        "    )\n"
    )

    for source in (two_statement, one_statement):
        tree = ast.parse(source)
        parents = quality._parents(tree)
        records = [
            _record(node, parents)
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        groups, totals = quality._duplicate_groups(records)

        assert [group["size"] for group in groups] == [2]
        assert totals["groups"] == 1
        assert totals["functions_in_groups"] == 2


def test_a_collapsed_forwarder_below_the_floor_is_non_evidence() -> None:
    """The documented boundary: a shape that shrinks below the floor is ignored."""
    before = ast.parse(
        "async def first(self, a, b, c, d, e, f):\n"
        "    result = await self.raw_call()\n"
        "    return result\n"
    ).body[0]
    after = ast.parse(
        "async def first(self, a, b, c, d, e, f):\n"
        "    return await self.raw_call()\n"
    ).body[0]

    assert quality._node_count(before) >= quality.MIN_DUPLICATE_NODES
    assert quality._fingerprint(before) is not None
    assert quality._node_count(after) < quality.MIN_DUPLICATE_NODES
    assert quality._fingerprint(after) is None


def test_the_duplicate_floor_is_inclusive() -> None:
    """The whole-function floor includes the boundary value itself."""
    below = cast(
        ast.FunctionDef,
        ast.parse(
            "def wrapper(a, b, c, d, e, f, g, h, i, j):\n    return value\n"
        ).body[0],
    )
    at_floor = cast(
        ast.FunctionDef,
        ast.parse(
            "def wrapper(a, b, c, d, e, f, g, h, i, j, k):\n    return value\n"
        ).body[0],
    )

    assert quality._node_count(below) == quality.MIN_DUPLICATE_NODES - 1
    assert quality._node_count(at_floor) == quality.MIN_DUPLICATE_NODES
    assert quality._fingerprint(below) is None
    assert quality._fingerprint(at_floor) is not None


def test_a_docstring_only_body_has_no_duplicate_fingerprint() -> None:
    """A docstring is not a logical statement, even when the signature is large."""
    node = cast(
        ast.FunctionDef,
        ast.parse(
            "def wrapper(\n"
            "    first,\n"
            "    second,\n"
            "    third,\n"
            "    fourth,\n"
            "    fifth,\n"
            "    sixth,\n"
            "    seventh,\n"
            "    eighth,\n"
            "    ninth,\n"
            "    tenth,\n"
            "    eleventh,\n"
            "    twelfth,\n"
            "):\n"
            '    """Only documentation."""\n'
        ).body[0],
    )

    assert quality._node_count(node) >= quality.MIN_DUPLICATE_NODES
    assert quality._fingerprint(node) is None


def test_fingerprinting_an_outer_function_keeps_nested_qualnames() -> None:
    tree = ast.parse(
        "def outer(values):\n"
        "    def inner(value):\n"
        "        return value + 1\n"
        "    total = sum(values)\n"
        "    return total + inner(total)\n"
    )
    parents = quality._parents(tree)
    outer = cast(ast.FunctionDef, tree.body[0])
    inner = cast(ast.FunctionDef, outer.body[0])
    before = quality._qualname(inner, parents)

    quality._fingerprint(outer)

    assert before == "outer.inner"
    assert quality._qualname(inner, parents) == "outer.inner"


def test_cycles_are_reported_canonically() -> None:
    assert quality._cycles({"core": {"sdk"}, "sdk": {"core"}}) == [["core", "sdk"]]
    assert quality._cycles(
        {"core": {"sdk"}, "sdk": {"docstruct"}, "docstruct": {"core"}}
    ) == [["core", "sdk", "docstruct"]]
    assert quality._cycles({"core": {"sdk"}, "sdk": set()}) == []


def test_the_committed_baseline_has_the_expected_shape() -> None:
    data = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))

    assert data["schema_version"] == quality.SCHEMA_VERSION
    assert data["tool"] == "scripts/architecture_quality.py"
    assert re.fullmatch(r"[0-9a-f]{40}", data["rev"])
    assert data["python"]
    assert set(data["components"]) == set(quality.COMPONENTS)
    for component, metrics in data["components"].items():
        assert metrics["files"] > 0, component
        assert metrics["nonblank_lines"] > 0, component
        assert metrics["functions"] > 0, component
    assert data["dependency_cycles"] == []
    assert data["duplication"]["min_nodes"] == quality.MIN_DUPLICATE_NODES
    assert data["duplication"]["floor_policy"] == quality.DUPLICATE_FLOOR_POLICY
    assert isinstance(data["duplication"]["groups"], list)
    assert data["duplication"]["totals"]["groups"] >= len(data["duplication"]["groups"])
    assert data["hotspots"]["functions"]
    assert data["hotspots"]["modules"]
    assert {"path", "nonblank_lines", "total_lines"} <= set(data["hotspots"]["modules"][0])

    fan_in: dict[str, set[str]] = {component: set() for component in quality.COMPONENTS}
    fan_out: dict[str, set[str]] = {component: set() for component in quality.COMPONENTS}
    for edge in data["dependency_edges"]:
        fan_out[edge["from"]].add(edge["to"])
        fan_in[edge["to"]].add(edge["from"])
    assert data["component_coupling"]["fan_in"] == {
        component: len(sources) for component, sources in fan_in.items()
    }
    assert data["component_coupling"]["fan_out"] == {
        component: len(targets) for component, targets in fan_out.items()
    }


def test_an_unknown_revision_is_a_cli_error() -> None:
    with pytest.raises(SystemExit) as caught:
        quality.main(["--rev", "revision-that-does-not-exist"])

    assert caught.value.code == 2
