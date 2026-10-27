"""Inline math spans in block text (``$…$`` and ``\\(…\\)``).

A paragraph, list item, callout or table (its caption and cells) can carry
formulas inside its prose: the page OCR model writes them as ``$…$``, and the
core marks the inline math it finds in the text layer the same way. The
canonical enrichment converts each span once (``metadata["inline_math"]``)
and the exporters render it as math instead of the literal delimiters.

The ``$`` rule is Pandoc's ``tex_math_dollars`` plus one guard for Portuguese
prose: the opening ``$`` is not followed by a space, the closing one is not
preceded by a space nor followed by a digit, and the opening one is not
preceded by a letter or digit, so ``R$ 10,00`` and ``R$5 ou R$ 3`` stay text.
``$$…$$`` is display math and is left alone.
"""
from __future__ import annotations

import re
from typing import Any

from docstruct.tables.ast import table_ast_from_block

_INLINE_MATH_RE = re.compile(
    r"(?<![\w\\$])\$(?![\s$])((?:\\.|[^$\\])+?)(?<![\s\\])\$(?![\d$])"
    r"|\\\((.+?)\\\)",
    re.DOTALL,
)

#: Block types whose text is prose that can carry inline math. The HTML, TXT
#: and Pandoc AST exporters render these types through their ``_prose_*``
#: helper: a new prose type goes here and in the three exporters. A table's
#: prose is its caption and the text of each cell (#260).
INLINE_MATH_BLOCK_TYPES = frozenset(
    {"paragraph", "list", "quote", "details", "note", "warning", "table"}
)


def split_inline_math(text: str) -> list[tuple[str, bool]]:
    """``text`` cut into ``(piece, is_math)``, math pieces without delimiters.

    Text pieces keep their whitespace, so joining the text pieces with the
    rendered formulas gives back the original spacing.
    """
    pieces: list[tuple[str, bool]] = []
    position = 0
    for match in _INLINE_MATH_RE.finditer(text):
        latex = (match.group(1) or match.group(2) or "").strip()
        if not latex:
            continue
        if match.start() > position:
            pieces.append((text[position : match.start()], False))
        pieces.append((latex, True))
        position = match.end()
    if position < len(text):
        pieces.append((text[position:], False))
    return pieces


def inline_math_sources(text: str) -> list[str]:
    """The LaTeX of each inline math span of ``text``, in order."""
    return [piece for piece, is_math in split_inline_math(text) if is_math]


def block_prose(block: dict[str, Any]) -> list[str]:
    """The prose strings of a block that can carry inline math."""
    if block.get("type") not in INLINE_MATH_BLOCK_TYPES:
        return []
    if block.get("type") == "list":
        return [str(item) for item in block.get("items", [])]
    if block.get("type") == "table":
        return _table_prose(block)
    return [str(block.get("text", ""))]


def _table_prose(block: dict[str, Any]) -> list[str]:
    """The caption and every cell text of a table block, in reading order."""
    table_ast = table_ast_from_block(block)
    if table_ast is None:
        return []
    prose = []
    caption = table_ast.get("caption")
    if isinstance(caption, str) and caption.strip():
        prose.append(caption)
    for section in ("header", "body", "footer"):
        for row in table_ast.get(section) or []:
            for cell in row.get("cells") or []:
                if isinstance(cell, dict) and str(cell.get("text", "")).strip():
                    prose.append(str(cell["text"]))
    return prose


def inline_math_entries(block: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """The block's converted inline formulas, keyed by their source LaTeX."""
    entries = (block.get("metadata") or {}).get("inline_math") or []
    return {
        str(entry["source"]): entry
        for entry in entries
        if isinstance(entry, dict) and entry.get("source")
    }


__all__ = [
    "INLINE_MATH_BLOCK_TYPES",
    "block_prose",
    "inline_math_entries",
    "inline_math_sources",
    "split_inline_math",
]
