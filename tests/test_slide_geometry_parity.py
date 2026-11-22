"""The slide layout's box geometry moved to docstruct without a change (#470).

``manifest/slides.py`` kept ``_overlaps``, ``_area`` and ``_union_area``; it
now uses ``docstruct.geometry.boxes.boxes_overlap``, ``union_area`` and
``docstruct.fusion.similarity.area``. The reference copies below are those
functions as they were on develop at 6844590e, frozen here so the equivalence
stays checked (review of #596). They live in ``tests/``, which the bridges
guard (``test_docstruct_bridges.py``) does not scan as core code.

The comparison covers the slide layout's domain, boxes in page fractions or
page points, all >= 0, including zero-width and reversed boxes. Below 0 the
two differ on purpose: docstruct's ``union_area`` counts what the old sweep,
starting at 0, left out.
"""

from __future__ import annotations

import random
from itertools import pairwise

import pytest

from docstruct.fusion.similarity import area
from docstruct.geometry.boxes import boxes_overlap, union_area

Box = tuple[float, float, float, float]


def _reference_overlaps(first: Box, second: Box) -> bool:
    return (
        min(first[2], second[2]) > max(first[0], second[0])
        and min(first[3], second[3]) > max(first[1], second[1])
    )


def _reference_area(box: Box) -> float:
    left, top, right, bottom = box
    return max(0.0, right - left) * max(0.0, bottom - top)


def _reference_union_area(boxes: list[Box]) -> float:
    xs = sorted({x for box in boxes for x in (box[0], box[2])})
    total = 0.0
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
        total += (right - left) * covered
    return total


def _box(generator: random.Random, scale: float) -> Box:
    left, top = generator.uniform(0, scale), generator.uniform(0, scale)
    kind = generator.random()
    if kind < 0.1:  # no width
        return (left, top, left, top + generator.uniform(0, scale / 10))
    if kind < 0.15:  # reversed
        return (left, top, left - generator.uniform(0, scale / 100), top)
    return (left, top, left + generator.uniform(0, scale / 2), top + generator.uniform(0, scale / 2))


@pytest.mark.parametrize("scale", [1.0, 800.0], ids=["page fractions", "page points"])
def test_the_moved_geometry_matches_the_slide_layouts_copy(scale: float) -> None:
    generator = random.Random(470)
    seen = {"overlap": 0, "apart": 0, "zero area": 0, "overlapping union": 0}
    for _ in range(5000):
        first, second = _box(generator, scale), _box(generator, scale)
        assert boxes_overlap(first, second) == _reference_overlaps(first, second), (first, second)
        assert area(first) == _reference_area(first), first
        boxes = [_box(generator, scale) for _ in range(generator.randint(0, 6))]
        assert union_area(boxes) == _reference_union_area(boxes), boxes

        seen["overlap" if boxes_overlap(first, second) else "apart"] += 1
        seen["zero area"] += area(first) == 0
        seen["overlapping union"] += any(
            boxes_overlap(a, b) for index, a in enumerate(boxes) for b in boxes[index + 1:]
        )
    # Both sides of every branch were exercised.
    assert all(count > 100 for count in seen.values()), seen


def test_below_zero_docstruct_counts_what_the_old_sweep_left_out() -> None:
    boxes = [(0.0, -5.0, 10.0, 5.0)]

    assert _reference_union_area(boxes) == pytest.approx(50.0)
    assert union_area(boxes) == pytest.approx(100.0)
