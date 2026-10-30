"""Conservative separation and rendering of display-equation identifiers."""
from __future__ import annotations

import re
from typing import Any

from docstruct.text.latex import bare_latex

_NUMBER = r"(?:[A-Za-z]\.)?[0-9]+(?:\.[0-9]+)*[A-Za-z]?"
_TAG = re.compile(rf"(?<!\\)\\tag\s*\{{\s*({_NUMBER})\s*\}}\s*$")
#: ``\quad(1)``, and ``\qquad\text{(1)}``, the label the DOCX export writes.
_SPACED = re.compile(
    rf"(?<!\\)\\(?:qquad|quad)\s*"
    rf"(?:\(\s*({_NUMBER})\s*\)|\\text\s*\{{\s*\(\s*({_NUMBER})\s*\)\s*\}})\s*$"
)
_PLAIN = re.compile(rf"(?P<separator>\s+|(?<=[.;]))\(\s*({_NUMBER})\s*\)\s*$")
_VALID_NUMBER = re.compile(rf"{_NUMBER}\Z")
#: Relations that make the left side a complete equation, so a bare ``(n)``
#: after it is a label. Each also ends an expression that is still open.
_RELATION = (
    r"=|<|>|\\(?:equiv|approx|leq?|geq?|neq?|lt|gt|ll|gg|sim|simeq|cong|propto"
    r"|to|rightarrow|Rightarrow|leftrightarrow|iff|in|subset|subseteq)(?![A-Za-z])"
)
_TRAILING_OPERATOR = re.compile(
    rf"(?:[=+*/<>:,\-]|{_RELATION}"
    r"|\\(?:times|cdot|div|pm|mp|sin|cos|tan|log|ln|exp|sqrt|sum|prod|int|lim)(?![A-Za-z]))\s*$"
)


def split_equation_number(latex: str) -> tuple[str, str | None]:
    """Separate a trailing tag, spaced label or unambiguous parenthesized number.

    Bare parentheses need separation and a complete equation to their left.
    An unlabelled or ambiguous expression is returned unchanged. This does
    not infer missing labels, renumber equations or parse arbitrary TeX.
    """
    text = bare_latex(latex)
    for pattern in (_TAG, _SPACED, _PLAIN):
        match = pattern.search(text)
        if match is None:
            continue
        expression = text[:match.start()].rstrip()
        if not expression or _TRAILING_OPERATOR.search(expression):
            return latex, None
        if r"\tag" in expression:
            return latex, None
        if pattern is _PLAIN and not re.search(_RELATION, expression):
            return latex, None
        return expression, next(group for group in match.groups()[::-1] if group)
    return latex, None


def preserve_equation_number(text: str, metadata: dict[str, Any]) -> str:
    """Keep an existing source label rather than overwrite it with OCR output."""
    expression, number = split_equation_number(text)
    if number is not None and equation_number(metadata) is None:
        metadata["equation_number"] = number
    return expression


def equation_number(metadata: dict[str, Any]) -> str | None:
    """Read a safe printable identifier; metadata cannot inject TeX or HTML."""
    raw = metadata.get("equation_number")
    value = str(raw) if raw is not None else ""
    return value if _VALID_NUMBER.fullmatch(value) else None


def numbered_latex(text: str, metadata: dict[str, Any], *, use_tag: bool = True) -> str:
    """Restore a tag, or a portable text label for Pandoc's DOCX writer."""
    number = equation_number(metadata)
    expression, detected = split_equation_number(text)
    if number is None:
        number = detected
    if not number:
        return text
    suffix = f"\\tag{{{number}}}" if use_tag else f"\\qquad\\text{{({number})}}"
    return bare_latex(expression) + suffix


def numbered_speech(speech: str, metadata: dict[str, Any]) -> str:
    """Prefix a language-neutral equation identifier exactly once."""
    number = equation_number(metadata)
    prefix = f"({number}) " if number else ""
    return prefix + speech if prefix and not speech.startswith(prefix) else speech
