"""Normalização de LaTeX para comparação e renderização.

Porta do fallback local de ``backend/tools/formula_tools.normalize_latex``.

Remove delimitadores externos (``$$``, ``$``, ``\\[``, ``\\(``), converte
símbolos matemáticos Unicode para equivalentes ASCII, normaliza comandos de
espaçamento e o espaçamento de operadores, e colapsa espaços.

Função pura, sem I/O e sem dependências pesadas.
"""
from __future__ import annotations

import re

# Símbolos Unicode → equivalente ASCII/LaTeX.
_UNICODE_MAP = {
    "\u2212": "-",  # minus sign
    "\u00a0": " ",  # non-breaking space
    "\u2009": " ",  # thin space
    "\u202f": " ",  # narrow no-break space
    "\u200b": "",  # zero-width space
    "\u00d7": "\\times ",
    "\u00f7": "\\div ",
}

_SPACING_CMD_RE = re.compile(r"\\(?:quad|qquad|enspace|thinspace)\b")
_SHORT_SPACE_RE = re.compile(r"\\[,;! ]")
_OPEN_BRACE_RE = re.compile(r"\{\s+")
_CLOSE_BRACE_RE = re.compile(r"\s+\}")
_OPERATOR_RE = re.compile(r"\s*([=+<>-])\s*")
_NEG_EXP_RE = re.compile(r"\^\s*-\s*")
_NEG_PAREN_RE = re.compile(r"\(\s*-\s*")


def normalize_latex(latex: str) -> str:
    """Normaliza ``latex``: sem delimitadores externos nem espaço sintático."""
    text = (latex or "").strip()
    if not text:
        return ""

    # Remove delimitadores externos: $$, $, \[, \], \(, \)
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        text = text[2:-2]
    elif text.startswith("$") and text.endswith("$") and len(text) > 2:
        text = text[1:-1]
    elif text.startswith("\\[") and text.endswith("\\]") and len(text) >= 4:
        text = text[2:-2]
    elif text.startswith("\\(") and text.endswith("\\)") and len(text) >= 4:
        text = text[2:-2]

    for k, v in _UNICODE_MAP.items():
        text = text.replace(k, v)

    text = _SPACING_CMD_RE.sub(" ", text)
    text = _SHORT_SPACE_RE.sub(" ", text)

    text = _OPEN_BRACE_RE.sub("{", text)
    text = _CLOSE_BRACE_RE.sub("}", text)

    text = _OPERATOR_RE.sub(r" \1 ", text)
    # Restaura expoentes negativos e sinais como ^- ou (-
    text = _NEG_EXP_RE.sub("^-", text)
    text = _NEG_PAREN_RE.sub("(-", text)

    return " ".join(text.split()).strip("$ ")


def wrap_latex(latex: str, display: bool = False) -> str:
    """Envolve ``latex`` normalizado em delimitadores display (``$$``) ou inline (``$``)."""
    norm = normalize_latex(latex)
    if not norm:
        return ""
    return f"$${norm}$$" if display else f"${norm}$"
