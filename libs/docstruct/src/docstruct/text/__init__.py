"""Text manipulation modules of docstruct."""
from __future__ import annotations

from docstruct.blocks.classify import classify_text_block
from docstruct.text.code_reflow import normalize_code_text
from docstruct.text.latex import normalize_latex, strip_latex_delimiters, wrap_latex
from docstruct.text.paragraphs import merge_broken_paragraphs
from docstruct.text.sanitize import sanitize_text

__all__ = [
    "classify_text_block",
    "merge_broken_paragraphs",
    "normalize_code_text",
    "normalize_latex",
    "sanitize_text",
    "strip_latex_delimiters",
    "wrap_latex",
]
