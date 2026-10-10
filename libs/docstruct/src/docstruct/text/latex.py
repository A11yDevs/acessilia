"""Canonical LaTeX normalization and formatting routines.

Pure: zero external dependencies, standard library only.
Provides formula delimiter stripping, math symbol normalization,
OCR wrapper pruning, and standardized spacing.
"""
from __future__ import annotations

import re

# Enclosing delimiter patterns for stripping
_DISPLAY_DELIM_RE = re.compile(r"^\s*\$\$(.*)\$\$\s*$", re.DOTALL)
_INLINE_DELIM_RE = re.compile(r"^\s*\$(.*)\$\s*$", re.DOTALL)
_BRACKET_DISPLAY_RE = re.compile(r"^\s*\\\[(.*)\\\]\s*$", re.DOTALL)
_PAREN_INLINE_RE = re.compile(r"^\s*\\\((.*)\\\)\s*$", re.DOTALL)
_EQUATION_ENV_RE = re.compile(r"^\s*\\begin\{equation\*?\}(.*)\\end\{equation\*?\}\s*$", re.DOTALL)

# Unicode math characters to standard LaTeX commands
_UNICODE_MATH_MAP: dict[str, str] = {
    # Relational & Arithmetic operators
    "×": r"\times",
    "÷": r"\div",
    "≤": r"\le",
    "≥": r"\ge",
    "≠": r"\ne",
    "≈": r"\approx",
    "±": r"\pm",
    "∓": r"\mp",
    "·": r"\cdot",
    "∞": r"\infty",
    "∑": r"\sum",
    "∏": r"\prod",
    "∫": r"\int",
    "∂": r"\partial",
    "√": r"\sqrt",
    # Greek lowercase
    "α": r"\alpha",
    "β": r"\beta",
    "γ": r"\gamma",
    "δ": r"\delta",
    "ε": r"\epsilon",
    "ζ": r"\zeta",
    "η": r"\eta",
    "θ": r"\theta",
    "ι": r"\iota",
    "κ": r"\kappa",
    "λ": r"\lambda",
    "μ": r"\mu",
    "ν": r"\nu",
    "ξ": r"\xi",
    "π": r"\pi",
    "ρ": r"\rho",
    "σ": r"\sigma",
    "τ": r"\tau",
    "υ": r"\upsilon",
    "φ": r"\phi",
    "χ": r"\chi",
    "ψ": r"\psi",
    "ω": r"\omega",
    # Greek uppercase
    "Γ": r"\Gamma",
    "Δ": r"\Delta",
    "Θ": r"\Theta",
    "Λ": r"\Lambda",
    "Ξ": r"\Xi",
    "Π": r"\Pi",
    "Σ": r"\Sigma",
    "Υ": r"\Upsilon",
    "Φ": r"\Phi",
    "Ψ": r"\Psi",
    "Ω": r"\Omega",
}


def strip_latex_delimiters(text: str) -> str:
    """Strip outer LaTeX math delimiters ($$, $, \\[ \\], \\( \\), equation environments)."""
    if not text:
        return ""
    stripped = text.strip()

    # Try display equation environment
    match = _EQUATION_ENV_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()

    # Try bracket display delimiters: \[ ... \]
    match = _BRACKET_DISPLAY_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()

    # Try double-dollar display delimiters: $$ ... $$
    match = _DISPLAY_DELIM_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()

    # Try paren inline delimiters: \( ... \)
    match = _PAREN_INLINE_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()

    # Try single-dollar inline delimiters: $ ... $
    match = _INLINE_DELIM_RE.match(stripped)
    if match:
        stripped = match.group(1).strip()

    return stripped


def normalize_latex(expr: str | None) -> str:
    """Normalize and standardize a LaTeX mathematical expression.

    - Strips external math delimiters.
    - Converts Unicode math symbols and Greek letters to canonical LaTeX macros.
    - Normalizes Unicode minus (\\u2212) to standard ASCII minus (-).
    - Removes trivial OCR text wrappers like \\text{x} -> x on single variables.
    - Standardizes superscripts and subscripts (e.g. x ^ { 2 } -> x^{2}).
    - Standardizes spacing around relational and binary operators.
    """
    if expr is None:
        return ""

    out = strip_latex_delimiters(expr)
    if not out:
        return ""

    # 1. Normalize Unicode minus and Unicode whitespace
    out = out.replace("\u2212", "-")
    out = re.sub(r"[\u00a0\u2000-\u200b\u202f]", " ", out)

    # 2. Convert Unicode math symbols and Greek characters
    for char, macro in _UNICODE_MATH_MAP.items():
        if char in out:
            out = out.replace(char, f" {macro} ")

    # 3. Strip trivial OCR wrappers like \text{x} -> x on single characters or simple numbers
    out = re.sub(r"\\(?:text|mathrm|mathnormal)\{\s*([A-Za-z0-9])\s*\}", r"\1", out)

    # 4. Normalize subscripts and superscripts
    # x ^ { 2 } -> x^{2}
    out = re.sub(r"\s*\^\s*\{\s*([^{}]+?)\s*\}", r"^{\1}", out)
    # x _ { i } -> x_{i}
    out = re.sub(r"\s*_\s*\{\s*([^{}]+?)\s*\}", r"_{\1}", out)
    # x ^ 2 -> x^2
    out = re.sub(r"\s*\^\s*([A-Za-z0-9])\b", r"^\1", out)
    # x _ 1 -> x_1
    out = re.sub(r"\s*_\s*([A-Za-z0-9])\b", r"_\1", out)

    # 5. Normalize spacing macros
    out = re.sub(r"\\[,;:!]", " ", out)
    out = re.sub(r"\\(?:quad|qquad)", " ", out)

    # 6. Standardize spacing around relational operators
    # =, <, >, \le, \ge, \ne, \approx, \sim
    relational_pattern = r"(?:\\(?:le|ge|ne|approx|sim|equiv|subset|subseteq|supset|supseteq)\b|=|<|>)"
    out = re.sub(rf"\s*({relational_pattern})\s*", r" \1 ", out)

    # 7. Standardize binary operators (+, - when used as binary)
    # Binary plus
    out = re.sub(r"([A-Za-z0-9\)\}])\s*\+\s*", r"\1 + ", out)
    # Binary minus (preceded by a variable, digit, or closing bracket)
    out = re.sub(r"([A-Za-z0-9\)\}])\s*-\s*", r"\1 - ", out)

    # 8. Collapse whitespace and strip
    out = re.sub(r"\s+", " ", out).strip()

    # Avoid dangling trailing/leading spaces inside braces
    out = re.sub(r"\{\s+", "{", out)
    out = re.sub(r"\s+\}", "}", out)

    return out


def wrap_latex(expr: str | None, *, display: bool = True) -> str:
    """Wrap a LaTeX expression in appropriate delimiters ($$ or $).

    Does not double-wrap if expression already has the matching delimiters.
    """
    if expr is None:
        return ""
    trimmed = expr.strip()
    if not trimmed:
        return ""

    if display:
        if trimmed.startswith("$$") and trimmed.endswith("$$") and len(trimmed) >= 4:
            return trimmed
        inner = strip_latex_delimiters(trimmed)
        return f"$${inner}$$"

    if trimmed.startswith("$") and trimmed.endswith("$") and not trimmed.startswith("$$") and len(trimmed) >= 2:
        return trimmed
    inner = strip_latex_delimiters(trimmed)
    return f"${inner}$"
