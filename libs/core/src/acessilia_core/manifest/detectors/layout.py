"""Per-page geometric and textual layout detectors for manifest needs."""

from __future__ import annotations

from collections import Counter

from docstruct.fusion.line_numbers import extract_line_numbers
from docstruct.fusion.tailjoin import join_tail, page_number_position, tailjoin3
from docstruct.fusion.types import DiffBlock
from docstruct.fusion.verse import verse_blocks
from docstruct.fusion.xycut import xycut_order

from acessilia_core.manifest.detectors.types import (
    NeedCandidate,
    PageSizes,
    normalized_element_bbox,
)
from acessilia_core.manifest.models import ManifestElement
from acessilia_core.manifest.slides import is_slide_heading

_NON_TEXT_ELEMENT_TYPES = frozenset({"formula", "table", "picture"})
_ROLE_BY_TYPE = {
    "page_header": "header",
    "page_footer": "footer",
    "page_number": "page_number",
}


def detect_reading_order_need(
    page_number: int | None,
    page_elements: list[ManifestElement],
    *,
    page_sizes: PageSizes | None,
) -> NeedCandidate | None:
    """Detect when XY-Cut column ordering differs from the page's current reading order."""
    # A slide's own heading opens the slide whatever its box, folding on or
    # off: a picture whose crop grew above-left of it would otherwise be read
    # first (slides.py, _absorb_near_pictures). The deck title has no box, so
    # it is never positioned.
    positioned_pairs = [
        (item, box)
        for item in page_elements
        if (box := normalized_element_bbox(item, page_sizes)) is not None
        and not is_slide_heading(item)
    ]
    if len(positioned_pairs) <= 1:
        return None
    positioned_pairs.sort(key=lambda pair: pair[0].reading_order)
    current = [item for item, _ in positioned_pairs]
    boxes = [box for _, box in positioned_pairs]
    order = xycut_order(boxes)
    if order == list(range(len(current))):
        return None
    return NeedCandidate(
        "refine-reading-order",
        current,
        {
            "page_number": page_number,
            "order_before": [item.id for item in current],
            "order_after": [current[index].id for index in order],
        },
    )


def detect_verse_chunk_need(
    text_elements: list[ManifestElement],
    blocks: list[DiffBlock],
) -> NeedCandidate | None:
    """Detect multi-line verse/record blocks that should be chunked."""
    verse_stats: Counter[str] = Counter()
    verse_blocks(blocks, verse_stats, "manifest", 300, "records")
    if not verse_stats.get("verse-manifest-split", 0):
        return None
    return NeedCandidate(
        "chunk-verse",
        text_elements,
        {"chunks": verse_stats["verse-manifest-chunks"]},
    )


def detect_line_numbers_need(
    text_elements: list[ManifestElement],
    blocks: list[DiffBlock],
) -> NeedCandidate | None:
    """Detect marginal line numbers that should be split into their own blocks."""
    line_stats: Counter[str] = Counter()
    extract_line_numbers(blocks, line_stats, "manifest")
    if not line_stats.get("line-numbers-manifest-count", 0):
        return None
    return NeedCandidate(
        "extract-line-numbers",
        text_elements,
        {"count": line_stats["line-numbers-manifest-count"]},
    )


def detect_tail_join_need(
    text_elements: list[ManifestElement],
    blocks: list[DiffBlock],
) -> NeedCandidate | None:
    """Detect short trailing blocks (headers, footers, page numbers) to join."""
    page_text = [item.text or "" for item in text_elements]
    position = page_number_position(blocks)
    if position is not None:
        joined = tailjoin3(page_text, position, 50, 3, "keep")
    else:
        joined = join_tail(page_text, "end", 50, 3)
    if joined == page_text:
        return None
    tail_targets = text_elements[
        len(text_elements) - (len(page_text) - len(joined) + 1) :
    ]
    return NeedCandidate(
        "join-tail-blocks",
        tail_targets,
        {
            "position": position,
            "before_count": len(page_text),
            "after_count": len(joined),
        },
    )


def detect_page_layout_needs(
    by_page: dict[int | None, list[ManifestElement]],
    *,
    page_sizes: PageSizes | None,
) -> list[NeedCandidate]:
    """Run reading-order, verse, line-number and tail-join detectors per page."""
    candidates: list[NeedCandidate] = []
    for page_number, page_elements in by_page.items():
        reading_order = detect_reading_order_need(
            page_number, page_elements, page_sizes=page_sizes
        )
        if reading_order is not None:
            candidates.append(reading_order)

        text_elements = [
            item
            for item in page_elements
            if item.text and item.type not in _NON_TEXT_ELEMENT_TYPES
        ]
        if not text_elements:
            continue
        blocks = _to_diff_blocks(text_elements, page_sizes)
        for detected in (
            detect_verse_chunk_need(text_elements, blocks),
            detect_line_numbers_need(text_elements, blocks),
            detect_tail_join_need(text_elements, blocks),
        ):
            if detected is not None:
                candidates.append(detected)
    return candidates


def _to_diff_blocks(
    text_elements: list[ManifestElement],
    page_sizes: PageSizes | None,
) -> list[DiffBlock]:
    return [
        DiffBlock(
            md=item.text or "",
            kind="text",
            box=normalized_element_bbox(item, page_sizes),
            text=item.text or "",
            type=item.type,
            role=_ROLE_BY_TYPE.get(item.type),
        )
        for item in text_elements
    ]
