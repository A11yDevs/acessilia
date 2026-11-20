"""Tests for skeleton-guided reading order reconstruction."""
from __future__ import annotations

from docstruct.fusion import skeleton_reading_order


def test_returns_none_when_fewer_than_two_items_or_insufficient_matches():
    assert skeleton_reading_order(0, {}) is None
    assert skeleton_reading_order(1, {0: 0}) is None
    assert skeleton_reading_order(4, {0: 2}) is None  # 0.25 < 0.5


def test_reorders_matched_items_by_skeleton_position():
    assert skeleton_reading_order(3, {0: 2, 1: 0, 2: 1}) == [1, 2, 0]


def test_unpaired_items_stay_after_preceding_paired_item_or_at_start():
    # Index 0 is unpaired before any match -> stays at the front (last=-1.0).
    # Index 2 is unpaired after index 1 (matched at 5) -> follows index 1.
    # Index 3 is matched at 1 -> moves before index 1.
    assert skeleton_reading_order(4, {1: 5, 3: 1}) == [0, 3, 1, 2]


def test_ignores_out_of_range_indices_and_respects_custom_threshold():
    assert skeleton_reading_order(4, {0: 2, 1: 0, 99: 1, -1: 3}) == [1, 2, 3, 0]
    assert skeleton_reading_order(4, {0: 2, 1: 0}, min_match_ratio=0.75) is None
    assert skeleton_reading_order(4, {0: 2, 1: 0, 2: 1}, min_match_ratio=0.75) == [1, 2, 3, 0]
