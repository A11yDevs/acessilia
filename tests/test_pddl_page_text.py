"""The plain text of the PDDL payload: each page's blocks, then the pages.

Characterization of ``_render_text_from_blocks`` and ``_render_text_from_pages``
(#402, Phase 3), written on develop before the rendering moved to docstruct.
The page header is also a marker: the service passes this text through
``merge_broken_paragraphs``, which must not join a line across a header.
"""

from __future__ import annotations

import pytest

from backend.core.pipeline.payload import _render_text_from_blocks
from docstruct.export.page_text import pages_text as _render_text_from_pages
from docstruct.text.paragraphs import merge_broken_paragraphs


def test_each_block_kind_has_its_line() -> None:
    blocks = [
        {"type": "heading", "level": 2, "text": " Title "},
        {"type": "heading", "level": 9, "text": "Deep"},
        {"type": "heading", "level": 0, "text": "Shallow"},
        {"type": "paragraph", "text": "  Prose.  "},
        {"type": "list", "ordered": False, "items": [" one ", "two"]},
        {"type": "list", "ordered": True, "start": 3, "numbering": "lower-alpha", "items": ["x", "y"]},
        {"type": "table", "rows": [[" a ", "b"], "not a row", [1, 2]]},
        {"type": "image", "alt_text": "A chart"},
        {"type": "image"},
        {"type": "image", "alt_text": ""},
        {"type": "formula", "text": "x^2"},
        {"type": "paragraph", "text": "   "},
        {"type": "paragraph", "text": 7},
    ]

    assert _render_text_from_blocks(blocks).split("\n") == [
        "## Title",
        "###### Deep",
        "# Shallow",
        "Prose.",
        "- one",
        "- two",
        "c. x",
        "d. y",
        "a | b",
        "1 | 2",
        "A chart",
        "Imagem",
        "",
        "x^2",
    ]


def test_a_table_without_rows_is_read_from_its_ast() -> None:
    block = {
        "type": "table",
        "table_ast": {"body": [{"cells": [{"text": "h1"}, {"text": "h2"}]}]},
    }

    assert _render_text_from_blocks([block]) == "h1 | h2"


def test_no_blocks_is_no_text() -> None:
    assert _render_text_from_blocks([]) == ""
    assert _render_text_from_blocks([{"type": "paragraph", "text": " "}]) == ""


def test_pages_are_joined_under_their_headers_and_empty_pages_are_left_out() -> None:
    pages = [
        {"page_number": 1, "text": " First page. "},
        {"page_number": 2, "text": "   "},
        {"page_number": 3, "text": "Third"},
        {"text": "No number"},
    ]

    assert _render_text_from_pages(pages) == (
        "=== Pagina 1 ===\nFirst page.\n\n"
        "=== Pagina 3 ===\nThird\n\n"
        "=== Pagina ? ===\nNo number"
    )


@pytest.mark.parametrize("page_number", [1, 12, 300])
def test_the_service_does_not_join_a_line_across_a_page_header(page_number) -> None:
    text = _render_text_from_pages([
        {"page_number": page_number - 1 or 1, "text": "a sentence without end"},
        {"page_number": page_number, "text": "continues here"},
    ])

    assert merge_broken_paragraphs(text) == text
