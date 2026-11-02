"""LaTeX normalization and the presentation of spoken formulas.

Core migrated to docstruct.text.latex: ``normalize_latex`` is docstruct's
conservative ``bare_latex`` (strip one pair of outer delimiters, collapse
whitespace, never rewrite the math) and ``ensure_math_delimiters`` is
re-exported. This adapter keeps the core's ``wrap_latex`` default
(``display=False``, unlike docstruct's) and the "Fórmula:" label, which is
presentation.

Recognition, MathML conversion and speech run on the Toolbox
(``math.recognize``, ``math.convert``, ``math.verbalize``; see
backend/tools/toolbox_math_tools.py and ADR-0007).
"""

from __future__ import annotations

from docstruct.text.latex import (  # noqa: F401
    bare_latex as normalize_latex,
    ensure_math_delimiters,
)

__all__ = [
    "ensure_math_delimiters",
    "label_spoken_formula",
    "normalize_latex",
    "wrap_latex",
]


def wrap_latex(latex: str, display: bool = False) -> str:
    """Wrap normalized LaTeX in display ($$) or inline ($) delimiters."""
    norm = normalize_latex(latex)
    if not norm:
        return ""
    return f"$${norm}$$" if display else f"${norm}$"


def label_spoken_formula(spoken: str) -> str:
    """Prefix the spoken text of a formula with the core's "Fórmula:" label.

    The spoken text comes from ``math.verbalize``; the label is how the core
    presents it in alt text and plain-text exports.
    """
    spoken = spoken.strip()
    return f"Fórmula: {spoken}" if spoken else ""
