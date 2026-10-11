"""Table AST modules of docstruct."""
from __future__ import annotations

from docstruct.tables.ast import (
    ALLOWED_SCOPES,
    MSG_TABLE_TEXT_CAPTION,
    MSG_TABLE_TEXT_FOOTER,
    MSG_TABLE_TEXT_ROW,
    TableAST,
    TableASTError,
    TableComplexityMetrics,
    analyze_table_complexity,
    effective_section_row_widths,
    linearize_table_for_text,
    normalize_table_ast,
    rows_from_table_ast,
    split_header_and_body,
    table_ast_from_block,
    table_ast_from_docling_grid,
    table_ast_from_rows,
)

__all__ = [
    "ALLOWED_SCOPES",
    "MSG_TABLE_TEXT_CAPTION",
    "MSG_TABLE_TEXT_FOOTER",
    "MSG_TABLE_TEXT_ROW",
    "TableAST",
    "TableASTError",
    "TableComplexityMetrics",
    "analyze_table_complexity",
    "effective_section_row_widths",
    "linearize_table_for_text",
    "normalize_table_ast",
    "rows_from_table_ast",
    "split_header_and_body",
    "table_ast_from_block",
    "table_ast_from_docling_grid",
    "table_ast_from_rows",
]
