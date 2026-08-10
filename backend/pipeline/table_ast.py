from __future__ import annotations

from copy import deepcopy
from typing import Any

ALLOWED_SCOPES = {"none", "row", "col", "rowgroup", "colgroup"}


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
                if str(cell).strip()
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
                if isinstance(cell, dict) and str(cell.get("text", "")).strip()
            ]
            if row_values:
                rows.append(row_values)
    return rows


def table_ast_from_block(block: dict[str, Any]) -> dict[str, Any] | None:
    table_ast = normalize_table_ast(block.get("table_ast"))
    if table_ast is not None:
        return table_ast
    return table_ast_from_rows(block.get("rows"), caption=block.get("caption"))


def split_header_and_body(
    table_ast: dict[str, Any], *, infer_legacy_header: bool = True
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    header = list(table_ast.get("header") or [])
    body = list(table_ast.get("body") or [])
    footer = list(table_ast.get("footer") or [])

    if not header and infer_legacy_header and len(body) >= 2:
        header = [body[0]]
        body = body[1:]

    return header, body, footer


def linearize_table_for_text(block: dict[str, Any]) -> list[str]:
    table_ast = table_ast_from_block(block)
    if table_ast is None:
        return []

    lines: list[str] = []
    caption = table_ast.get("caption")
    if isinstance(caption, str) and caption.strip():
        lines.append(f"Tabela: {caption.strip()}")

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
            lines.append(f"Linha {index}: {joined}")
        else:
            lines.append(f"Linha {index}: {' | '.join(cells)}")

    for row in footer_rows:
        footer_text = " | ".join(_row_texts(row))
        if footer_text:
            lines.append(f"Rodape: {footer_text}")

    if not lines:
        # Fallback defensivo para tabelas degeneradas.
        for row in rows_from_table_ast(table_ast):
            lines.append(" | ".join(row))

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
        if isinstance(cell, dict) and str(cell.get("text", "")).strip()
    ]
    return values


def _normalize_row(raw_row: Any) -> dict[str, Any] | None:
    if isinstance(raw_row, list):
        cells = [{"text": str(cell).strip()} for cell in raw_row if str(cell).strip()]
        return {"cells": cells} if cells else None

    row_obj = _coerce_object(raw_row)
    if row_obj is None:
        return None

    if isinstance(row_obj, list):
        cells = [{"text": str(cell).strip()} for cell in row_obj if str(cell).strip()]
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
        text = raw_cell.strip()
        return {"text": text} if text else None

    cell_obj = _coerce_object(raw_cell)
    if cell_obj is None:
        return None

    if isinstance(cell_obj, str):
        text = cell_obj.strip()
        return {"text": text} if text else None

    if not isinstance(cell_obj, dict):
        return None

    text = cell_obj.get("text")
    if not isinstance(text, str) or not text.strip():
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
            values = [str(cell).strip() for cell in raw_row if str(cell).strip()]
            if values:
                rows.append(values)
            continue

        row_dict = _normalize_row(raw_row)
        if row_dict is not None:
            values = _row_texts(row_dict)
            if values:
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
            try:
                dumped = method()
            except TypeError:
                try:
                    dumped = method(mode="json")
                except Exception:
                    continue
            except Exception:
                continue
            if isinstance(dumped, (dict, list)):
                return dumped
    return None
