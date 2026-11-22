"""The instrumentation behind #656's architectural baseline (PR 1).

The baseline JSON is a snapshot, not a ratchet; PR 5 decides which measures
become CI guards. These tests cover the parsers and the committed baseline's
shape, not a full re-scan of the repository (which the script's CLI performs).
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

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
        "import acessilia_sdk\n"
        "from docstruct.fusion import payload\n"
        "from . import sibling\n"
        "from backend.api import routes\n"
        "import httpx\n"
    )

    assert quality._imported_components(tree, "core") == {
        "sdk",
        "docstruct",
        "core",
        "backend",
    }


def _record(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> quality.FunctionRecord:
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


def test_a_trivial_function_has_no_duplicate_fingerprint() -> None:
    node = ast.parse("def tiny(value):\n    return value\n").body[0]
    assert quality._fingerprint(node) is None


def test_cycles_are_reported_canonically() -> None:
    assert quality._cycles({"core": {"sdk"}, "sdk": {"core"}}) == [["core", "sdk"]]
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
    assert isinstance(data["duplication"]["groups"], list)
    assert data["duplication"]["totals"]["groups"] >= len(data["duplication"]["groups"])
    assert data["hotspots"]["functions"]
    assert data["hotspots"]["modules"]
