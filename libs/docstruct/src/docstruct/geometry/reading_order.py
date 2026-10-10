"""Column-aware reading order refinement and marginal isolation.

Pure: zero external dependencies, standard library only.
Refines block reading orders by isolating headers and footers,
detecting multi-column gutters (2 and 3 columns) based on median block width,
and ordering columns top-to-bottom without horizontal traversal.
"""
from __future__ import annotations

import statistics
from typing import Any

from docstruct.types import BBox

_HEADER_TYPES = frozenset({"page_header", "header", "running_header", "running_head"})
_FOOTER_TYPES = frozenset({"page_footer", "footer", "running_footer", "page_number"})


def _extract_bbox(item: Any) -> BBox | None:
    """Extract (x0, y0, x1, y1) bounding box from dict or object."""
    if isinstance(item, dict):
        raw = item.get("bbox")
    else:
        raw = getattr(item, "bbox", None)

    if raw is None:
        prov = getattr(item, "provenance", None)
        if isinstance(prov, (list, tuple)) and len(prov) > 0:
            first_prov = prov[0]
            if hasattr(first_prov, "bbox"):
                b = getattr(first_prov, "bbox", None)
                if b is not None:
                    if hasattr(b, "l") and hasattr(b, "t") and hasattr(b, "r") and hasattr(b, "b"):
                        return (float(b.l), float(b.t), float(b.r), float(b.b))
                    if hasattr(b, "left") and hasattr(b, "top") and hasattr(b, "right") and hasattr(b, "bottom"):
                        return (float(b.left), float(b.top), float(b.right), float(b.bottom))

    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        return (float(raw[0]), float(raw[1]), float(raw[2]), float(raw[3]))
    return None


def _extract_type(item: Any) -> str:
    """Extract block type from dict or object."""
    if isinstance(item, dict):
        return str(item.get("type") or item.get("raw_label") or "").lower()
    return str(getattr(item, "type", None) or getattr(item, "raw_label", "") or "").lower()


def _extract_page(item: Any) -> int | None:
    """Extract page number from dict or object."""
    if isinstance(item, dict):
        page = item.get("page_index")
        if page is None:
            page = item.get("page_number")
        if page is None:
            page = item.get("page_no")
        return int(page) if page is not None else None
    page = getattr(item, "page_index", None)
    if page is None:
        page = getattr(item, "page_number", None)
    return int(page) if page is not None else None


def _top_left_key(item: Any) -> tuple[float, float]:
    """Sort key using bounding box top (y0) then left (x0)."""
    bbox = _extract_bbox(item)
    if bbox is not None:
        return (bbox[1], bbox[0])
    return (0.0, 0.0)


def _order_body_columns(body_elements: list[Any]) -> list[Any]:
    """Order page body elements respecting 2- or 3-column gutters and full-width banners."""
    elements_with_bbox = [e for e in body_elements if _extract_bbox(e) is not None]
    if len(elements_with_bbox) < 2:
        return sorted(body_elements, key=_top_left_key)

    min_left = min(_extract_bbox(e)[0] for e in elements_with_bbox)  # type: ignore[index]
    max_right = max(_extract_bbox(e)[2] for e in elements_with_bbox)  # type: ignore[index]
    page_width = max(1.0, max_right - min_left)

    widths = [_extract_bbox(e)[2] - _extract_bbox(e)[0] for e in elements_with_bbox]  # type: ignore[index]
    median_width = statistics.median(widths)

    # Multi-column candidates have median width reduced relative to page content width
    if median_width >= 0.65 * page_width:
        return sorted(body_elements, key=_top_left_key)

    # Separate full-width banners (titles, wide figures/tables spanning >= 75% of content width)
    narrow_elements = [
        e for e in elements_with_bbox if (_extract_bbox(e)[2] - _extract_bbox(e)[0]) < (0.75 * page_width)  # type: ignore[index]
    ]

    # Check 3-column layout
    third_1 = min_left + (1.0 / 3.0) * page_width
    third_2 = min_left + (2.0 / 3.0) * page_width
    c1_3 = [e for e in narrow_elements if _extract_bbox(e)[2] <= (third_1 + 0.05 * page_width)]  # type: ignore[index]
    c2_3 = [
        e for e in narrow_elements
        if _extract_bbox(e)[0] >= (third_1 - 0.05 * page_width) and _extract_bbox(e)[2] <= (third_2 + 0.05 * page_width)  # type: ignore[index]
    ]
    c3_3 = [e for e in narrow_elements if _extract_bbox(e)[0] >= (third_2 - 0.05 * page_width)]  # type: ignore[index]

    is_three_col = len(c1_3) >= 2 and len(c2_3) >= 2 and len(c3_3) >= 2

    # Check 2-column layout
    mid_x = min_left + 0.5 * page_width
    c1_2 = [e for e in narrow_elements if _extract_bbox(e)[2] <= (mid_x + 0.05 * page_width)]  # type: ignore[index]
    c2_2 = [e for e in narrow_elements if _extract_bbox(e)[0] >= (mid_x - 0.05 * page_width)]  # type: ignore[index]

    is_two_col = len(c1_2) >= 2 and len(c2_2) >= 2

    if not is_three_col and not is_two_col:
        return sorted(body_elements, key=_top_left_key)

    full_width = [
        e for e in elements_with_bbox if (_extract_bbox(e)[2] - _extract_bbox(e)[0]) >= (0.75 * page_width)  # type: ignore[index]
    ]
    full_width.sort(key=_top_left_key)

    ordered: list[Any] = []
    seen_ids: set[int] = set()
    prev_top = -1.0

    def partition_and_append(segment: list[Any]) -> None:
        if is_three_col:
            s1 = [e for e in segment if (_extract_bbox(e)[0] + _extract_bbox(e)[2]) / 2.0 < third_1]  # type: ignore[index]
            s2 = [e for e in segment if third_1 <= (_extract_bbox(e)[0] + _extract_bbox(e)[2]) / 2.0 < third_2]  # type: ignore[index]
            s3 = [e for e in segment if (_extract_bbox(e)[0] + _extract_bbox(e)[2]) / 2.0 >= third_2]  # type: ignore[index]
            s1.sort(key=lambda e: (_extract_bbox(e)[1], _extract_bbox(e)[0]))  # type: ignore[index]
            s2.sort(key=lambda e: (_extract_bbox(e)[1], _extract_bbox(e)[0]))  # type: ignore[index]
            s3.sort(key=lambda e: (_extract_bbox(e)[1], _extract_bbox(e)[0]))  # type: ignore[index]
            for col in (s1, s2, s3):
                for el in col:
                    ordered.append(el)
                    seen_ids.add(id(el))
        else:
            s1 = [e for e in segment if (_extract_bbox(e)[0] + _extract_bbox(e)[2]) / 2.0 < mid_x]  # type: ignore[index]
            s2 = [e for e in segment if (_extract_bbox(e)[0] + _extract_bbox(e)[2]) / 2.0 >= mid_x]  # type: ignore[index]
            s1.sort(key=lambda e: (_extract_bbox(e)[1], _extract_bbox(e)[0]))  # type: ignore[index]
            s2.sort(key=lambda e: (_extract_bbox(e)[1], _extract_bbox(e)[0]))  # type: ignore[index]
            for col in (s1, s2):
                for el in col:
                    ordered.append(el)
                    seen_ids.add(id(el))

    for fw in full_width:
        fw_top = _extract_bbox(fw)[1]  # type: ignore[index]
        segment = [
            e for e in narrow_elements
            if prev_top < _extract_bbox(e)[1] < fw_top and id(e) not in seen_ids  # type: ignore[index]
        ]
        partition_and_append(segment)
        ordered.append(fw)
        seen_ids.add(id(fw))
        prev_top = _extract_bbox(fw)[3]  # type: ignore[index]

    remainder = [
        e for e in narrow_elements
        if _extract_bbox(e)[1] > prev_top and id(e) not in seen_ids  # type: ignore[index]
    ]
    partition_and_append(remainder)

    # Any elements without bbox or unassigned
    for e in body_elements:
        if id(e) not in seen_ids:
            ordered.append(e)
            seen_ids.add(id(e))

    return ordered


def refine_reading_order(blocks: list[Any]) -> list[Any]:
    """Refine document blocks with column-aware gutter partitioning and marginals isolation.

    - Isolates headers at page tops and footers/page numbers at page bottoms.
    - Detects 2- and 3-column layouts and orders blocks column-by-column (top-to-bottom).
    - Preserves full-width banners as section dividers.
    - Handles multiple pages independently, preserving document-level root elements at index 0.
    """
    if not blocks:
        return blocks

    by_page: dict[int | None, list[Any]] = {}
    for block in blocks:
        page = _extract_page(block)
        by_page.setdefault(page, []).append(block)

    refined: list[Any] = []

    # Sort pages: document-level containers (None) come first
    for page_no, page_blocks in sorted(
        by_page.items(),
        key=lambda pair: (0 if pair[0] is None else 1, pair[0] or 0),
    ):
        if page_no is None or len(page_blocks) <= 1:
            refined.extend(page_blocks)
            continue

        headers: list[Any] = []
        footers: list[Any] = []
        body: list[Any] = []

        for b in page_blocks:
            b_type = _extract_type(b)
            if b_type in _HEADER_TYPES:
                headers.append(b)
            elif b_type in _FOOTER_TYPES:
                footers.append(b)
            else:
                body.append(b)

        headers.sort(key=_top_left_key)
        footers.sort(key=_top_left_key)

        ordered_body = _order_body_columns(body)
        refined.extend(headers)
        refined.extend(ordered_body)
        refined.extend(footers)

    return refined
