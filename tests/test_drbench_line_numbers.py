"""Tests for marginal verse line-number extraction in the Dr.DocBench differ.

Ground truth keeps marginal verse line numbers as their own blocks. OCR often
folds them into the surrounding text ("be seen 3964 or recognized") or emits them
as standalone lines. ``extract_line_numbers`` detects the arithmetic run and
re-emits the numbers as separate blocks right after the text.
"""
from __future__ import annotations

from collections import Counter

from scripts.drbench.experiments.differ.tree_differ_v2 import (
    extract_line_numbers,
    line_number_chain,
)


class TestLineNumberChain:
    def test_step_five_chain(self):
        step, idx = line_number_chain([10, 15, 20, 25])
        assert step == 5
        assert idx == {0, 1, 2, 3}

    def test_step_four_chain(self):
        step, idx = line_number_chain([4, 8, 12])
        assert step == 4
        assert idx == {0, 1, 2}

    def test_values_need_not_be_adjacent(self):
        # a year interleaved between line numbers must not break the chain
        step, idx = line_number_chain([10, 1999, 15, 20])
        assert step == 5
        assert idx == {0, 2, 3}

    def test_chain_shorter_than_min_len_is_rejected(self):
        step, idx = line_number_chain([10, 15])
        assert idx == set()

    def test_no_arithmetic_progression(self):
        step, idx = line_number_chain([1, 7, 33, 91])
        assert idx == set()

    def test_longest_chain_wins(self):
        # step 2 gives a 4-element chain; step 5 gives 3
        step, idx = line_number_chain([2, 4, 6, 8, 100, 105, 110])
        assert step == 2
        assert len(idx) == 4

    def test_empty_input(self):
        assert line_number_chain([]) == (0, set())


class TestExtractLineNumbers:
    def _block(self, md: str, kind: str = "text") -> dict:
        return {"md": md, "kind": kind, "box": (0.0, 0.0, 1.0, 1.0), "text": md, "type": "text"}

    def test_inline_numbers_are_extracted(self):
        md = ("word " * 30) + " 10 more words 15 more words 20 more words 25"
        stats = Counter()
        out = extract_line_numbers([self._block(md)], stats, "docling")
        assert len(out) > 1
        assert stats["line-numbers-docling"] == 1
        assert stats["line-numbers-docling-count"] == 4

    def test_numbers_become_separate_blocks_after_the_text(self):
        md = ("word " * 30) + " 10 more words 15 more words 20 more words 25"
        stats = Counter()
        out = extract_line_numbers([self._block(md)], stats, "docling")
        assert out[0]["verse_nums"] is True
        assert [b["md"] for b in out[1:]] == ["10", "15", "20", "25"]
        assert all(b["type"] == "line_number" for b in out[1:])

    def test_short_block_is_skipped(self):
        stats = Counter()
        out = extract_line_numbers([self._block("10 15 20 25")], stats, "docling")
        assert len(out) == 1
        assert stats["line-numbers-docling"] == 0

    def test_fewer_than_three_numbers_is_skipped(self):
        md = ("word " * 30) + " 10 more 15"
        stats = Counter()
        out = extract_line_numbers([self._block(md)], stats, "docling")
        assert len(out) == 1

    def test_non_text_blocks_are_untouched(self):
        md = ("word " * 30) + " 10 more words 15 more words 20 more words 25"
        block = self._block(md, kind="table")
        stats = Counter()
        out = extract_line_numbers([block], stats, "docling")
        assert out == [block]

    def test_already_processed_block_is_not_reprocessed(self):
        md = ("word " * 30) + " 10 more words 15 more words 20 more words 25"
        block = {**self._block(md), "verse_nums": True}
        stats = Counter()
        out = extract_line_numbers([block], stats, "docling")
        assert out == [block]

    def test_block_that_becomes_empty_is_kept_whole(self):
        # only numbers, no surrounding prose -> nothing left to keep as text
        md = " ".join(str(n) for n in range(10, 205, 5))
        stats = Counter()
        out = extract_line_numbers([self._block(md)], stats, "docling")
        assert len(out) == 1
        assert stats["line-numbers-docling"] == 0

    def test_number_boxes_are_derived_from_the_block(self):
        md = ("word " * 30) + " 10 more words 15 more words 20 more words 25"
        stats = Counter()
        out = extract_line_numbers([self._block(md)], stats, "docling")
        for b in out[1:]:
            assert b["box"] is not None
            assert b["box"][2] <= 1.0
