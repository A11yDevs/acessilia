"""The core builds a table AST from rows with docstruct's function (#470).

``pipeline/elements.py`` kept ``_table_ast_from_rows``, a near-copy of
``docstruct.tables.ast.table_ast_from_rows``. The core now uses docstruct's.
The reference below is the core's copy as it was on develop at 8ef77f89,
frozen so the difference stays documented and checked.

On the inputs the core gives it, lists of cells, the two differ in one way
only: docstruct leaves out the rows whose cells are all blank, and returns
``None`` when no row is left, where the core's copy kept them
(``{"body": [...]}`` with empty cells, or ``{"body": []}``). On other inputs
they differ too: the core's copy skipped a row that is not a list, which
docstruct reads when it is a ``{"cells": [...]}`` row (review of #600). No
caller of the core passes one. Of the core's two callers:

- the table backfill (``enrichment/tables.py``) reads rows from
  ``rows_from_visual_table_text``, whose cells are never blank, so nothing
  changes. Its ``table_ast is None`` check fits docstruct's return type, but
  with these rows it still never holds (review of #600);
- the payload builder (``_element_to_block``) gets a single row,
  ``[[text]]``. Only a table whose text is all whitespace, with no usable
  table AST, changes: its block has ``table_ast: None`` instead of an AST of
  one empty cell. The canonical builder makes the table's AST from its rows
  either way, so the exported document is the same.
"""

from __future__ import annotations

import copy
import itertools
import random
from typing import Any

import pytest

from acessilia_core.manifest.models import ManifestElement
from acessilia_core.pipeline.elements import _element_to_block
from docstruct.canonical import build_canonical_document
from docstruct.export.html import document_to_html
from docstruct.tables.ast import table_ast_from_rows
from docstruct.tables.text_rows import rows_from_visual_table_text


def _reference(rows: list[list[str]]) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = []
        for cell in row:
            text = str(cell).strip()
            cells.append({"text": text})
        if cells:
            body.append({"cells": cells})
    return {"body": body}


def _random_rows(generator: random.Random) -> list[list[str]]:
    words = ["", " ", "a", " b ", "c d", "1", "\t", "x|y"]
    return [
        [generator.choice(words) for _ in range(generator.randint(0, 4))]
        for _ in range(generator.randint(0, 5))
    ]


def test_the_two_agree_unless_a_row_is_all_blank() -> None:
    generator = random.Random(470)
    same = differ = 0
    for _ in range(20000):
        rows = _random_rows(generator)
        kept = [row for row in rows if any(str(cell).strip() for cell in row)]
        if kept == rows and rows:
            assert table_ast_from_rows(rows) == _reference(rows), rows
            same += 1
        else:
            expected = _reference(kept) if kept else None
            assert table_ast_from_rows(rows) == expected, rows
            differ += 1
    assert same > 1000 and differ > 1000, (same, differ)


def test_a_cells_row_that_is_not_a_list_is_read_now() -> None:
    """Outside the core's inputs: the copy skipped it, docstruct reads it."""
    rows = [["x"], {"cells": [{"text": "y"}]}]

    assert _reference(rows) == {"body": [{"cells": [{"text": "x"}]}]}
    assert table_ast_from_rows(rows) == {
        "body": [{"cells": [{"text": "x"}]}, {"cells": [{"text": "y"}]}]
    }


def test_the_backfill_rows_never_meet_the_difference() -> None:
    texts = ["a | b\nc | d", "x;y;z\n1;2;3", "p,q\nr,s", "a\tb\nc\td", "| h | i |\n|---|---|\n| 1 | 2 |"]
    for text in texts:
        rows = rows_from_visual_table_text(text)
        assert rows, text
        assert table_ast_from_rows(rows) == _reference(rows), text


def _table(text: str, metadata: dict | None = None) -> ManifestElement:
    return ManifestElement(
        id="element-000001", type="table", raw_label="table", reading_order=1,
        hierarchy_level=0, text=text, page_number=1, metadata=metadata or {},
    )


def _exported(block: dict) -> tuple[dict, str]:
    document = build_canonical_document({"pages": [{"blocks": [block]}]}, id_factory=lambda: "d")
    tables = [
        item for section in document["sections"] for item in section["blocks"]
        if item["type"] == "table"
    ]
    return tables[0], document_to_html(document, profile="html")


@pytest.mark.parametrize(
    ("text", "metadata"),
    list(itertools.product(
        [" ", "\t\n"],
        [None, {"table_ast": {"body": []}}, {"table_rows": [["p", "q"]]}],
    )),
)
def test_a_whitespace_table_exports_the_same(text: str, metadata: dict | None) -> None:
    """The one block that changes: same canonical table, same HTML."""
    block = _element_to_block(_table(text, copy.deepcopy(metadata)))
    assert block["table_ast"] is None
    assert block["rows"] == [[text]]

    before = dict(block, table_ast=_reference(block["rows"]))

    assert _exported(block) == _exported(before)
