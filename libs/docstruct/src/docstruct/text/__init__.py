"""Text manipulation modules of docstruct."""
from __future__ import annotations

from docstruct.blocks.classify import classify_text_block
from docstruct.text.code_reflow import normalize_code_text
from docstruct.text.latex import (
    bare_latex,
    ensure_math_delimiters,
    has_latex_markup,
    latex_text_agreement,
    normalize_latex,
    strip_latex_delimiters,
    wrap_latex,
)
from docstruct.text.paragraphs import merge_broken_paragraphs
from docstruct.text.sanitize import sanitize_text
from docstruct.text.unicode_repair import (
    Detection,
    Edit,
    UnicodeRepairContext,
    UnicodeRepairDecision,
    detect_legacy_unicode,
    repair_legacy_unicode,
)

__all__ = [
    "Detection",
    "Edit",
    "UnicodeRepairContext",
    "UnicodeRepairDecision",
    "bare_latex",
    "classify_text_block",
    "detect_legacy_unicode",
    "ensure_math_delimiters",
    "has_latex_markup",
    "latex_text_agreement",
    "merge_broken_paragraphs",
    "normalize_code_text",
    "normalize_latex",
    "repair_legacy_unicode",
    "sanitize_text",
    "strip_latex_delimiters",
    "wrap_latex",
]
