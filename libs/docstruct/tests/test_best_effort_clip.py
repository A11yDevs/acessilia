"""Best-effort crop regions (docstruct.geometry.boxes.best_effort_clip).

Moved from the core's PDDL payload (#402); the core covers the render
fallbacks around it in tests/test_picture_bytes_policy.py.
"""

from __future__ import annotations

import math

import pytest

from docstruct.geometry.boxes import OrientedBox, best_effort_clip


@pytest.mark.parametrize(
    ("box", "expected"),
    [
        (OrientedBox(1, 700, 2, 600, "BOTTOMLEFT"), ((1.0, 700.0, 2.0, 600.0), "BOTTOMLEFT")),
        (OrientedBox(1, 20, 2, 220, "TOPLEFT"), ((1.0, 20.0, 2.0, 220.0), "TOPLEFT")),
        (OrientedBox(1, 700, 2, 600, "UNKNOWN"), ((1.0, 700.0, 2.0, 600.0), "BOTTOMLEFT")),
        (OrientedBox(1, 20, 2, 220, None), ((1.0, 20.0, 2.0, 220.0), "TOPLEFT")),
        (OrientedBox(1, 20, 2, 20, "UNKNOWN"), ((1.0, 20.0, 2.0, 20.0), "TOPLEFT")),
    ],
)
def test_the_box_is_kept_with_its_origin(box, expected) -> None:
    clip, origin = best_effort_clip(box)

    assert (clip, origin) == expected
    assert all(isinstance(value, float) for value in clip)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_a_non_finite_box_is_the_whole_page(value) -> None:
    assert best_effort_clip(OrientedBox(1, 2, value, 4, "TOPLEFT")) == (None, "TOPLEFT")


def test_no_box_is_the_whole_page() -> None:
    assert best_effort_clip(None) == (None, "TOPLEFT")
