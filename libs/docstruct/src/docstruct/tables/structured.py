"""Pure table-AST builders, strict normalization and structured-content checks."""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from docstruct.tables.ast import (
    ALLOWED_SCOPES,
    TABLE_SECTIONS,
    raw_rows_from_table_ast,
)


class StructuredTableCell(Protocol):
    """Read-only cell interface accepted by :func:`table_ast_from_structured_rows`."""

    @property
    def text(self) -> str: ...

    @property
    def header(self) -> bool: ...

    @property
    def scope(self) -> str: ...

    @property
    def rowspan(self) -> int: ...

    @property
    def colspan(self) -> int: ...


def rows_look_like_placeholder(
    rows: Sequence[Sequence[str]], placeholder: str
) -> bool:
    """Whether ``rows`` is a single cell carrying only ``placeholder`` (case-insensitive)."""
    if len(rows) != 1 or len(rows[0]) != 1:
        return False
    return rows[0][0].strip().lower() == placeholder.strip().lower()


def table_ast_has_structured_content(
    table_ast: Any, *, placeholder: str | None = None
) -> bool:
    """Whether ``table_ast`` holds real table cells rather than a single placeholder cell."""
    if not isinstance(table_ast, dict):
        return False
    rows = raw_rows_from_table_ast(table_ast)
    if not rows:
        return False
    width = max((len(row) for row in rows), default=0)
    if len(rows) >= 2 and width >= 2:
        return True
    if placeholder is not None and rows_look_like_placeholder(rows, placeholder):
        return False
    return True


def _normalize_strict_cell(cell: Any) -> dict[str, Any] | None:
    if not isinstance(cell, dict) or "text" not in cell:
        return None
    normalized: dict[str, Any] = {"text": str(cell.get("text", "")).strip()}
    if isinstance(cell.get("header"), bool):
        normalized["header"] = cell["header"]
    scope = cell.get("scope")
    if isinstance(scope, str) and scope in ALLOWED_SCOPES:
        normalized["scope"] = scope
    for span_key in ("rowspan", "colspan"):
        span = cell.get(span_key)
        if type(span) is int and span >= 1:
            normalized[span_key] = span
    return normalized


def _normalize_strict_section(section: Any) -> list[dict[str, Any]]:
    if not isinstance(section, list):
        return []
    normalized_rows: list[dict[str, Any]] = []
    for row in section:
        if not isinstance(row, dict):
            continue
        cells = row.get("cells")
        if not isinstance(cells, list):
            continue
        normalized_cells = [
            item
            for cell in cells
            if (item := _normalize_strict_cell(cell)) is not None
        ]
        if normalized_cells:
            normalized_rows.append({"cells": normalized_cells})
    return normalized_rows


def normalize_strict_table_ast(raw: Any) -> dict[str, Any] | None:
    """Normalize a raw ``table_ast`` mapping keeping only explicit section/cell fields.

    Unlike :func:`docstruct.tables.ast.normalize_table_ast`, this validator does
    not unwrap nested ``table``/``rows``/``grid`` wrappers: it expects a dict
    with ``header``/``body``/``footer`` sections whose cells explicitly carry a
    ``text`` key, coerces cell text with ``str(...).strip()``, and returns
    ``None`` unless ``body`` is non-empty.
    """
    if not isinstance(raw, dict):
        return None
    table_ast: dict[str, Any] = {}
    caption = raw.get("caption")
    if isinstance(caption, str) and caption.strip():
        table_ast["caption"] = caption.strip()
    for section_name in TABLE_SECTIONS:
        rows = _normalize_strict_section(raw.get(section_name))
        if rows:
            table_ast[section_name] = rows
    metadata_obj = raw.get("metadata")
    if isinstance(metadata_obj, dict):
        table_ast["metadata"] = metadata_obj
    return table_ast if table_ast.get("body") else None


def _structured_cell_to_ast(cell: StructuredTableCell) -> dict[str, Any]:
    canonical: dict[str, Any] = {"text": cell.text}
    if cell.header or cell.scope != "none":
        canonical["header"] = True
    if cell.scope != "none":
        canonical["scope"] = cell.scope
    if cell.rowspan > 1:
        canonical["rowspan"] = cell.rowspan
    if cell.colspan > 1:
        canonical["colspan"] = cell.colspan
    return canonical


def _leading_header_row_count(rows: Sequence[Sequence[StructuredTableCell]]) -> int:
    count = 0
    for row in rows[:-1]:
        if not row or not all(
            (cell.header or cell.scope in {"col", "colgroup"})
            and cell.scope not in {"row", "rowgroup"}
            for cell in row
        ):
            break
        count += 1
    return count


def _footer_rows_from_notes(
    notes: Sequence[str],
    rows: Sequence[Sequence[StructuredTableCell]],
) -> list[dict[str, Any]]:
    non_empty = [note for note in notes if note]
    if not non_empty:
        return []
    column_count = max(
        (sum(cell.colspan for cell in row) for row in rows),
        default=1,
    )
    footer: list[dict[str, Any]] = []
    for note in non_empty:
        cell: dict[str, Any] = {"text": note}
        if column_count > 1:
            cell["colspan"] = column_count
        footer.append({"cells": [cell]})
    return footer


def table_ast_from_structured_rows(
    rows: Sequence[Sequence[StructuredTableCell]],
    *,
    caption: str | None = None,
    notes: Sequence[str] = (),
    warnings: Sequence[str] = (),
) -> dict[str, Any]:
    """Build a canonical table AST from structured cell rows.

    Promotes leading, fully marked column-header rows into ``header`` while
    keeping at least one row in ``body`` (the canonical contract requires a
    non-empty body). Non-empty ``notes`` become full-width ``footer`` rows.
    """
    if not rows:
        raise ValueError("table_ast requires at least one row")
    ast_rows = [
        {"cells": [_structured_cell_to_ast(cell) for cell in row]}
        for row in rows
    ]
    header_count = _leading_header_row_count(rows)
    table_ast: dict[str, Any] = {"body": ast_rows[header_count:]}
    if header_count:
        table_ast["header"] = ast_rows[:header_count]
    if caption:
        table_ast["caption"] = caption
    footer_rows = _footer_rows_from_notes(notes, rows)
    if footer_rows:
        table_ast["footer"] = footer_rows
    if warnings:
        table_ast["metadata"] = {"warnings": list(warnings)}
    return table_ast


__all__ = [
    "StructuredTableCell",
    "normalize_strict_table_ast",
    "rows_look_like_placeholder",
    "table_ast_from_structured_rows",
    "table_ast_has_structured_content",
]
