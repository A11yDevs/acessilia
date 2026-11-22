"""Canonical table AST normalization and linearization.

Core migrated to docstruct.tables.ast; pure functions and constants remain
here only as deprecated compatibility re-exports. Import them from
``docstruct.tables.ast`` instead. ``linearize_table_for_text`` keeps the
localized contract: the lib returns canonical-English msgid lines, which this
bridge resolves through the backend i18n catalog (and re-matches msgids back
for translation).
"""
from __future__ import annotations

import warnings
from typing import Any

import docstruct.tables.ast as _docstruct_ast
from acessilia_core.i18n import t

_DEPRECATED_NAMES = (
    "ALLOWED_SCOPES",
    "MSG_TABLE_TEXT_CAPTION",
    "MSG_TABLE_TEXT_FOOTER",
    "MSG_TABLE_TEXT_ROW",
    "normalize_table_ast",
    "rows_from_table_ast",
    "split_header_and_body",
    "table_ast_from_block",
    "table_ast_from_rows",
)
_DEPRECATED: dict[str, Any] = {
    name: getattr(_docstruct_ast, name) for name in _DEPRECATED_NAMES
}

__all__ = [
    *_DEPRECATED_NAMES,
    "linearize_table_for_text",
]


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__) | set(_DEPRECATED))


def __getattr__(name: str) -> Any:
    if name in _DEPRECATED:
        warnings.warn(
            f"acessilia_core.pipeline.table_ast.{name} is deprecated; "
            "import it from docstruct.tables.ast",
            DeprecationWarning,
            stacklevel=2,
        )
        return _DEPRECATED[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# Reverse map: canonical English line prefix -> (msgid, format kwargs).
_LINE_TO_MSGID = (
    (_docstruct_ast.MSG_TABLE_TEXT_CAPTION, "caption"),
    (_docstruct_ast.MSG_TABLE_TEXT_FOOTER, "footer_text"),
)


def _translate(line: str) -> str:
    """Translate a canonical msgid line produced by the lib.

    The lib emits English msgid lines. To re-map them to the catalog we
    match the prefix before the first formatted value and rebuild kwargs.
    """
    # Caption: "Table: <rest>" / Footer: "Footer: <rest>"
    for prefix_template, key in _LINE_TO_MSGID:
        prefix = prefix_template.split("{")[0]  # "Table: " (with its trailing space)
        if line.startswith(prefix):
            value = line[len(prefix):].strip()
            return t(prefix_template).format(**{key: value})
    # Row: "Row <n>: <joined>"
    if line.startswith("Row "):
        head, sep, rest = line.partition(": ")
        if sep:
            row_index = head.removeprefix("Row ").strip()
            return t(_docstruct_ast.MSG_TABLE_TEXT_ROW).format(
                row_index=row_index, joined=rest
            )
    return line


def linearize_table_for_text(block: dict) -> list[str]:
    """Localized linearization: lib (canonical English) -> backend i18n catalog."""
    return [_translate(line) for line in _docstruct_ast.linearize_table_for_text(block)]
