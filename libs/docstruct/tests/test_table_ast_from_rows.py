"""One builder of a table AST from rows, and the grid it keeps (#601).

A blank cell is a grid position: stripping it away or dropping its row would
shift the remaining cells and change the table a screen reader announces. The
canonical path always kept blank rows; ``table_ast_from_rows`` now does too, so
the two paths cannot disagree. A row with no cell at all occupies no position
and is left out; the table is ``None`` only when no row with a cell remains.
"""

from __future__ import annotations

from docstruct.canonical import sanitize_canonical_document
from docstruct.export.html import document_to_html
from docstruct.export.markdown import document_to_markdown
from docstruct.export.txt import document_to_txt_lines
from docstruct.tables.ast import (
    linearize_table_for_text,
    normalize_table_ast,
    split_header_and_body,
    table_ast_from_rows,
)


def _cells(ast: dict) -> list[list[str]]:
    return [[cell["text"] for cell in row["cells"]] for row in ast["body"]]


def test_a_blank_row_stays_in_the_grid() -> None:
    ast = table_ast_from_rows([["h1", "h2"], ["", " "], ["a", "b"]])

    assert _cells(ast) == [["h1", "h2"], ["", ""], ["a", "b"]]


def test_a_blank_cell_keeps_its_column() -> None:
    ast = table_ast_from_rows([["", "value"]])

    assert _cells(ast) == [["", "value"]]


def test_cells_are_stripped() -> None:
    ast = table_ast_from_rows([[" a ", "\tb\t"]])

    assert _cells(ast) == [["a", "b"]]


def test_a_row_without_cells_is_left_out() -> None:
    ast = table_ast_from_rows([["x"], [], ["y"]])

    assert _cells(ast) == [["x"], ["y"]]


def test_no_row_with_a_cell_means_none() -> None:
    assert table_ast_from_rows([]) is None
    assert table_ast_from_rows([[], []]) is None


def test_caption_is_kept() -> None:
    ast = table_ast_from_rows([["a"]], caption=" T ")

    assert ast == {"body": [{"cells": [{"text": "a"}]}], "caption": "T"}


def test_normalize_table_ast_reads_rows_with_the_same_builder() -> None:
    rows = [["h"], [""], ["v"]]

    assert normalize_table_ast(rows) == table_ast_from_rows(rows)
    assert normalize_table_ast({"rows": rows}) == table_ast_from_rows(rows)
    assert normalize_table_ast({"rows": rows, "caption": "T"}) == table_ast_from_rows(
        rows, caption="T"
    )


def test_a_blank_first_row_is_not_promoted_to_a_header() -> None:
    ast = table_ast_from_rows([["", ""], ["a", "b"]])

    header, body, footer = split_header_and_body(ast)

    assert header == []
    assert body == ast["body"]
    assert footer == []
    assert linearize_table_for_text({"type": "table", "table_ast": ast}) == [
        "Row 1:  | ",
        "Row 2: a | b",
    ]


def test_the_canonical_path_uses_the_same_builder() -> None:
    rows = [["h1", "h2"], ["", ""], ["a", "b"]]
    document = {
        "sections": [
            {
                "id": "s1",
                "title": "T",
                "level": 1,
                "blocks": [{"id": "t1", "type": "table", "rows": rows}],
            }
        ]
    }

    table = sanitize_canonical_document(document)["sections"][0]["blocks"][0]

    assert table["table_ast"] == table_ast_from_rows(rows)
    assert table["rows"] == rows


def test_the_canonical_path_keeps_the_block_caption() -> None:
    document = {
        "sections": [
            {
                "id": "s1",
                "title": "T",
                "level": 1,
                "blocks": [
                    {"id": "t1", "type": "table", "rows": [["a"]], "caption": " T "}
                ],
            }
        ]
    }

    table = sanitize_canonical_document(document)["sections"][0]["blocks"][0]

    assert table["table_ast"] == table_ast_from_rows([["a"]], caption="T")
    assert table["table_ast"]["caption"] == "T"


def test_canonical_table_with_only_empty_rows_has_no_ast() -> None:
    """`rows: [[], []]` would have produced the schema-invalid {"body": []}."""
    document = {
        "sections": [
            {
                "id": "s1",
                "title": "T",
                "level": 1,
                "blocks": [{"id": "t1", "type": "table", "rows": [[], []]}],
            }
        ]
    }

    table = sanitize_canonical_document(document)["sections"][0]["blocks"][0]

    assert table["rows"] == [[], []]
    assert "table_ast" not in table


def _rows_document(rows: list[list[str]]) -> dict:
    return {
        "schema_version": "1.0.0",
        "id": "d",
        "title": "T",
        "language": "pt-BR",
        "audience": ["reader"],
        "verbosity": "detailed",
        "sections": [
            {
                "id": "s1",
                "title": "T",
                "level": 1,
                "blocks": [{"id": "t1", "type": "table", "rows": rows}],
            }
        ],
    }


def test_exporters_do_not_make_a_blank_first_row_a_header() -> None:
    document = _rows_document([["", ""], ["a", "b"]])
    body = "<tbody><tr><td></td><td></td></tr><tr><td>a</td><td>b</td></tr></tbody>"

    html = document_to_html(document, profile="html")
    markdown = document_to_markdown(document)

    assert "<thead>" not in html
    assert body in html
    assert "<thead>" not in markdown
    assert body in markdown
    assert document_to_txt_lines(document) == ["T", "Row 1:  | ", "Row 2: a | b"]
