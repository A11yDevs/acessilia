"""Canonical table AST normalization and linearization.

Ported from backend/pipeline/table_ast.py. Pure: no i18n resolution —
``linearize_table_for_text`` returns lines with untranslated msgid
templates applied (``MSG_TABLE_TEXT_*``); the consumer translates them
via ``msgid.format(**kwargs)`` with its own catalog. Since msgids are
English canonical templates, ``.format()`` on them yields valid English
output, which keeps the lib output directly usable without a catalog.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any

ALLOWED_SCOPES = {"none", "row", "col", "rowgroup", "colgroup"}


class TableASTError(Exception):
    """Raised when TableAST conversion or validation encounters an error."""


#: Type alias representing a normalized table AST dictionary.
TableAST = dict[str, Any]


@dataclass
class TableComplexityMetrics:
    """Structural complexity metrics for a table AST.

    Supports attribute access (metrics.has_spans) and dictionary-style access
    (metrics["has_spans"]) for full compatibility.
    """

    has_spans: bool
    max_rowspan: int
    max_colspan: int
    spanned_cell_count: int
    is_complex: bool

    def __getitem__(self, key: str) -> Any:
        try:
            return getattr(self, key)
        except AttributeError as err:
            raise KeyError(key) from err

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def to_dict(self) -> dict[str, Any]:
        return {
            "has_spans": self.has_spans,
            "max_rowspan": self.max_rowspan,
            "max_colspan": self.max_colspan,
            "spanned_cell_count": self.spanned_cell_count,
            "is_complex": self.is_complex,
        }

#: Canonical English msgid template for the TXT table caption line; {caption} is the table caption.
MSG_TABLE_TEXT_CAPTION: str = "Table: {caption}"
#: Canonical English msgid template for a TXT table row line; {row_index} is the 1-based body row number and {joined} the rendered cells.
MSG_TABLE_TEXT_ROW: str = "Row {row_index}: {joined}"
#: Canonical English msgid template for the TXT table footer line; {footer_text} is the rendered footer cells.
MSG_TABLE_TEXT_FOOTER: str = "Footer: {footer_text}"


def normalize_table_ast(raw: Any) -> dict[str, Any] | None:
    candidate = _coerce_object(raw)
    if candidate is None:
        return None

    if isinstance(candidate, list):
        return table_ast_from_rows(_rows_from_mixed(candidate))

    if not isinstance(candidate, dict):
        return None

    nested = candidate.get("table_ast")
    if nested is not None:
        return normalize_table_ast(nested)

    if "table" in candidate and isinstance(candidate["table"], (dict, list)):
        nested_table = normalize_table_ast(candidate["table"])
        if nested_table is not None:
            return nested_table

    if "table_cells" in candidate or "grid" in candidate:
        grid_table = table_ast_from_docling_grid(candidate)
        if grid_table is not None:
            return grid_table

    result: dict[str, Any] = {}

    caption = candidate.get("caption") or candidate.get("title")
    if isinstance(caption, str) and caption.strip():
        result["caption"] = caption.strip()

    rows_only = candidate.get("rows")
    if isinstance(rows_only, list) and not any(
        section in candidate for section in ("header", "body", "footer")
    ):
        return table_ast_from_rows(_rows_from_mixed(rows_only), caption=result.get("caption"))

    cells_only = candidate.get("cells")
    if isinstance(cells_only, list) and not any(
        section in candidate for section in ("header", "body", "footer")
    ):
        row = _normalize_row({"cells": cells_only})
        if row is not None:
            result["body"] = [row]

    for section_name in ("header", "body", "footer"):
        section = candidate.get(section_name)
        if section is None:
            continue
        if not isinstance(section, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for raw_row in section:
            row = _normalize_row(raw_row)
            if row is not None:
                normalized_rows.append(row)
        if normalized_rows:
            result[section_name] = normalized_rows

    metadata = candidate.get("metadata")
    if isinstance(metadata, dict):
        result["metadata"] = deepcopy(metadata)

    if not result.get("body"):
        return None
    return result


def table_ast_from_rows(rows: Any, *, caption: str | None = None) -> dict[str, Any] | None:
    normalized_rows = _rows_from_mixed(rows)
    if not normalized_rows:
        return None
    body = [
        {
            "cells": [
                {
                    "text": str(cell).strip(),
                }
                for cell in row
            ]
        }
        for row in normalized_rows
    ]
    body = [row for row in body if row["cells"]]
    if not body:
        return None
    result: dict[str, Any] = {"body": body}
    if isinstance(caption, str) and caption.strip():
        result["caption"] = caption.strip()
    return result


def table_ast_from_docling_grid(
    grid_or_cells: Any,
    *,
    caption: str | None = None,
) -> dict[str, Any] | None:
    """Extract a canonical table_ast from Docling table grid or cell items.

    Handles Docling table representations such as:
    - Lists of table cell dicts or objects with:
      start_row_offset_idx, start_col_offset_idx, row_span, col_span, text, column_header, row_header
    - Objects with .table_cells, .data.table_cells, or .data.grid
    - Dictionaries containing "table_cells" or "grid"
    """
    if grid_or_cells is None:
        return None
    candidate = _coerce_object(grid_or_cells)
    if candidate is None:
        candidate = grid_or_cells

    raw_cells: list[tuple[Any, int | None, int | None]] = []
    if isinstance(candidate, list):
        if candidate and isinstance(candidate[0], list):
            # 2D grid of cells
            for r_idx, row in enumerate(candidate):
                if isinstance(row, list):
                    for c_idx, cell in enumerate(row):
                        raw_cells.append((cell, r_idx, c_idx))
        else:
            raw_cells = [(c, None, None) for c in candidate]
    elif isinstance(candidate, dict):
        if "table_cells" in candidate and isinstance(candidate["table_cells"], list):
            raw_cells = [(c, None, None) for c in candidate["table_cells"]]
        elif "grid" in candidate and isinstance(candidate["grid"], list):
            grid = candidate["grid"]
            if grid and isinstance(grid[0], list):
                for r_idx, row in enumerate(grid):
                    if isinstance(row, list):
                        for c_idx, cell in enumerate(row):
                            raw_cells.append((cell, r_idx, c_idx))
            else:
                raw_cells = [(c, None, None) for c in grid]
        elif "data" in candidate and isinstance(candidate["data"], dict):
            return table_ast_from_docling_grid(candidate["data"], caption=caption)
    else:
        # Check object attributes
        data_attr = getattr(candidate, "data", None)
        if data_attr is not None:
            return table_ast_from_docling_grid(data_attr, caption=caption)
        cells_attr = getattr(candidate, "table_cells", None)
        if isinstance(cells_attr, list):
            raw_cells = [(c, None, None) for c in cells_attr]
        grid_attr = getattr(candidate, "grid", None)
        if isinstance(grid_attr, list):
            return table_ast_from_docling_grid(grid_attr, caption=caption)

    if not raw_cells:
        return None

    rows_by_idx: dict[int, list[tuple[int, dict[str, Any]]]] = {}
    is_header_row: dict[int, bool] = {}

    for item, fallback_r, fallback_c in raw_cells:
        cell_dict = _coerce_object(item)
        if cell_dict is None:
            cell_dict = item

        raw_r: Any = None
        raw_c: Any = None
        raw_row_span: Any = None
        raw_col_span: Any = None
        if isinstance(cell_dict, dict):
            text = str(cell_dict.get("text", "")).strip()
            raw_r = cell_dict.get("start_row_offset_idx")
            if raw_r is None:
                raw_r = cell_dict.get("row_idx", fallback_r)
            raw_c = cell_dict.get("start_col_offset_idx")
            if raw_c is None:
                raw_c = cell_dict.get("col_idx", fallback_c)
            raw_row_span = cell_dict.get("row_span") or cell_dict.get("rowspan")
            if raw_row_span is None and "end_row_offset_idx" in cell_dict and raw_r is not None:
                raw_row_span = cell_dict["end_row_offset_idx"] - raw_r
            raw_col_span = cell_dict.get("col_span") or cell_dict.get("colspan")
            if raw_col_span is None and "end_col_offset_idx" in cell_dict and raw_c is not None:
                raw_col_span = cell_dict["end_col_offset_idx"] - raw_c
            is_col_header = bool(cell_dict.get("column_header", False))
            is_row_header = bool(cell_dict.get("row_header", False))
        else:
            text = str(getattr(cell_dict, "text", "")).strip()
            raw_r = getattr(cell_dict, "start_row_offset_idx", fallback_r)
            raw_c = getattr(cell_dict, "start_col_offset_idx", fallback_c)
            raw_row_span = getattr(cell_dict, "row_span", 1)
            raw_col_span = getattr(cell_dict, "col_span", 1)
            is_col_header = bool(getattr(cell_dict, "column_header", False))
            is_row_header = bool(getattr(cell_dict, "row_header", False))

        r_idx = 0 if raw_r is None else int(raw_r)
        c_idx = 0 if raw_c is None else int(raw_c)
        row_span = 1 if raw_row_span is None else max(1, int(raw_row_span))
        col_span = 1 if raw_col_span is None else max(1, int(raw_col_span))

        norm_cell: dict[str, Any] = {"text": text}
        if row_span > 1:
            norm_cell["rowspan"] = row_span
        if col_span > 1:
            norm_cell["colspan"] = col_span
        if is_col_header or is_row_header:
            norm_cell["header"] = True
            if is_col_header:
                norm_cell["scope"] = "col"
            elif is_row_header:
                norm_cell["scope"] = "row"

        rows_by_idx.setdefault(r_idx, []).append((c_idx, norm_cell))
        if is_col_header:
            is_header_row[r_idx] = True

    if not rows_by_idx:
        return None

    header_section: list[dict[str, Any]] = []
    body_section: list[dict[str, Any]] = []

    for r_idx in sorted(rows_by_idx.keys()):
        cells_in_row = [cell for _, cell in sorted(rows_by_idx[r_idx], key=lambda t: t[0])]
        row_obj = {"cells": cells_in_row}
        if is_header_row.get(r_idx, False):
            header_section.append(row_obj)
        else:
            body_section.append(row_obj)

    if not body_section and header_section:
        if len(header_section) == 1:
            body_section = header_section
            header_section = []
        else:
            body_section = header_section[1:]
            header_section = [header_section[0]]

    table_ast: dict[str, Any] = {}
    if header_section:
        table_ast["header"] = header_section
    if body_section:
        table_ast["body"] = body_section
    if caption:
        table_ast["caption"] = caption.strip()

    return normalize_table_ast(table_ast)


def analyze_table_complexity(table_ast: Any) -> TableComplexityMetrics:
    """Analyze table AST structure to compute span and complexity metrics.

    Returns:
        TableComplexityMetrics dataclass with:
        - has_spans: bool
        - max_rowspan: int
        - max_colspan: int
        - spanned_cell_count: int
        - is_complex: bool
    """
    normalized = normalize_table_ast(table_ast)
    if normalized is None:
        return TableComplexityMetrics(
            has_spans=False,
            max_rowspan=1,
            max_colspan=1,
            spanned_cell_count=0,
            is_complex=False,
        )

    all_cells: list[dict[str, Any]] = []
    for section_name in ("header", "body", "footer"):
        section = normalized.get(section_name)
        if isinstance(section, list):
            for row in section:
                if isinstance(row, dict):
                    cells = row.get("cells")
                    if isinstance(cells, list):
                        for cell in cells:
                            if isinstance(cell, dict):
                                all_cells.append(cell)

    max_rowspan = 1
    max_colspan = 1
    spanned_count = 0

    for cell in all_cells:
        rs = cell.get("rowspan") or 1
        cs = cell.get("colspan") or 1
        if isinstance(rs, int) and rs > max_rowspan:
            max_rowspan = rs
        if isinstance(cs, int) and cs > max_colspan:
            max_colspan = cs
        if (isinstance(rs, int) and rs > 1) or (isinstance(cs, int) and cs > 1):
            spanned_count += 1

    has_spans = max_rowspan > 1 or max_colspan > 1
    is_complex = has_spans

    return TableComplexityMetrics(
        has_spans=has_spans,
        max_rowspan=max_rowspan,
        max_colspan=max_colspan,
        spanned_cell_count=spanned_count,
        is_complex=is_complex,
    )


def rows_from_table_ast(table_ast: Any) -> list[list[str]]:
    normalized = normalize_table_ast(table_ast)
    if normalized is None:
        return []
    rows: list[list[str]] = []
    for section_name in ("header", "body", "footer"):
        section = normalized.get(section_name)
        if not isinstance(section, list):
            continue
        for row in section:
            cells = row.get("cells", []) if isinstance(row, dict) else []
            row_values = [
                str(cell.get("text", "")).strip()
                for cell in cells
                if isinstance(cell, dict)
            ]
            if row_values:
                rows.append(row_values)
    return rows


def table_ast_from_block(block: dict[str, Any]) -> dict[str, Any] | None:
    table_ast = normalize_table_ast(block.get("table_ast"))
    if table_ast is not None:
        return table_ast
    return table_ast_from_rows(block.get("rows"), caption=block.get("caption"))


def effective_section_row_widths(rows: list[dict[str, Any]]) -> list[int]:
    """Return each row's logical width while carrying active row spans.

    Cells in HTML/Pandoc tables are placed in the first contiguous free column
    range. A cell spanning subsequent rows therefore occupies those columns
    even though it is absent from the later rows' ``cells`` lists.
    """
    return [width for width, _leading_headers in _project_section_rows(rows)]


def effective_section_width(rows: list[dict[str, Any]]) -> int:
    """Return the maximum logical width of a table section."""
    return max(effective_section_row_widths(rows), default=0)


def row_header_column_count(body_rows: list[dict[str, Any]]) -> int:
    """Return the common leading width carrying row-header semantics."""
    if not body_rows:
        return 0

    projections = _project_section_rows(body_rows)
    leading_widths = [leading_headers for _width, leading_headers in projections]

    # A legacy body-only AST may mark the whole first row as headers while the
    # following rows mark only their first column. Let split_header_and_body()
    # promote that first row instead of treating it as another row-header row.
    first_width, first_leading_headers = projections[0]
    if (
        len(projections) >= 2
        and first_width > 0
        and first_leading_headers == first_width
        and not _row_has_explicit_row_scope(body_rows[0])
        and any(
            leading_headers < first_leading_headers
            for _width, leading_headers in projections[1:]
        )
    ):
        return 0

    return min(leading_widths, default=0)


def _cell_is_row_header(cell: dict[str, Any]) -> bool:
    scope = str(cell.get("scope", "")).strip().lower()
    return scope in {"row", "rowgroup"} or (
        bool(cell.get("header")) and scope not in {"col", "colgroup"}
    )


def _row_has_explicit_row_scope(row: dict[str, Any]) -> bool:
    cells = row.get("cells", []) if isinstance(row, dict) else []
    return any(
        isinstance(cell, dict)
        and str(cell.get("scope", "")).strip().lower() in {"row", "rowgroup"}
        for cell in cells
    )


def _project_section_rows(
    rows: list[dict[str, Any]],
) -> list[tuple[int, int]]:
    """Project rows into a logical grid as ``(width, leading_headers)``."""
    # column -> (number of future rows still occupied, row-header semantics)
    active_spans: dict[int, tuple[int, bool]] = {}
    projections: list[tuple[int, int]] = []

    for row in rows:
        occupied = {
            column: is_row_header
            for column, (_remaining, is_row_header) in active_spans.items()
        }
        next_spans = {
            column: (remaining - 1, is_row_header)
            for column, (remaining, is_row_header) in active_spans.items()
            if remaining > 1
        }

        cells = row.get("cells", []) if isinstance(row, dict) else []
        cursor = 0
        for cell in cells:
            if not isinstance(cell, dict):
                continue

            colspan_value = cell.get("colspan")
            colspan = (
                colspan_value
                if isinstance(colspan_value, int) and colspan_value >= 1
                else 1
            )
            rowspan_value = cell.get("rowspan")
            rowspan = (
                rowspan_value
                if isinstance(rowspan_value, int) and rowspan_value >= 1
                else 1
            )

            while True:
                conflicting_column = next(
                    (
                        column
                        for column in range(cursor, cursor + colspan)
                        if column in occupied
                    ),
                    None,
                )
                if conflicting_column is None:
                    break
                cursor = conflicting_column + 1

            is_row_header = _cell_is_row_header(cell)
            for column in range(cursor, cursor + colspan):
                occupied[column] = is_row_header
                if rowspan > 1:
                    next_spans[column] = (rowspan - 1, is_row_header)
            cursor += colspan

        width = max(occupied, default=-1) + 1
        leading_headers = 0
        while occupied.get(leading_headers) is True:
            leading_headers += 1
        projections.append((width, leading_headers))
        active_spans = next_spans

    return projections


def split_header_and_body(
    table_ast: dict[str, Any], *, infer_legacy_header: bool = True
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    header = list(table_ast.get("header") or [])
    body = list(table_ast.get("body") or [])
    footer = list(table_ast.get("footer") or [])

    has_complete_row_headers = row_header_column_count(body) > 0
    if (
        not header
        and not has_complete_row_headers
        and infer_legacy_header
        and len(body) >= 2
        and not _row_has_explicit_row_scope(body[0])
    ):
        header = [body[0]]
        body = body[1:]

    return header, body, footer


def linearize_table_for_text(block: dict[str, Any]) -> list[str]:
    """Linearizes the block's table_ast into TXT lines.

    Args:
        block (dict): Canonical table block mapping, expected to carry a "table_ast" (or legacy "rows"/"caption").

    Returns:
        list[str]: One line per caption, body row, and footer row, using the
        canonical English msgid templates (already formatted). Empty when the
        block has no usable table_ast.
    """
    table_ast = table_ast_from_block(block)
    if table_ast is None:
        return []

    lines: list[str] = []
    caption = table_ast.get("caption")
    if isinstance(caption, str) and caption.strip():
        lines.append(MSG_TABLE_TEXT_CAPTION.format(caption=caption.strip()))

    header_rows, body_rows, footer_rows = split_header_and_body(table_ast)
    headers = _effective_headers(header_rows)

    if not body_rows:
        body_rows = []

    for index, row in enumerate(body_rows, start=1):
        cells = _row_texts(row)
        if headers and len(headers) == len(cells):
            joined = "; ".join(
                f"{headers[cell_index]}: {value}" for cell_index, value in enumerate(cells)
            )
            lines.append(MSG_TABLE_TEXT_ROW.format(row_index=index, joined=joined))
        else:
            lines.append(
                MSG_TABLE_TEXT_ROW.format(
                    row_index=index, joined=" | ".join(cells)
                )
            )

    for row in footer_rows:
        footer_text = " | ".join(_row_texts(row))
        if footer_text:
            lines.append(MSG_TABLE_TEXT_FOOTER.format(footer_text=footer_text))

    if not lines:
        # Defensive fallback for degenerate tables.
        for fallback_row in rows_from_table_ast(table_ast):
            lines.append(" | ".join(fallback_row))

    return lines


def _effective_headers(header_rows: list[dict[str, Any]]) -> list[str]:
    if not header_rows:
        return []
    if len(header_rows) == 1:
        return _row_texts(header_rows[0])

    merged: list[str] = []
    width = max((len(_row_texts(row)) for row in header_rows), default=0)
    for col_index in range(width):
        parts = []
        for row in header_rows:
            row_values = _row_texts(row)
            if col_index < len(row_values) and row_values[col_index]:
                parts.append(row_values[col_index])
        merged.append(" - ".join(parts))
    return merged


def _row_texts(row: dict[str, Any]) -> list[str]:
    cells = row.get("cells", []) if isinstance(row, dict) else []
    values = [
        str(cell.get("text", "")).strip()
        for cell in cells
        if isinstance(cell, dict)
    ]
    return values


def _normalize_row(raw_row: Any) -> dict[str, Any] | None:
    if isinstance(raw_row, list):
        cells = [{"text": str(cell).strip()} for cell in raw_row]
        return {"cells": cells} if cells else None

    row_obj = _coerce_object(raw_row)
    if row_obj is None:
        return None

    if isinstance(row_obj, list):
        cells = [{"text": str(cell).strip()} for cell in row_obj]
        return {"cells": cells} if cells else None

    if not isinstance(row_obj, dict):
        return None

    raw_cells = row_obj.get("cells")
    if isinstance(raw_cells, list):
        cells = []
        for raw_cell in raw_cells:
            cell = _normalize_cell(raw_cell)
            if cell is not None:
                cells.append(cell)
        return {"cells": cells} if cells else None

    rows_field = row_obj.get("rows")
    if isinstance(rows_field, list):
        rows = _rows_from_mixed(rows_field)
        if rows:
            return {"cells": [{"text": value} for value in rows[0]]}

    text = row_obj.get("text")
    if isinstance(text, str) and text.strip():
        return {"cells": [{"text": text.strip()}]}

    return None


def _normalize_cell(raw_cell: Any) -> dict[str, Any] | None:
    if isinstance(raw_cell, str):
        return {"text": raw_cell.strip()}

    cell_obj = _coerce_object(raw_cell)
    if cell_obj is None:
        return None

    if isinstance(cell_obj, str):
        return {"text": cell_obj.strip()}

    if not isinstance(cell_obj, dict):
        return None

    text = cell_obj.get("text")
    if not isinstance(text, str):
        return None

    cell: dict[str, Any] = {"text": text.strip()}
    if isinstance(cell_obj.get("header"), bool):
        cell["header"] = cell_obj["header"]

    scope = cell_obj.get("scope")
    if isinstance(scope, str) and scope in ALLOWED_SCOPES:
        cell["scope"] = scope

    for span_key in ("rowspan", "colspan"):
        span_value = cell_obj.get(span_key)
        if isinstance(span_value, int) and span_value >= 1:
            cell[span_key] = span_value

    metadata = cell_obj.get("metadata")
    if isinstance(metadata, dict):
        cell["metadata"] = deepcopy(metadata)

    return cell


def _rows_from_mixed(raw_rows: Any) -> list[list[str]]:
    if not isinstance(raw_rows, list):
        return []
    rows: list[list[str]] = []
    for raw_row in raw_rows:
        if isinstance(raw_row, list):
            values = [str(cell).strip() for cell in raw_row]
            if any(values):
                rows.append(values)
            continue

        row_dict = _normalize_row(raw_row)
        if row_dict is not None:
            values = _row_texts(row_dict)
            if any(values):
                rows.append(values)
    return rows


def _coerce_object(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (dict, list, str, int, float, bool)):
        return value

    for method_name in ("model_dump", "to_dict", "export_to_dict"):
        method = getattr(value, method_name, None)
        if callable(method):
            dumped = None
            try:
                dumped = method()
            except TypeError:
                try:
                    dumped = method(mode="json")
                except Exception:  # noqa: BLE001
                    dumped = None
            except Exception:  # noqa: BLE001
                dumped = None
            if isinstance(dumped, (dict, list)):
                return dumped
    return None
