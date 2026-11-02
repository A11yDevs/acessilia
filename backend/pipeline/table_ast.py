"""Canonical table AST normalization and linearization.

Core migrated to docstruct.tables.ast; re-exported here for compatibility
with existing imports. ``linearize_table_for_text`` keeps the localized
contract: the lib returns canonical-English msgid lines, which this bridge
resolves through the backend i18n catalog (and re-matches msgids back for
translation).
"""
from __future__ import annotations

from docstruct.tables.ast import (  # noqa: F401
    ALLOWED_SCOPES,
    MSG_TABLE_TEXT_CAPTION,
    MSG_TABLE_TEXT_FOOTER,
    MSG_TABLE_TEXT_ROW,
    normalize_table_ast,
    rows_from_table_ast,
    split_header_and_body,
    table_ast_from_block,
    table_ast_from_rows,
)
from backend.i18n import t

__all__ = [
    "ALLOWED_SCOPES",
    "MSG_TABLE_TEXT_CAPTION",
    "MSG_TABLE_TEXT_FOOTER",
    "MSG_TABLE_TEXT_ROW",
    "normalize_table_ast",
    "rows_from_table_ast",
    "split_header_and_body",
    "table_ast_from_block",
    "table_ast_from_rows",
    "linearize_table_for_text",
]

# Reverse map: canonical English line prefix -> (msgid, format kwargs).
_LINE_TO_MSGID = (
    (MSG_TABLE_TEXT_CAPTION, "caption"),
    (MSG_TABLE_TEXT_FOOTER, "footer_text"),
)


def _translate(line: str) -> str:
    """Translate a canonical msgid line produced by the lib.

    The lib emits English msgid lines. To re-map them to the catalog we
    match the prefix before the first formatted value and rebuild kwargs.
    """
    # Caption: "Table: <rest>" / Footer: "Footer: <rest>"
    for prefix_template, key in _LINE_TO_MSGID:
        prefix = prefix_template.split("{")[0]  # "Table: " (com espaço final)
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            return t(prefix_template).format(**{key: value})
    # Row: "Row <n>: <joined>"
    if line.startswith("Row "):
        head, sep, rest = line.partition(": ")
        if sep:
            row_index = head.removeprefix("Row ").strip()
            return t(MSG_TABLE_TEXT_ROW).format(row_index=row_index, joined=rest)
    return line


def linearize_table_for_text(block: dict) -> list[str]:
    """Localized linearization: lib (canonical English) -> backend i18n catalog."""
    from docstruct.tables.ast import linearize_table_for_text as _lib_linearize

    return [_translate(line) for line in _lib_linearize(block)]
