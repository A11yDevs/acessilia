"""Deterministic handlers that reorder a page's elements.

``skeleton-order`` follows the secondary provider's reading order (a
Dr.DocBench rule, calibrated on docling + mineru); ``xycut-order`` applies
XY-cut to the elements' boxes. Moved verbatim from the PDDL orchestrator
(#402, phase 3, step 6).
"""

from __future__ import annotations

from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.core.pipeline.elements import (
    _element_bbox,
)
from backend.core.pipeline.handlers.common import (
    _fusion_agent,
    _missing_obligation,
    _target_elements,
)
from backend.core.pipeline.handlers.messages import (
    MSG_SKELETON_APPLIED,
    MSG_SKELETON_CONFIRMED,
    MSG_SKELETON_NO_MATCH,
    MSG_XYCUT_APPLIED,
    MSG_XYCUT_NONE,
)
from backend.core.pipeline.secondary import (
    _pair_block,
    _secondary_or_failure,
)
from backend.core.i18n import t


#: Share of a page's elements that must be paired to follow the skeleton order.
_MIN_SKELETON_MATCH = 0.5


def _handle_skeleton_order_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Follow the secondary provider's reading order (MinerU skeleton).

    Page elements are paired with the secondary blocks by position (falling
    back to text); paired elements take the skeleton order and unpaired ones
    stay right after the element that preceded them. A page with fewer than
    half its elements paired is left alone.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    by_page: dict[int, list[ManifestElement]] = {}
    for element in elements:
        if element.page_number is not None:
            by_page.setdefault(element.page_number, []).append(element)

    reordered: set[int] = set()
    confirmed: set[int] = set()
    for page_number, page_elements in by_page.items():
        current = sorted(page_elements, key=lambda element: element.reading_order)
        skeleton = secondary.pages.get(page_number, [])
        used: set[int] = set()
        keys: dict[int, int] = {}
        for index, element in enumerate(current):
            match = _pair_block(element, manifest, skeleton, secondary, used)
            if match is not None:
                used.add(match)
                keys[index] = match
        if len(current) < 2 or len(keys) < _MIN_SKELETON_MATCH * len(current):
            continue
        ranked: list[tuple[float, int, int]] = []
        last = -1.0
        for index in range(len(current)):
            if index in keys:
                last = float(keys[index])
                ranked.append((last, 0, index))
            else:
                ranked.append((last, 1, index))
        order = [index for _, _, index in sorted(ranked)]
        if _apply_page_order(current, order):
            reordered.add(page_number)
        else:
            confirmed.add(page_number)

    if not reordered and not confirmed:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_SKELETON_NO_MATCH),
        )
    _refresh_page_element_ids(manifest, reordered)
    parts = []
    if reordered:
        parts.append(
            t(MSG_SKELETON_APPLIED).format(
                pages=", ".join(map(str, sorted(reordered)))
            )
        )
    if confirmed:
        parts.append(
            t(MSG_SKELETON_CONFIRMED).format(
                pages=", ".join(map(str, sorted(confirmed)))
            )
        )
    return MethodResult(
        success=True,
        validated=True,
        message="; ".join(parts),
    )


def _apply_page_order(current: list[ManifestElement], order: list[int]) -> bool:
    """Reassign the reading-order slots of ``current`` following ``order``.

    ``order[i]`` is the index in ``current`` of the element that goes to the
    i-th slot. Returns whether anything moved.
    """
    if order == list(range(len(current))):
        return False
    slots = sorted(element.reading_order for element in current)
    for slot, index in zip(slots, order):
        current[index].reading_order = slot
    return True


def _refresh_page_element_ids(
    manifest: ProcessingManifest, page_numbers: set[int]
) -> None:
    manifest.elements.sort(key=lambda element: element.reading_order)
    for page in manifest.pages:
        if page.page_number in page_numbers:
            page.element_ids = [
                element.id
                for element in manifest.elements
                if element.page_number == page.page_number
            ]


def _handle_xycut_order_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Apply XY-cut reading order to the evidenced page elements."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fusion_agent = _fusion_agent()
    reordered_pages: set[int] = set()
    by_page: dict[int, list[ManifestElement]] = {}
    for element in elements:
        if element.page_number is not None:
            by_page.setdefault(element.page_number, []).append(element)

    for page_number, page_elements in by_page.items():
        positioned = [
            element for element in page_elements
            if _element_bbox(element, manifest) is not None
        ]
        if len(positioned) < 2:
            continue
        current = sorted(positioned, key=lambda element: element.reading_order)
        boxes = [_element_bbox(element, manifest) for element in current]
        order = fusion_agent.process_refine_reading_order(
            [list(box) for box in boxes if box is not None]
        )
        if _apply_page_order(current, order):
            reordered_pages.add(page_number)

    if not reordered_pages:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_XYCUT_NONE),
        )

    _refresh_page_element_ids(manifest, reordered_pages)
    return MethodResult(
        success=True,
        validated=True,
        message=t(MSG_XYCUT_APPLIED).format(
            pages=", ".join(map(str, sorted(reordered_pages)))
        ),
    )
