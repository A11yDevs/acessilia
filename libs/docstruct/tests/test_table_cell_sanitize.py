"""Canonicalization keeps what a table cell starts with (#260).

The reference case's second table has ``−0,0833`` in a cell, extracted as
``- 0 , 0833``; the bullet rule of the block sanitizer used to drop the sign,
which inverts what the table says (the position decreases).
"""
from docstruct.canonical import sanitize_canonical_document
from docstruct.export.txt import document_to_txt_lines


def _document(block):
    return {"sections": [{"id": "s1", "title": "T", "level": 1, "blocks": [block]}]}


def _table_block():
    return {
        "id": "t1",
        "type": "table",
        "table_ast": {
            "body": [
                {"cells": [{"text": "h"}, {"text": "velocidade"}]},
                {"cells": [{"text": "1"}, {"text": "- 0 , 0833 (aproximadamente)"}]},
            ]
        },
    }


def _cells(document):
    block = document["sections"][0]["blocks"][0]
    return [cell["text"] for row in block["table_ast"]["body"] for cell in row["cells"]]


def test_table_ast_cell_keeps_minus_sign():
    sanitized = sanitize_canonical_document(_document(_table_block()))

    assert _cells(sanitized)[-1] == "- 0 , 0833 (aproximadamente)"
    block = sanitized["sections"][0]["blocks"][0]
    assert block["rows"][1][1] == "- 0 , 0833 (aproximadamente)"


def test_rows_cell_keeps_minus_sign():
    block = {"id": "t1", "type": "table", "rows": [["h", "v"], ["1", "- 2"]]}

    sanitized = sanitize_canonical_document(_document(block))

    assert sanitized["sections"][0]["blocks"][0]["rows"][1][1] == "- 2"
    assert _cells(sanitized)[-1] == "- 2"


def test_txt_reads_the_negative_cell():
    sanitized = sanitize_canonical_document(_document(_table_block()))

    text = "\n".join(document_to_txt_lines(sanitized))

    assert "- 0 , 0833" in text


def test_paragraph_list_marker_is_still_stripped():
    block = {"id": "p1", "type": "paragraph", "text": "- item"}

    sanitized = sanitize_canonical_document(_document(block))

    assert sanitized["sections"][0]["blocks"][0]["text"] == "item"
