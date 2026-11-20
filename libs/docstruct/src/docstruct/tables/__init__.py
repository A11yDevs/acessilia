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
from docstruct.tables.structured import (
    StructuredTableCell,
    normalize_strict_table_ast,
    rows_look_like_placeholder,
    table_ast_from_structured_rows,
    table_ast_has_structured_content,
)

__all__ = [
    "ALLOWED_SCOPES",
    "MSG_TABLE_TEXT_CAPTION",
    "MSG_TABLE_TEXT_FOOTER",
    "MSG_TABLE_TEXT_ROW",
    "StructuredTableCell",
    "TableAST",
    "TableASTError",
    "TableComplexityMetrics",
    "analyze_table_complexity",
    "effective_section_row_widths",
    "linearize_table_for_text",
    "normalize_strict_table_ast",
    "normalize_table_ast",
    "rows_from_table_ast",
    "rows_look_like_placeholder",
    "split_header_and_body",
    "table_ast_from_block",
    "table_ast_from_docling_grid",
    "table_ast_from_rows",
    "table_ast_from_structured_rows",
    "table_ast_has_structured_content",
]
