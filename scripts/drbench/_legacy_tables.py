"""Legacy helper: render a raw docling table node as markdown-embedded HTML.

Used only in the provider-payload → plain-text bridge inside run_pipeline;
once the text passes through build_canonical_document the canonical table_ast
path (markdown_converter._render_table) takes over.
"""

from __future__ import annotations

from typing import Any


def docling_table_to_markdown(table_node: dict[str, Any]) -> str:
    """Render a docling table node as an HTML <table> string."""
    data = table_node.get("data") or {}
    grid = data.get("grid") or table_node.get("grid") or []
    num_rows = int(data.get("num_rows") or table_node.get("num_rows") or 0)
    num_cols = int(data.get("num_cols") or table_node.get("num_cols") or 0)

    rows_html: list[str] = []
    for r in range(num_rows):
        cells: list[str] = []
        for c in range(num_cols):
            cell = grid[r][c] if r < len(grid) and c < len(grid[r]) else None
            if cell is None:
                continue
            text = (cell.get("text") if isinstance(cell, dict) else str(cell)) or ""
            is_header = isinstance(cell, dict) and bool(
                cell.get("column_header") or cell.get("row_header") or cell.get("header")
            )
            tag = "th" if is_header else "td"
            cells.append(f"<{tag}>{_escape(text)}</{tag}>")
        if cells:
            rows_html.append(f"<tr>{''.join(cells)}</tr>")

    return f"<table><tbody>{''.join(rows_html)}</tbody></table>"


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


__all__ = ["docling_table_to_markdown"]
