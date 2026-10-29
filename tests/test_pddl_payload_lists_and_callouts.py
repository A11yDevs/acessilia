"""Blocks the PDDL payload builds from list items and callouts."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

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


def _page(elements: list[ManifestElement]) -> dict[str, Any]:
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
    return payload["pages"][0]


def _blocks(elements: list[ManifestElement]) -> list[dict[str, Any]]:
    return _page(elements)["blocks"]


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


@pytest.mark.parametrize("slide_role,level", [("slide_heading", 2), ("deck_title", 1)])
@pytest.mark.parametrize("callout_type", ["note", "warning"])
def test_slide_heading_takes_precedence_over_inherited_callout(
    slide_role: str, level: int, callout_type: str
) -> None:
    heading = _element(
        1, "title" if level == 1 else "heading", "Slide 37 of 42: vitamin C",
        slide_role=slide_role, callout_id="callout-auto-000045",
        callout_role="content", callout_type=callout_type, callout_title="OH",
    )
    heading.hierarchy_level = level
    page = _page([
        heading,
        _element(2, "paragraph", "A real callout.", callout_id="callout-auto-000045",
                 callout_role="content", callout_type=callout_type, callout_title="OH"),
    ])

    assert page["blocks"][0]["type"] == "heading"
    assert page["blocks"][0]["level"] == level
    assert page["blocks"][1]["type"] == callout_type
    assert page["blocks"][1]["title"] == "OH"
    ast = build_pandoc_ast({"title": "Deck", "language": "en", "sections": [
        {"id": "slide-37", "blocks": page["blocks"]},
    ]})
    assert any(block["t"] == "Header" and block["c"][0] == level for block in ast["blocks"])


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


def test_a_lettered_item_after_a_formula_keeps_its_letter() -> None:
    blocks = _blocks([
        _item(1, "Rewrite the expression", "a)", "group-a"),
        _element(2, "formula", r"\frac{s(t+h)-s(t)}{h}"),
        _item(3, "It is undefined at zero.", "b)", "group-b"),
    ])

    assert blocks[0]["numbering"] == "lower-alpha" and "start" not in blocks[0]
    assert blocks[2]["numbering"] == "lower-alpha" and blocks[2]["start"] == 2


def test_empty_lettered_items_recover_text_from_a_sibling_paragraph() -> None:
    heading = _element(
        1,
        "heading",
        "Slide 37 of 42: vitamin C",
        slide_role="slide_heading",
    )
    heading.hierarchy_level = 2
    items = [
        _item(3, "", "a)", "exercise-list"),
        _item(4, "", "b)", "exercise-list"),
        _item(5, "", "c)", "exercise-list"),
    ]
    item_text = (
        "a) minimum formula of vitamin C "
        "b) mass percent composition of the minimum formula "
        "c) mass percent composition of the molecular formula"
    )
    page = _page(
        [
            heading,
            _element(2, "paragraph", "Calculate the following for vitamin C:"),
            *items,
            _element(6, "paragraph", item_text),
            _element(7, "picture", "Structure of the vitamin C molecule"),
            _element(8, "caption", "Structural formula"),
        ]
    )

    blocks = page["blocks"]
    assert blocks[0]["type"] == "heading"
    assert blocks[0]["level"] == 2
    assert blocks[0]["text"] == "Slide 37 of 42: vitamin C"
    [list_block] = [block for block in blocks if block["type"] == "list"]
    assert list_block["numbering"] == "lower-alpha"
    assert list_block["items"] == [
        "minimum formula of vitamin C",
        "mass percent composition of the minimum formula",
        "mass percent composition of the molecular formula",
    ]
    assert not any(
        block.get("type") == "list"
        and not any(str(item).strip() for item in block.get("items", []))
        for block in blocks
    )
    for item in list_block["items"]:
        assert page["text"].count(item) == 1
    assert "Calculate the following for vitamin C:" in page["text"]
    assert "a) minimum formula" not in page["text"]


def test_an_empty_list_item_without_recoverable_text_is_not_exported() -> None:
    blocks = _blocks([_item(1, "  ", "a)", "exercise-list")])

    assert not any(block.get("type") == "list" for block in blocks)


@pytest.mark.parametrize("source_order", [2, 4, 7], ids=["before", "between", "after"])
def test_recovered_exercise_keeps_its_preamble_before_its_questions(source_order: int) -> None:
    heading = _element(1, "heading", "Slide 37 of 42: vitamin C", slide_role="slide_heading")
    heading.hierarchy_level = 2
    source = _element(
        source_order,
        "paragraph",
        "Calculate the following: a) First question b) Second question c) Third question",
    )
    elements = [
        heading,
        _item(3, "", "a)", "exercise-list"),
        _item(5, "", "b)", "exercise-list"),
        _item(6, "", "c)", "exercise-list"),
        source,
        _element(8, "picture", "Structural formula"),
    ]
    original = [element.model_dump() for element in elements]

    page = _page(elements)

    assert [element.model_dump() for element in elements] == original
    assert [block["type"] for block in page["blocks"]] == [
        "heading", "paragraph", "list", "image"
    ]
    assert page["blocks"][0]["level"] == 2
    assert page["blocks"][1]["id"] == source.id
    assert page["blocks"][1]["text"] == "Calculate the following:"
    assert page["blocks"][2]["items"] == ["First question", "Second question", "Third question"]
    for text in ["Calculate the following:", "First question", "Second question", "Third question"]:
        assert page["text"].count(text) == 1


def test_page_text_numbers_an_ordered_list() -> None:
    page = _page([
        _item(1, "Rewrite the expression", "i.", "group-a"),
        _element(2, "formula", r"\frac{s(t+h)-s(t)}{h}"),
        _item(3, "It is undefined at zero.", "ii.", "group-b"),
        _item(4, "These ideas come back.", "iii.", "group-b"),
    ])

    assert page["blocks"][2]["numbering"] == "lower-roman"
    assert "ii. It is undefined at zero.\niii. These ideas come back." in page["text"]


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


def test_exporters_keep_the_style_of_a_lettered_list() -> None:
    lettered = {**ORDERED, "numbering": "upper-alpha"}

    assert '<ol id="list-1" start="2" type="A">' in document_to_html(
        _document(lettered), profile="html"
    )
    lines = document_to_txt_lines(_document(lettered))
    assert "B. b" in lines and "C. c" in lines
    pandoc = next(
        block for block in build_pandoc_ast(_document(lettered))["blocks"]
        if block["t"] == "OrderedList"
    )
    assert pandoc["c"][0] == [2, {"t": "UpperAlpha"}, {"t": "Period"}]


def test_markdown_numbers_items_by_their_position() -> None:
    """An empty item it drops leaves the numbers the other exports give."""
    with_gap = {**ORDERED, "items": ["b", "", "d"]}

    assert "2. b\n4. d" in document_to_markdown(_document(with_gap))
