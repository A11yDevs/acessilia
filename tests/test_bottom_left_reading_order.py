"""Reading-order refinement must honour boxes whose y axis grows upwards.

Staging regression: Docling/Toolbox boxes for `001.pdf` use a bottom-left origin
(`top` > `bottom`). `_refine_reading_order` sorted them by `top` ascending as if
y grew downwards, so every page came out bottom to top, footers aside.
"""

import pytest

from backend.core.manifest.builder import (
    _normalized_element_bbox,
    _refine_reading_order,
)
from backend.core.manifest.models import BoundingBox, ManifestElement, Provenance

PAGE_HEIGHT = 842.0

#: Page 1 of tests/dataset/input/001.pdf in the Toolbox order, with the boxes of
#: the staging canonical document: (n, type, raw_label, left, top, right, bottom).
PAGE_1 = [
    (1, "paragraph", "text", 56.0, 735.27, 108.40, 723.82),
    (2, "heading", "section_header", 56.0, 717.15, 345.90, 662.10),
    (3, "paragraph", "text", 56.0, 575.95, 385.67, 564.61),
    (4, "paragraph", "text", 73.29, 549.30, 272.80, 537.96),
    (5, "list_item", "list_item", 79.05, 522.66, 271.22, 511.32),
    (6, "list_item", "list_item", 79.05, 505.37, 262.27, 494.03),
    (7, "list_item", "list_item", 79.05, 488.08, 269.29, 476.74),
    (8, "list_item", "list_item", 79.05, 470.80, 295.28, 459.46),
    (9, "heading", "section_header", 56.0, 433.32, 231.91, 418.43),
    (10, "paragraph", "text", 73.29, 405.26, 482.23, 393.63),
    (11, "code", "code", 56.0, 378.94, 217.47, 316.95),
    (12, "paragraph", "text", 56.0, 302.98, 539.14, 239.79),
    (13, "code", "code", 56.0, 226.25, 302.95, 67.03),
    (14, "paragraph", "page_footer", 330.69, 41.53, 513.34, 32.94),
    (15, "paragraph", "page_footer", 524.86, 41.53, 539.28, 32.94),
]


def _element(n, element_type, raw_label, box, origin, reading_order=None):
    left, top, right, bottom = box
    return ManifestElement(
        id=f"element-{n:06d}",
        type=element_type,
        raw_label=raw_label,
        reading_order=reading_order or n,
        hierarchy_level=1,
        page_number=1,
        text=f"texto {n}",
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=left, top=top, right=right, bottom=bottom,
                    coord_origin=origin,
                ),
            )
        ],
    )


def _page(rows, origin, *, flip=False, shuffle=False):
    elements = []
    for index, (n, element_type, raw_label, left, top, right, bottom) in enumerate(rows):
        if flip:  # same page in top-left coordinates
            top, bottom = PAGE_HEIGHT - top, PAGE_HEIGHT - bottom
        reading_order = len(rows) - index if shuffle else n
        elements.append(
            _element(
                n, element_type, raw_label, (left, top, right, bottom), origin,
                reading_order=reading_order,
            )
        )
    return elements


def _order(elements):
    return [int(element.id[-6:]) for element in _refine_reading_order(elements)]


@pytest.mark.parametrize("origin", ["BOTTOMLEFT", "UNKNOWN"])
def test_bottom_left_page_reads_top_to_bottom(origin):
    assert _order(_page(PAGE_1, origin)) == list(range(1, 16))


@pytest.mark.parametrize("origin", ["TOPLEFT", "UNKNOWN"])
def test_top_left_page_is_unchanged(origin):
    assert _order(_page(PAGE_1, origin, flip=True)) == list(range(1, 16))


@pytest.mark.parametrize("origin", ["BOTTOMLEFT", "TOPLEFT"])
def test_geometry_wins_over_a_reversed_incoming_order(origin):
    # The refinement must rebuild the order from the boxes, not keep the input.
    page = _page(PAGE_1, origin, flip=origin == "TOPLEFT", shuffle=True)
    assert _order(page) == list(range(1, 16))


@pytest.mark.parametrize("origin", ["BOTTOMLEFT", "UNKNOWN"])
def test_bottom_left_two_columns_read_column_by_column(origin):
    # Two columns of three blocks each, plus a full-width title on top.
    rows = [(1, "heading", "section_header", 56.0, 800.0, 539.0, 780.0)]
    n = 2
    for left, right in ((56.0, 280.0), (315.0, 539.0)):
        for top in (740.0, 600.0, 460.0):
            rows.append((n, "paragraph", "text", left, top, right, top - 120.0))
            n += 1
    assert _order(_page(rows, origin)) == list(range(1, 8))


@pytest.mark.parametrize("origin", ["BOTTOMLEFT", "UNKNOWN"])
def test_normalized_bbox_converts_bottom_left_once(origin):
    element = _element(1, "paragraph", "text", (56.0, 735.27, 108.40, 723.82), origin)

    left, top, right, bottom = _normalized_element_bbox(
        element, {1: (595.0, PAGE_HEIGHT)}
    )

    assert top == pytest.approx((PAGE_HEIGHT - 735.27) / PAGE_HEIGHT)
    assert bottom == pytest.approx((PAGE_HEIGHT - 723.82) / PAGE_HEIGHT)
    assert top < bottom
    assert (left, right) == pytest.approx((56.0 / 595.0, 108.40 / 595.0))


def test_normalized_bbox_keeps_top_left_boxes():
    element = _element(1, "paragraph", "text", (56.0, 106.73, 108.40, 118.18), "TOPLEFT")

    _, top, _, bottom = _normalized_element_bbox(element, {1: (595.0, PAGE_HEIGHT)})

    assert top == pytest.approx(106.73 / PAGE_HEIGHT)
    assert bottom == pytest.approx(118.18 / PAGE_HEIGHT)
