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

import warnings
from typing import Any

import docstruct.text.latex as _docstruct_latex

_DEPRECATED_NAMES = ("ensure_math_delimiters", "normalize_latex")
_DEPRECATED: dict[str, Any] = {
    "ensure_math_delimiters": _docstruct_latex.ensure_math_delimiters,
    "normalize_latex": _docstruct_latex.bare_latex,
}
_REPLACEMENTS = {
    "ensure_math_delimiters": "ensure_math_delimiters",
    "normalize_latex": "bare_latex",
}

__all__ = [
    *_DEPRECATED_NAMES,
    "label_spoken_formula",
    "wrap_latex",
]


def __dir__() -> list[str]:
    return sorted({"label_spoken_formula", "wrap_latex", *_DEPRECATED_NAMES})


def __getattr__(name: str) -> Any:
    if name in _DEPRECATED:
        warnings.warn(
            f"acessilia_core.formula_tools.{name} is deprecated; "
            f"import {_REPLACEMENTS[name]} from docstruct.text.latex",
            DeprecationWarning,
            stacklevel=2,
        )
        return _DEPRECATED[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


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
