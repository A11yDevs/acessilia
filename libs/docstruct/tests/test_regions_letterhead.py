"""Letterheads (docstruct.regions.letterhead), moved from the core's PDDL payload (#402).

The core covers them end to end with case 036's boxes
(tests/test_letterhead_header.py); here the rules run on unit-page boxes.
"""

from __future__ import annotations

import pytest

from docstruct.regions.letterhead import (
    LETTERHEAD_MAX_GAP,
    LETTERHEAD_MAX_HEIGHT,
    LETTERHEAD_TOLERANCE,
    PlacedItem,
    is_beside,
    is_logo_sized,
    letterhead_groups,
)

LOGO = (0.10, 0.05, 0.20, 0.10)


def _item(item_id: str, box, order: int = 1, page: int = 1) -> PlacedItem:
    return PlacedItem(item_id, page, order, box)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ((0.21, 0.06, 0.50, 0.08), True),
        ((0.20 + LETTERHEAD_MAX_GAP, 0.06, 0.50, 0.08), True),
        ((0.20 + LETTERHEAD_MAX_GAP + 0.01, 0.06, 0.50, 0.08), False),
        ((0.21, 0.10 + LETTERHEAD_TOLERANCE, 0.50, 0.12), True),
        ((0.21, 0.10 + LETTERHEAD_TOLERANCE + 0.01, 0.50, 0.12), False),
        ((0.00, 0.06, 0.09, 0.08), True),
    ],
    ids=["right", "gap-limit", "too-far", "tolerance", "below", "left"],
)
def test_a_line_beside_a_picture(line, expected) -> None:
    assert is_beside(LOGO, line) is expected


def test_only_a_short_picture_is_a_logo() -> None:
    assert is_logo_sized((0.1, 0.0, 0.2, LETTERHEAD_MAX_HEIGHT))
    assert not is_logo_sized((0.1, 0.0, 0.2, LETTERHEAD_MAX_HEIGHT + 0.01))


def test_a_logo_and_its_lines_are_one_group_in_reading_order() -> None:
    groups = letterhead_groups(
        [_item("logo", LOGO, 2)],
        [_item("line-1", (0.21, 0.05, 0.4, 0.07), 1), _item("line-2", (0.21, 0.08, 0.4, 0.10), 3)],
    )

    assert groups == {"line-1": ["line-1", "logo", "line-2"]}


def test_two_logos_sharing_a_line_form_one_group() -> None:
    groups = letterhead_groups(
        [_item("a", (0.05, 0.05, 0.20, 0.10), 1), _item("b", (0.45, 0.05, 0.60, 0.10), 3)],
        [_item("shared", (0.22, 0.06, 0.43, 0.08), 2)],
    )

    assert groups == {"a": ["a", "shared", "b"]}


def test_two_institutions_stay_apart() -> None:
    groups = letterhead_groups(
        [_item("a", (0.05, 0.05, 0.15, 0.10), 1), _item("b", (0.60, 0.05, 0.70, 0.10), 3)],
        [_item("la", (0.16, 0.06, 0.30, 0.08), 2), _item("lb", (0.71, 0.06, 0.90, 0.08), 4)],
    )

    assert groups == {"a": ["a", "la"], "b": ["b", "lb"]}


@pytest.mark.parametrize(
    ("pictures", "lines"),
    [
        pytest.param([_item("tall", (0.1, 0.0, 0.2, 0.5))], [_item("l", (0.21, 0.1, 0.4, 0.12))],
                     id="tall-picture"),
        pytest.param([_item("logo", LOGO)], [], id="no-line"),
        pytest.param([], [_item("l", (0.21, 0.06, 0.4, 0.08))], id="no-picture"),
        pytest.param([_item("logo", LOGO, page=1)], [_item("l", (0.21, 0.06, 0.4, 0.08), page=2)],
                     id="other-page"),
    ],
)
def test_no_group_without_a_logo_and_a_line_beside_it(pictures, lines) -> None:
    assert letterhead_groups(pictures, lines) == {}


def test_reading_order_ties_keep_the_given_order() -> None:
    groups = letterhead_groups(
        [_item("logo", LOGO, 1)],
        [_item("z-line", (0.21, 0.05, 0.4, 0.07), 1), _item("a-line", (0.21, 0.08, 0.4, 0.10), 1)],
    )

    assert groups == {"logo": ["logo", "z-line", "a-line"]}
