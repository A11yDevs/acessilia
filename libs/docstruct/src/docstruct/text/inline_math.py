r"""Inline math found in a PDF text layer from its fonts and baselines (ADR 0011).

A typeset PDF keeps no trace of the ``$…$`` its author wrote, but its glyphs
do: TeX sets variables in a math italic font (``CMMI``), symbols in ``CMSY``,
``ℝ`` in ``MSBM``, and scripts in a smaller size on a raised or lowered
baseline. Layout models report none of it, so ``s(t) = t³`` reaches the text
as ``s ( t ) = t 3``.

``detect_inline_math`` reads the spans of an element's lines (the Toolbox's
``document.text.spans``) and returns each run of math with LaTeX rebuilt from
the geometry. ``splice_inline_math`` writes the runs into the element's text
as ``$…$``: the text came from the same text layer through another
extractor, so both character sequences are aligned (whitespace and spacing
accents folded away), and a run whose characters do not align exactly is left
out rather than guessed.

A run:

- starts from a glyph in a math font (``MATH_FONT_PREFIXES``) other than
  punctuation;
- grows over neighbouring text-font digits, operators, brackets, a named
  function (``lim``, ``sen``) and the smaller letters of a script;
- stops at a text-font word, and at a ``,`` or ``;`` outside brackets
  (``s(t), v(t)`` is two runs, ``[-2, 0)`` one), unless what precedes has no
  relation and what follows has one (``s_0, a \in \mathbb{R}``) or the ``,``
  is a decimal separator between digits (``x = 3,5``);
- drops the punctuation, spaces and unmatched brackets at its ends.
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

from docstruct.text.latex import _COMMAND_GLYPHS, _FUNCTION_ALIASES, _FUNCTION_NAMES
from docstruct.text.math_spans import split_inline_math

#: Font-name prefixes of math fonts (TeX's Computer Modern and AMS families,
#: the Euler and RSFS script fonts, and OpenType math fonts).
MATH_FONT_PREFIXES = (
    "CMMI", "CMSY", "CMEX", "CMBSY", "MSBM", "MSAM", "EUFM", "EURM", "EUSM",
    "RSFS", "LMMATH", "STIXMATH", "CAMBRIAMATH", "XITSMATH",
)

#: A script is at most this fraction of the run's body size.
SCRIPT_SIZE_RATIO = 0.85
#: A baseline this fraction of the body size away from the body's is a script.
SCRIPT_SHIFT_RATIO = 0.1

_NEGATION = "̸"
_PUNCTUATION = frozenset(",.;:")
_SEPARATORS = frozenset(",;")
_TEXT_MATH = frozenset("0123456789=+-−<>()[]{}|/!'*")
_OPEN = frozenset("([{")
_CLOSE = frozenset(")]}")

#: Glyph → LaTeX, the inverse of the glyph table the agreement uses.
_GLYPH_COMMANDS: dict[str, str] = {}
for _command, _glyph in _COMMAND_GLYPHS.items():
    if len(_glyph) == 1 and not _glyph.isalnum():
        _GLYPH_COMMANDS.setdefault(_glyph, _command)
for _command, _glyph in _COMMAND_GLYPHS.items():
    if len(_glyph) == 1 and _glyph.isalpha() and not _glyph.isascii():
        _GLYPH_COMMANDS.setdefault(_glyph, _command)
_GLYPH_COMMANDS.update({
    "−": "-", "√": r"\surd", "∣": r"\mid", "′": "'", "∗": "*",
    # The long forms, which every scorer and converter knows.
    "≤": r"\leq", "≥": r"\geq", "≠": r"\neq",
})
#: Relations: a comma before one joins a list of variables to it (``s_0, a \in R``).
_RELATIONS = frozenset("=<>≤≥≠∈∉⊂⊆⊃⊇≈≡∼→")
_NEGATED = {"=": r"\neq", "∈": r"\notin", "<": r"\not<", ">": r"\not>", "≤": r"\nleq", "≥": r"\ngeq"}
_ESCAPED = {"{": r"\{", "}": r"\}", "%": r"\%", "#": r"\#", "&": r"\&", "$": r"\$", "_": r"\_"}

_FUNCTIONS = {name: f"\\{name}" for name in _FUNCTION_NAMES} | {
    alias: f"\\{name}" for alias, name in _FUNCTION_ALIASES.items()
}
_WORD_RE = re.compile(r"[^\W\d_]+")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"^\s+(?=[.,;:!?)])")


@dataclass(frozen=True)
class TextSpan:
    """A span of ``document.text.spans@1``: TOPLEFT points, ``origin`` on the baseline."""

    text: str
    font: str
    size: float
    bbox: tuple[float, float, float, float]
    origin: tuple[float, float]

    @classmethod
    def from_dict(cls, span: dict[str, Any]) -> "TextSpan":
        return cls(
            text=str(span["text"]),
            font=str(span["font"]),
            size=float(span["size"]),
            bbox=tuple(float(value) for value in span["bbox"]),  # type: ignore[arg-type]
            origin=tuple(float(value) for value in span["origin"]),  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class InlineMathRun:
    latex: str
    #: The run's folded characters (``fold``), as they must appear in the text.
    flat: str
    #: ``[start, end)`` of the run in ``InlineMathDetection.flat``.
    start: int
    end: int
    bbox: tuple[float, float, float, float]
    #: Boxes of the negation slashes the run composed into its relation.
    negations: tuple[tuple[float, float, float, float], ...] = ()


@dataclass
class InlineMathDetection:
    #: Folded characters of every span read, prose included.
    flat: str = ""
    runs: list[InlineMathRun] = field(default_factory=list)


@dataclass
class SpliceResult:
    text: str
    marked: list[InlineMathRun] = field(default_factory=list)
    unmatched: list[InlineMathRun] = field(default_factory=list)


@dataclass
class _Glyph:
    char: str
    span: TextSpan
    box: tuple[float, float, float, float]
    kind: str = "text"  # math, text-math, function, script, space, punct, prose
    function: str = ""


def is_math_font(font: str) -> bool:
    name = font.split("+", 1)[-1].upper().replace("-", "")
    return name.startswith(MATH_FONT_PREFIXES)


def fold(char: str) -> str:
    """The character as both extractors agree on it: '' for what one may drop."""
    if char.isspace() or char == _NEGATION or unicodedata.combining(char):
        return ""
    if unicodedata.category(char) == "Sk":  # spacing accents of legacy TeX text
        return ""
    return {"−": "-", "≠": "=", "∉": "∈"}.get(char, char)


def detect_inline_math(lines: Iterable[Sequence[TextSpan]]) -> InlineMathDetection:
    """The inline math runs of ``lines`` (in reading order) and their folded text."""
    detection = InlineMathDetection()
    flat: list[str] = []
    for line in lines:
        glyphs = _glyphs(line)
        if not glyphs:
            continue
        body = _body_size(glyphs)
        baseline = _body_baseline(glyphs, body)
        _classify(glyphs, body, baseline)
        offsets = []
        for glyph in glyphs:
            offsets.append(len(flat))
            flat.extend(fold(glyph.char))
        offsets.append(len(flat))
        for first, last in _runs(glyphs):
            run = _build_run(glyphs[first : last + 1], body, baseline)
            if run is None:
                continue
            latex, negations = run
            start, end = offsets[first], offsets[last + 1]
            folded = "".join(flat[start:end])
            if not folded:
                continue
            boxes = [glyph.box for glyph in glyphs[first : last + 1]]
            detection.runs.append(
                InlineMathRun(
                    latex=latex,
                    flat=folded,
                    start=start,
                    end=end,
                    bbox=(
                        min(box[0] for box in boxes),
                        min(box[1] for box in boxes),
                        max(box[2] for box in boxes),
                        max(box[3] for box in boxes),
                    ),
                    negations=tuple(negations),
                )
            )
        # Lines are joined by a space in the text; folding drops it anyway.
    detection.flat = "".join(flat)
    return detection


def splice_inline_math(text: str, detection: InlineMathDetection) -> SpliceResult:
    """``text`` with each detected run written as ``$latex$``.

    A run is written only where its folded characters align exactly with the
    text's and do not touch a math span the text already has.
    """
    result = SpliceResult(text=text)
    if not detection.runs:
        return result
    folded_chars: list[str] = []
    positions: list[int] = []
    for index, char in enumerate(text):
        for piece in fold(char):
            folded_chars.append(piece)
            positions.append(index)
    folded = "".join(folded_chars)
    protected = _protected_ranges(text)
    matcher = difflib.SequenceMatcher(None, detection.flat, folded, autojunk=False)
    mapped: dict[int, int] = {}
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            mapped[block.a + offset] = block.b + offset
    edits: list[tuple[int, int, InlineMathRun]] = []
    for run in detection.runs:
        first, last = mapped.get(run.start), mapped.get(run.end - 1)
        if (
            first is None
            or last is None
            or folded[first : last + 1] != run.flat
        ):
            result.unmatched.append(run)
            continue
        start, end = positions[first], positions[last] + 1
        if any(start < high and low < end for low, high in protected) or any(
            start < high and low < end for low, high, _ in edits
        ):
            result.unmatched.append(run)
            continue
        edits.append((start, end, run))
    for start, end, run in sorted(edits, key=lambda edit: edit[0], reverse=True):
        # The extractor spaces the punctuation that follows math ("60 t ."); the
        # reader would pause on it.
        rest = _SPACE_BEFORE_PUNCTUATION.sub("", text[end:], count=1)
        text = f"{text[:start]}${run.latex}${rest}"
    result.text = text
    result.marked = [run for _, _, run in sorted(edits, key=lambda edit: edit[0])]
    return result


# ── Detection ────────────────────────────────────────────────────────


def _glyphs(line: Sequence[TextSpan]) -> list[_Glyph]:
    """The line's characters in order, each with an estimated box.

    Spans are ordered left to right; within one, the width is split evenly,
    which is enough to tell scripts and runs apart.
    """
    glyphs: list[_Glyph] = []
    for span in sorted(line, key=lambda span: span.bbox[0]):
        chars = list(span.text)
        if not chars:
            continue
        left, top, right, bottom = span.bbox
        step = (right - left) / len(chars)
        for index, char in enumerate(chars):
            x0 = left + step * index
            glyphs.append(_Glyph(char, span, (x0, top, x0 + step, bottom)))
        if glyphs and glyphs[-1].char != " ":
            glyphs.append(_Glyph(" ", span, (right, top, right, bottom)))
    return glyphs


def _body_size(glyphs: list[_Glyph]) -> float:
    sizes: dict[float, int] = {}
    for glyph in glyphs:
        if not glyph.char.isspace():
            sizes[glyph.span.size] = sizes.get(glyph.span.size, 0) + 1
    return max(sizes, key=lambda size: (sizes[size], size)) if sizes else 0.0


def _is_script(span: TextSpan, body: float, baseline: float) -> bool:
    return span.size <= body * SCRIPT_SIZE_RATIO and abs(span.origin[1] - baseline) >= body * SCRIPT_SHIFT_RATIO


def _classify(glyphs: list[_Glyph], body: float, baseline: float) -> None:
    for glyph in glyphs:
        char, span = glyph.char, glyph.span
        if char.isspace():
            glyph.kind = "space"
        elif is_math_font(span.font):
            glyph.kind = "punct" if char in _PUNCTUATION else "math"
        elif char in _PUNCTUATION:
            glyph.kind = "punct"
        elif char in _TEXT_MATH or char in _GLYPH_COMMANDS or char == _NEGATION:
            glyph.kind = "text-math"
        elif _is_script(span, body, baseline):
            glyph.kind = "script"
        else:
            glyph.kind = "prose"
    _mark_functions(glyphs)


def _body_baseline(glyphs: list[_Glyph], body: float) -> float:
    baselines: dict[float, int] = {}
    for glyph in glyphs:
        if glyph.span.size == body and not glyph.char.isspace():
            baselines[glyph.span.origin[1]] = baselines.get(glyph.span.origin[1], 0) + 1
    return max(baselines, key=lambda y: baselines[y]) if baselines else 0.0


def _mark_functions(glyphs: list[_Glyph]) -> None:
    """Text-font words that are named functions (``lim``, ``sen``) become math."""
    text = "".join(glyph.char for glyph in glyphs)
    for match in _WORD_RE.finditer(text):
        name = match.group().lower()
        if name not in _FUNCTIONS:
            continue
        span = glyphs[match.start()].span
        if is_math_font(span.font):
            continue
        for index in range(match.start(), match.end()):
            glyphs[index].kind = "function"
        glyphs[match.start()].function = _FUNCTIONS[name]


def _runs(glyphs: list[_Glyph]) -> list[tuple[int, int]]:
    """``(first, last)`` glyph indexes of each run, ends trimmed."""
    runs: list[tuple[int, int]] = []
    index = 0
    while index < len(glyphs):
        if glyphs[index].kind == "prose":
            index += 1
            continue
        start = index
        depth = 0
        while index < len(glyphs) and glyphs[index].kind != "prose":
            char = glyphs[index].char
            if char in _OPEN:
                depth += 1
            elif char in _CLOSE:
                depth = max(0, depth - 1)
            elif (
                char in _SEPARATORS
                and depth == 0
                and glyphs[index].kind == "punct"
                and not _is_decimal_separator(glyphs, index)
                and not _joins_a_relation(glyphs, start, index)
            ):
                break
            index += 1
        runs.extend(_trimmed(glyphs, start, index - 1))
        index += 1
    return runs


def _is_decimal_separator(glyphs: list[_Glyph], index: int) -> bool:
    """Whether the glyph is a ``,`` between two digits (``3,5``, ``1.000,50``)."""
    return (
        glyphs[index].char == ","
        and 0 < index < len(glyphs) - 1
        and glyphs[index - 1].char.isdigit()
        and glyphs[index + 1].char.isdigit()
    )


def _joins_a_relation(glyphs: list[_Glyph], start: int, separator: int) -> bool:
    """Whether the separator lists variables for a relation that follows it."""
    if any(glyph.char in _RELATIONS for glyph in glyphs[start:separator]):
        return False
    index = separator + 1
    while index < len(glyphs) and glyphs[index].kind != "prose":
        if (
            glyphs[index].char in _SEPARATORS
            and glyphs[index].kind == "punct"
            and not _is_decimal_separator(glyphs, index)
        ):
            return False
        if glyphs[index].char in _RELATIONS:
            return True
        index += 1
    return False


def _trimmed(glyphs: list[_Glyph], first: int, last: int) -> list[tuple[int, int]]:
    while first <= last and glyphs[first].kind in {"space", "punct"}:
        first += 1
    while last >= first and glyphs[last].kind in {"space", "punct"}:
        last -= 1
    # An unmatched bracket at an end belongs to the prose around the run.
    while first <= last:
        chars = [glyph.char for glyph in glyphs[first : last + 1]]
        opened = sum(char in _OPEN for char in chars)
        closed = sum(char in _CLOSE for char in chars)
        if opened > closed and glyphs[first].char in _OPEN:
            first += 1
        elif closed > opened and glyphs[last].char in _CLOSE:
            last -= 1
        else:
            break
        while first <= last and glyphs[first].kind in {"space", "punct"}:
            first += 1
        while last >= first and glyphs[last].kind in {"space", "punct"}:
            last -= 1
    if first > last:
        return []
    if not any(glyph.kind == "math" for glyph in glyphs[first : last + 1]):
        return []
    return [(first, last)]


def _build_run(
    glyphs: list[_Glyph], line_body: float, line_baseline: float
) -> tuple[str, list[tuple[float, float, float, float]]] | None:
    """LaTeX of a run: scripts by size and baseline, glyphs mapped to commands.

    Scripts are measured against the line's body, as ``_classify`` did: a
    large delimiter or operator in the run (``\\left(``, ``\\sum``) is not
    the body its neighbours are scripts of. A run ending on a negation slash
    has no relation to compose it into and is left to the slash reattachment.
    """
    visible = [glyph for glyph in glyphs if not glyph.char.isspace()]
    if not visible:
        return None
    baseline = line_baseline or visible[0].span.origin[1]
    tokens: list[tuple[str, str]] = []  # (level, latex)
    negations: list[tuple[float, float, float, float]] = []
    slash: tuple[float, float, float, float] | None = None
    for glyph in visible:
        if glyph.kind == "function" and not glyph.function:
            continue  # the rest of a function name
        if glyph.char == _NEGATION:
            slash = glyph.box
            continue
        token = glyph.function or _token(glyph)
        if slash is not None:
            token = _NEGATED.get(glyph.char, rf"\not{token}")
            negations.append(slash)
            slash = None
        level = "0"
        if _is_script(glyph.span, line_body, baseline):
            level = "^" if glyph.span.origin[1] < baseline else "_"
        tokens.append((level, token))
    if slash is not None:
        return None
    return _join(tokens), negations


def _token(glyph: _Glyph) -> str:
    char = glyph.char
    font = glyph.span.font.split("+", 1)[-1].upper()
    if font.startswith(("MSBM",)) and char.isalpha():
        return rf"\mathbb{{{char}}}"
    if char in _GLYPH_COMMANDS:
        return _GLYPH_COMMANDS[char]
    return _ESCAPED.get(char, char)


def _join(tokens: list[tuple[str, str]]) -> str:
    out: list[str] = []
    index = 0
    while index < len(tokens):
        level, token = tokens[index]
        if level == "0":
            out.append(token)
            index += 1
            continue
        group = []
        while index < len(tokens) and tokens[index][0] == level:
            group.append(tokens[index][1])
            index += 1
        body = _concat(group)
        out.append(f"{level}{{{body}}}" if len(group) > 1 or len(body) > 1 else f"{level}{body}")
    return _concat(out)


def _concat(tokens: list[str]) -> str:
    """Tokens joined, with a space where a command would swallow a letter."""
    text = ""
    for token in tokens:
        if re.search(r"\\[A-Za-z]+$", text) and token[:1].isalpha():
            text += " "
        text += token
    return text


# ── Splicing ─────────────────────────────────────────────────────────


def _protected_ranges(text: str) -> list[tuple[int, int]]:
    """Ranges of the math spans ``text`` already has, delimiters included."""
    ranges: list[tuple[int, int]] = []
    position = 0
    for piece, is_math in split_inline_math(text):
        located = text.find(piece, position)
        if located < 0:
            continue
        if is_math:
            ranges.append((max(0, located - 2), located + len(piece) + 2))
        position = located + len(piece)
    return ranges


__all__ = [
    "MATH_FONT_PREFIXES",
    "InlineMathDetection",
    "InlineMathRun",
    "SpliceResult",
    "TextSpan",
    "detect_inline_math",
    "fold",
    "is_math_font",
    "splice_inline_math",
]
