"""Tests for ``docstruct.tables.structured`` builders and validators."""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from docstruct.tables import (
    normalize_strict_table_ast,
    rows_look_like_placeholder,
    table_ast_from_structured_rows,
    table_ast_has_structured_content,
)


@dataclass
class _Cell:
    text: str
    header: bool = False
    scope: str = "none"
    rowspan: int = 1
    colspan: int = 1


def test_rows_look_like_placeholder():
    assert rows_look_like_placeholder([["Detected table"]], "Detected table") is True
    assert rows_look_like_placeholder([["  detected table  "]], "Detected table") is True
    assert rows_look_like_placeholder([["A", "B"]], "Detected table") is False
    assert rows_look_like_placeholder([["Detected table"], ["Row 2"]], "Detected table") is False
    assert rows_look_like_placeholder([], "Detected table") is False


def test_table_ast_has_structured_content():
    assert table_ast_has_structured_content(None) is False
    assert table_ast_has_structured_content({}) is False
    placeholder_ast = {"body": [{"cells": [{"text": "Detected table"}]}]}
    assert table_ast_has_structured_content(placeholder_ast, placeholder="Detected table") is False
    assert table_ast_has_structured_content(placeholder_ast) is True
    real_ast = {
        "header": [{"cells": [{"text": "A"}, {"text": "B"}]}],
        "body": [{"cells": [{"text": "1"}, {"text": "2"}]}],
    }
    assert table_ast_has_structured_content(real_ast, placeholder="Detected table") is True


def test_normalize_strict_table_ast_validates_and_filters_fields():
    raw = {
        "caption": "  Table 1  ",
        "header": [
            {
                "cells": [
                    {"text": " Name ", "header": True, "scope": "col", "colspan": 2, "extra": 1},
                    {"header": True},  # missing "text" -> skipped
                ]
            }
        ],
        "body": [
            {
                "cells": [
                    {"text": 42, "scope": "invalid", "rowspan": 0, "colspan": True},
                    {"text": "ok", "rowspan": 2, "header": "yes"},
                ]
            },
            "not-a-row",
        ],
        "metadata": {"source": "docling"},
    }
    normalized = normalize_strict_table_ast(raw)
    assert normalized == {
        "caption": "Table 1",
        "header": [{"cells": [{"text": "Name", "header": True, "scope": "col", "colspan": 2}]}],
        "body": [{"cells": [{"text": "42"}, {"text": "ok", "rowspan": 2}]}],
        "metadata": {"source": "docling"},
    }


@pytest.mark.parametrize(
    "raw",
    [
        None,
        [],
        {},
        {"header": [{"cells": [{"text": "Only header"}]}]},  # missing body
        {"body": [{"cells": [{"header": True}]}]},  # body becomes empty
    ],
)
def test_normalize_strict_table_ast_returns_none_without_valid_body(raw):
    assert normalize_strict_table_ast(raw) is None


def test_table_ast_from_structured_rows_promotes_headers_and_builds_footer():
    rows = [
        [_Cell("Metric", header=True, scope="col"), _Cell("Value", scope="col")],
        [_Cell("Accuracy", header=True, scope="row"), _Cell("98%")],
        [_Cell("Recall", scope="row"), _Cell("97%", colspan=1, rowspan=1)],
    ]
    ast = table_ast_from_structured_rows(
        rows,
        caption="Evaluation",
        notes=["Source: internal run", ""],
        warnings=["truncated note"],
    )
    assert ast == {
        "header": [
            {
                "cells": [
                    {"text": "Metric", "header": True, "scope": "col"},
                    {"text": "Value", "header": True, "scope": "col"},
                ]
            }
        ],
        "body": [
            {
                "cells": [
                    {"text": "Accuracy", "header": True, "scope": "row"},
                    {"text": "98%"},
                ]
            },
            {
                "cells": [
                    {"text": "Recall", "header": True, "scope": "row"},
                    {"text": "97%"},
                ]
            },
        ],
        "caption": "Evaluation",
        "footer": [{"cells": [{"text": "Source: internal run", "colspan": 2}]}],
        "metadata": {"warnings": ["truncated note"]},
    }


def test_table_ast_from_structured_rows_keeps_last_row_in_body_when_all_headers():
    rows = [
        [_Cell("Col A", header=True), _Cell("Col B", header=True)],
        [_Cell("Sub A", header=True), _Cell("Sub B", header=True)],
    ]
    ast = table_ast_from_structured_rows(rows)
    assert len(ast["header"]) == 1
    assert len(ast["body"]) == 1
    assert ast["body"][0]["cells"][0]["header"] is True


def test_table_ast_from_structured_rows_rejects_empty_rows():
    with pytest.raises(ValueError, match="at least one row"):
        table_ast_from_structured_rows([])
