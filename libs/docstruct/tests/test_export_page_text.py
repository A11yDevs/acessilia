"""Plain text of the PDDL payload's pages (docstruct.export.page_text).

Moved from the core's PDDL orchestrator (#402, Phase 3). The core also covers
it end to end (tests/test_pddl_page_text.py), with its own image text.
"""

from __future__ import annotations

import re

import pytest

from docstruct.export.page_text import DEFAULT_IMAGE_TEXT, blocks_text, pages_text
from docstruct.text.paragraphs import PAGE_HEADING, merge_broken_paragraphs


def test_headings_lists_tables_and_prose() -> None:
    blocks = [
        {"type": "heading", "level": 3, "text": "Section"},
        {"type": "list", "ordered": True, "numbering": "upper-roman", "items": ["a", "b"]},
        {"type": "list", "ordered": False, "items": ["c"]},
        {"type": "table", "rows": [["1", " 2 "]]},
        {"type": "code", "text": " x = 1 "},
    ]

    assert blocks_text(blocks) == "### Section\nI. a\nII. b\n- c\n1 | 2\nx = 1"


@pytest.mark.parametrize(
    ("block", "line"),
    [
        ({"type": "image", "alt_text": "A chart"}, "A chart"),
        ({"type": "image"}, DEFAULT_IMAGE_TEXT),
    ],
)
def test_an_image_reads_its_alt_text_or_the_default(block, line) -> None:
    assert blocks_text([block]) == line


def test_the_caller_names_an_image_without_alt_text() -> None:
    assert blocks_text([{"type": "image"}], image_text="Imagem") == "Imagem"
    assert blocks_text([{"type": "image", "alt_text": ""}], image_text="Imagem") == ""


def test_a_table_without_rows_is_read_from_its_ast() -> None:
    block = {"type": "table", "table_ast": {"body": [{"cells": [{"text": "x"}, {"text": "y"}]}]}}
    assert blocks_text([block]) == "x | y"


def test_pages_are_joined_under_their_headers() -> None:
    pages = [{"page_number": 2, "text": " two "}, {"page_number": 3, "text": ""}, {"text": "?"}]

    assert pages_text(pages) == "=== Pagina 2 ===\ntwo\n\n=== Pagina ? ===\n?"


@pytest.mark.parametrize("page_number", [1, 9, 10, 125])
def test_the_page_heading_is_the_marker_merge_broken_paragraphs_keeps(page_number) -> None:
    """The writer and the reader of the header must agree (PAGE_HEADING)."""
    heading = PAGE_HEADING.format(page_number=page_number)
    assert pages_text([{"page_number": page_number, "text": "x"}]).startswith(heading + "\n")

    text = f"a sentence without end\n{heading}\ncontinues here"
    assert merge_broken_paragraphs(text) == text
    # Without the marker the same lines would be joined.
    assert merge_broken_paragraphs("a sentence without end\ncontinues here") == (
        "a sentence without end continues here"
    )


def test_the_heading_is_one_line_with_one_number() -> None:
    assert re.fullmatch(r"=== Pagina \{page_number\} ===", PAGE_HEADING)
