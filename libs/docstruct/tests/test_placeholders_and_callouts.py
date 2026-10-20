"""Unstructured-page placeholders and callout title deduplication (#203)."""
from docstruct.blocks.callouts import dedupe_callout_titles
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
