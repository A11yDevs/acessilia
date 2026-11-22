"""Visual text ownership, surrounding picture context, and conservative deduplication (#653).

Pure: zero external dependencies, standard library only.

Distinguishes the semantic relationship between extracted text elements and
visual regions on a page (#263, #325, #398):

- ``document_text``: independent textual content (prose, headings, lists,
  tables, formulas, code); preserved as accessible text.
- ``scene_text``: OCR fragments read off a photograph, illustration, or map
  (signage, painted inscriptions, scattered labels on a standalone image or
  geometrically contained inside a picture). Text inside an image belongs to
  the image: it is never emitted as a document-level block. What the image's
  description does not already convey is carried by the image itself (see
  :func:`scene_text_residue`).
- ``figure_label``: short labels folded into a chart or diagram by slide or
  figure structuring; preserved within the figure's description.
- ``caption``: independent figure/table caption or source line; preserved as
  an accessible caption without redundant repetition inside the image
  description.
- ``decorative``: non-informational furniture or confirmed letterhead mark.
- ``uncertain``: text overlapping a visual region whose ownership cannot be
  established with high confidence; preserved as accessible text.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from docstruct.geometry.boxes import box_contains_center
from docstruct.placeholders import ExtractedElement, is_ocr_noise, is_placeholder_text

VisualTextRole = Literal[
    "document_text",
    "scene_text",
    "figure_label",
    "caption",
    "decorative",
    "uncertain",
]

Box = tuple[float, float, float, float]

#: Per-item and total character bounds for surrounding page context sent to the VLM (#653).
MAX_CONTEXT_ITEM_CHARS = 160
MAX_CONTEXT_TOTAL_CHARS = 480
MAX_CONTEXT_ITEMS = 6

#: Share of an owner picture's meaningful scene-text fragments that its
#: description must cover for the description to count as a transcription of
#: the scene; the uncovered remainder is then OCR misreading, not content
#: (#398: 39 of 42 real fragments covered, the rest garbled).
SCENE_TEXT_TRANSCRIBED_SHARE = 0.6

#: Media-inspection natures whose pages are documents, not scenes: their short
#: text lines (form labels, headings) are document text even on a photo.
_DOCUMENT_ARTIFACT_NATURES = frozenset({"scanned_page", "paginated_document"})

_SENTENCE_END_RE = re.compile(r"[.!?;\u2026]$")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_SCENE_CANDIDATE_TYPES = frozenset(
    {"paragraph", "heading", "title", "list_item", "unknown"}
)

_CAPTION_PREFIXES = (
    "figura ",
    "figure ",
    "fig. ",
    "fig ",
    "imagem ",
    "image ",
    "quadro ",
    "tabela ",
    "table ",
    "fonte:",
    "source:",
)

_LOGO_MARKER_RE = re.compile(
    r"\b(?:logo|logotipo|logomarca|brasao|emblema|selo|simbolo|insignia|monograma|"
    r"crest|emblem|seal)\b|coat of arms|marca institucional"
)

_NON_LOGO_MARKER_RE = re.compile(
    r"\b(?:fotografia|foto|retrato|autor|pessoa|homem|mulher|rosto|icone|icon|"
    r"grafico|diagrama|fluxograma|organograma|tabela|mapa|map|equacao|formula|"
    r"photograph|photo|portrait|author|person|chart|diagram|plot|barcode)\b|"
    r"qr code|codigo qr|codigo de barras"
)

_TRANSCRIPTION_BOILERPLATE = frozenset(
    {
        "primeira",
        "segunda",
        "terceira",
        "quarta",
        "linha",
        "linhas",
        "texto",
        "textos",
        "escrito",
        "escrita",
        "escritos",
        "inscrito",
        "inscricao",
        "dizeres",
        "legenda",
        "titulo",
        "subtitulo",
        "abaixo",
        "acima",
        "direita",
        "esquerda",
        "centro",
        "lado",
        "contem",
        "traz",
        "exibe",
        "mostra",
        "apresenta",
        "le",
        "se",
        "com",
        "onde",
        "qual",
        "first",
        "second",
        "third",
        "line",
        "lines",
        "text",
        "reads",
        "says",
        "written",
        "inscribed",
        "caption",
        "title",
        "with",
        "containing",
    }
)

_TRANSCRIPTION_CUE_WORDS = frozenset(
    {
        "linha",
        "linhas",
        "texto",
        "escrito",
        "escrita",
        "inscrito",
        "inscricao",
        "dizeres",
        "legenda",
        "line",
        "lines",
        "text",
        "reads",
        "says",
        "written",
    }
)


@dataclass(frozen=True)
class TextOwnership:
    """Semantic ownership decision for one extracted element."""

    element_id: str
    role: VisualTextRole
    owner_id: str | None = None
    confidence: float = 1.0
    reason: str = ""

    def to_metadata(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "role": self.role,
            "confidence": self.confidence,
            "reason": self.reason,
        }
        if self.owner_id is not None:
            payload["owner_id"] = self.owner_id
        return payload


@dataclass(frozen=True)
class PictureTextContext:
    """Textual context on the same page around one picture."""

    picture_id: str
    surrounding_text: tuple[str, ...] = ()
    header_text: tuple[str, ...] = ()
    caption_text: tuple[str, ...] = ()
    scene_text: tuple[str, ...] = ()


def _ascii_fold(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _tokens(text: str) -> list[str]:
    return [tok for tok in _TOKEN_RE.findall(_ascii_fold(text)) if len(tok) >= 3]


def _is_all_upper(text: str) -> bool:
    cased = [ch for ch in text if ch.isalpha()]
    return bool(cased) and all(ch.isupper() for ch in cased)


def _truncate_context_item(text: str, max_chars: int = MAX_CONTEXT_ITEM_CHARS) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= max_chars:
        return collapsed
    cut = collapsed[:max_chars].rsplit(" ", 1)[0]
    return cut or collapsed[:max_chars]


def is_caption_text(
    text: str | None, raw_label: str = "", element_type: str = ""
) -> bool:
    """Whether an element's type, raw label or prefix marks it as a caption/source."""
    if element_type == "caption" or raw_label.strip().lower() == "caption":
        return True
    folded = _ascii_fold((text or "").strip())
    return bool(folded) and folded.startswith(_CAPTION_PREFIXES)


def is_prose_sentence(text: str | None) -> bool:
    """Whether ``text`` looks like independent document prose rather than signage."""
    normalized = (text or "").strip()
    if not normalized or is_placeholder_text(normalized) or is_ocr_noise(normalized):
        return False
    words = normalized.split()
    has_lower = any(ch.islower() for ch in normalized)
    if not has_lower:
        return False
    if len(words) >= 6:
        return True
    return len(words) >= 3 and bool(_SENTENCE_END_RE.search(normalized))


def is_scene_text_fragment(text: str | None) -> bool:
    """Whether ``text`` is a short OCR fragment or scene inscription (#398)."""
    normalized = (text or "").strip()
    if is_ocr_noise(normalized) or is_placeholder_text(normalized):
        return True
    if is_caption_text(normalized):
        return False
    if " " not in normalized and len(normalized) <= 24 and _is_all_upper(normalized):
        return True
    words = normalized.split()
    return len(words) <= 4 and len(normalized) <= 32 and _is_all_upper(normalized)


def is_scene_text_garbage(text: str | None) -> bool:
    """Whether a scene-text fragment carries no readable word (#398).

    Unlike :func:`docstruct.placeholders.is_ocr_noise`, which answers "does
    this document have content?", a single short word on a photo *is* the
    content (``ZECA``, ``Luci``). Only blank text, placeholders, and text
    with no run of two letters (``R:T``, a stray glyph, digits or symbols)
    are garbage.
    """
    normalized = (text or "").strip()
    if not normalized or is_placeholder_text(normalized):
        return True
    longest = run = 0
    for ch in normalized:
        run = run + 1 if ch.isalpha() else 0
        longest = max(longest, run)
    return longest < 2


def is_document_artifact(media_inspection: Mapping[str, Any] | None) -> bool:
    """Whether a media inspection classifies the input as a document page, not a scene."""
    if not isinstance(media_inspection, Mapping):
        return False
    return media_inspection.get("artifact_nature") in _DOCUMENT_ARTIFACT_NATURES


def is_document_page_picture(picture: ExtractedElement) -> bool:
    """Whether ``picture`` is part of a document page (scanned or photographed form, PDF page).

    The page's nature is recorded on the picture either as the injected
    picture's ``media_inspection`` or as ``artifact_nature`` stamped by the
    enrichment stage. Such a picture owns no scene text: OCR lines inside it
    are the document's own text.
    """
    if is_document_artifact(picture.metadata.get("media_inspection")):
        return True
    return picture.metadata.get("artifact_nature") in _DOCUMENT_ARTIFACT_NATURES


def is_scene_artifact(media_inspection: Mapping[str, Any] | None) -> bool:
    """Whether a media inspection describes a standalone image whose text is scene text."""
    return (
        isinstance(media_inspection, Mapping)
        and bool(media_inspection.get("is_image"))
        and not is_document_artifact(media_inspection)
    )


def is_scene_text_covered(
    fragment: str | None,
    description: str | None,
    mentioned_elements: Iterable[str] = (),
) -> bool:
    """Whether ``fragment`` is covered by ``description`` (or carries no readable word)."""
    normalized = (fragment or "").strip()
    if is_scene_text_garbage(normalized):
        return True
    combined_desc = " ".join(
        [description or "", *(str(item) for item in mentioned_elements)]
    ).strip()
    if not combined_desc:
        return False
    folded_desc = _ascii_fold(combined_desc)
    spaceless_desc = _ALNUM_RE.sub("", folded_desc)
    spaceless_frag = _ALNUM_RE.sub("", _ascii_fold(normalized))
    if len(spaceless_frag) >= 4 and spaceless_frag in spaceless_desc:
        return True
    frag_tokens = _tokens(normalized)
    if not frag_tokens:
        return False
    desc_tokens = set(_tokens(combined_desc))
    matched = sum(
        1 for tok in frag_tokens if tok in desc_tokens or (len(tok) >= 4 and tok in spaceless_desc)
    )
    return matched * 2 >= len(frag_tokens)


def scene_text_residue(
    fragments: Iterable[str | None],
    description: str | None,
    mentioned_elements: Iterable[str] = (),
    *,
    described: bool,
) -> tuple[str, ...]:
    """The scene text an image must still carry beyond its description (#398, #653).

    Scene text is never a document block; this decides what of it the image
    keeps, once each, in reading order:

    - garbage with no readable word is dropped (:func:`is_scene_text_garbage`);
      short words are kept, since on a photo they are the inscriptions;
    - without a usable description (vision failure, dry run) every meaningful
      fragment is kept, so the text is not lost;
    - fragments the description covers are dropped;
    - when the description covers at least ``SCENE_TEXT_TRANSCRIBED_SHARE`` of
      the meaningful fragments, it transcribes the scene and the uncovered
      remainder is OCR misreading (``WUNIDADES``, ``TINHO DAVILA``): dropped;
    - otherwise (a generic description) the uncovered fragments are kept.
    """
    meaningful: list[str] = []
    for fragment in fragments:
        normalized = " ".join((fragment or "").split())
        if not is_scene_text_garbage(normalized) and normalized not in meaningful:
            meaningful.append(normalized)
    if not meaningful or not described:
        return tuple(meaningful)
    mentioned = tuple(str(item) for item in mentioned_elements)
    uncovered = [
        fragment
        for fragment in meaningful
        if not is_scene_text_covered(fragment, description, mentioned)
    ]
    covered_share = 1 - len(uncovered) / len(meaningful)
    if covered_share >= SCENE_TEXT_TRANSCRIBED_SHARE:
        return ()
    return tuple(uncovered)


def _is_standalone_scene_fragment(text: str) -> bool:
    """On a confirmed standalone image with an injected picture, short non-prose labels are scene OCR."""
    normalized = text.strip()
    if is_scene_text_fragment(normalized):
        return True
    if is_prose_sentence(normalized) or is_caption_text(normalized):
        return False
    return len(normalized.split()) <= 4 and len(normalized) <= 36


def _page_has_document_prose(
    elements: Sequence[ExtractedElement], *, standalone_image: bool
) -> bool:
    for element in elements:
        text = (element.text or "").strip()
        if not text:
            continue
        if element.type in {"table", "formula", "code"} or element.metadata.get("slide_role"):
            return True
        if is_prose_sentence(text):
            return True
        if not standalone_image and not is_scene_text_fragment(text):
            return True
        if standalone_image and not _is_standalone_scene_fragment(text):
            return True
    return False


def _find_containing_picture(
    element_id: str,
    pictures: Sequence[ExtractedElement],
    page_boxes: Mapping[str, Box],
) -> str | None:
    box = page_boxes.get(element_id)
    if box is None:
        return None
    for picture in pictures:
        if is_document_page_picture(picture):
            continue
        pic_box = page_boxes.get(str(getattr(picture, "id", "")))
        if pic_box is not None and box_contains_center(pic_box, box):
            return str(getattr(picture, "id", ""))
    return None


def _is_contained_scene_candidate(element: ExtractedElement) -> bool:
    if element.type in {"paragraph", "unknown"}:
        return True
    return element.type == "list_item" and not element.metadata.get("enumerated")


def _classify_page_element(
    element: ExtractedElement,
    *,
    primary_picture_id: str | None,
    full_page_picture_id: str | None,
    has_document_prose: bool,
    standalone_image: bool,
    pictures: Sequence[ExtractedElement],
    page_boxes: Mapping[str, Box],
) -> TextOwnership:
    element_id = str(getattr(element, "id", ""))
    text = (element.text or "").strip()
    if element.metadata.get("slide_role"):
        return TextOwnership(
            element_id=element_id,
            role="document_text",
            reason="slide_structure",
        )
    if is_caption_text(text, element.raw_label, element.type):
        return TextOwnership(
            element_id=element_id,
            role="caption",
            owner_id=primary_picture_id,
            reason="caption_element",
        )
    if full_page_picture_id is not None and not has_document_prose:
        is_fragment = (
            _is_standalone_scene_fragment(text)
            if standalone_image
            else is_scene_text_fragment(text)
        )
        if is_fragment and element.type in _SCENE_CANDIDATE_TYPES:
            return TextOwnership(
                element_id=element_id,
                role="scene_text",
                owner_id=full_page_picture_id,
                reason="standalone_scene_ocr",
            )
    host_id = _find_containing_picture(element_id, pictures, page_boxes)
    if host_id is not None and _is_contained_scene_candidate(element):
        if is_scene_text_fragment(text):
            return TextOwnership(
                element_id=element_id,
                role="scene_text",
                owner_id=host_id,
                reason="contained_scene_fragment",
            )
        if not is_prose_sentence(text):
            return TextOwnership(
                element_id=element_id,
                role="uncertain",
                owner_id=host_id,
                confidence=0.5,
                reason="ambiguous_contained_text",
            )
    return TextOwnership(
        element_id=element_id,
        role="document_text",
        reason="independent_content",
    )


def _full_page_picture_id(
    pictures: Sequence[ExtractedElement],
    *,
    standalone_image: bool,
) -> str | None:
    """A picture owns unboxed page-level scene OCR only on an explicit standalone/injected image.

    An injected picture whose recorded media inspection marks the input as a
    document page (a photographed or scanned form) owns no scene text: its
    short lines are document text.
    """
    for pic in pictures:
        if is_document_page_picture(pic):
            continue
        if pic.metadata.get("injected_picture") or standalone_image:
            return str(getattr(pic, "id", ""))
    return None


def _analyze_page_elements(
    page_elements: Sequence[ExtractedElement],
    *,
    boxes: Mapping[str, Box],
    standalone_image: bool,
) -> dict[str, TextOwnership]:
    pictures = [el for el in page_elements if el.type == "picture"]
    non_pictures = [el for el in page_elements if el.type != "picture"]
    primary_id = str(getattr(pictures[0], "id", "")) if pictures else None
    full_page_pic = _full_page_picture_id(
        pictures,
        standalone_image=standalone_image,
    )
    effective_standalone = standalone_image or full_page_pic is not None
    has_prose = _page_has_document_prose(
        non_pictures, standalone_image=effective_standalone
    )
    decisions: dict[str, TextOwnership] = {}
    for element in non_pictures:
        ownership = _classify_page_element(
            element,
            primary_picture_id=primary_id,
            full_page_picture_id=full_page_pic,
            has_document_prose=has_prose,
            standalone_image=effective_standalone,
            pictures=pictures,
            page_boxes=boxes,
        )
        decisions[ownership.element_id] = ownership
    return decisions


def analyze_visual_text_ownership(
    elements: Sequence[ExtractedElement],
    *,
    page_boxes: Mapping[str, Box] | None = None,
    standalone_image: bool = False,
) -> dict[str, TextOwnership]:
    """Determine semantic ownership for every non-picture element in ``elements``."""
    boxes = page_boxes or {}
    by_page: dict[int, list[ExtractedElement]] = {}
    for element in elements:
        page = int(getattr(element, "page_number", None) or 1)
        by_page.setdefault(page, []).append(element)

    decisions: dict[str, TextOwnership] = {}
    for page_elements in by_page.values():
        decisions.update(
            _analyze_page_elements(
                page_elements,
                boxes=boxes,
                standalone_image=standalone_image,
            )
        )
    return decisions


def _is_header_like(element: ExtractedElement) -> bool:
    raw = (element.raw_label or "").strip().lower()
    return (
        element.type == "page_header"
        or raw in {"page_header", "header"}
        or element.metadata.get("content_layer") == "furniture"
    )


def _page_items_for_picture(
    picture_id: str, elements: Sequence[ExtractedElement]
) -> tuple[list[ExtractedElement], int]:
    target = next(
        (el for el in elements if str(getattr(el, "id", "")) == picture_id),
        None,
    )
    if target is None:
        return [], -1
    target_page = int(getattr(target, "page_number", None) or 1)
    page_items = [
        el
        for el in elements
        if int(getattr(el, "page_number", None) or 1) == target_page
    ]
    target_idx = next(
        (
            idx
            for idx, el in enumerate(page_items)
            if str(getattr(el, "id", "")) == picture_id
        ),
        0,
    )
    return page_items, target_idx


def bound_surrounding_items(items: Sequence[str]) -> tuple[str, ...]:
    """Cap surrounding context items by count, per-item length, and total length.

    The single bound shared by :func:`collect_picture_context` and the vision
    prompt that lists the context: ``MAX_CONTEXT_ITEMS`` items of at most
    ``MAX_CONTEXT_ITEM_CHARS`` characters, ``MAX_CONTEXT_TOTAL_CHARS`` in all.
    """
    bounded: list[str] = []
    total_chars = 0
    for raw in items:
        clipped = _truncate_context_item(raw, MAX_CONTEXT_ITEM_CHARS)
        if not clipped or clipped in bounded:
            continue
        if total_chars + len(clipped) > MAX_CONTEXT_TOTAL_CHARS:
            remaining = MAX_CONTEXT_TOTAL_CHARS - total_chars
            if remaining < 24:
                break
            clipped = _truncate_context_item(clipped, remaining)
        bounded.append(clipped)
        total_chars += len(clipped)
        if len(bounded) >= MAX_CONTEXT_ITEMS:
            break
    return tuple(bounded)


def _accumulate_context_item(
    el: ExtractedElement,
    *,
    idx: int,
    target_idx: int,
    picture_id: str,
    resolved: Mapping[str, TextOwnership],
    headers: list[str],
    captions: list[str],
    nearby: list[str],
    scene: list[str],
) -> None:
    text = (el.text or "").strip()
    if el.type == "picture" or not text:
        return
    decision = resolved.get(str(getattr(el, "id", "")))
    role = decision.role if decision is not None else "document_text"
    if role == "scene_text":
        if decision is not None and decision.owner_id == picture_id:
            scene.append(text)
        return
    if role == "decorative":
        return
    is_hdr = _is_header_like(el)
    if role == "caption":
        captions.append(text)
    if is_hdr:
        headers.append(text)
    if abs(idx - target_idx) <= 4 and not is_hdr and role != "caption":
        nearby.append(text)


def collect_picture_context(
    picture_id: str,
    elements: Sequence[ExtractedElement],
    ownership: Mapping[str, TextOwnership] | None = None,
) -> PictureTextContext:
    """Gather bounded surrounding document text and owned scene text for ``picture_id``."""
    resolved = (
        ownership
        if ownership is not None
        else analyze_visual_text_ownership(elements)
    )
    page_items, target_idx = _page_items_for_picture(picture_id, elements)
    if not page_items:
        return PictureTextContext(picture_id=picture_id)

    headers: list[str] = []
    captions: list[str] = []
    nearby: list[str] = []
    scene: list[str] = []
    for idx, el in enumerate(page_items):
        _accumulate_context_item(
            el,
            idx=idx,
            target_idx=target_idx,
            picture_id=picture_id,
            resolved=resolved,
            headers=headers,
            captions=captions,
            nearby=nearby,
            scene=scene,
        )
    # Prioritize headers and captions before nearby body paragraphs.
    ordered_candidates = [*headers, *captions, *nearby]
    return PictureTextContext(
        picture_id=picture_id,
        surrounding_text=bound_surrounding_items(ordered_candidates),
        header_text=tuple(headers),
        caption_text=tuple(captions),
        scene_text=tuple(scene),
    )


def _is_redundant_transcription_sentence(
    sentence: str,
    context_phrases: Sequence[str],
    context_tokens: set[str],
) -> bool:
    folded = _ascii_fold(sentence)
    sent_tokens = _tokens(sentence)
    if not sent_tokens:
        return False
    content_tokens = [tok for tok in sent_tokens if tok not in _TRANSCRIPTION_BOILERPLATE]
    has_cue = any(tok in _TRANSCRIPTION_CUE_WORDS for tok in sent_tokens)
    phrase_hits = sum(1 for phrase in context_phrases if len(phrase) >= 8 and phrase in folded)
    if not content_tokens:
        return phrase_hits > 0
    overlap = sum(1 for tok in content_tokens if tok in context_tokens) / len(content_tokens)
    if has_cue and (phrase_hits >= 1 or overlap >= 0.75):
        return True
    return phrase_hits >= 2 and overlap >= 0.8


def deduplicate_picture_description(
    description: str, surrounding_texts: Iterable[str]
) -> str:
    """Conservatively remove sentences that only re-transcribe adjacent document text (#263)."""
    cleaned = description.strip()
    if not cleaned:
        return cleaned
    phrases = [
        _ascii_fold(text.strip())
        for text in surrounding_texts
        if text and len(_tokens(text)) >= 2
    ]
    if not phrases:
        return cleaned
    context_tokens = {tok for phrase in phrases for tok in _tokens(phrase)}
    sentences = [part.strip() for part in _SENTENCE_SPLIT_RE.split(cleaned) if part.strip()]
    if len(sentences) < 2:
        return cleaned

    kept = [
        sentence
        for sentence in sentences
        if not _is_redundant_transcription_sentence(sentence, phrases, context_tokens)
    ]
    if not kept:
        return sentences[0]
    return " ".join(kept)


def is_confirmed_logo_description(
    description: str | None,
    mentioned_elements: Iterable[str] = (),
    *,
    described: bool = False,
    classified_as_logo: bool | None = None,
) -> bool:
    """Whether a header-adjacent picture is confirmed as an institutional logo (#325).

    ``classified_as_logo`` is the vision model's own answer for the picture
    (``VisionOutput.institutional_logo``). ``False`` keeps the picture even if
    its description uses logo words; ``True`` confirms the logo unless the
    description also names a non-logo subject, because a logo shown next to a
    photograph is still one picture and folding it into ``Logo.`` would drop
    the photograph; ``None`` falls back to the description, for answers stored
    before the field existed.

    When ``described=True`` (the VLM ran on the picture), an explicit positive
    logo/emblem/crest marker is required, and no non-logo marker may appear,
    so icons, author photos, maps, QR codes, arbitrary shapes, or a logo shown
    beside a photo are never called ``Logo.``. When
    ``described=False`` (dry-run or VLM unavailable), existing extractor text
    is still checked for non-logo markers before falling back to geometry.
    """
    combined = _ascii_fold(
        " ".join([description or "", *(str(item) for item in mentioned_elements)])
    ).strip()
    has_logo = bool(_LOGO_MARKER_RE.search(combined))
    has_non_logo = bool(_NON_LOGO_MARKER_RE.search(combined))
    if classified_as_logo is False:
        # An explicit non-logo answer outweighs any word in the description.
        return False
    if classified_as_logo is True:
        return not has_non_logo
    if described:
        # Both cues ("logo next to the author's photograph") is not a confirmed
        # logo: keeping the description loses nothing, folding it would.
        return has_logo and not has_non_logo
    if has_non_logo and not has_logo:
        return False
    return True


__all__ = [
    "MAX_CONTEXT_ITEMS",
    "MAX_CONTEXT_ITEM_CHARS",
    "MAX_CONTEXT_TOTAL_CHARS",
    "SCENE_TEXT_TRANSCRIBED_SHARE",
    "PictureTextContext",
    "TextOwnership",
    "VisualTextRole",
    "analyze_visual_text_ownership",
    "bound_surrounding_items",
    "collect_picture_context",
    "deduplicate_picture_description",
    "is_caption_text",
    "is_confirmed_logo_description",
    "is_document_artifact",
    "is_document_page_picture",
    "is_prose_sentence",
    "is_scene_artifact",
    "is_scene_text_covered",
    "is_scene_text_fragment",
    "is_scene_text_garbage",
    "scene_text_residue",
]
