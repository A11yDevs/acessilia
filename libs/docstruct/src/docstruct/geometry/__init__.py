"""Geometry primitives and reading order algorithms for docstruct."""
from __future__ import annotations

from docstruct.geometry.reading_order import refine_reading_order
from docstruct.types import BBox


def content_fingerprint(text: str) -> int:
    """Stable text fingerprint: lowercase + whitespace collapse."""
    return hash(" ".join(text.lower().split()))


def overlaps_clean(
    bbox: BBox,
    clean_bboxes: list[BBox],
    threshold: float = 0.3,
) -> bool:
    """True if ``bbox`` intersects any clean bbox above ``threshold``."""
    x0, y0, x1, y1 = bbox
    area = max((x1 - x0) * (y1 - y0), 1)
    for cb in clean_bboxes:
        ox0, oy0 = max(x0, cb[0]), max(y0, cb[1])
        ox1, oy1 = min(x1, cb[2]), min(y1, cb[3])
        if ox0 < ox1 and oy0 < oy1 and ((ox1 - ox0) * (oy1 - oy0)) / area >= threshold:
            return True
    return False


def merge_bboxes(bboxes: list[BBox], vertical_gap: float = 5.0) -> list[BBox]:
    """Group vertically proximate bounding boxes into bands."""
    if not bboxes:
        return []
    sorted_b = sorted(bboxes, key=lambda b: (b[1], b[0]))
    merged: list[list[float]] = [list(sorted_b[0])]
    for b in sorted_b[1:]:
        if b[1] <= merged[-1][3] + vertical_gap:
            merged[-1][2] = max(merged[-1][2], b[2])
            merged[-1][3] = max(merged[-1][3], b[3])
        else:
            merged.append(list(b))
    return [(b[0], b[1], b[2], b[3]) for b in merged]


def union(a: BBox, b: BBox) -> BBox:
    """Smallest bounding box containing both a and b."""
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def intersection_area(a: BBox, b: BBox) -> float:
    """Intersection area between two bounding boxes."""
    ox0, oy0 = max(a[0], b[0]), max(a[1], b[1])
    ox1, oy1 = min(a[2], b[2]), min(a[3], b[3])
    if ox0 >= ox1 or oy0 >= oy1:
        return 0.0
    return (ox1 - ox0) * (oy1 - oy0)


__all__ = [
    "content_fingerprint",
    "intersection_area",
    "merge_bboxes",
    "overlaps_clean",
    "refine_reading_order",
    "union",
]
