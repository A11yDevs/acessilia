r"""Named operators that speech would read as a product of letters.

A recognizer may keep the printed name of an operator with spaces between its
letters, as in ``\operatorname{D o m}``. MathJax honours those spaces and
writes one ``<mi>`` per letter, so MathCAT reads the letters and treats the
parenthesis after the last one as an implicit product: case 036 spoke "maiúscula
d o m, multiplicado por" for the domain of a function (#546).

This module gives the few operators whose meaning the document makes
unambiguous a canonical spelling before MathML and speech are produced:
``\operatorname{D o m}``, ``\operatorname{D\,o\,m}`` and
``\operatorname{Dom}`` all become ``\operatorname{Dom}``, a single ``<mi>``
that MathCAT applies as a function ("Dom de"), never a product. Spaces and the
LaTeX spacing commands a recognizer may print between the letters are ignored
for the name lookup. For the pt-BR speech, the same operator is written as
``\mathop{\text{domínio}}``, which MathCAT reads as "domínio de"; the engine
still produces every word, so there is no second verbalizer.

The rule is conservative and only covers names in ``_NAMED_OPERATORS``.
Anything else keeps the LaTeX as the source had it: an unknown name is not
given a meaning it may not have. The document's text is never rewritten; only
the LaTeX sent for MathML and speech goes through here.

Known limits:

- Only ``\operatorname`` is read as a name. A bare ``Dom(...)`` stays untouched:
  without the command there is no evidence that the letters are a name rather
  than a product.
- The list holds ``Dom`` only. Operators MathCAT already names (``\lim``,
  ``\sin``, ``\log``, …) need no entry; a new one is added with a real pt-BR
  name and an example, never guessed from the letters.
- The speech form depends on MathCAT applying an ``<mtext>`` head to its
  argument, as the pinned engine does ("domínio de"); the golden file of
  ``math.verbalize`` is where an upgrade that changes it would show.
"""
from __future__ import annotations

import re
import unicodedata

#: Canonical spelling and pt-BR speech form of each recognized operator.
#: The keys are the casefolded names a recognizer may produce, with or without
#: the spaces that break a printed name into letters.
_NAMED_OPERATORS: dict[str, tuple[str, str]] = {
    "dom": ("Dom", r"\mathop{\text{domínio}}"),
    # A recognizer may print the Portuguese name; it is the same operator.
    "dominio": ("Dom", r"\mathop{\text{domínio}}"),
    "domínio": ("Dom", r"\mathop{\text{domínio}}"),
}

#: ``\operatorname{…}`` and its starred form; the argument is not nested.
_OPERATORNAME = re.compile(r"\\operatorname(\*?)\s*\{([^{}]*)\}")

#: Spaces and LaTeX spacing commands a recognizer may put between the letters
#: of a printed name: ``D o m``, ``D\,o\,m``, ``D\;o\;m``. Same set the math
#: benchmark strips from ``\operatorname{l\,i\,m}``.
_OPERATOR_SPACE = re.compile(r"(?:\\[,;:! ]|\s)+")


def _operator(content: str) -> tuple[str, str] | None:
    r"""Canonical spelling and pt-BR speech form of an ``\operatorname`` argument."""
    name = _OPERATOR_SPACE.sub("", content)
    return _NAMED_OPERATORS.get(unicodedata.normalize("NFC", name).casefold())


def normalize_named_operators(latex: str) -> str:
    r"""``latex`` with recognized named operators in their canonical spelling.

    Only the name is rewritten: ``\operatorname{D o m}(vm_2)`` becomes
    ``\operatorname{Dom}(vm_2)``, so MathJax writes one identifier and
    MathCAT applies the operator instead of multiplying its letters. Unknown
    operators are returned unchanged.
    """
    if "\\operatorname" not in latex:
        return latex

    def replace(match: re.Match[str]) -> str:
        found = _operator(match.group(2))
        if found is None:
            return match.group(0)
        return f"\\operatorname{match.group(1)}{{{found[0]}}}"

    return _OPERATORNAME.sub(replace, latex)


def speak_named_operators(latex: str) -> str:
    r"""``latex`` with recognized named operators written for pt-BR speech.

    ``\operatorname{D o m}(x)`` becomes ``\mathop{\text{domínio}}(x)``:
    MathCAT says "domínio de x", which its Brazilian rules do not offer for
    the bare name "Dom". The rest of the expression is unchanged, so the
    operator keeps its argument and the other symbols their reading.
    """
    if "\\operatorname" not in latex:
        return latex

    def replace(match: re.Match[str]) -> str:
        found = _operator(match.group(2))
        return match.group(0) if found is None else found[1]

    return _OPERATORNAME.sub(replace, latex)


__all__ = [
    "normalize_named_operators",
    "speak_named_operators",
]
