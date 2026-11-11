"""Plain text of the PDDL payload's pages (pure transformation).

Moved from the core's PDDL orchestrator (#402). ``blocks_text`` gives one
page's text; ``pages_text`` joins the pages under their headers, the text the
service then passes through :func:`docstruct.text.paragraphs.merge_broken_paragraphs`.
Words a reader sees are the caller's: ``image_text`` is a parameter.
"""
from __future__ import annotations

from typing import Any

from docstruct.blocks.lists import item_label, list_numbering, list_start
from docstruct.tables.ast import raw_rows_from_table_ast
from docstruct.text.paragraphs import PAGE_HEADING

#: What an image without ``alt_text`` reads as, unless the caller says otherwise.
DEFAULT_IMAGE_TEXT = "Image"


def blocks_text(blocks: list[dict[str, Any]], *, image_text: str = DEFAULT_IMAGE_TEXT) -> str:
    """One page's blocks as plain text, one line per heading, item, row or block.

    Headings get ``#`` marks (1 to 6), list items their marker, table rows
    their cells joined by ``" | "`` (read from ``table_ast`` when there are no
    ``rows``), and an image its ``alt_text``, or ``image_text`` when it has
    none. Other blocks give their stripped ``text``, if any.
    """
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "heading":
            level = int(block.get("level", 1))
            prefix = "#" * max(1, min(level, 6))
            lines.append(f"{prefix} {block.get('text', '').strip()}")
        elif block_type == "list":
            numbering = list_numbering(block)
            for number, item in enumerate(block.get("items", []), start=list_start(block)):
                marker = f"{item_label(number, numbering)}." if block.get("ordered") else "-"
                lines.append(f"{marker} {str(item).strip()}")
        elif block_type == "table":
            rows = block.get("rows")
            if not rows and isinstance(block.get("table_ast"), dict):
                rows = raw_rows_from_table_ast(block["table_ast"])
            for row in rows or []:
                if isinstance(row, list):
                    lines.append(" | ".join(str(cell).strip() for cell in row))
        elif block_type == "image":
            lines.append(block.get("alt_text", image_text))
        else:
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
    return "\n".join(lines).strip()


def pages_text(pages: list[dict[str, Any]]) -> str:
    """The pages' texts, each under its :data:`~docstruct.text.paragraphs.PAGE_HEADING`.

    Pages without text are left out; a page without ``page_number`` is "?".
    """
    chunks: list[str] = []
    for page in pages:
        page_number = page.get("page_number", "?")
        text = str(page.get("text", "")).strip()
        if text:
            chunks.append(f"{PAGE_HEADING.format(page_number=page_number)}\n{text}")
    return "\n\n".join(chunks)


__all__ = ["DEFAULT_IMAGE_TEXT", "blocks_text", "pages_text"]
