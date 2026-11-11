"""Unstructured-page placeholders and callout titles (#203; callout_titles, #402)."""
from dataclasses import dataclass, field
from typing import Any

from docstruct.blocks.callouts import callout_titles, dedupe_callout_titles
from docstruct.manifest import DocumentElement
from docstruct.placeholders import (
    UNSTRUCTURED_PAGE_FLAG,
    UNSTRUCTURED_PAGE_LABEL,
    is_unstructured_page_placeholder,
)


def test_placeholder_needs_both_the_label_and_the_flag():
    assert is_unstructured_page_placeholder(UNSTRUCTURED_PAGE_LABEL, {UNSTRUCTURED_PAGE_FLAG: True})
    assert not is_unstructured_page_placeholder(UNSTRUCTURED_PAGE_LABEL, {})
    assert not is_unstructured_page_placeholder(UNSTRUCTURED_PAGE_LABEL, {UNSTRUCTURED_PAGE_FLAG: 0})
    assert not is_unstructured_page_placeholder("text", {UNSTRUCTURED_PAGE_FLAG: True})


def test_callout_title_kept_on_its_first_block_only():
    blocks = [
        {"type": "note", "title": "Tip", "metadata": {"callout_id": "c1"}},
        {"type": "note", "title": "Tip", "metadata": {"callout_id": "c1"}},
        {"type": "warning", "title": "Careful", "metadata": {"callout_id": " c2 "}},
        {"type": "warning", "title": "Careful", "metadata": {"callout_id": "c2"}},
        {"type": "paragraph", "title": "Kept", "metadata": {"callout_id": "c1"}},
        {"type": "note", "title": "No id", "metadata": {}},
        {"type": "note", "title": "No metadata"},
        {"type": "note", "title": "No id", "metadata": {"callout_id": "  "}},
    ]

    dedupe_callout_titles(blocks)

    assert [block.get("title") for block in blocks] == [
        "Tip", None, "Careful", None, "Kept", "No id", "No metadata", "No id",
    ]


def test_callout_dedupe_on_nothing():
    blocks: list = []
    dedupe_callout_titles(blocks)
    assert blocks == []


# callout_titles (moved from the core's PDDL payload, #402)



@dataclass
class _Part:
    text: str | None
    metadata: dict[str, Any] = field(default_factory=dict)


def test_callout_titles_come_from_title_elements_with_text() -> None:
    parts = [
        _Part(" Note ", {"callout_id": "c1", "callout_role": "Title"}),
        _Part("body", {"callout_id": "c1", "callout_role": "content"}),
        _Part("  ", {"callout_id": "c2", "callout_role": "title"}),
        _Part(None, {"callout_id": "c4", "callout_role": "title"}),
        _Part("Numbered", {"callout_id": 7, "callout_role": "TITLE"}),
        _Part("No id", {"callout_role": "title"}),
        _Part("Empty id", {"callout_id": "", "callout_role": "title"}),
    ]

    assert callout_titles(parts) == {"c1": "Note", "7": "Numbered"}


def test_the_last_title_of_a_callout_wins() -> None:
    parts = [
        _Part("First", {"callout_id": "c", "callout_role": "title"}),
        _Part("Second", {"callout_id": "c", "callout_role": "title"}),
    ]

    assert callout_titles(parts) == {"c": "Second"}


def test_document_elements_are_callout_parts() -> None:
    element = DocumentElement(
        id="e1", type="paragraph", raw_label="text", reading_order=1, hierarchy_level=1,
        text="Remember", metadata={"callout_id": "c9", "callout_role": "title"},
    )

    assert callout_titles([element]) == {"c9": "Remember"}
