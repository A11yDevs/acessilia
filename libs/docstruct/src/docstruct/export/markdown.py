"""Canonical document → benchmark markdown.

The target is the markdown that document-parsing benchmarks (Dr.DocBench,
OmniDocBench) compare against: ``#`` headings, tables as structured HTML
(``table_ast`` with rowspan/colspan), display math as ``$$...$$``, fenced
code, ``-`` list items and plain text; images carry no content. Port of
``scripts/drbench/markdown_converter.py`` (tag drbench-2026-snapshot).
"""
from __future__ import annotations

from typing import Any

from docstruct.tables.ast import table_ast_from_block
from docstruct.text.latex import bare_latex

_HEADER_SCOPES = {"row", "col", "rowgroup", "colgroup"}


def document_to_markdown(document: dict[str, Any]) -> str:
    """Render a canonical document as benchmark markdown, in reading order."""
    lines: list[str] = []
    title = (document.get("title") or "").strip()
    sections = document.get("sections", [])
    # build_canonical_document may promote the first heading to the document
    # title; do not emit it twice.
    first_section_title = (sections[0].get("title") or "").strip() if sections else ""
    if title and title != first_section_title:
        lines.append(f"# {title}")
    lines.extend(_walk_sections(sections))
    return "\n\n".join(lines).strip() + "\n"


def _walk_sections(sections: list[dict[str, Any]]):
    for section in sections:
        level = int(section.get("level", 1) or 1)
        sec_title = (section.get("title") or "").strip()
        if sec_title:
            yield f"{'#' * max(1, min(level, 6))} {sec_title}"
        for block in section.get("blocks", []):
            # build_canonical_document emits both the section title and its
            # heading block.
            if block.get("type") == "heading" and sec_title:
                if (block.get("text") or "").strip() == sec_title:
                    continue
            rendered = _render_block(block)
            if rendered:
                yield rendered
        yield from _walk_sections(section.get("children", []))


def _render_block(block: dict[str, Any]) -> str:
    btype = block.get("type", "")
    if btype == "heading":
        level = int(block.get("level", 1) or 1)
        text = (block.get("text") or "").strip()
        return f"{'#' * max(1, min(level, 6))} {text}" if text else ""
    if btype == "math":
        latex = bare_latex(block.get("text") or "")
        return f"$$\n{latex}\n$$" if latex else ""
    if btype == "code":
        language = (block.get("language") or "").strip()
        return f"```{language}\n{block.get('text') or ''}\n```"
    if btype == "table":
        return render_table(block)
    if btype == "list":
        return "\n".join(f"- {str(i).strip()}" for i in block.get("items", []) if str(i).strip())
    if btype == "image":
        return ""
    return (block.get("text") or "").strip()


def render_table(block: dict[str, Any]) -> str:
    """Render a canonical table block as HTML (provider HTML kept as is)."""
    raw_html = block.get("html")
    if isinstance(raw_html, str) and "<table" in raw_html.lower():
        return raw_html.strip()
    ast = block.get("table_ast") or table_ast_from_block(block)
    if not ast:
        rows = block.get("rows") or []
        ast = {"body": [{"cells": [{"text": str(c)} for c in r]} for r in rows]}

    parts: list[str] = []
    caption = ast.get("caption")
    if caption:
        parts.append(f"<caption>{_escape(caption)}</caption>")
    for part, tag in (("header", "thead"), ("body", "tbody"), ("footer", "tfoot")):
        rows = ast.get(part) or []
        if rows:
            trs = "".join(_render_row(row, header=part == "header") for row in rows)
            parts.append(f"<{tag}>{trs}</{tag}>")
    return f"<table>{''.join(parts)}</table>"


def _render_row(row: dict[str, Any], *, header: bool) -> str:
    row_cells = row.get("cells", [])
    # Only a positive mark (header=True or a header scope) makes a <thead> row
    # follow per-cell metadata; ``header: False`` on every cell means "not detected".
    unmarked_header_row = header and not any(
        isinstance(cell, dict)
        and (cell.get("header") is True or str(cell.get("scope", "")).strip().lower() in _HEADER_SCOPES)
        for cell in row_cells
    )
    cells = []
    for cell in row_cells:
        scope = str(cell.get("scope", "")).strip().lower()
        is_header = unmarked_header_row or bool(cell.get("header")) or scope in _HEADER_SCOPES
        tag = "th" if is_header else "td"
        attrs = ""
        if cell.get("colspan"):
            attrs += f' colspan="{cell["colspan"]}"'
        if cell.get("rowspan"):
            attrs += f' rowspan="{cell["rowspan"]}"'
        if is_header:
            attrs += f' scope="{scope if scope in _HEADER_SCOPES else ("col" if header else "row")}"'
        cells.append(f"<{tag}{attrs}>{_escape(cell.get('text', ''))}</{tag}>")
    return f"<tr>{''.join(cells)}</tr>"


def _escape(text: Any) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


__all__ = ["bare_latex", "document_to_markdown", "render_table"]
