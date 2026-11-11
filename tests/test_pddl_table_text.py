"""Rows read from a table's plain text, and a table's column count (#402).

Characterization of the orchestrator's table text helpers, written on develop
before the parsing moved to docstruct. ``_backfill_table_from_existing_text``
stays in the core and fills the element from the parsed rows.
"""

from __future__ import annotations

import pytest

from backend.agents.pddl_orchestrator import (
    _backfill_table_from_existing_text,
    _rows_from_visual_table_text,
    _table_ast_column_count,
)
from backend.core.manifest.models import ManifestElement


@pytest.mark.parametrize(
    ("text", "rows"),
    [
        pytest.param("a\tb\nc\td", [["a", "b"], ["c", "d"]], id="tabs"),
        pytest.param("a;b\nc;d", [["a", "b"], ["c", "d"]], id="semicolons"),
        pytest.param("a,b\nc,d", [["a", "b"], ["c", "d"]], id="commas"),
        # Equal scores: semicolons win.
        pytest.param("a;b,c\nd;e,f", [["a", "b,c"], ["d", "e,f"]], id="tie-semicolon"),
        # More commas than semicolons: commas win.
        pytest.param("a;b,c,d\ne;f,g,h", [["a;b", "c", "d"], ["e;f", "g", "h"]], id="commas-win"),
        # A pipe table below the minimum score falls through to the delimiters.
        pytest.param("a | b\nx,y\nz,w", [["x", "y"], ["z", "w"]], id="small-pipe"),
        pytest.param("| h1 | h2 |\n|:--|--:|\n| 1 | 2 |", [["h1", "h2"], ["1", "2"]], id="aligned-separator"),
        pytest.param("|a||b|\n|c||d|", [["a", "b"], ["c", "d"]], id="empty-cells-dropped"),
        pytest.param("single line, two cells", [], id="one-row"),
        pytest.param("a|b\nc;d\ne;f", [["c", "d"], ["e", "f"]], id="pipe-lines-skipped-by-delimiters"),
        pytest.param("   ", [], id="blank"),
        pytest.param("no delimiters here\nnor here", [], id="prose"),
    ],
)
def test_rows_from_visual_table_text(text, rows) -> None:
    assert _rows_from_visual_table_text(text) == rows


def test_the_column_count_reads_the_widest_section_with_spans() -> None:
    table_ast = {
        "header": [{"cells": [{"text": "a", "colspan": 3}]}],
        "body": [{"cells": [{"text": "x"}, {"text": "y"}]}],
        "footer": "not a list",
    }

    assert _table_ast_column_count(table_ast) == 3
    assert _table_ast_column_count({}) == 0


def _table(text: str) -> ManifestElement:
    return ManifestElement(
        id="t1", type="table", raw_label="table", reading_order=1, hierarchy_level=1,
        text=text, page_number=1,
    )


def test_a_table_is_backfilled_from_its_own_text() -> None:
    element = _table("Nome;Nota\nAna;9\nBeto;8")

    assert _backfill_table_from_existing_text(element) is True
    assert element.text == ""
    assert element.metadata["table_linearization_hint"] == "text-heuristic"
    assert element.metadata["table_row_count"] == 3
    assert element.metadata["table_column_count"] == 2
    assert element.metadata["table_has_header"] is True
    assert element.metadata["table_ast"]["body"][1]["cells"][0]["text"] == "Ana"


@pytest.mark.parametrize("text", ["", "just a sentence"])
def test_a_table_without_rows_in_its_text_is_left_alone(text) -> None:
    element = _table(text)

    assert _backfill_table_from_existing_text(element) is False
    assert element.text == text
    assert "table_ast" not in element.metadata
