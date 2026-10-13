"""Tests for the generation-loop guard in the Dr.DocBench page pipeline.

MinerU/VLM sources occasionally degenerate into repetition ("5 5 5 5 ..." or one
sentence repeated many times on a blank page). ``collapse`` cuts an n-gram repeated
k >= reps times down to the largest run seen in the reference sources (Docling or
the VLM page), so a legitimate repetition is preserved.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PAGES_DIR = Path(__file__).resolve().parents[1] / "scripts" / "drbench" / "experiments" / "pages"
sys.path.insert(0, str(PAGES_DIR))

rep_guard = pytest.importorskip("rep_guard")


class TestMaxRun:
    def test_counts_consecutive_repeats(self):
        ref = ["a", "b", "a", "b", "a", "b"]
        assert rep_guard.max_run(ref, ("a", "b")) == 3

    def test_absent_gram_returns_zero(self):
        assert rep_guard.max_run(["x", "y"], ("a", "b")) == 0

    def test_single_occurrence(self):
        assert rep_guard.max_run(["a", "b", "c"], ("a", "b")) == 1


class TestCollapse:
    def test_loop_is_cut_to_the_reference_run(self):
        block = " ".join(["5"] * 20)
        out, cut = rep_guard.collapse(block, [["5", "5"]], reps=5, max_n=12)
        assert cut > 0
        assert out.split().count("5") < 20

    def test_legitimate_repetition_is_preserved(self):
        # the reference shows the same run, so nothing is cut
        block = " ".join(["5"] * 6)
        out, cut = rep_guard.collapse(block, [["5"] * 6], reps=5, max_n=12)
        assert cut == 0
        assert out.split().count("5") == 6

    def test_short_repetition_below_threshold_is_untouched(self):
        block = " ".join(["5"] * 4)
        out, cut = rep_guard.collapse(block, [[]], reps=5, max_n=12)
        assert cut == 0
        assert out == block

    def test_non_repeated_text_is_untouched(self):
        block = "the quick brown fox jumps over the lazy dog"
        out, cut = rep_guard.collapse(block, [[]], reps=5, max_n=12)
        assert cut == 0
        assert out == block

    def test_whitespace_is_preserved(self):
        block = "alpha beta gamma"
        out, cut = rep_guard.collapse(block, [[]], reps=5, max_n=12)
        assert out == block

    def test_empty_block(self):
        out, cut = rep_guard.collapse("", [[]], reps=5, max_n=12)
        assert out == ""
        assert cut == 0

    def test_sentence_loop_is_cut(self):
        sentence = "the fox jumped over the dog"
        block = " ".join([sentence] * 10)
        out, cut = rep_guard.collapse(block, [[]], reps=5, max_n=12)
        assert cut > 0
        assert out.count(sentence) < 10
