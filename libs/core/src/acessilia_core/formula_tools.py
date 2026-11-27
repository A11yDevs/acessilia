"""LaTeX normalization and the presentation of spoken formulas.

Core migrated to docstruct.text.latex: ``normalize_latex`` is docstruct's
conservative ``bare_latex`` (strip one pair of outer delimiters, collapse
whitespace, never rewrite the math) and ``ensure_math_delimiters`` remains only
as a deprecated compatibility re-export; import ``bare_latex`` and
``ensure_math_delimiters`` from ``docstruct.text.latex``. This adapter keeps the
core's ``wrap_latex`` default (``display=False``, unlike docstruct's) and the
"Fórmula:" label, which is presentation.

Recognition, MathML conversion and speech run on the Toolbox
(``math.recognize``, ``math.convert``, ``math.verbalize``; see
libs/core/src/acessilia_core/toolbox/toolbox_math_tools.py and ADR-0007).
"""

from __future__ import annotations

from typing import Any

import docstruct.text.latex as _docstruct_latex
from acessilia_core.pipeline._deprecations import _deprecated_attribute

_DEPRECATED_NAMES = ("ensure_math_delimiters", "normalize_latex")
_DEPRECATED: dict[str, Any] = {
    "ensure_math_delimiters": _docstruct_latex.ensure_math_delimiters,
    "normalize_latex": _docstruct_latex.bare_latex,
}
_REPLACEMENTS = {
    "ensure_math_delimiters": "ensure_math_delimiters from docstruct.text.latex",
    "normalize_latex": "bare_latex from docstruct.text.latex",
}

__all__ = [
    *_DEPRECATED_NAMES,
    "label_spoken_formula",
    "wrap_latex",
]


def __dir__() -> list[str]:
    return sorted({"label_spoken_formula", "wrap_latex", *_DEPRECATED_NAMES})


def __getattr__(name: str) -> Any:
    return _deprecated_attribute(__name__, name, _REPLACEMENTS, _DEPRECATED)


def wrap_latex(latex: str, display: bool = False) -> str:
    """Wrap normalized LaTeX in display ($$) or inline ($) delimiters."""
    norm = _docstruct_latex.bare_latex(latex)
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
