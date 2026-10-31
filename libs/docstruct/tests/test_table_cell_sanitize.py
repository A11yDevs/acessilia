"""Canonicalization keeps a leading minus sign (#260).

The reference case's second table has ``−0,0833`` in a cell, extracted as
``- 0 , 0833``; the bullet rule of the block sanitizer used to drop the sign,
which inverts what the table says (the position decreases).
"""
import pytest

from docstruct.blocks.parser import parse_text_to_blocks
from docstruct.canonical import sanitize_canonical_document
from docstruct.export.txt import document_to_txt_lines


def _document(block):
    return {"sections": [{"id": "s1", "title": "T", "level": 1, "blocks": [block]}]}


def _table_block(value="- 0 , 0833 (aproximadamente)"):
    return {
        "id": "t1",
        "type": "table",
        "table_ast": {
            "body": [
                {"cells": [{"text": "h"}, {"text": "velocidade"}]},
                {"cells": [{"text": "1"}, {"text": value}]},
            ]
        },
    }


def _block(document):
    return document["sections"][0]["blocks"][0]


def _cells(document):
    return [cell["text"] for row in _block(document)["table_ast"]["body"] for cell in row["cells"]]


def test_table_ast_cell_keeps_minus_sign():
    sanitized = sanitize_canonical_document(_document(_table_block()))

    assert _cells(sanitized)[-1] == "- 0 , 0833 (aproximadamente)"
    assert _block(sanitized)["rows"][1][1] == "- 0 , 0833 (aproximadamente)"


@pytest.mark.parametrize("value", ["- 2", "* 2", "+ 2", "1. 2", "(2) 3"])
def test_table_ast_cell_keeps_leading_marker_before_number(value):
    sanitized = sanitize_canonical_document(_document(_table_block(value)))

    assert _cells(sanitized)[-1] == value


def test_rows_cell_keeps_minus_sign():
    block = {"id": "t1", "type": "table", "rows": [["h", "v"], ["1", "- 2"]]}

    sanitized = sanitize_canonical_document(_document(block))

    assert _block(sanitized)["rows"][1][1] == "- 2"
    assert _cells(sanitized)[-1] == "- 2"


def test_txt_reads_the_negative_cell():
    sanitized = sanitize_canonical_document(_document(_table_block()))

    text = "\n".join(document_to_txt_lines(sanitized))

    assert "- 0 , 0833" in text


@pytest.mark.parametrize(
    ("block", "field"),
    [
        ({"id": "p1", "type": "paragraph", "text": "- 0,08 (aprox.)"}, "text"),
        ({"id": "m1", "type": "math", "text": r"- \frac{1}{2}"}, "text"),
        ({"id": "l1", "type": "list", "items": ["- 0,08"]}, "items"),
    ],
)
def test_other_blocks_keep_minus_sign(block, field):
    sanitized = _block(sanitize_canonical_document(_document(block)))

    assert sanitized[field] == block[field]


def test_paragraph_list_marker_is_still_stripped():
    block = {"id": "p1", "type": "paragraph", "text": "- item"}

    sanitized = sanitize_canonical_document(_document(block))

    assert _block(sanitized)["text"] == "item"


def test_markdown_table_cell_keeps_minus_sign():
    blocks = parse_text_to_blocks("| h | v |\n|---|---|\n| 1 | - 0,08 |")

    table = next(block for block in blocks if block["type"] == "table")
    assert table["rows"][-1] == ["1", "- 0,08"]


def test_markdown_line_with_negative_number_is_not_a_list():
    blocks = parse_text_to_blocks("- 0,08 (aprox.)\n\n- item")

    assert blocks[0]["type"] == "paragraph"
    assert blocks[0]["text"] == "- 0,08 (aprox.)"
    assert blocks[-1]["type"] == "list"
    assert blocks[-1]["items"] == ["item"]


def test_table_cells_normalize_tabs_to_spaces():
    # Regression for #338: table cells and caption normalize tabs to spaces
    block = {
        "id": "t1",
        "type": "table",
        "table_ast": {
            "caption": "Tabela\t1",
            "body": [
                {"cells": [{"text": "header\t1"}, {"text": "header\t2"}]},
                {"cells": [{"text": "valor\tA"}, {"text": "valor\tB"}]},
            ],
        },
    }
    sanitized = sanitize_canonical_document(_document(block))
    table = _block(sanitized)
    assert table["table_ast"]["caption"] == "Tabela 1"
    assert _cells(sanitized) == ["header 1", "header 2", "valor A", "valor B"]
