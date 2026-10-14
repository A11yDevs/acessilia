"""Tests for the verse/drama chunking policy in the Dr.DocBench differ.

The evaluator can only re-group consecutive predictions into a ground-truth block
when the strings are <= 300 chars, so a whole-page verse block loses every stanza
but one. ``verse_blocks`` chunks list-like blocks (TOC, index, records) while
leaving real verse whole.
"""
from __future__ import annotations

from collections import Counter

from scripts.drbench.experiments.differ.tree_differ_v2 import (
    chunk_verse,
    record_like,
    split_box_rows,
    verse_blocks,
    verse_lines,
)


class TestRecordLike:
    def test_lines_ending_with_numbers_are_records(self):
        assert record_like(["Chapter one 1", "Chapter two 2", "Chapter three 3"]) is True

    def test_dot_leaders_are_records(self):
        assert record_like(["Introduction .......", "Methods ..........", "Results ........."]) is True

    def test_verse_lines_ending_with_words_are_not_records(self):
        lines = ["Shall I compare thee to a summer's day", "Thou art more lovely and more temperate"]
        assert record_like(lines) is False

    def test_empty_input_is_not_records(self):
        assert record_like([]) is False
        assert record_like(["", "   "]) is False

    def test_threshold_is_respected(self):
        # 2 of 4 lines end with a number -> 0.5 < 0.6 default
        assert record_like(["a 1", "b 2", "c", "d"]) is False
        assert record_like(["a 1", "b 2", "c", "d"], min_frac=0.5) is True


class TestVerseLines:
    def test_short_multiline_block_is_verse_like(self):
        md = "line one\nline two\nline three"
        assert verse_lines(md) == ["line one", "line two", "line three"]

    def test_single_line_is_not_verse(self):
        assert verse_lines("just one line") is None

    def test_too_few_lines_is_not_verse(self):
        assert verse_lines("one\ntwo") is None

    def test_markdown_structures_are_excluded(self):
        for prefix in ("#", "<", "|", "$$", "!["):
            assert verse_lines(f"{prefix} a\nb\nc") is None

    def test_long_lines_are_not_verse(self):
        long_line = "x" * 130
        assert verse_lines(f"{long_line}\nb\nc") is None

    def test_median_length_gate(self):
        # median line length above max_median -> prose, not verse
        prose = "\n".join(["y" * 80] * 3)
        assert verse_lines(prose) is None


class TestChunkVerse:
    def test_blank_line_splits_stanzas(self):
        chunks = chunk_verse(["a", "b", "", "c", "d"], max_chars=1000)
        assert chunks == ["a\nb", "c\nd"]

    def test_speaker_label_starts_a_new_chunk(self):
        # SPEAKER_RE matches a standalone label line, not a label followed by dialogue.
        chunks = chunk_verse(["HAMLET:", "to be", "or not to be", "KING:", "what ho"], max_chars=1000)
        assert chunks == ["HAMLET:\nto be\nor not to be", "KING:\nwhat ho"]

    def test_inline_speaker_label_does_not_split(self):
        chunks = chunk_verse(["HAMLET: to be", "or not to be"], max_chars=1000)
        assert chunks == ["HAMLET: to be\nor not to be"]

    def test_max_chars_forces_a_split(self):
        chunks = chunk_verse(["aaaa", "bbbb", "cccc"], max_chars=5)
        assert len(chunks) == 3

    def test_sentence_end_flushes_after_soft_threshold(self):
        chunks = chunk_verse(["first sentence.", "second sentence."], max_chars=10, soft=0.5)
        assert chunks == ["first sentence.", "second sentence."]

    def test_empty_input_yields_no_chunks(self):
        assert chunk_verse([], max_chars=100) == []


class TestSplitBoxRows:
    def test_none_box_returns_none_per_part(self):
        assert split_box_rows(None, [1, 2]) == [None, None]

    def test_box_is_split_proportionally(self):
        boxes = split_box_rows((0.0, 0.0, 1.0, 1.0), [1, 3])
        assert boxes[0] == (0.0, 0.0, 1.0, 0.25)
        assert boxes[1] == (0.0, 0.25, 1.0, 1.0)

    def test_zero_parts_do_not_divide_by_zero(self):
        boxes = split_box_rows((0.0, 0.0, 1.0, 1.0), [0, 0])
        assert len(boxes) == 2


class TestVerseBlocks:
    def _block(self, md: str, kind: str = "text", box=None) -> dict:
        return {"md": md, "kind": kind, "box": box, "text": md, "type": "text"}

    def test_records_are_chunked(self):
        md = "\n".join(f"Entry {i} {i}" for i in range(1, 8))
        stats = Counter()
        out = verse_blocks([self._block(md)], stats, "docling", max_chars=20)
        assert len(out) > 1
        assert stats["verse-docling-split"] == 1
        assert all(b.get("verse") for b in out)

    def test_real_verse_stays_whole_in_records_mode(self):
        md = "Shall I compare thee\nTo a summer's day\nThou art more lovely"
        stats = Counter()
        out = verse_blocks([self._block(md)], stats, "docling", max_chars=20, kind="records")
        assert len(out) == 1
        assert stats["verse-docling-whole"] == 1

    def test_all_mode_chunks_real_verse(self):
        md = "Shall I compare thee\nTo a summer's day\nThou art more lovely"
        stats = Counter()
        out = verse_blocks([self._block(md)], stats, "docling", max_chars=20, kind="all")
        assert len(out) > 1

    def test_non_text_blocks_are_untouched(self):
        block = self._block("a\nb\nc", kind="table")
        stats = Counter()
        out = verse_blocks([block], stats, "docling", max_chars=10)
        assert out == [block]

    def test_single_chunk_is_kept_as_is(self):
        # "a\nb\nc" is not record-like, so records mode keeps it whole before chunking.
        md = "a\nb\nc"
        stats = Counter()
        out = verse_blocks([self._block(md)], stats, "docling", max_chars=1000)
        assert len(out) == 1
        assert stats["verse-docling-whole"] == 1

    def test_single_chunk_in_all_mode_is_kept(self):
        md = "a\nb\nc"
        stats = Counter()
        out = verse_blocks([self._block(md)], stats, "docling", max_chars=1000, kind="all")
        assert len(out) == 1
        assert stats["verse-docling-kept"] == 1

    def test_chunk_boxes_are_derived_from_the_original(self):
        md = "\n".join(f"Entry {i} {i}" for i in range(1, 8))
        stats = Counter()
        out = verse_blocks([self._block(md, box=(0.0, 0.0, 1.0, 1.0))], stats, "docling", max_chars=20)
        assert all(b["box"] is not None for b in out)
        assert out[0]["box"][1] == 0.0
        assert out[-1]["box"][3] == 1.0
