"""OrientedBox keeps the origin of its y axis through every conversion."""
import pytest

from docstruct.geometry import OrientedBox, is_bottom_left


@pytest.mark.parametrize(
    ("origin", "top", "bottom", "expected"),
    [
        ("BOTTOMLEFT", 10.0, 20.0, True),
        ("bottomleft", 10.0, 20.0, True),
        ("TOPLEFT", 20.0, 10.0, False),
        ("UNKNOWN", 20.0, 10.0, True),
        ("UNKNOWN", 10.0, 20.0, False),
        ("UNKNOWN", 10.0, 10.0, False),
        (None, 20.0, 10.0, True),
        ("", 10.0, 20.0, False),
    ],
)
def test_is_bottom_left(origin, top, bottom, expected):
    assert is_bottom_left(origin, top, bottom) is expected


# The same box on a 600 x 800 page, stored in each frame.
TOP_LEFT = OrientedBox(60, 80, 300, 160, "TOPLEFT")
BOTTOM_LEFT = OrientedBox(60, 720, 300, 640, "BOTTOMLEFT")
UNKNOWN_UP = OrientedBox(60, 720, 300, 640, "UNKNOWN")
UNKNOWN_DOWN = OrientedBox(60, 80, 300, 160)


def test_top_down_mirrors_bottom_left_boxes():
    assert TOP_LEFT.top_down() == (60, 80, 300, 160)
    assert UNKNOWN_DOWN.top_down() == (60, 80, 300, 160)
    assert BOTTOM_LEFT.top_down() == (60, -720, 300, -640)
    assert UNKNOWN_UP.top_down() == (60, -720, 300, -640)


def test_top_down_keeps_the_vertical_order_of_boxes():
    higher = OrientedBox(0, 700, 10, 690, "BOTTOMLEFT").top_down()
    lower = OrientedBox(0, 100, 10, 90, "BOTTOMLEFT").top_down()
    assert higher[1] < lower[1]


@pytest.mark.parametrize("box", [TOP_LEFT, BOTTOM_LEFT, UNKNOWN_UP, UNKNOWN_DOWN])
def test_page_fractions_agree_in_every_frame(box):
    assert box.page_fractions(600.0, 800.0) == pytest.approx((0.1, 0.1, 0.5, 0.2))


@pytest.mark.parametrize("size", [(None, 800.0), (600.0, None), (0.0, 800.0), (600.0, 0.0)])
def test_page_fractions_need_a_page_size(size):
    assert TOP_LEFT.page_fractions(*size) is None


def test_boxes_are_values():
    assert OrientedBox(1, 2, 3, 4, "TOPLEFT") == OrientedBox(1, 2, 3, 4, "TOPLEFT")
    with pytest.raises(AttributeError):
        TOP_LEFT.left = 0  # type: ignore[misc]


# --- boxes_overlap and union_area, moved from the core's slide layout (#470) ---

from docstruct.geometry.boxes import boxes_overlap, union_area  # noqa: E402


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((0, 0, 10, 10), (5, 5, 15, 15), True),
        ((0, 0, 10, 10), (10, 0, 20, 10), False),  # a shared edge is no overlap
        ((0, 0, 10, 10), (10, 10, 20, 20), False),  # nor a shared corner
        ((0, 0, 10, 10), (2, 2, 3, 3), True),  # one inside the other
        ((0, 0, 10, 10), (20, 20, 30, 30), False),
    ],
)
def test_boxes_overlap_only_when_they_share_an_area(first, second, expected):
    assert boxes_overlap(first, second) is expected
    assert boxes_overlap(second, first) is expected


@pytest.mark.parametrize(
    ("boxes", "expected"),
    [
        ([], 0.0),
        ([(0, 0, 10, 10)], 100.0),
        ([(0, 0, 10, 10), (0, 0, 10, 10)], 100.0),  # the same box counts once
        ([(0, 0, 10, 10), (5, 5, 15, 15)], 175.0),  # 100 + 100 - 25
        ([(0, 0, 10, 10), (20, 0, 30, 10)], 200.0),  # apart
        ([(0, 0, 10, 10), (2, 2, 3, 3)], 100.0),  # one inside the other
        ([(0, 0, 10, 0)], 0.0),  # no height
    ],
)
def test_union_area_counts_overlaps_once(boxes, expected):
    assert union_area(boxes) == pytest.approx(expected)


def test_union_area_matches_a_grid_count_on_integer_boxes():
    """An independent oracle: count the unit cells some box covers."""
    import random

    generator = random.Random(470)
    for _ in range(300):
        boxes = []
        for _ in range(generator.randint(1, 5)):
            left, top = generator.randint(0, 20), generator.randint(0, 20)
            boxes.append((left, top, left + generator.randint(0, 8), top + generator.randint(0, 8)))
        cells = {
            (x, y)
            for left, top, right, bottom in boxes
            for x in range(left, right)
            for y in range(top, bottom)
        }
        assert union_area(boxes) == pytest.approx(len(cells)), boxes


def test_union_area_counts_negative_coordinates():
    """The sweep starts below every box, not at 0 (review of #596)."""
    assert union_area([(0, -5, 10, 5)]) == pytest.approx(100.0)
    assert union_area([(0, -20, 10, -10), (5, -15, 15, -5)]) == pytest.approx(175.0)


# --- spatial box helpers (#612) ---

from docstruct.geometry.boxes import (  # noqa: E402
    box_contains_center,
    box_distance,
    boxes_side_by_side,
    expand_box,
    spans_horizontally,
)


def test_expand_box_grows_all_four_edges():
    assert expand_box((1.0, 2.0, 3.0, 4.0), 0.5) == pytest.approx((0.5, 1.5, 3.5, 4.5))
    assert expand_box((1.0, 2.0, 3.0, 4.0), 0.0) == pytest.approx((1.0, 2.0, 3.0, 4.0))


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((0.0, 0.0, 10.0, 5.0), (5.0, 20.0, 15.0, 25.0), True),
        ((0.0, 0.0, 10.0, 5.0), (10.0, 0.0, 20.0, 5.0), False),  # touching edge
        ((0.0, 0.0, 10.0, 5.0), (12.0, 0.0, 20.0, 5.0), False),
    ],
)
def test_spans_horizontally(first, second, expected):
    assert spans_horizontally(first, second) is expected
    assert spans_horizontally(second, first) is expected


@pytest.mark.parametrize(
    ("boxes", "expected"),
    [
        ([], False),
        ([(0.0, 10.0, 5.0, 20.0)], True),
        ([(0.0, 10.0, 5.0, 20.0), (10.0, 15.0, 15.0, 25.0)], True),
        ([(0.0, 10.0, 5.0, 20.0), (10.0, 20.0, 15.0, 30.0)], False),  # touching edge
        ([(0.0, 10.0, 5.0, 20.0), (10.0, 25.0, 15.0, 35.0)], False),
    ],
)
def test_boxes_side_by_side(boxes, expected):
    assert boxes_side_by_side(boxes) is expected


@pytest.mark.parametrize(
    ("first", "second", "expected"),
    [
        ((0.0, 0.0, 10.0, 10.0), (5.0, 5.0, 15.0, 15.0), 0.0),
        ((0.0, 0.0, 10.0, 10.0), (10.0, 0.0, 20.0, 10.0), 0.0),
        ((0.0, 0.0, 10.0, 10.0), (13.0, 0.0, 20.0, 10.0), 3.0),
        ((0.0, 0.0, 10.0, 10.0), (0.0, 14.0, 10.0, 20.0), 4.0),
        ((0.0, 0.0, 10.0, 10.0), (13.0, 14.0, 20.0, 20.0), 7.0),
    ],
)
def test_box_distance(first, second, expected):
    assert box_distance(first, second) == pytest.approx(expected)
    assert box_distance(second, first) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("container", "inner", "expected"),
    [
        ((0.0, 0.0, 10.0, 10.0), (2.0, 2.0, 4.0, 4.0), True),
        ((0.0, 0.0, 10.0, 10.0), (8.0, 8.0, 12.0, 12.0), True),  # centre (10, 10) on edge
        ((0.0, 0.0, 10.0, 10.0), (9.0, 9.0, 13.0, 13.0), False),  # centre (11, 11) outside
    ],
)
def test_box_contains_center(container, inner, expected):
    assert box_contains_center(container, inner) is expected


def test_union_area_of_a_bottom_left_box_seen_top_down():
    """``top_down()`` mirrors a bottom-left box to negative y; its area holds."""
    box = OrientedBox(0, 700, 10, 690, "BOTTOMLEFT").top_down()

    assert union_area([box]) == pytest.approx(100.0)
