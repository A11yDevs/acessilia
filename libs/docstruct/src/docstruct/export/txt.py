"""Plain-text rendering of canonical documents (pure transformation).

Ported from backend/export/renderers/txt_renderer.py. The file write
stays in the backend; this module produces the lines only.
"""
from __future__ import annotations

from typing import Any

from docstruct.blocks.lists import item_label, list_numbering, list_start
from docstruct.profiles import filter_blocks_for_profile
from docstruct.sections import section_body_blocks
from docstruct.tables.ast import linearize_table_for_text, table_ast_from_block
from docstruct.text.math_spans import inline_math_entries, split_inline_math

DEFAULT_FORMULA_LABEL = "Fórmula: {text}"


def document_to_txt_lines(
    document: dict[str, Any],
    *,
    profile: str = "txt",
    formula_label: str = DEFAULT_FORMULA_LABEL,
) -> list[str]:
    """Render the canonical document into plain-text lines (no file I/O)."""
    lines: list[str] = []
    for section in document.get("sections", []):
        lines.extend(_render_section(section, profile, formula_label))
    return [line for line in lines if line is not None]


def _render_section(section: dict[str, Any], profile_name: str, formula_label: str = DEFAULT_FORMULA_LABEL) -> list[str]:
    """Renders one section (its title, profile-filtered blocks, and nested children) into text lines.

    Args:
        section (dict): Canonical section mapping with optional "title", "blocks", "children".
        profile_name (str): Export verbosity profile applied to the section's block filtering.

    Returns:
        list[str]: The rendered lines for the section and its nested children.
    """
    lines: list[str] = []
    if section.get("title"):
        lines.append(section["title"])
    for block in filter_blocks_for_profile(section_body_blocks(section), profile_name):
        lines.extend(_render_block(block, formula_label))
    for child in section.get("children", []):
        lines.extend(_render_section(child, profile_name))
    return lines


def _render_block(block: dict[str, Any], formula_label: str = DEFAULT_FORMULA_LABEL) -> list[str]:
    """Renders one canonical block into plain-text lines, choosing formatting by block type.

    Args:
        block (dict): Canonical block mapping with at least "type" and the type-specific payload.

    Returns:
        list[str]: The rendered lines for the block.
    """
    block_type = block.get("type")
    if block_type == "heading":
        return [block.get("title", block.get("text", ""))]
    if block_type == "paragraph":
        return [_prose_text(block.get("text", ""), block)]
    if block_type == "code":
        return [block.get("text", "")]
    if block_type == "list":
        items = block.get("items", [])
        if not block.get("ordered"):
            return [f"- {_prose_text(str(item), block)}" for item in items]
        numbering = list_numbering(block)
        return [
            f"{item_label(number, numbering)}. {_prose_text(str(item), block)}"
            for number, item in enumerate(items, start=list_start(block))
        ]
    if block_type == "table":
        return linearize_table_for_text(_spoken_table(block))
    if block_type == "image":
        return [block.get("alt_text") or block.get("text", "")]
    if block_type == "math":
        return [block.get("alt_text") or formula_label.format(text=block.get('text', ''))]
    if block_type in {"details", "note", "warning", "quote"}:
        return [_prose_text(block.get("text", ""), block)]
    return [block.get("text", "")]


def _prose_text(text: str, block: dict[str, Any]) -> str:
    """Prose whose ``$…$`` spans are read: their speech, else their bare LaTeX
    (normalized when the canonical enrichment saw it).

    The TXT is also what the MP3 speaks, so a formula inside a sentence is
    read in it ("s de t igual a t ao cubo") rather than spelled with dollars.
    """
    entries = inline_math_entries(block)
    return "".join(
        _spoken(entries.get(piece, {}), piece) if is_math else piece
        for piece, is_math in split_inline_math(str(text))
    )


def _spoken_table(block: dict[str, Any]) -> dict[str, Any]:
    """A copy of the table block whose caption and cells have their ``$…$``
    spans read (``_prose_text``), so the linearized rows speak the formulas.

    ``table_ast_from_block`` returns a fresh normalized AST, so ``block`` is
    not mutated."""
    table_ast = table_ast_from_block(block)
    if table_ast is None:
        return block
    caption = table_ast.get("caption")
    if isinstance(caption, str):
        table_ast["caption"] = _prose_text(caption, block)
    for section in ("header", "body", "footer"):
        for row in table_ast.get(section) or []:
            for cell in row.get("cells") or []:
                if isinstance(cell, dict) and isinstance(cell.get("text"), str):
                    cell["text"] = _prose_text(cell["text"], block)
    return {**block, "table_ast": table_ast}


def _spoken(entry: dict[str, Any], source: str) -> str:
    return str(entry.get("speech") or entry.get("latex") or source)
