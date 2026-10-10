"""Tests for Docling table grid extraction and complexity metrics in docstruct.tables.ast."""
from __future__ import annotations

from types import SimpleNamespace
from typing import get_origin

from docstruct.tables.ast import (
    TableAST,
    TableASTError,
    TableComplexityMetrics,
    analyze_table_complexity,
    table_ast_from_docling_grid,
)


class TestTableAstFromDoclingGrid:
    def test_docling_cell_list(self):
        cells = [
            {
                "text": "Header A",
                "start_row_offset_idx": 0,
                "start_col_offset_idx": 0,
                "row_span": 1,
                "col_span": 2,
                "column_header": True,
            },
            {
                "text": "Header B",
                "start_row_offset_idx": 0,
                "start_col_offset_idx": 2,
                "row_span": 1,
                "col_span": 1,
                "column_header": True,
            },
            {
                "text": "Data 1",
                "start_row_offset_idx": 1,
                "start_col_offset_idx": 0,
                "row_span": 2,
                "col_span": 1,
            },
            {
                "text": "Data 2",
                "start_row_offset_idx": 1,
                "start_col_offset_idx": 1,
                "row_span": 1,
                "col_span": 1,
            },
            {
                "text": "Data 3",
                "start_row_offset_idx": 2,
                "start_col_offset_idx": 1,
                "row_span": 1,
                "col_span": 1,
            },
        ]

        ast = table_ast_from_docling_grid(cells, caption="Sample Grid")
        assert ast is not None
        assert ast["caption"] == "Sample Grid"
        assert len(ast["header"]) == 1
        assert ast["header"][0]["cells"][0]["text"] == "Header A"
        assert ast["header"][0]["cells"][0]["colspan"] == 2
        assert len(ast["body"]) == 2
        assert ast["body"][0]["cells"][0]["text"] == "Data 1"
        assert ast["body"][0]["cells"][0]["rowspan"] == 2

    def test_docling_object_structure(self):
        cell1 = SimpleNamespace(
            text="H1", start_row_offset_idx=0, start_col_offset_idx=0,
            row_span=1, col_span=1, column_header=True,
        )
        cell2 = SimpleNamespace(
            text="B1", start_row_offset_idx=1, start_col_offset_idx=0,
            row_span=1, col_span=1, column_header=False,
        )
        docling_item = SimpleNamespace(data=SimpleNamespace(table_cells=[cell1, cell2]))

        ast = table_ast_from_docling_grid(docling_item)
        assert ast is not None
        assert len(ast["header"]) == 1
        assert ast["header"][0]["cells"][0]["text"] == "H1"
        assert len(ast["body"]) == 1
        assert ast["body"][0]["cells"][0]["text"] == "B1"


class TestAnalyzeTableComplexity:
    def test_simple_flat_table(self):
        simple_ast = {
            "header": [{"cells": [{"text": "A"}, {"text": "B"}]}],
            "body": [{"cells": [{"text": "1"}, {"text": "2"}]}],
        }
        res = analyze_table_complexity(simple_ast)
        assert res["has_spans"] is False
        assert res["max_rowspan"] == 1
        assert res["max_colspan"] == 1
        assert res["spanned_cell_count"] == 0
        assert res["is_complex"] is False

    def test_table_with_rowspan(self):
        rowspan_ast = {
            "header": [{"cells": [{"text": "A"}, {"text": "B"}]}],
            "body": [
                {"cells": [{"text": "Multi", "rowspan": 3}, {"text": "2"}]},
                {"cells": [{"text": "3"}]},
            ],
        }
        res = analyze_table_complexity(rowspan_ast)
        assert res["has_spans"] is True
        assert res["max_rowspan"] == 3
        assert res["max_colspan"] == 1
        assert res["spanned_cell_count"] == 1
        assert res["is_complex"] is True

    def test_table_with_colspan(self):
        colspan_ast = {
            "header": [{"cells": [{"text": "Super Header", "colspan": 4}]}],
            "body": [{"cells": [{"text": "1"}, {"text": "2"}, {"text": "3"}, {"text": "4"}]}],
        }
        res = analyze_table_complexity(colspan_ast)
        assert isinstance(res, TableComplexityMetrics)
        assert res.has_spans is True
        assert res["has_spans"] is True
        assert res.max_rowspan == 1
        assert res.max_colspan == 4
        assert res.spanned_cell_count == 1
        assert res.is_complex is True
        assert res.to_dict()["max_colspan"] == 4

    def test_invalid_table_fallback(self):
        res = analyze_table_complexity(None)
        assert isinstance(res, TableComplexityMetrics)
        assert res.has_spans is False
        assert res.is_complex is False
        assert res.max_rowspan == 1
        assert res.max_colspan == 1

    def test_table_ast_types(self):
        assert issubclass(TableASTError, Exception)
        assert get_origin(TableAST) is dict
