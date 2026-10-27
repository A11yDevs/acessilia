"""Blocks the PDDL payload builds from list items and callouts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.agents.pddl_orchestrator import build_pddl_structured_payload
from backend.core.manifest.models import (
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    PageDescriptor,
    ProcessingManifest,
    SourceDocument,
)
from docstruct.export.html import document_to_html
from docstruct.export.markdown import document_to_markdown
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.txt import document_to_txt_lines
from tests.test_pddl_orchestrator import _sample_plan

NOW = datetime(2026, 10, 27, tzinfo=timezone.utc)


def _element(index: int, kind: str, text: str, **metadata: Any) -> ManifestElement:
    return ManifestElement(
        id=f"el-{index}",
        type=kind,
        raw_label=kind,
        reading_order=index,
        hierarchy_level=1,
        text=text,
        page_number=1,
        metadata=metadata,
    )


def _blocks(elements: list[ManifestElement]) -> list[dict[str, Any]]:
    # The Docling lists the items name as their parent, kept off the page.
    all_elements = elements + [
        ManifestElement(
            id=parent, type="group", raw_label="list", reading_order=100 + offset,
            hierarchy_level=0,
        )
        for offset, parent in enumerate(sorted({e.parent_id for e in elements if e.parent_id}))
    ]
    manifest = ProcessingManifest(
        manifest_id="manifest-lists",
        created_at=NOW,
        source=SourceDocument(
            document_id="doc-lists",
            filename="lists.pdf",
            path="/tmp/lists.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="1" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0", started_at=NOW, completed_at=NOW, duration_ms=1
        ),
        title="Lists",
        language="en",
        pages=[PageDescriptor(page_number=1, element_ids=[e.id for e in elements])],
        elements=all_elements,
        obligations=[],
        summary=ManifestSummary(
            page_count=1,
            element_count=len(all_elements),
            observation_count=0,
            obligation_count=0,
            element_types={},
        ),
    )
    payload = build_pddl_structured_payload(
        file_path=Path("/tmp/lists.pdf"),
        manifest=manifest,
        plan=_sample_plan(),
        planner_backend="internal",
        execution_report=None,
        comparison=None,
    )
    return payload["pages"][0]["blocks"]


def _item(index: int, text: str, marker: str, parent: str, **metadata: Any) -> ManifestElement:
    element = _element(index, "list_item", text, enumerated=True, marker=marker, **metadata)
    element.parent_id = parent
    return element


def test_callout_title_comes_from_the_repaired_title_text() -> None:
    """The Toolbox copied the title before the unicode repair fixed its text."""
    broken = "Notes on the r´ esum´ e:"
    blocks = _blocks([
        _element(1, "paragraph", "Notes on the r\u00e9sum\u00e9:",
                 callout_id="callout-auto-000001", callout_role="title",
                 callout_title=broken, is_callout_title=True),
        _element(2, "paragraph", "Letting h approach zero, find v(3).",
                 callout_id="callout-auto-000001", callout_role="content",
                 callout_title=broken),
    ])

    note = next(block for block in blocks if block["type"] == "note")
    assert note["title"] == "Notes on the r\u00e9sum\u00e9:"


def test_numbered_items_of_one_list_become_one_ordered_list() -> None:
    blocks = _blocks([
        _item(1, "First remark.", "1.", "group-a"),
        _item(2, "Second remark.", "2.", "group-a"),
        _item(3, "Third remark.", "3.", "group-a"),
    ])

    assert [block["type"] for block in blocks] == ["list"]
    assert blocks[0]["ordered"] is True
    assert blocks[0]["items"] == ["First remark.", "Second remark.", "Third remark."]
    assert "start" not in blocks[0]


def test_an_item_after_a_formula_carries_the_numbering_on() -> None:
    blocks = _blocks([
        _item(1, "Rewrite the expression", "1.", "group-a"),
        _element(2, "formula", r"\frac{s(t+h)-s(t)}{h}"),
        _item(3, "It is undefined at zero.", "2.", "group-b"),
        _item(4, "These ideas come back.", "3.", "group-b"),
    ])

    assert [block["type"] for block in blocks] == ["list", "math", "list"]
    assert blocks[2]["ordered"] is True
    assert blocks[2]["start"] == 2
    assert blocks[2]["items"] == ["It is undefined at zero.", "These ideas come back."]


def test_bullet_items_stay_unordered() -> None:
    first = _element(1, "list_item", "A bullet.", marker="-")
    first.parent_id = "group-a"
    second = _element(2, "list_item", "Another bullet.", marker="-")
    second.parent_id = "group-a"

    blocks = _blocks([first, second])

    assert [block["type"] for block in blocks] == ["list"]
    assert blocks[0]["ordered"] is False


def _document(block: dict[str, Any]) -> dict[str, Any]:
    return {"title": "Lists", "sections": [{"blocks": [block]}]}


ORDERED = {"id": "list-1", "type": "list", "ordered": True, "start": 2, "items": ["b", "c"]}


def test_exporters_keep_the_start_of_an_ordered_list() -> None:
    assert '<ol id="list-1" start="2"><li>b</li><li>c</li></ol>' in document_to_html(
        _document(ORDERED), profile="html"
    )
    lines = document_to_txt_lines(_document(ORDERED))
    assert "2. b" in lines and "3. c" in lines
    assert "2. b\n3. c" in document_to_markdown(_document(ORDERED))
    pandoc = next(
        block for block in build_pandoc_ast(_document(ORDERED))["blocks"]
        if block["t"] == "OrderedList"
    )
    assert pandoc["c"][0] == [2, {"t": "Decimal"}, {"t": "Period"}]
