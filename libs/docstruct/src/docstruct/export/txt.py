"""Plain-text rendering of canonical documents (pure transformation).

Ported from backend/export/renderers/txt_renderer.py. The file write
stays in the backend; this module produces the lines only.
"""
from __future__ import annotations

from typing import Any

from docstruct.blocks.lists import item_label, list_numbering, list_start
from docstruct.export.walk import SectionContext, Visitor, walk
from docstruct.profiles import normalize_profile
from docstruct.tables.ast import linearize_table_for_text, table_ast_from_block
from docstruct.text.equations import numbered_speech
from docstruct.text.math_spans import inline_math_entries, split_inline_math

DEFAULT_FORMULA_LABEL = "Fórmula: {text}"


def document_to_txt_lines(
    document: dict[str, Any],
    *,
    profile: str = "txt",
    formula_label: str = DEFAULT_FORMULA_LABEL,
) -> list[str]:
    """Render the canonical document into plain-text lines (no file I/O)."""
    lines = _document_lines(document, profile, formula_label)
    return [line for line in lines if line is not None]


def _render_section(section: dict[str, Any], profile_name: str, formula_label: str = DEFAULT_FORMULA_LABEL) -> list[str]:
    """Compatibility entry point for one section, including its children."""
    return _document_lines({"sections": [section]}, profile_name, formula_label)


def _document_lines(document: dict[str, Any], profile: str, formula_label: str) -> list[str]:
    allowed = set(normalize_profile(profile)["verbosity"])
    return [line for group in walk(
        document, _visitor(formula_label),
        select=lambda block, ctx: not ctx.is_legacy_title and block.get("verbosity", "basic") in allowed,
    ) for line in group]


def _section_title(ctx: SectionContext) -> list[str]:
    return [ctx.data["title"]] if ctx.data.get("title") else []


def _visitor(formula_label: str) -> Visitor[list[str]]:
    return Visitor(
        default=lambda block, ctx: _fallback(block),
        heading=lambda block, ctx: _heading(block),
        paragraph=lambda block, ctx: _prose(block),
        list=lambda block, ctx: _list(block),
        table=lambda block, ctx: _table(block),
        image=lambda block, ctx: _image(block),
        code=lambda block, ctx: _plain(block),
        # Preserve the current child label policy until E1.8 (#161).
        math=lambda block, ctx: _math(
            block, formula_label if ctx.section.depth == 0 else DEFAULT_FORMULA_LABEL,
        ),
        quote=lambda block, ctx: _prose(block),
        details=lambda block, ctx: _prose(block),
        note=lambda block, ctx: _prose(block),
        warning=lambda block, ctx: _prose(block),
        enter_section=_section_title,
    )


def _render_block(block: dict[str, Any], formula_label: str = DEFAULT_FORMULA_LABEL) -> list[str]:
    """Compatibility entry point for one block, using the same visitor."""
    return [line for group in walk(
        {"sections": [{"blocks": [block]}]}, _visitor(formula_label),
    ) for line in group]


def _heading(block: dict[str, Any]) -> list[str]:
    return [block.get("title", block.get("text", ""))]


def _prose(block: dict[str, Any]) -> list[str]:
    return [_prose_text(block.get("text", ""), block)]


def _plain(block: dict[str, Any]) -> list[str]:
    return [block.get("text", "")]


def _fallback(block: dict[str, Any]) -> list[str]:
    # Retain the TypeError for unhashable kinds from the former set dispatch.
    hash(block.get("type"))
    return _plain(block)


def _list(block: dict[str, Any]) -> list[str]:
    items = block.get("items", [])
    if not block.get("ordered"):
        return [f"- {_prose_text(str(item), block)}" for item in items]
    numbering = list_numbering(block)
    return [
        f"{item_label(number, numbering)}. {_prose_text(str(item), block)}"
        for number, item in enumerate(items, start=list_start(block))
    ]


def _table(block: dict[str, Any]) -> list[str]:
    return linearize_table_for_text(_spoken_table(block))


def _image(block: dict[str, Any]) -> list[str]:
    return [block.get("alt_text") or block.get("text", "")]


def _math(block: dict[str, Any], formula_label: str) -> list[str]:
    speech = block.get("alt_text") or formula_label.format(text=block.get('text', ''))
    return [numbered_speech(speech, block.get("metadata") or {})]


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
