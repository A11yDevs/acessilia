"""Canonical document → benchmark markdown.

The target is the markdown that document-parsing benchmarks (Dr.DocBench,
OmniDocBench) compare against: ``#`` headings, tables as structured HTML
(``table_ast`` with rowspan/colspan), display math as ``$$...$$``, fenced
code, ``-`` list items and plain text; images carry no content. Port of
``scripts/drbench/markdown_converter.py`` (tag drbench-2026-snapshot).
"""
from __future__ import annotations

from typing import Any

from docstruct.blocks.lists import list_start
from docstruct.export.walk import BlockContext, SectionContext, Visitor, walk
from docstruct.tables.ast import table_ast_from_block
from docstruct.text.equations import numbered_latex
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
    for rendered in walk({"sections": sections}, _visitor(), select=_select_block):
        if rendered:
            yield rendered


def _select_block(block: dict[str, Any], ctx: BlockContext) -> bool:
    # Markdown historically omits every matching heading, regardless of its
    # position or level. Unifying this with legacy-title selection is E1.8.
    title = (ctx.section.data.get("title") or "").strip()
    return not (
        block.get("type") == "heading" and title
        and (block.get("text") or "").strip() == title
    )


def _section_title(ctx: SectionContext) -> str | None:
    level = int(ctx.data.get("level", 1) or 1)
    title = (ctx.data.get("title") or "").strip()
    return f"{'#' * max(1, min(level, 6))} {title}" if title else None


def _visitor() -> Visitor[str]:
    return Visitor(
        default=lambda block, ctx: _text(block),
        heading=lambda block, ctx: _heading(block),
        paragraph=lambda block, ctx: _text(block),
        list=lambda block, ctx: _list(block),
        table=lambda block, ctx: render_table(block),
        image=lambda block, ctx: _image(block),
        code=lambda block, ctx: _code(block),
        math=lambda block, ctx: _math(block),
        quote=lambda block, ctx: _text(block),
        details=lambda block, ctx: _text(block),
        note=lambda block, ctx: _text(block),
        warning=lambda block, ctx: _text(block),
        enter_section=_section_title,
    )


def _render_block(block: dict[str, Any]) -> str:
    """Render one block using the document visitor, without section selection."""
    return next(walk({"sections": [{"blocks": [block]}]}, _visitor()), "")


def _heading(block: dict[str, Any]) -> str:
    level = int(block.get("level", 1) or 1)
    text = (block.get("text") or "").strip()
    return f"{'#' * max(1, min(level, 6))} {text}" if text else ""


def _math(block: dict[str, Any]) -> str:
    latex = numbered_latex(bare_latex(block.get("text") or ""), block.get("metadata") or {})
    return f"$$\n{latex}\n$$" if latex else ""


def _code(block: dict[str, Any]) -> str:
    language = (block.get("language") or "").strip()
    return f"```{language}\n{block.get('text') or ''}\n```"


def _list(block: dict[str, Any]) -> str:
    # Numbered by source position, so an empty item dropped here leaves
    # the same numbers as in the other exports; CommonMark lists are
    # decimal only, so a lettered or roman list keeps its numbers.
    lines = []
    for number, item in enumerate(block.get("items", []), start=list_start(block)):
        marker = f"{number}." if block.get("ordered") else "-"
        if str(item).strip():
            lines.append(f"{marker} {str(item).strip()}")
    return "\n".join(lines)


def _image(block: dict[str, Any]) -> str:
    return ""


def _text(block: dict[str, Any]) -> str:
    return (block.get("text") or "").strip()


def render_table(block: dict[str, Any]) -> str:
    """Render a canonical table block as HTML (provider HTML kept as is).

    Benchmark Markdown keeps the AST's sections as they are. The legacy
    first-row header inference that the accessible exporters apply is not
    repeated here.
    """
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
    # A <thead> row with no cell marked as a header (``header: True`` or a
    # header scope) uses column headers, so the ``header: False`` defaults a
    # promoted first row carries do not turn it into data cells; marked rows
    # follow each cell's own metadata, as in the HTML exporter.
    unmarked_header_row = header and not any(
        isinstance(cell, dict)
        and (
            bool(cell.get("header"))
            or str(cell.get("scope", "")).strip().lower() in _HEADER_SCOPES
        )
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
