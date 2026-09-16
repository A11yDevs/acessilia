"""Convert an Acessilia canonical document to Dr.DocBench target markdown.

The canonical tree (schemas/accessible_document.schema.json) is the pipeline's
internal AST: ``sections`` recursively contain ``blocks`` of types heading |
paragraph | list | table | image | code | math | quote | details | note |
warning. This converter walks the canonical tree in reading order and emits:

- headings        -> markdown ``#`` levels (from section level + heading blocks)
- tables          -> structured HTML from ``table_ast`` (header/body cells,
                    rowspan/colspan preserved)
- math            -> LaTeX ``$$...$$``
- code            -> fenced code (chemistry/music preserved via ``language``)
- lists           -> bullet items
- text            -> original-language text unchanged

DoclingDocument or other provider payloads must first be converted to the
canonical form (via toolbox structurer + build_canonical_document).
"""

from __future__ import annotations

from typing import Any

from backend.pipeline.table_ast import table_ast_from_block


def canonical_to_drbench_md(document: dict[str, Any]) -> str:
    """Render a canonical document into benchmark markdown."""
    lines: list[str] = []

    title = (document.get("title") or "").strip()
    sections = document.get("sections", [])
    # build_canonical_document may promote the first heading to document
    # title; avoid emitting it twice.
    first_section_title = (
        (sections[0].get("title") or "").strip() if sections else ""
    )
    if title and title != first_section_title:
        lines.append(f"# {title}")

    for line in _walk_sections(sections):
        lines.append(line)

    return "\n\n".join(lines).strip() + "\n"


def _walk_sections(sections: list[dict[str, Any]]):
    """Yield markdown lines per section in reading order (depth-first)."""
    for section in sections:
        level = int(section.get("level", 1) or 1)
        sec_title = (section.get("title") or "").strip()
        if sec_title:
            lines = [f"{'#' * max(1, min(level, 6))} {sec_title}"]
        else:
            lines = []

        for block in section.get("blocks", []):
            # Skip heading blocks duplicating their own section title
            # (build_canonical_document emits both).
            if block.get("type") == "heading" and sec_title:
                if (block.get("text") or "").strip() == sec_title:
                    continue
            rendered = _render_block(block)
            if rendered:
                lines.append(rendered)

        yield from lines
        yield from _walk_sections(section.get("children", []))


def _render_block(block: dict[str, Any]) -> str:
    btype = block.get("type", "")

    if btype == "heading":
        level = int(block.get("level", 1) or 1)
        text = (block.get("text") or "").strip()
        return f"{'#' * max(1, min(level, 6))} {text}" if text else ""

    if btype == "math":
        latex = (block.get("text") or "").strip()
        return f"$$\n{latex}\n$$" if latex else ""

    if btype == "code":
        text = block.get("text") or ""
        language = (block.get("language") or "").strip()
        fence = f"```{language}" if language else "```"
        return f"{fence}\n{text}\n```"

    if btype == "table":
        return _render_table(block)

    if btype == "list":
        items = [f"- {str(i).strip()}" for i in block.get("items", []) if str(i).strip()]
        return "\n".join(items)

    if btype == "image":
        # Images carry no content in benchmark markdown.
        return ""

    text = (block.get("text") or "").strip()
    return text if text else ""


def _render_table(block: dict[str, Any]) -> str:
    """Render a canonical table block as structured HTML via table_ast."""
    ast = block.get("table_ast") or table_ast_from_block(block)
    if not ast:
        # Fallback: flat rows.
        rows = block.get("rows") or []
        ast = {"body": [{"cells": [{"text": str(c)} for c in r]} for r in rows]}

    parts: list[str] = []

    caption = ast.get("caption")
    if caption:
        parts.append(f"<caption>{_escape(caption)}</caption>")

    for part, tag in (("header", "thead"), ("body", "tbody"), ("footer", "tfoot")):
        rows = ast.get(part) or []
        if not rows:
            continue
        trs = []
        for row in rows:
            cells = []
            for cell in row.get("cells", []):
                tag_c = "th" if cell.get("header") or part == "header" else "td"
                attrs = _cell_attrs(cell)
                cells.append(
                    f"<{tag_c}{attrs}>{_escape(cell.get('text', ''))}</{tag_c}>"
                )
            trs.append(f"<tr>{''.join(cells)}</tr>")
        parts.append(f"<{tag}>{''.join(trs)}</{tag}>")

    return f"<table>{''.join(parts)}</table>"


def _cell_attrs(cell: dict[str, Any]) -> str:
    attrs = ""
    if cell.get("colspan"):
        attrs += f" colspan=\"{cell['colspan']}\""
    if cell.get("rowspan"):
        attrs += f" rowspan=\"{cell['rowspan']}\""
    return attrs


def _escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


__all__ = ["canonical_to_drbench_md"]
