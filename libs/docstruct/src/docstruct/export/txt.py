"""Plain-text rendering of canonical documents (pure transformation).

Ported from backend/export/renderers/txt_renderer.py. The file write
stays in the backend; this module produces the lines only.
"""
from __future__ import annotations

from typing import Any

from docstruct.profiles import filter_blocks_for_profile
from docstruct.tables.ast import linearize_table_for_text

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
    for block in filter_blocks_for_profile(section.get("blocks", []), profile_name):
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
        return [block.get("text", "")]
    if block_type == "code":
        return [block.get("text", "")]
    if block_type == "list":
        prefix = "1." if block.get("ordered") else "-"
        return [f"{prefix} {item}" for item in block.get("items", [])]
    if block_type == "table":
        return linearize_table_for_text(block)
    if block_type == "image":
        return [block.get("alt_text") or block.get("text", "")]
    if block_type == "math":
        return [block.get("alt_text") or formula_label.format(text=block.get('text', ''))]
    if block_type in {"details", "note", "warning", "quote"}:
        return [block.get("text", "")]
    return [block.get("text", "")]
