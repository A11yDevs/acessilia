"""One builder of a table AST from rows, and the grid it keeps (#601).

A blank cell is a grid position: stripping it away or dropping its row would
shift the remaining cells and change the table a screen reader announces. The
canonical path always kept blank rows; ``table_ast_from_rows`` now does too, so
the two paths cannot disagree. A row with no cell at all occupies no position
and is left out; the table is ``None`` only when no row with a cell remains.
"""

from __future__ import annotations

from docstruct.canonical import sanitize_canonical_document
from docstruct.tables.ast import normalize_table_ast, table_ast_from_rows


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
