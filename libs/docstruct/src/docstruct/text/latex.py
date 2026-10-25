"""Canonical LaTeX normalization and formatting routines.

Pure: zero external dependencies, standard library only.
Provides formula delimiter stripping, math symbol normalization,
OCR wrapper pruning, and standardized spacing.

Two normalizations coexist on purpose: ``bare_latex`` is conservative (it
strips one pair of outer delimiters and collapses whitespace, leaving the
expression untouched); ``normalize_latex`` rewrites symbols and spacing.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter

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


def bare_latex(latex: str) -> str:
    """Strip one pair of outer math delimiters and collapse whitespace.

    Leaves the expression itself untouched, unlike ``normalize_latex``, which
    rewrites symbols. Returns ``""`` when nothing but delimiters is left.
    """
    text = latex.strip()
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        text = text[2:-2]
    elif text.startswith("$") and text.endswith("$") and len(text) > 2:
        text = text[1:-1]
    elif (text.startswith("\\[") and text.endswith("\\]")) or (
        text.startswith("\\(") and text.endswith("\\)")
    ):
        text = text[2:-2]
    if not text.strip("$ "):
        return ""
    return " ".join(text.split())


def ensure_math_delimiters(latex: str) -> str:
    """Wrap ``latex`` in ``$...$`` unless it is already ``$``- or ``\\[``-delimited.

    Structural parsers recognize a block as math by its delimiters. Blank
    input stays blank.
    """
    text = latex.strip()
    if not text:
        return text
    if (text.startswith("$") and text.endswith("$")) or (
        text.startswith("\\[") and text.endswith("\\]")
    ):
        return text
    return f"${text}$"


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

    # 1. Normalize Unicode minus and Unicode whitespace.
    # Zero-width space is invisible, so it is removed rather than widened to a
    # space; the other Unicode spaces are equivalent to a plain space.
    out = out.replace("\u2212", "-")
    out = out.replace("\u200b", "")
    out = re.sub(r"[\u00a0\u2000-\u200a\u202f]", " ", out)

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
    # =, \le, \ge, \ne, \approx, \sim
    relational_macros = r"(?:\\(?:le|ge|ne|approx|sim|equiv|subset|subseteq|supset|supseteq)\b|=)"
    out = re.sub(rf"\s*({relational_macros})\s*", r" \1 ", out)

    # Standardize spacing around relational < and >, protecting angle delimiters
    # such as \left<, \right>, \<, \>
    def _relational_angle_replace(m: re.Match[str]) -> str:
        delim_or_macro = m.group(1)
        if delim_or_macro:
            if "left" in delim_or_macro:
                return r"\left<"
            if "right" in delim_or_macro:
                return r"\right>"
            return delim_or_macro
        op = m.group(2).strip()
        return f" {op} "

    out = re.sub(
        r"(\\left\s*<|\\right\s*>|\\<|\\>)|(\s*(?:<|>)\s*)",
        _relational_angle_replace,
        out,
    )

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


# ── Text-layer formulas ─────────────────────────────────────────────

#: Markup that only LaTeX has: a command, or a sub/superscript applied to a
#: group (``x^{2}``, ``v_{0}``). Text extracted from a PDF's text layer has none
#: of it, even when the page shows a fraction or an exponent. A bare ``^`` or
#: ``_`` is not enough: text layers and code-style text carry them too
#: (``2^8``, ``v_0``, ``CO_2``). Braces alone are not markup either: set
#: notation puts them in the text layer (``{h ∈ R : h ≥ −2}``).
_LATEX_MARKUP_RE = re.compile(r"\\[A-Za-z]+|[\^_]\s*\{")

#: Named functions whose glyph is their name. LaTeX spells them ``\sin``; a
#: recognizer may keep the printed name as ``\operatorname{s e n}``.
_FUNCTION_NAMES = (
    "lim", "sin", "cos", "tan", "cot", "sec", "csc", "arcsin", "arccos", "arctan",
    "sinh", "cosh", "tanh", "log", "ln", "exp", "max", "min", "sup", "inf", "det",
)

#: LaTeX commands whose rendering is visible text, as the text layer shows it.
#: This is the single source of the symbols the agreement compares: a symbol
#: missing here is invisible on both sides, so a recognition that swaps or
#: drops it would go unnoticed.
_COMMAND_GLYPHS: dict[str, str] = {
    **{command: char for char, command in _UNICODE_MATH_MAP.items()},
    # Relations
    r"\neq": "≠", r"\leq": "≤", r"\geq": "≥", r"\equiv": "≡", r"\sim": "∼",
    r"\simeq": "≃", r"\cong": "≅", r"\propto": "∝", r"\parallel": "∥", r"\perp": "⊥",
    # Sets
    r"\in": "∈", r"\notin": "∉", r"\ni": "∋", r"\cup": "∪", r"\cap": "∩",
    r"\subset": "⊂", r"\subseteq": "⊆", r"\supset": "⊃", r"\supseteq": "⊇",
    r"\setminus": "∖", r"\emptyset": "∅", r"\varnothing": "∅",
    # Logic
    r"\wedge": "∧", r"\land": "∧", r"\vee": "∨", r"\lor": "∨", r"\neg": "¬",
    r"\lnot": "¬", r"\forall": "∀", r"\exists": "∃",
    # Arrows
    r"\to": "→", r"\rightarrow": "→", r"\leftarrow": "←", r"\gets": "←",
    r"\leftrightarrow": "↔", r"\Rightarrow": "⇒", r"\implies": "⇒",
    r"\Leftarrow": "⇐", r"\Leftrightarrow": "⇔", r"\iff": "⇔", r"\mapsto": "↦",
    # Operators and others
    r"\circ": "∘", r"\nabla": "∇", r"\angle": "∠", r"\ldots": "…", r"\cdots": "⋯",
    r"\varepsilon": "ε", r"\varphi": "φ",
    **{f"\\{name}": name for name in _FUNCTION_NAMES},
}
_COMMAND_RE = re.compile(r"\\[A-Za-z]+")
_OPERATORNAME_RE = re.compile(r"\\operatorname\*?\s*\{([^{}]*)\}")

#: Symbols that a reader hears, besides letters and digits; spacing,
#: grouping and punctuation are left out because the two sides lay them out
#: differently. Derived from the glyph table so the two cannot drift apart.
_VISIBLE_SYMBOLS = frozenset("=+-<>") | frozenset(
    glyph for glyph in _COMMAND_GLYPHS.values() if len(glyph) == 1 and not glyph.isalnum()
)

#: Portuguese names of functions, as pt-BR material prints them, mapped to
#: the names LaTeX uses; applied to both sides, so ``sen x`` and ``\sin x``
#: (or ``\operatorname{sen} x``) read the same.
_FUNCTION_ALIASES = {
    "sen": "sin", "tg": "tan", "cotg": "cot", "cossec": "csc", "arcsen": "arcsin",
    "arctg": "arctan", "senh": "sinh", "tgh": "tanh", "máx": "max", "mín": "min",
}
_FUNCTION_ALIAS_RE = re.compile(
    r"(?<![^\W\d_])(" + "|".join(sorted(_FUNCTION_ALIASES, key=len, reverse=True)) + r")(?![^\W\d_])"
)


def has_latex_markup(text: str | None) -> bool:
    """Whether ``text`` is LaTeX, not just math characters.

    It is when it carries math delimiters (``$x=1$``: whoever wrote them wrote
    LaTeX), a command (``\\frac``) or a script applied to a group (``x^{2}``).
    A formula an extractor took from the PDF text layer (``s(t) = s0 + v0t + 1
    2 at2``) has none of them. Undelimited expressions with only bare scripts
    (``2^8``, ``v_0``) or no structure at all (``x = 1``) read as text too:
    recognizing them again costs a call, and the caller's agreement check keeps
    the extractor's version when the recognition reads something else.
    """
    text = " ".join((text or "").split())
    bare = bare_latex(text)
    return bool(bare) and (bare != text or bool(_LATEX_MARKUP_RE.search(bare)))


def _visible_symbols(text: str, *, latex: bool) -> list[str]:
    if latex:
        # \operatorname{s e n} prints its argument as a name; drop the spaces
        # so the name can be aliased like a command.
        text = _OPERATORNAME_RE.sub(lambda m: " " + "".join(m.group(1).split()) + " ", text)
        text = _COMMAND_RE.sub(lambda m: f" {_COMMAND_GLYPHS.get(m.group(0), '')} ", text)
    # NFKC folds what text layers deliver as compatibility characters: x² and
    # v₀ read as x2 and v0 (as x^2 and v_0 do once structure is ignored), and
    # the ﬁ ligature as fi. It also composes a detached long solidus with "="
    # into "≠".
    text = unicodedata.normalize("NFKC", text).replace("\u2212", "-")
    text = _FUNCTION_ALIAS_RE.sub(lambda m: _FUNCTION_ALIASES[m.group(1)], text)
    return [ch for ch in text if ch.isalnum() or ch in _VISIBLE_SYMBOLS]


def latex_text_agreement(latex: str, text: str) -> float | None:
    """F1 (0-1) between the visible symbols of ``latex`` and of ``text``.

    Compares what a reader of each would see: letters, digits and math
    symbols, with LaTeX commands rendered as their glyphs (``\\alpha`` → α,
    ``\\lim`` → lim) and structure (``\\frac``, ``^``, braces) ignored, because
    the text layer has no structure to compare. A recognition that reads the
    same formula as the text layer scores near 1 even when it restores
    fractions and exponents; one that invents or drops terms scores lower.
    A change of a single symbol barely moves it, so it does not guard against
    a recognizer "correcting" one digit of the printed formula. ``None`` when
    neither side has a visible symbol: there is no evidence either way.

    The text layer is the reference, not the truth: a garbled or truncated
    text layer lowers the score of a correct reading and can make a caller
    keep the text-layer error. Callers should record what they rejected.
    """
    left = Counter(_visible_symbols(bare_latex(latex), latex=True))
    right = Counter(_visible_symbols(text, latex=False))
    total = sum(left.values()) + sum(right.values())
    if not total:
        return None
    return 2 * sum((left & right).values()) / total
