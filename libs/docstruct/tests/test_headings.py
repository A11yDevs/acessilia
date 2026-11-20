"""Tests for heading-hierarchy gap detection and deterministic repair."""
from __future__ import annotations

import pytest

from docstruct.sections import HeadingGap, find_heading_gaps, repair_heading_levels


def test_find_heading_gaps_accepts_valid_sequences():
    assert find_heading_gaps([]) == []
    assert find_heading_gaps([1]) == []
    assert find_heading_gaps([1, 2, 3, 2, 3, 4, 5, 6, 2]) == []


def test_find_heading_gaps_reports_each_invalid_transition():
    assert find_heading_gaps([2, 4, 1, 3]) == [
        HeadingGap(index=0, previous_level=0, current_level=2),
        HeadingGap(index=1, previous_level=2, current_level=4),
        HeadingGap(index=2, previous_level=4, current_level=1),
        HeadingGap(index=3, previous_level=1, current_level=3),
    ]


def test_find_heading_gaps_rejects_levels_above_six():
    assert find_heading_gaps([1, 2, 3, 4, 5, 6, 7]) == [
        HeadingGap(index=6, previous_level=6, current_level=7),
    ]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ([], []),
        ([3], [1]),
        ([1, 2, 3], [1, 2, 3]),
        ([2, 4, 1, 5], [1, 2, 2, 3]),
        ([1, 2, 3, 4, 5, 6, 7, 8], [1, 2, 3, 4, 5, 6, 6, 6]),
        ([0, 0, 4], [1, 2, 3]),
    ],
)
def test_repair_heading_levels(raw: list[int], expected: list[int]):
    repaired = repair_heading_levels(raw)
    assert repaired == expected
    assert find_heading_gaps(repaired) == []
