"""LaTeX normalization and the presentation of spoken formulas.

Recognition, MathML conversion and speech run on the Toolbox
(``math.recognize``, ``math.convert``, ``math.verbalize``; see
backend/tools/toolbox_math_tools.py and ADR-0007). This module only reshapes
LaTeX strings and labels spoken text.
"""

from __future__ import annotations


def ensure_math_delimiters(latex: str) -> str:
    """Garante $...$ para que o parser estrutural reconheça o bloco como math."""
    text = latex.strip()
    if not text:
        return text
    if (text.startswith("$") and text.endswith("$")) or (
        text.startswith("\\[") and text.endswith("\\]")
    ):
        return text
    return f"${text}$"


def normalize_latex(latex: str) -> str:
    """Strip outer math delimiters and collapse whitespace without rewriting math."""
    text = latex.strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        text = text[2:-2]
    elif text.startswith("$") and text.endswith("$") and len(text) > 2:
        text = text[1:-1]
    elif text.startswith("\\[") and text.endswith("\\]"):
        text = text[2:-2]
    elif text.startswith("\\(") and text.endswith("\\)"):
        text = text[2:-2]
    if not text.strip("$ "):
        return ""
    return " ".join(text.split())


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
