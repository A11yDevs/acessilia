"""Tests for the PageLevelAgent (Agno tools over the docstruct page-selection stack).

Dr.DocBench PR #125. The deterministic ``process_*`` methods are exercised
directly so the tests run without Agno installed.
"""
from __future__ import annotations

from backend.core.agents.page_level_agent import PageLevelAgent


def agent() -> PageLevelAgent:
    return PageLevelAgent()


def box(w: float, h: float) -> list:
    return [[0.0, 0.0], [w, 0.0], [w, h], [0.0, h]]


class TestFusePage:
    def test_empty_b_returns_a_unchanged(self):
        assert agent().fuse_page("first\n\nsecond", "")["text"] == "first\n\nsecond"

    def test_order_mode_keeps_a_block_count(self):
        out = agent().fuse_page("alpha\n\nbeta", "alpha\n\nbeta")
        assert out["text"].count("alpha") == 1

    def test_head_mode_preserves_a_heading_markup(self):
        out = agent().fuse_page("# Title\n\nbody text", "Title\n\nbody text", mode="head")
        assert out["text"].lstrip().startswith("#")

    def test_swap_mode_takes_b_text(self):
        out = agent().fuse_page("the quick brown fox", "the quick brown cat", mode="swap")
        assert "cat" in out["text"]

    def test_swap_mode_does_not_swap_tables_by_default(self):
        a = "<table><tr><td>alpha beta gamma</td></tr></table>"
        b = "<table><tr><td>alpha beta delta</td></tr></table>"
        assert "gamma" in agent().fuse_page(a, b, mode="swap")["text"]

    def test_swap_mode_can_swap_tables(self):
        a = "<table><tr><td>alpha beta gamma</td></tr></table>"
        b = "<table><tr><td>alpha beta delta</td></tr></table>"
        assert "delta" in agent().fuse_page(a, b, mode="swap", tables=True)["text"]


class TestSelectPage:
    def test_vlm_page_replaces_a_shorter_differ_output(self):
        out = agent().select_page(
            "short", "a much longer vlm transcription here",
            "docling text", "zzz qqq", "stop",
        )
        assert out["swapped"] is True

    def test_incomplete_generation_is_not_used(self):
        out = agent().select_page(
            "short", "a much longer vlm transcription here",
            "docling text", "zzz qqq", "length",
        )
        assert out["swapped"] is False

    def test_high_agreement_keeps_the_differ_output(self):
        out = agent().select_page("short", "vlm text", "same text", "same text", "stop")
        assert out["swapped"] is False


class TestSwapLowAgreement:
    def test_low_agreement_swaps(self):
        out = agent().swap_low_agreement("base text here", "alt text here", "aaa", "zzz")
        assert out["swapped"] is True
        assert out["text"] == "alt text here"

    def test_missing_alternative_keeps_the_base(self):
        assert agent().swap_low_agreement("base", None, "d", "m")["swapped"] is False

    def test_high_agreement_keeps_the_base(self):
        assert agent().swap_low_agreement("base", "alt", "same", "same")["swapped"] is False

    def test_short_alternative_keeps_the_base(self):
        out = agent().swap_low_agreement("a" * 100, "b", "aaa", "zzz")
        assert out["swapped"] is False


class TestPageAgreement:
    def test_identical_pages(self):
        assert agent().page_agreement("hello world", "hello world")["agreement"] == 1.0

    def test_different_pages(self):
        assert agent().page_agreement("hello world", "xyz")["agreement"] < 0.5


class TestJoinTail:
    def test_end_mode_joins(self):
        assert agent().join_tail(["body", "HEAD", "42"], mode="end")["blocks"] == ["body", "HEAD 42"]

    def test_positioned_bottom_keeps(self):
        out = agent().join_tail(["body", "HEAD", "42"], position="bot", bot="keep")
        assert out["blocks"] == ["body", "HEAD", "42"]

    def test_positioned_bottom_moves_number_last(self):
        out = agent().join_tail(["body", "42", "HEAD"], position="bot", bot="hdr")
        assert out["blocks"] == ["body", "HEAD", "42"]

    def test_positioned_top_joins(self):
        out = agent().join_tail(["body", "HEAD", "42"], position="top")
        assert out["blocks"] == ["body", "HEAD 42"]


class TestMoveHeaderFooterToEnd:
    def test_header_moves_to_the_end(self):
        elements = [
            {"category": "Page-header", "text": "H"},
            {"category": "Text", "text": "body"},
        ]
        out = agent().move_header_footer_to_end(elements)["elements"]
        assert [e["text"] for e in out] == ["body", "H"]

    def test_no_header_is_a_no_op(self):
        elements = [{"category": "Text", "text": "a"}]
        assert agent().move_header_footer_to_end(elements)["elements"] == elements


class TestUpscaleFactor:
    def test_small_page(self):
        assert agent().upscale_factor(400, 600)["factor"] == 2.0

    def test_medium_page(self):
        assert agent().upscale_factor(900, 1000)["factor"] == 1.5

    def test_large_page(self):
        assert agent().upscale_factor(2000, 3000)["factor"] == 1.0


class TestDecideOrientation:
    def test_upright_page_stays_at_zero(self):
        out = agent().decide_orientation([box(20, 10)] * 4, {90: (10.0, 5), 270: (20.0, 5)})
        assert out["angle"] == 0

    def test_rotated_page_picks_the_best_score(self):
        out = agent().decide_orientation([box(10, 20)] * 4, {90: (10.0, 5), 270: (20.0, 5)})
        assert out["angle"] == 270

    def test_candidate_without_scores_stays_at_zero(self):
        assert agent().decide_orientation([box(10, 20)] * 4)["angle"] == 0
