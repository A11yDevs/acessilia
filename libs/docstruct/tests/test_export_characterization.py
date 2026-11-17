"""E1.0: preserve the current exports before extracting a shared walker (#371).

Golden text is byte-exact; Pandoc objects are compared structurally, retaining
array order and all content. The fixture harness only calls public pure APIs.
"""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from docstruct.profiles import OUTPUT_PROFILES

FIXTURES = Path(__file__).resolve().parents[3] / "tests/fixtures/export_snapshots"
SPEC = importlib.util.spec_from_file_location("export_snapshot_capture", FIXTURES / "capture.py")
assert SPEC and SPEC.loader
CAPTURE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CAPTURE)
VARIANTS = list(CAPTURE.variants())


@pytest.mark.parametrize(
    "case,export", VARIANTS,
    ids=[f"{case}-{export['snapshot']}" for case, export in VARIANTS],
)
def test_export_matches_frozen_baseline(case: str, export: dict[str, Any]) -> None:
    document = json.loads((FIXTURES / "inputs" / f"{case}.json").read_text("utf-8"))
    before = deepcopy(document)
    value = CAPTURE.render(document, export)
    assert document == before, "export mutated the canonical input"
    assert json.dumps(document) == json.dumps(before), "export changed input types or key order"
    expected = FIXTURES / "expected" / CAPTURE.filename(case, export)
    if export["kind"] == "pandoc":
        assert value == json.loads(expected.read_text("utf-8"))
    elif export["kind"] == "txt":
        assert "\n".join(value).encode("utf-8") == expected.read_bytes()
        assert value == json.loads(expected.with_suffix(".lines.json").read_text("utf-8"))
    else:
        assert value.encode("utf-8") == expected.read_bytes()


def test_fixtures_cover_block_enum_and_unknown_fallback() -> None:
    schema = json.loads((FIXTURES.parents[2] / "schemas/accessible_document.schema.json").read_text("utf-8"))
    required = set(schema["$defs"]["block"]["properties"]["type"]["enum"])
    found = set()
    for path in (FIXTURES / "inputs").glob("*.json"):
        pending = list(json.loads(path.read_text("utf-8"))["sections"])
        while pending:
            section = pending.pop()
            found.update(block["type"] for block in section.get("blocks", []))
            pending.extend(section.get("children", []))
    assert len(required) == 11
    assert required <= found
    assert "custom" in found
    for kind in ("txt", "html"):
        profiles = {e["profile"] for case, e in VARIANTS if case == "blocks" and e["kind"] == kind}
        assert set(OUTPUT_PROFILES) <= profiles
        assert "unrecognized" in profiles


def test_baseline_keeps_different_title_and_child_label_policies() -> None:
    expected = FIXTURES / "expected/sections"
    lines = json.loads((expected / "txt.lines.json").read_text("utf-8"))
    markdown = (expected / "markdown.md").read_text("utf-8")
    assert lines.count("Repeat") == 2
    assert markdown.count("# Repeat") == 1
    assert "Equation: root_math" in lines
    assert "Equation: child_math" not in lines
    assert any(line.endswith("child_math") for line in lines)
    assert "legacy-alias" in (expected / "html.html").read_text("utf-8")
    assert "legacy-alias" in (expected / "pandoc-docx.json").read_text("utf-8")
    ast = json.loads((expected / "pandoc-docx.json").read_text("utf-8"))
    assert sum(
        block["t"] == "Header" and block["c"][2] == [{"t": "Str", "c": "Repeat"}]
        for block in ast["blocks"]
    ) == 2


def test_baseline_keeps_profile_and_pandoc_target_differences() -> None:
    expected = FIXTURES / "expected/blocks"
    basic = (expected / "txt.txt").read_text("utf-8")
    all_levels = (expected / "txt-html.txt").read_text("utf-8")
    assert "BASIC_ONLY" in basic
    assert "DETAIL_ONLY" not in basic and "TECH_ONLY" not in basic
    assert "DETAIL_ONLY" in all_levels and "TECH_ONLY" in all_levels
    assert "DETAIL_ONLY" in (expected / "html.html").read_text("utf-8")
    assert "DETAIL_ONLY" not in (expected / "html-txt.html").read_text("utf-8")
    html = (expected / "html.html").read_text("utf-8")
    assert 'rowspan="2"' in html and 'colspan="2"' in html and 'scope="rowgroup"' in html
    assert "TECH_ONLY" in (expected / "markdown.md").read_text("utf-8")
    assert "TECH_ONLY" in (expected / "pandoc-docx.json").read_text("utf-8")
    assert r"\\tag{2.1}" in (expected / "pandoc-pdf-ua.json").read_text("utf-8")
    assert r"\\qquad\\text{(2.1)}" in (expected / "pandoc-docx.json").read_text("utf-8")
