"""Tests for whole-page fusion in the Dr.DocBench page pipeline.

``page_fuse`` combines a whole-page VLM transcription (B) with the differ output
(A) at block level. ``order``/``head`` keep A's block order and heading markup
(A carries the ground-truth decor-tail and reading-order conventions) while taking
B's text; ``swap`` replaces each A block whose best B match is similar enough.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PAGES_DIR = Path(__file__).resolve().parents[1] / "scripts" / "drbench" / "experiments" / "pages"
sys.path.insert(0, str(PAGES_DIR))

page_fuse = pytest.importorskip("page_fuse")


class TestNorm:
    def test_strips_markup_and_lowercases(self):
        assert page_fuse.norm("**Hello** _World_") == "hello world"

    def test_strips_html_tags(self):
        assert page_fuse.norm("<table><tr><td>x</td></tr></table>") == "x"

    def test_collapses_whitespace(self):
        assert page_fuse.norm("a   b\n\nc") == "a b c"

    def test_empty_input(self):
        assert page_fuse.norm("") == ""


class TestBlocks:
    def test_splits_on_blank_lines(self):
        assert page_fuse.blocks("one\n\ntwo\n\n\nthree") == ["one", "two", "three"]

    def test_ignores_empty_chunks(self):
        assert page_fuse.blocks("\n\n\n") == []

    def test_single_block(self):
        assert page_fuse.blocks("only one") == ["only one"]


class TestFuse:
    def test_empty_b_returns_a_unchanged(self):
        a = "first\n\nsecond"
        assert page_fuse.fuse(a, "", "order", 0.5) == a

    def test_order_mode_keeps_a_block_count(self):
        a = "alpha\n\nbeta"
        b = "alpha\n\nbeta"
        out = page_fuse.fuse(a, b, "order", 0.5)
        assert len(page_fuse.blocks(out)) == 2

    def test_head_mode_preserves_a_heading_markup(self):
        a = "# Title\n\nbody text"
        b = "Title\n\nbody text"
        out = page_fuse.fuse(a, b, "head", 0.5)
        assert out.lstrip().startswith("#")

    def test_swap_mode_takes_b_text_for_similar_blocks(self):
        a = "the quick brown fox"
        b = "the quick brown cat"
        out = page_fuse.fuse(a, b, "swap", 0.5)
        assert "cat" in out

    def test_swap_mode_keeps_a_when_below_similarity(self):
        a = "completely different content here"
        b = "nothing alike at all"
        out = page_fuse.fuse(a, b, "swap", 0.99)
        assert "completely different" in out

    def test_swap_mode_does_not_swap_tables_by_default(self):
        a = "<table><tr><td>alpha beta gamma</td></tr></table>"
        b = "<table><tr><td>alpha beta delta</td></tr></table>"
        out = page_fuse.fuse(a, b, "swap", 0.5)
        assert "gamma" in out

    def test_swap_mode_can_swap_tables_when_enabled(self):
        a = "<table><tr><td>alpha beta gamma</td></tr></table>"
        b = "<table><tr><td>alpha beta delta</td></tr></table>"
        out = page_fuse.fuse(a, b, "swap", 0.5, tables=True)
        assert "delta" in out
