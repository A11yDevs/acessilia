"""Rows read from a table's plain text (docstruct.tables.text_rows), and the
column count of a table AST. Moved from the core's PDDL payload (#402); the core
covers the same rules in tests/test_pddl_table_text.py."""

from __future__ import annotations

import pytest

from docstruct.tables.ast import table_ast_column_count
from docstruct.tables.text_rows import (
    looks_like_markdown_separator,
    rows_from_delimited_lines,
    rows_from_pipe_table,
    rows_from_visual_table_text,
    score_rows,
)


def test_a_markdown_table_loses_its_separator_line() -> None:
    text = "| Coluna | Valor |\n| --- | --- |\n| Taxa | 10% |"

    assert rows_from_visual_table_text(text) == [["Coluna", "Valor"], ["Taxa", "10%"]]


@pytest.mark.parametrize(
    ("line", "expected"),
    [("| --- | --- |", True), ("|:--|--:|", True), ("| :-: |", False), ("| :--: |", True), ("---", True),
     ("| - | - |", False), ("| a | --- |", False), ("", False), ("||", False)],
)
def test_a_markdown_separator(line, expected) -> None:
    assert looks_like_markdown_separator(line) is expected


def test_a_table_must_score_at_least_four() -> None:
    assert score_rows([]) == 0
    assert score_rows([["a", "b"], ["c"]]) == 4
    assert rows_from_pipe_table("a | b\nc | d") == [["a", "b"], ["c", "d"]]
    assert rows_from_pipe_table("a | b") == []
    assert rows_from_delimited_lines("a;b;c;d", delimiter=";") == [["a", "b", "c", "d"]]


def test_delimited_lines_leave_out_lines_with_a_pipe() -> None:
    assert rows_from_delimited_lines("a|b;c\nd;e\nf;g", delimiter=";") == [["d", "e"], ["f", "g"]]


def test_tabs_come_before_semicolons_and_commas() -> None:
    assert rows_from_visual_table_text("a\tb;c\nd\te;f") == [["a", "b;c"], ["d", "e;f"]]


def test_semicolons_win_a_tie_with_commas() -> None:
    assert rows_from_visual_table_text("a;b,c\nd;e,f") == [["a", "b,c"], ["d", "e,f"]]


@pytest.mark.parametrize("text", ["", "   ", "plain prose\non two lines"])
def test_no_table_in_plain_text(text) -> None:
    assert rows_from_visual_table_text(text) == []


def test_the_column_count_is_the_widest_section_with_spans() -> None:
    table_ast = {
        "header": [{"cells": [{"text": "a", "colspan": 2}, {"text": "b"}]}],
        "body": [{"cells": [{"text": "x"}]}],
    }

    assert table_ast_column_count(table_ast) == 3
    assert table_ast_column_count({"body": "not a list"}) == 0
