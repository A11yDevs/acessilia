"""Tests for the OrderAdjudicationAgent (Agno tools over the reading-order stack).

Dr.DocBench PR #125. The deterministic ``process_*`` methods are exercised
directly so the tests run without Agno installed.
"""
from __future__ import annotations

from backend.core.agents.order_adjudication_agent import (
    OrderAdjudicationAgent,
    complete_order,
    kendall_tau,
    parse_order,
)


def agent() -> OrderAdjudicationAgent:
    return OrderAdjudicationAgent()


class TestParseOrder:
    def test_numbers_become_zero_based(self):
        assert parse_order("1, 2, 3", 3) == [0, 1, 2]

    def test_order_is_preserved(self):
        assert parse_order("3, 1, 2", 3) == [2, 0, 1]

    def test_duplicates_are_dropped(self):
        assert parse_order("1, 1, 2", 3) == [0, 1]

    def test_out_of_range_is_dropped(self):
        assert parse_order("1, 9, 2", 3) == [0, 1]

    def test_zero_is_dropped(self):
        assert parse_order("0, 1, 2", 3) == [0, 1]

    def test_empty_answer(self):
        assert parse_order("", 3) == []

    def test_none_answer(self):
        assert parse_order(None, 3) == []

    def test_extra_text_is_ignored(self):
        assert parse_order("The order is: 2, 1, 3.", 3) == [1, 0, 2]


class TestKendallTau:
    def test_identical_orders(self):
        assert kendall_tau([0, 1, 2], [0, 1, 2]) == 1.0

    def test_reversed_orders(self):
        assert kendall_tau([2, 1, 0], [0, 1, 2]) == -1.0

    def test_single_item(self):
        assert kendall_tau([0], [0]) == 1.0

    def test_empty(self):
        assert kendall_tau([], []) == 1.0

    def test_partial_agreement(self):
        assert -1.0 < kendall_tau([0, 2, 1], [0, 1, 2]) < 1.0


class TestCompleteOrder:
    def test_missing_blocks_are_appended_in_skeleton_order(self):
        assert complete_order([2], 3) == [2, 0, 1]

    def test_complete_order_is_unchanged(self):
        assert complete_order([0, 1, 2], 3) == [0, 1, 2]

    def test_empty_permutation(self):
        assert complete_order([], 3) == [0, 1, 2]


class TestAdjudicateOrder:
    def test_low_cover_is_rejected(self):
        out = agent().adjudicate_order("1", 3, [0, 1, 2])
        assert out["status"] == "low-cover"
        assert out["vlm"] is None

    def test_identity_permutation_matches_the_skeleton(self):
        out = agent().adjudicate_order("1, 2, 3", 3, [0, 1, 2])
        assert out["status"] == "vlm=skeleton"
        assert out["vlm"] is None

    def test_reorder_is_reported(self):
        out = agent().adjudicate_order("2, 1, 3", 3, [0, 1, 2])
        assert out["status"] == "vlm-reorder"
        assert out["vlm"] == [1, 0, 2]

    def test_sel_picks_xy_when_closer_to_the_vlm(self):
        # VLM says [2,1,0]; xy is [2,1,0] (tau 1.0) vs skeleton [0,1,2] (tau -1.0)
        out = agent().adjudicate_order("3, 2, 1", 3, [2, 1, 0])
        assert out["sel"] == [2, 1, 0]

    def test_sel_is_none_when_the_skeleton_wins(self):
        # VLM says [1,0,2]; skeleton [0,1,2] is closer than xy [2,1,0]
        out = agent().adjudicate_order("2, 1, 3", 3, [2, 1, 0])
        assert out["sel"] is None

    def test_sel_is_none_when_xy_is_the_identity(self):
        out = agent().adjudicate_order("2, 1, 3", 3, [0, 1, 2])
        assert out["sel"] is None

    def test_min_cover_is_configurable(self):
        # "2" sozinho: com min_cover 0.8 é rejeitado; com 0.3 passa e reordena.
        assert agent().adjudicate_order("2", 3, [0, 1, 2])["status"] == "low-cover"
        out = agent().adjudicate_order("2", 3, [0, 1, 2], min_cover=0.3)
        assert out["status"] == "vlm-reorder"
        assert out["vlm"] == [1, 0, 2]


class TestRefineReadingOrder:
    def test_returns_a_permutation(self):
        boxes = [[0.0, 0.0, 0.5, 0.5], [0.5, 0.0, 1.0, 0.5]]
        order = agent().refine_reading_order(boxes)["order"]
        assert sorted(order) == [0, 1]

    def test_empty_boxes(self):
        assert agent().refine_reading_order([])["order"] == []
