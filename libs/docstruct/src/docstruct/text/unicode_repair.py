"""Conservative Unicode repair for text extracted from legacy PDFs.

PDFs produced by old TeX/dvips toolchains often arrive without a reliable
``/ToUnicode`` map: the extractor returns the base letter followed by a
combining mark (NFD) and, for ``i``, uses ``ı`` (U+0131, dotless i) before the
accent. ``NFC`` composes most cases, but ``ı`` + mark does not compose and
needs its own rule.

The module is pure and conservative by design:

- it only acts on prose, headings and alt text; formulas, code and URLs stay
  untouched;
- it does not reinterpret spacing diacritics (``C´ alculo``) by default, because
  that form also appears in metalinguistic text and code; that repair needs
  font/geometry evidence and must be enabled explicitly;
- it does not handle ligatures, NBSP or hyphenation: those stay in
  :mod:`docstruct.text.norm_fix`, so there is a single implementation.

Every edit carries its rule and the offsets in the original text, so the core
can audit the transformation without storing an opaque copy of the text.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Literal

#: Block types the repair may act on. The others are preserved byte by byte,
#: even when they contain the same sequences.
PROSE_BLOCK_TYPES = frozenset({"prose", "heading", "alt_text"})

#: Languages in which ``ı`` is a letter (not an extraction artifact). The
#: dotless-i rule is never applied there.
DOTLESS_IS_LETTER = frozenset({"tr", "az"})

_MARKS = "\u0300-\u036f"
#: Letter + combining marks. ``[^\W\d_]`` means "Unicode letter", no digits.
_COMBINING_RUN = re.compile(rf"(?P<dotless>[ıȷ][{_MARKS}]+)|(?P<run>[^\W\d_][{_MARKS}]+)")
_DOTLESS_MARKS = re.compile(rf"[ıȷ][{_MARKS}]+")
_SPACING_DIACRITIC = re.compile(r"[´ˆ˜¸][\u00a0 \t]*[A-Za-zıȷ]")

_SPACING_MARKS = {"´": "\u0301", "ˆ": "\u0302", "˜": "\u0303", "¸": "\u0327"}
_SPACING_BASES = {
    "´": set("AEIOUaeiou"),
    "ˆ": set("AEIOUaeiou"),
    "˜": set("AaOoNn"),
    "¸": set("Cc"),
}

#: Spans where character identity matters: inline code, URLs and ``$...$``
#: formulas. No rule changes a protected span.
_PROTECTED_SPANS = (
    re.compile(r"`[^`]*`"),
    re.compile(r"(?:https?://|www\.)\S+"),
    re.compile(r"\$[^$]*\$"),
)


@dataclass(frozen=True)
class Detection:
    """Legacy Unicode signals found, without rewriting the text."""

    combining_runs: int = 0
    combining_marks: int = 0
    dotless: int = 0
    spacing_diacritics: int = 0
    replacement_characters: int = 0

    @property
    def has_signal(self) -> bool:
        return bool(
            self.combining_runs
            or self.dotless
            or self.spacing_diacritics
            or self.replacement_characters
        )

    @property
    def needs_review(self) -> bool:
        """Whether some signal is known to be left unrepaired by this phase."""
        return bool(self.spacing_diacritics or self.replacement_characters)


@dataclass(frozen=True)
class UnicodeRepairContext:
    """Where the text appeared; decides what may (or may not) be rewritten."""

    language: str = "pt-BR"
    block_type: str = "prose"
    page: int | None = None
    provider: str | None = None
    source_font_risk: Literal["low", "medium", "high", "unknown"] = "unknown"
    #: Spacing diacritics are ambiguous; they only enter with explicit evidence.
    allow_spacing_diacritics: bool = False


@dataclass(frozen=True)
class Edit:
    """A traceable change; ``start``/``end`` are offsets in the original text."""

    rule: str
    start: int
    end: int
    before: str
    after: str


@dataclass(frozen=True)
class UnicodeRepairDecision:
    original: str
    repaired: str
    detection: Detection
    edits: tuple[Edit, ...] = ()
    confidence: float | None = None
    needs_review: bool = False
    skipped_reason: str | None = None


def detect_legacy_unicode(text: str) -> Detection:
    """Count the legacy extraction signals without changing ``text``."""
    if not text:
        return Detection()
    return Detection(
        combining_runs=len(_COMBINING_RUN.findall(text)),
        combining_marks=sum(1 for char in text if 0x0300 <= ord(char) <= 0x036F),
        dotless=len(_DOTLESS_MARKS.findall(text)),
        spacing_diacritics=len(_SPACING_DIACRITIC.findall(text)),
        replacement_characters=text.count("\ufffd"),
    )


def repair_legacy_unicode(
    text: str,
    *,
    context: UnicodeRepairContext | None = None,
) -> UnicodeRepairDecision:
    """Repair the recognised TeX sequences and return the trace of the edits."""
    ctx = context or UnicodeRepairContext()
    detection = detect_legacy_unicode(text)
    if not text:
        return UnicodeRepairDecision(
            original=text,
            repaired=text,
            detection=detection,
            skipped_reason="empty-text",
        )
    if ctx.block_type not in PROSE_BLOCK_TYPES:
        return UnicodeRepairDecision(
            original=text,
            repaired=text,
            detection=detection,
            needs_review=detection.needs_review,
            skipped_reason=f"block-type:{ctx.block_type}",
        )

    protected = _protected_spans(text)
    language = ctx.language.split("-", 1)[0].lower()
    edits: list[Edit] = []

    for match in _COMBINING_RUN.finditer(text):
        if _overlaps(match.span(), protected):
            continue
        if match.group("dotless"):
            if language in DOTLESS_IS_LETTER:
                continue
            composed = unicodedata.normalize(
                "NFC", _dotless_base(match.group("dotless")[0]) + match.group("dotless")[1:]
            )
            # If marks remain, the pair does not compose: keeping the letter is
            # safer than replacing it and leaving a loose mark behind.
            if _has_combining(composed):
                continue
            edits.append(
                Edit("dotless-base", match.start(), match.end(), match.group(0), composed)
            )
        else:
            composed = unicodedata.normalize("NFC", match.group(0))
            if composed == match.group(0):
                continue
            edits.append(Edit("nfc", match.start(), match.end(), match.group(0), composed))

    if ctx.allow_spacing_diacritics and ctx.source_font_risk in {"medium", "high"}:
        edits.extend(_spacing_edits(text, protected))

    edits = _non_overlapping(edits)
    repaired = _apply(text, edits)
    needs_review = (
        detection.needs_review
        or _has_combining(repaired)
        or (language in DOTLESS_IS_LETTER and detection.dotless > 0)
    )
    return UnicodeRepairDecision(
        original=text,
        repaired=repaired,
        detection=detection,
        edits=tuple(edits),
        confidence=None,
        needs_review=needs_review,
        skipped_reason=None if edits else "no-applicable-rule",
    )


def _spacing_edits(text: str, protected: list[tuple[int, int]]) -> list[Edit]:
    """Spacing diacritics, only when the font is the available evidence."""
    edits: list[Edit] = []
    for match in _SPACING_DIACRITIC.finditer(text):
        if _overlaps(match.span(), protected):
            continue
        accent, base = match.group(0)[0], match.group(0)[-1]
        if base not in _SPACING_BASES[accent]:
            continue
        composed = unicodedata.normalize(
            "NFC", _dotless_base(base) + _SPACING_MARKS[accent]
        )
        if len(composed) != 1:
            continue
        edits.append(
            Edit("spacing-diacritic", match.start(), match.end(), match.group(0), composed)
        )
    return edits


def _dotless_base(char: str) -> str:
    return {"ı": "i", "ȷ": "j"}.get(char, char)


def _has_combining(text: str) -> bool:
    return any(0x0300 <= ord(char) <= 0x036F for char in text)


def _protected_spans(text: str) -> list[tuple[int, int]]:
    spans = [match.span() for pattern in _PROTECTED_SPANS for match in pattern.finditer(text)]
    return sorted(spans)


def _overlaps(span: tuple[int, int], protected: list[tuple[int, int]]) -> bool:
    start, end = span
    return any(start < other_end and other_start < end for other_start, other_end in protected)


def _non_overlapping(edits: list[Edit]) -> list[Edit]:
    """Keep the first edit of each overlap, in text order.

    ``dotless`` and ``nfc`` come from the same regex and never overlap; a
    spacing edit can share the base letter with a combining run, and the
    earlier (already composed) edit wins.
    """
    accepted: list[Edit] = []
    for edit in sorted(edits, key=lambda item: (item.start, item.end)):
        if accepted and edit.start < accepted[-1].end:
            continue
        accepted.append(edit)
    return accepted


def _apply(text: str, edits: list[Edit]) -> str:
    result: list[str] = []
    cursor = 0
    for edit in edits:
        result.append(text[cursor : edit.start])
        result.append(edit.after)
        cursor = edit.end
    result.append(text[cursor:])
    return "".join(result)
