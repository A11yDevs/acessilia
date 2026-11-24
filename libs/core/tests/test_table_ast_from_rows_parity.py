"""One builder for a table AST from rows, and the blank rows it keeps (#601).

``pipeline/elements.py`` and the table backfill use
``docstruct.tables.ast.table_ast_from_rows`` (#470, #600). ``docstruct.canonical``
kept a private copy, ``_table_ast_from_rows``, which disagreed with it on rows
whose cells are all blank: the canonical copy kept them, the public function
dropped them. #601 made the public function the single implementation and chose
the canonical reading: a blank cell, and a row of blank cells, is still a grid
position, so both keep it. Only a row with no cell at all is left out, and the
table is ``None`` when no row with a cell remains.

The reference below is the behavior the canonical path had before #601, frozen
so the contract stays checked: cells are stripped, blank rows stay, rows that
are not lists are skipped, and no row left means ``None``.
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


def _reference(rows: list[list[str]]) -> dict[str, Any] | None:
    body: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = [{"text": str(cell).strip()} for cell in row]
        if cells:
            body.append({"cells": cells})
    return {"body": body} if body else None


def _random_rows(generator: random.Random) -> list[list[str]]:
    words = ["", " ", "a", " b ", "c d", "1", "\t", "x|y"]
    return [
        [generator.choice(words) for _ in range(generator.randint(0, 4))]
        for _ in range(generator.randint(0, 5))
    ]


def test_the_single_builder_reads_every_row_like_the_canonical_path() -> None:
    generator = random.Random(601)
    blank_rows = 0
    for _ in range(20000):
        rows = _random_rows(generator)
        blank_rows += sum(
            1 for row in rows if row and not any(str(cell).strip() for cell in row)
        )
        assert table_ast_from_rows(rows) == _reference(rows), rows
    assert blank_rows > 1000, blank_rows


def test_a_blank_row_is_a_grid_position() -> None:
    rows = [["h1", "h2"], ["", " "], ["a", "b"]]

    assert table_ast_from_rows(rows) == {
        "body": [
            {"cells": [{"text": "h1"}, {"text": "h2"}]},
            {"cells": [{"text": ""}, {"text": ""}]},
            {"cells": [{"text": "a"}, {"text": "b"}]},
        ]
    }


def test_no_row_with_a_cell_means_none() -> None:
    assert table_ast_from_rows([]) is None
    assert table_ast_from_rows([[], []]) is None


def test_a_cells_row_that_is_not_a_list_is_read_now() -> None:
    """Outside the core's inputs: the copy skipped it, docstruct reads it."""
    rows = [["x"], {"cells": [{"text": "y"}]}]

    assert _reference(rows) == {"body": [{"cells": [{"text": "x"}]}]}
    assert table_ast_from_rows(rows) == {
        "body": [{"cells": [{"text": "x"}]}, {"cells": [{"text": "y"}]}]
    }


def test_canonical_has_no_private_builder() -> None:
    """The canonical path builds its table AST with the public function."""
    import docstruct.canonical as canonical

    assert not hasattr(canonical, "_table_ast_from_rows")


def test_canonical_and_the_public_function_build_the_same_ast() -> None:
    rows = [["h1", "h2"], ["", ""], ["a", "b"]]
    document = build_canonical_document(
        {
            "pages": [
                {
                    "blocks": [
                        {"type": "table", "rows": copy.deepcopy(rows)},
                    ]
                }
            ]
        },
        id_factory=lambda: "d",
    )
    table = document["sections"][0]["blocks"][0]

    assert table["table_ast"] == table_ast_from_rows(rows)
    assert table["rows"] == rows


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
def test_a_whitespace_table_keeps_its_blank_cell_and_exports_the_same(
    text: str, metadata: dict | None
) -> None:
    """The block that changes: it now has the AST the canonical path built."""
    block = _element_to_block(_table(text, copy.deepcopy(metadata)))
    assert block["table_ast"] == {"body": [{"cells": [{"text": ""}]}]}
    assert block["rows"] == [[text]]

    before = dict(block, table_ast=None)

    assert _exported(block) == _exported(before)
