"""Slide-by-slide structure for a presentation.

A slide deck exported to PDF is not one running document: each page is a unit
a screen reader user navigates to. When ``media.inspect`` says the source is a
presentation, the builder reshapes the extraction before deriving its
processing needs:

- the deck gets one H1 (its first slide title, or the file name), since the
  canonical document must start with a single main heading;
- every slide opens with an H2 "Slide N of T: <title>", or "Slide N of T" when
  the slide has no title, and the slide's other headings move under it;
- a slide whose pictures cover most of the page becomes one picture of the
  whole slide, which the vision model describes, instead of the fragments of
  text the extractor read off it;
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
        if deck_title is None and title is not None and (title.text or "").strip():
            deck_title = title.text.strip()
        heading = _slide_heading(slide, title, number, position, total)
        body = [element for element in slide if element is not heading]
        for element in body:
            if element.type in {"title", "heading"}:
                if element.type == "title":
                    element.metadata["original_type"] = "title"
                    element.type = "heading"
                element.hierarchy_level = max(element.hierarchy_level, INNER_LEVEL)
        if _is_visual(body, visual_coverage, page_fractions):
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
    """Whether the slide's pictures cover at least ``threshold`` of it."""
    coverage = 0.0
    for element in body:
        if element.type != "picture":
            continue
        box = page_fractions(element)
        if box is None:
            continue
        left, top, right, bottom = box
        coverage += max(0.0, min(right, 1.0) - max(left, 0.0)) * max(
            0.0, min(bottom, 1.0) - max(top, 0.0)
        )
    return coverage >= threshold


def _whole_slide_picture(number: int, replaced: list[ManifestElement]) -> ManifestElement:
    """One picture of the whole slide, without a box, so the page is rendered whole."""
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
        },
    )
