"""Slide-by-slide structure for a presentation.

A slide deck exported to PDF is not one running document: each page is a unit
a screen reader user navigates to. When ``media.inspect`` says the source is a
presentation, the builder reshapes the extraction before deriving its
processing needs:

- the deck gets one H1 (the title of its first slide, or the file name), since
  the canonical document must start with a single main heading;
- every slide opens with an H2 "Slide N of T: <title>", or "Slide N of T" when
  the slide has no title, and the slide's other headings move under it;
- a slide whose pictures cover most of the page, and whose text was read off
  those pictures, becomes one picture of the whole slide, which the vision
  model describes, instead of the fragments of text the extractor read off it;
  a slide nothing was extracted from becomes one too, so it is still described;
- on a slide read as text, short text lying on a picture (the labels of a
  diagram, the cells of a chart read one by one) is folded into that picture,
  whose description transcribes it in place, instead of standing as loose
  paragraphs out of their place; a label just beside a picture grows the
  picture's crop to take it in, and text spanning several pictures (a caption
  row read across their columns) merges them into one;
- reading order is numbered slide by slide, so it never crosses a slide.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from itertools import pairwise

from backend.core.manifest.models import BoundingBox, ManifestElement, ProcessingManifest
from backend.i18n import t
from backend.log_messages import MSG_SLIDE_HEADING, MSG_SLIDE_HEADING_WITH_TITLE

#: Default share of the slide its pictures must cover for the slide to be
#: described as an image rather than read as text (SLIDE_VISUAL_COVERAGE).
DEFAULT_VISUAL_COVERAGE = 0.5

#: A picture covering this much of the slide is its background, not its
#: content: a template's backdrop would otherwise turn every slide into a
#: picture. 006.pdf's largest content picture covers 0.82 of its slide.
_BACKGROUND_COVERAGE = 0.95

#: Largest share of the slide the text outside its pictures may cover for the
#: slide to be described as an image. Text read off a picture (labels of a
#: chart, a screenshot) lies inside it, and a caption or a source line is
#: small; bullets or a table beside a picture are not. In 006.pdf's visual
#: slides that text covers at most 0.013 of the slide.
_MAX_TEXT_OUTSIDE = 0.05

#: Default for folding the labels on a text slide's pictures into them
#: (SLIDE_FOLD_FIGURE_LABELS).
DEFAULT_FOLD_FIGURE_LABELS = True

#: Most words of three letters or more a text on a picture may have to be one
#: of its labels. 006.pdf's labels ("1nm", "Transistor (2003)", "Mg2+",
#: "1 2 3 … 18") have at most two.
_LABEL_MAX_WORDS = 3

#: A text with a word of three letters or more that ends like a sentence
#: ("Cresceu 10%.") or names something ("Fonte: IBGE, 2024") is the author's
#: own, even when short; garbled OCR such as "p3." or "2." is not.
_SENTENCE = re.compile(r"[.!?]$|:\s")

#: How far beside a picture, as a share of the slide, a label still belongs to
#: it. 006.pdf slide 12's nuclide notation ("E Z") lies 0.07 to the right of
#: the lamp it was pasted with; a heading naming a picture sits further off
#: (slide 26's "Tartrazina", 0.11 above its drawing) and stays.
_NEAR_MARGIN = 0.08

#: Element types a picture's label can have been extracted as. A formula, a
#: table or a list keeps its own structure; a caption is the author's text
#: (a source, "Figure 3 — …"), not something read off the picture.
_LABEL_TYPES = {"paragraph", "heading", "title", "unknown"}

#: Heading levels: the deck title, each slide, and headings inside a slide.
DECK_LEVEL, SLIDE_LEVEL, INNER_LEVEL = 1, 2, 3

#: Running headers and footers repeat on every slide; they are not its title.
_DECORATION = {"page_header", "page_footer"}

#: A link the extractor labelled as a heading is a reference, not a title.
_URL = re.compile(r"^(https?://|www\.)", re.IGNORECASE)

#: An element's box as fractions (left, top, right, bottom) of its page, or None.
PageFractions = Callable[[ManifestElement], "tuple[float, float, float, float] | None"]


def structure_as_slides(
    manifest: ProcessingManifest,
    *,
    visual_coverage: float = DEFAULT_VISUAL_COVERAGE,
    fold_figure_labels: bool = DEFAULT_FOLD_FIGURE_LABELS,
    page_fractions: PageFractions,
) -> None:
    """Reshape ``manifest`` in place so each page is one slide.

    ``page_fractions(element)`` returns the element's box as fractions of its
    page, or ``None``; the builder passes its own normalization.
    ``fold_figure_labels`` folds the labels on a text slide's pictures into
    them (SLIDE_FOLD_FIGURE_LABELS).
    """
    numbers = sorted(page.page_number for page in manifest.pages)
    if not numbers:
        return
    total = len(numbers)
    by_page: dict[int, list[ManifestElement]] = {number: [] for number in numbers}
    loose: list[ManifestElement] = []
    for element in sorted(manifest.elements, key=lambda item: item.reading_order):
        if element.page_number in by_page:
            by_page[element.page_number].append(element)
        else:
            # Groups and other nodes without a page are not exported; they keep
            # their place at the end.
            loose.append(element)

    deck_title: str | None = None
    ordered: list[ManifestElement] = []
    for position, number in enumerate(numbers, start=1):
        slide = by_page[number]
        title = _slide_title(slide)
        if position == 1 and title is not None and (title.text or "").strip():
            deck_title = title.text.strip()
        heading = _slide_heading(slide, title, number, position, total)
        body = [element for element in slide if element is not heading]
        for element in body:
            if element.type in {"title", "heading"}:
                if element.type == "title":
                    element.metadata["original_type"] = "title"
                    element.type = "heading"
                element.hierarchy_level = max(element.hierarchy_level, INNER_LEVEL)
        if not slide or _is_visual(body, visual_coverage, page_fractions):
            # A slide nothing was extracted from may be a scan or a photo; the
            # heading would hide it from the unstructured-page inspection.
            body = [_whole_slide_picture(number, body)]
        elif fold_figure_labels:
            body = _fold_figure_labels(body, page_fractions)
            body = _absorb_near_pictures(body, page_fractions)
        ordered.append(heading)
        ordered.extend(body)

    deck = ManifestElement(
        id="element-slide-deck-title",
        type="title",
        raw_label="title",
        reading_order=1,
        hierarchy_level=DECK_LEVEL,
        text=deck_title or manifest.source.filename.rsplit(".", 1)[0],
        page_number=numbers[0],
        metadata={"slide_role": "deck_title"},
    )
    elements = [deck, *ordered, *loose]
    for order, element in enumerate(elements, start=1):
        element.reading_order = order
    manifest.elements = elements
    for page in manifest.pages:
        page.element_ids = [
            element.id for element in elements if element.page_number == page.page_number
        ]
    manifest.summary.element_count = len(elements)
    manifest.summary.element_types = dict(Counter(element.type for element in elements))


def _slide_title(slide: list[ManifestElement]) -> ManifestElement | None:
    """The slide's first title or heading in reading order that reads as a title.

    Running headers are skipped, and so are headings with no letter or that
    are a link: in 006.pdf the extractor labelled a periodic table's column
    numbers ("1 2 3 … 18") and a NIST URL as headings.
    """
    return next(
        (
            element
            for element in slide
            if element.type in {"title", "heading"}
            and element.raw_label not in _DECORATION
            and _reads_as_title(element.text or "")
        ),
        None,
    )


def _reads_as_title(text: str) -> bool:
    text = text.strip()
    return any(char.isalpha() for char in text) and not _URL.match(text)


def _slide_heading(
    slide: list[ManifestElement],
    title: ManifestElement | None,
    number: int,
    position: int,
    total: int,
) -> ManifestElement:
    """The slide's own H2: its title rewritten, or a new heading when it has none."""
    if title is not None:
        text = (title.text or "").strip()
        title.metadata["slide_title"] = text
        if title.type == "title":
            title.metadata["original_type"] = "title"
        title.type = "heading"
        title.raw_label = "heading"
        title.hierarchy_level = SLIDE_LEVEL
        title.text = t(MSG_SLIDE_HEADING_WITH_TITLE).format(
            number=position, total=total, title=text
        )
        title.metadata["slide_role"] = "slide_heading"
        return title
    return ManifestElement(
        id=f"element-slide-{number:04d}",
        type="heading",
        raw_label="heading",
        reading_order=1,
        hierarchy_level=SLIDE_LEVEL,
        text=t(MSG_SLIDE_HEADING).format(number=position, total=total),
        page_number=number,
        metadata={"slide_role": "slide_heading"},
    )


def _is_visual(
    body: list[ManifestElement], threshold: float, page_fractions: PageFractions
) -> bool:
    """Whether the slide is mostly a picture its text was read off.

    The union of its pictures, a background left out, must cover at least
    ``threshold`` of the slide, and the text outside them at most
    ``_MAX_TEXT_OUTSIDE``. Text without a box keeps the slide as text, since
    where it lies is unknown.
    """
    pictures = [box for _, box in _content_pictures(body, page_fractions)]
    if _union_area(pictures) < threshold:
        return False
    outside = []
    for element in body:
        if (
            element.type == "picture"
            or element.raw_label in _DECORATION
            or not (element.text or "").strip()
        ):
            continue
        box = page_fractions(element)
        if box is None:
            return False
        if not any(_contains(picture, box) for picture in pictures):
            outside.append(box)
    return _union_area(outside) <= _MAX_TEXT_OUTSIDE


def _content_pictures(
    body: list[ManifestElement], page_fractions: PageFractions
) -> list[tuple[ManifestElement, tuple[float, float, float, float]]]:
    """The slide's pictures with their boxes clipped to the slide, background left out.

    A picture without a box is left out too, since where it lies is unknown.
    """
    pictures = []
    for element in body:
        if element.type != "picture":
            continue
        box = page_fractions(element)
        if box is None:
            continue
        left, top, right, bottom = box
        box = (max(left, 0.0), max(top, 0.0), min(right, 1.0), min(bottom, 1.0))
        if 0 < _area(box) < _BACKGROUND_COVERAGE:
            pictures.append((element, box))
    return pictures


def _fold_figure_labels(
    body: list[ManifestElement], page_fractions: PageFractions
) -> list[ManifestElement]:
    """``body`` without the labels lying on its pictures, each kept by its picture.

    A label is short text (at most ``_LABEL_MAX_WORDS`` words of three letters
    or more, not a sentence) whose box centre lies on a picture that is not the
    slide's background: text over a backdrop is the slide's own. The vision
    model reads it off the picture with the rest (the picture prompt asks for
    every legible text), so it is not handed over; its text is kept, in reading
    order, in the picture's ``figure_labels`` and its id in
    ``figure_label_ids``. A label on nested pictures goes to the smallest, the
    one it most likely names. Should the picture be left undescribed, those
    labels are its alt text (``_element_to_block``), so they are not lost.

    Handing the labels to the model was tried on 006.pdf and made it worse: a
    structural formula's atom letters ("H", "O", "SOH") pushed it to transcribe
    the drawing as a formula, garbled or cut off.
    """
    pictures = _content_pictures(body, page_fractions)
    if not pictures:
        return body
    kept = []
    for element in body:
        text = (element.text or "").strip()
        box = page_fractions(element) if element.type in _LABEL_TYPES else None
        hosts = [
            (picture, picture_box)
            for picture, picture_box in pictures
            if box is not None and _contains(picture_box, box)
        ]
        if (
            not text
            or not hosts
            or element.raw_label in _DECORATION
            or not _reads_as_label(text)
        ):
            kept.append(element)
            continue
        host, _ = min(hosts, key=lambda pair: _area(pair[1]))
        host.metadata.setdefault("figure_labels", []).append(text)
        host.metadata.setdefault("figure_label_ids", []).append(element.id)
    return kept


def _absorb_near_pictures(
    body: list[ManifestElement], page_fractions: PageFractions
) -> list[ManifestElement]:
    """``body`` with the fragments just beside its pictures taken into them.

    A label (see ``_fold_figure_labels``) within ``_NEAR_MARGIN`` of a picture
    goes to the nearest one, and the picture's box grows to cover it, so the
    crop the vision model describes shows the label in place. Text whose span
    covers several pictures across (a caption row read through their columns,
    006.pdf slide 18) merges them into the first one, whose box covers them all;
    a caption is taken in only then, or when it lies on or beside such a merged
    picture (the rest of that row), since a caption under one picture is the
    author's own text. A
    picture whose box cannot be grown (no box, or a different origin) takes
    nothing. Taken text is kept in ``figure_labels`` like a folded label, and
    the merged pictures' ids in ``merged_picture_ids``.
    """
    # Boxes by picture id; a merged picture's id leaves it.
    pictures = {picture.id: box for picture, box in _content_pictures(body, page_fractions)}
    if not pictures:
        return body
    by_id = {element.id: element for element in body}
    removed: set[str] = set()
    changed = True
    while changed:
        changed = False
        for element in body:
            if element.id in removed or element.id in pictures:
                continue
            text = (element.text or "").strip()
            box = page_fractions(element)
            if (
                not text
                or box is None
                or element.type not in _LABEL_TYPES | {"caption"}
                or element.raw_label in _DECORATION
            ):
                continue
            label = _reads_as_label(text)
            near = [
                picture
                for picture, picture_box in pictures.items()
                if _overlaps(_expanded(picture_box, _NEAR_MARGIN), box)
            ]
            spanned = [p for p in near if _spans_across(box, pictures[p])]
            near_merged = [p for p in near if by_id[p].metadata.get("merged_picture_ids")]
            if len(spanned) >= 2 and (label or element.type == "caption"):
                host = _merge_pictures([by_id[p] for p in spanned], pictures, removed)
            elif near_merged and (label or element.type == "caption"):
                host = by_id[near_merged[0]]
            elif near and label and element.type != "caption":
                host = by_id[min(near, key=lambda p: _distance(pictures[p], box))]
            else:
                continue
            if host is None or not _grow(host, element):
                continue
            pictures[host.id] = _union(pictures[host.id], box)
            host.metadata.setdefault("figure_labels", []).append(text)
            host.metadata.setdefault("figure_label_ids", []).append(element.id)
            removed.add(element.id)
            changed = True
    return [element for element in body if element.id not in removed]


def _merge_pictures(
    spanned: list[ManifestElement],
    pictures: dict[str, tuple[float, float, float, float]],
    removed: set[str],
) -> ManifestElement | None:
    """Merge ``spanned`` into the first in reading order; None if a box cannot grow."""
    host, *others = sorted(spanned, key=lambda p: p.reading_order)
    if not all(_growable(host, other) for other in others):
        return None
    for other in others:
        _grow(host, other)
        pictures[host.id] = _union(pictures[host.id], pictures.pop(other.id))
        host.metadata.setdefault("merged_picture_ids", []).append(other.id)
        for key in ("figure_labels", "figure_label_ids"):
            if other.metadata.get(key):
                host.metadata.setdefault(key, []).extend(other.metadata[key])
        removed.add(other.id)
    return host


def _growable(host: ManifestElement, other: ManifestElement) -> bool:
    """Whether both source boxes exist and share an origin, so one can cover the other."""
    if not host.provenance or not other.provenance:
        return False
    first, second = host.provenance[0].bbox, other.provenance[0].bbox
    return first is not None and second is not None and first.coord_origin == second.coord_origin


def _grow(host: ManifestElement, other: ManifestElement) -> bool:
    """Grow ``host``'s source box to cover ``other``'s; False when it cannot."""
    if not _growable(host, other):
        return False
    first, second = host.provenance[0].bbox, other.provenance[0].bbox
    upward = first.coord_origin == "BOTTOMLEFT"
    host.provenance[0].bbox = BoundingBox(
        left=min(first.left, second.left),
        right=max(first.right, second.right),
        top=max(first.top, second.top) if upward else min(first.top, second.top),
        bottom=min(first.bottom, second.bottom) if upward else max(first.bottom, second.bottom),
        coord_origin=first.coord_origin,
    )
    return True


def _expanded(
    box: tuple[float, float, float, float], margin: float
) -> tuple[float, float, float, float]:
    return (box[0] - margin, box[1] - margin, box[2] + margin, box[3] + margin)


def _overlaps(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> bool:
    return (
        min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )


def _spans_across(
    box: tuple[float, float, float, float], picture: tuple[float, float, float, float]
) -> bool:
    """Whether ``box`` shares part of ``picture``'s width."""
    return min(box[2], picture[2]) > max(box[0], picture[0])


def _distance(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> float:
    across = max(0.0, max(first[0], second[0]) - min(first[2], second[2]))
    down = max(0.0, max(first[1], second[1]) - min(first[3], second[3]))
    return across + down


def _union(
    first: tuple[float, float, float, float], second: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    return (
        min(first[0], second[0]),
        min(first[1], second[1]),
        max(first[2], second[2]),
        max(first[3], second[3]),
    )


def _reads_as_label(text: str) -> bool:
    words = sum(1 for word in text.split() if sum(char.isalpha() for char in word) >= 3)
    return words <= _LABEL_MAX_WORDS and not (words and _SENTENCE.search(text))


def _area(box: tuple[float, float, float, float]) -> float:
    left, top, right, bottom = box
    return max(0.0, right - left) * max(0.0, bottom - top)


def _union_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """Area covered by ``boxes``, overlaps counted once."""
    xs = sorted({x for box in boxes for x in (box[0], box[2])})
    area = 0.0
    for left, right in pairwise(xs):
        spans = sorted(
            (box[1], box[3]) for box in boxes if box[0] <= left and box[2] >= right
        )
        covered, reach = 0.0, 0.0
        for top, bottom in spans:
            top = max(top, reach)
            if bottom > top:
                covered += bottom - top
                reach = bottom
        area += (right - left) * covered
    return area


def _contains(
    picture: tuple[float, float, float, float], box: tuple[float, float, float, float]
) -> bool:
    """Whether the center of ``box`` lies within ``picture``."""
    x, y = (box[0] + box[2]) / 2, (box[1] + box[3]) / 2
    return picture[0] <= x <= picture[2] and picture[1] <= y <= picture[3]


def _whole_slide_picture(number: int, replaced: list[ManifestElement]) -> ManifestElement:
    """One picture of the whole slide, without a box, so the page is rendered whole.

    The text of the elements it replaces is kept in ``replaced_text``.
    """
    return ManifestElement(
        id=f"element-slide-{number:04d}-visual",
        type="picture",
        raw_label="picture",
        reading_order=1,
        hierarchy_level=0,
        page_number=number,
        metadata={
            "slide_visual": True,
            "replaced_element_ids": [element.id for element in replaced],
            "replaced_text": "\n".join(
                text
                for element in replaced
                if element.type != "picture" and (text := (element.text or "").strip())
            ),
        },
    )
