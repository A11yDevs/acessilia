"""Page-number rules (docstruct.fusion.noise), moved from the core's PDDL payload (#402).

The core covers them end to end in tests/test_page_number_furniture.py; here
they are checked on plain values, with the constants ``decor_role`` shares.
"""

from __future__ import annotations

import pytest

from docstruct.fusion.noise import (
    PAGE_NUMBER_MARGIN,
    PAGE_NUMBER_MAX_LEN,
    decor_role,
    is_decorated_page_number,
    is_page_number_in_margin,
    select_page_numbers,
)
from docstruct.fusion.types import DiffBlock


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("5", True), (" - 7 - ", True), ("5.", True), ("Page 12", True), ("281 281", True),
        ("iv", True), ("XII", True),
        ("mid", False), ("abc", False), ("", False), ("5 6", False),
        ("Chapter 3: Motion 12", False),
    ],
)
def test_a_decorated_page_number(text, expected) -> None:
    assert is_decorated_page_number(text) is expected


def test_a_decoration_longer_than_the_limit_is_not_a_page_number() -> None:
    padded = "Page" + " " * (PAGE_NUMBER_MAX_LEN - 5) + "5"
    assert len(padded) == PAGE_NUMBER_MAX_LEN and is_decorated_page_number(padded)
    assert not is_decorated_page_number("Page" + " " * (PAGE_NUMBER_MAX_LEN - 4) + "5")


def _box(center: float) -> tuple[float, float, float, float]:
    return (0.4, center - 0.01, 0.6, center + 0.01)


@pytest.mark.parametrize(
    ("text", "box", "expected"),
    [
        ("7", _box(0.95), True),
        ("7", _box(0.05), True),
        ("7", _box(0.5), False),
        ("7", _box(PAGE_NUMBER_MARGIN), False),
        ("7", _box(1 - PAGE_NUMBER_MARGIN), False),
        ("iv", _box(0.95), True),
        ("V", _box(0.95), False),
        ("Page 7", _box(0.95), False),
        ("7", None, False),
        (None, _box(0.95), False),
    ],
)
def test_a_bare_number_in_the_margin(text, box, expected) -> None:
    assert is_page_number_in_margin(text, box) is expected


def test_marked_candidates_are_page_numbers_and_a_page_has_one() -> None:
    candidates = [
        ("marked", 1, True),
        ("beside-marked", 1, False),
        ("alone", 2, False),
        ("first", 3, False),
        ("second", 3, False),
    ]

    assert select_page_numbers(candidates) == {"marked", "alone"}


def test_no_candidates_no_page_numbers() -> None:
    assert select_page_numbers([]) == set()


def test_decor_role_reads_the_same_margin_and_length() -> None:
    def block(md: str, center: float) -> DiffBlock:
        return DiffBlock(kind="text", md=md, text=md, box=_box(center), type="text")

    assert decor_role(block("12", 0.95)) == "page_number"
    assert decor_role(block("12", 0.5)) is None
    assert decor_role(block("Page" + " " * PAGE_NUMBER_MAX_LEN + "1", 0.95)) is None
