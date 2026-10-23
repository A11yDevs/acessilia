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
- reading order is numbered slide by slide, so it never crosses a slide.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable

from backend.core.manifest.models import ManifestElement, ProcessingManifest
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
    page_fractions: PageFractions,
) -> None:
    """Reshape ``manifest`` in place so each page is one slide.

    ``page_fractions(element)`` returns the element's box as fractions of its
    page, or ``None``; the builder passes its own normalization.
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
            pictures.append(box)
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


def _area(box: tuple[float, float, float, float]) -> float:
    left, top, right, bottom = box
    return max(0.0, right - left) * max(0.0, bottom - top)


def _union_area(boxes: list[tuple[float, float, float, float]]) -> float:
    """Area covered by ``boxes``, overlaps counted once."""
    xs = sorted({x for box in boxes for x in (box[0], box[2])})
    area = 0.0
    for left, right in zip(xs, xs[1:]):
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
