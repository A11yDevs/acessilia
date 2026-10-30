"""Implicit products that speech would read as function application.

``h(12 + 6h + h^2)`` and ``s(t)`` have the same shape: a letter, then a
parenthesis. MathJax writes both as ``<mi>`` followed by ``<mo>(</mo>``, with no
invisible operator between them, and MathCAT reads both as a function ("h of,
open parenthesis…"). Only the document says which is which: here ``h``
is a variable (``vm_2(h)``, ``h \\neq 0``, ``h \\to 0``) and ``s`` a function
(``s(t)``, ``s(2)``).

``implicit_product_variables`` collects, over every formula of a document, the
single letters used as variables and never applied to a lone argument.
``mark_implicit_products`` puts U+2062 INVISIBLE TIMES between such a letter
and the parenthesis after it. MathJax turns it into an invisible
``<mo>\\u2062</mo>``, so the rendering does not change, and MathCAT says "h times".
The mark only goes into the LaTeX sent for MathML and speech, never into the
document's text: LaTeX written for the PDF stays as the source had it.

The rule is conservative. A letter with no variable use, or one also applied
to a lone argument (``h(t)``, ``h(2)``), keeps the current reading.
"""
from __future__ import annotations

import re
from collections.abc import Iterable

INVISIBLE_TIMES = "\u2062"

# A single letter that is a token of its own: not part of a command name
# (\frac, \lim), not glued to a letter on either side as in a word.
_LETTER = r"(?<![A-Za-z\\])([A-Za-z])(?![A-Za-z])"
_OPEN = r"(?:\\left)?\("
# Deliberately limited to common variable evidence; relations such as
# \equiv, \propto and \subseteq alone do not establish a variable.
_RELATION = (
    r"(?:=|<|>|\\neq?|\\geq?|\\leq?|\\geqslant|\\leqslant|\\to|\\rightarrow"
    r"|\\in|\\notin|\\approx|\\sim)(?![A-Za-z])"
)
# The letter applied to something: "h(" or "h\left(".
_APPLIED = re.compile(_LETTER + r"\s*(?=" + _OPEN + r")")
# Applied to a lone argument, a letter or a number: "s(t)", "s(2)", "s(-1)".
_APPLIED_TO_LONE = re.compile(
    _LETTER + r"\s*" + _OPEN + r"\s*-?\s*(?:[A-Za-z]|[0-9]+(?:[.,][0-9]+)?)\s*(?:\\right)?\)"
)
# Used as a variable: the lone argument of an application ("vm_2(h)"), or a
# side of a relation ("h \neq 0", "t = 2", "x \in A").
_LONE_ARGUMENT = re.compile(r"\(\s*" + _LETTER + r"\s*\)")
_BEFORE_RELATION = re.compile(_LETTER + r"\s*" + _RELATION)
_AFTER_RELATION = re.compile(_RELATION + r"\s*" + _LETTER + r"\s*(?:$|[,.;)}]|\\quad|\\qquad|&|\\\\)")

_TEXT_COMMAND = re.compile(r"\\(?:text|mbox|mathrm|operatorname)\*?\s*\{")


def _mask_text_commands(latex: str) -> str:
    """Hide text groups, preserving indexes and nested/escaped braces."""
    masked = list(latex)
    position = 0
    while match := _TEXT_COMMAND.search(latex, position):
        depth = 1
        end = match.end()
        while end < len(latex) and depth:
            if latex[end] == "\\":
                end += 2  # An escaped brace does not open or close a group.
                continue
            if latex[end] == "{":
                depth += 1
            elif latex[end] == "}":
                depth -= 1
            end += 1
        end = min(end, len(latex))
        # A non-whitespace sentinel prevents matches spanning a hidden group.
        masked[match.start():end] = "~" * (end - match.start())
        position = end
    return "".join(masked)


def implicit_product_variables(sources: Iterable[str]) -> frozenset[str]:
    """The letters of these formulas that are variables, never functions.

    ``sources`` is the LaTeX of every formula of one document, display and
    inline: a letter's role is read from the whole document, since one formula
    rarely shows both.
    """
    variables: set[str] = set()
    functions: set[str] = set()
    for latex in sources:
        latex = _mask_text_commands(latex)
        for match in _APPLIED_TO_LONE.finditer(latex):
            functions.add(match.group(1))
        for pattern in (_LONE_ARGUMENT, _BEFORE_RELATION, _AFTER_RELATION):
            for match in pattern.finditer(latex):
                variables.add(match.group(1))
    return frozenset(variables - functions)


def mark_implicit_products(latex: str, variables: frozenset[str]) -> str:
    """``latex`` with U+2062 between each of ``variables`` and a parenthesis after it."""
    if not variables:
        return latex
    positions = [
        match.end()
        for match in _APPLIED.finditer(_mask_text_commands(latex))
        if match.group(1) in variables
    ]
    for position in reversed(positions):
        latex = latex[:position] + INVISIBLE_TIMES + latex[position:]
    return latex


__all__ = [
    "INVISIBLE_TIMES",
    "implicit_product_variables",
    "mark_implicit_products",
]
