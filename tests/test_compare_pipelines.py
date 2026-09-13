"""Tests for pipeline comparison helpers (stateless logic only).

Full end-to-end comparison tests require the Toolbox to be running
and are covered by E2E tests (pytest -m e2e).
"""
from __future__ import annotations

from scripts.compare_pipelines import (
    _compare_documents,
    _compute_verdict,
    _count_by_type,
    _extract_formulas,
    _extract_tables,
    _extract_text,
    _flatten_blocks,
    _jaccard_similarity,
    _summarize_document,
    _tokenize,
)


def _make_canonical(title: str, blocks: list[dict], sections: list | None = None) -> dict:
    """Build a minimal canonical document for testing."""
    if sections is None:
        sections = [{"title": "root", "blocks": blocks, "children": []}]
    return {
        "title": title,
        "metadata": {"page_count": 1},
        "sections": sections,
    }


SAMPLE_BLOCKS = [
    {"type": "paragraph", "text": "Hello world"},
    {"type": "heading", "title": "Introduction", "text": "Introduction"},
    {"type": "list", "items": ["item A", "item B"]},
    {"type": "table", "rows": [["a", "b"], ["c", "d"]]},
    {"type": "formula", "text": "E = mc^2"},
    {"type": "image", "alt_text": "Chart"},
]


class TestFlattenBlocks:
    def test_flat_list(self):
        doc = _make_canonical("Test", SAMPLE_BLOCKS)
        result = _flatten_blocks(doc)
        assert len(result) == 6
        for block in result:
            assert "_section_path" in block

    def test_nested_sections(self):
        doc = _make_canonical("Nested", [], sections=[
            {"title": "Ch1", "blocks": [
                {"type": "paragraph", "text": "para 1"},
            ], "children": [
                {"title": "Ch1.1", "blocks": [
                    {"type": "paragraph", "text": "para 2"},
                ], "children": []},
            ]},
        ])
        result = _flatten_blocks(doc)
        assert len(result) == 2
        assert "Ch1" in result[0]["_section_path"]
        assert "Ch1.1" in result[1]["_section_path"]


class TestCountByType:
    def test_counts(self):
        result = _count_by_type(SAMPLE_BLOCKS)
        assert result == {
            "formula": 1,
            "heading": 1,
            "image": 1,
            "list": 1,
            "paragraph": 1,
            "table": 1,
        }

    def test_empty(self):
        assert _count_by_type([]) == {}


class TestExtractText:
    def test_extracts_all_text(self):
        doc = _make_canonical("T", [
            {"type": "paragraph", "text": "Hello"},
            {"type": "heading", "title": "Intro"},
            {"type": "list", "items": ["a", "b"]},
            {"type": "table", "rows": [["cell1", "cell2"]]},
            {"type": "image", "alt_text": "Chart img"},
        ])
        text = _extract_text(doc)
        assert "Hello" in text
        assert "Intro" in text
        assert "a" in text
        assert "b" in text
        assert "cell1" in text
        assert "Chart img" in text


class TestJaccardSimilarity:
    def test_identical(self):
        assert _jaccard_similarity("hello world", "hello world") == 1.0

    def test_partial(self):
        sim = _jaccard_similarity("hello world", "hello there")
        assert 0.3 < sim < 0.7

    def test_disjoint(self):
        assert _jaccard_similarity("abc", "xyz") == 0.0

    def test_both_empty(self):
        assert _jaccard_similarity("", "") == 1.0

    def test_case_insensitive(self):
        assert _jaccard_similarity("Hello World", "hello world") == 1.0


class TestTokenize:
    def test_basic(self):
        assert _tokenize("Hello World") == {"hello", "world"}

    def test_empty(self):
        assert _tokenize("") == set()


class TestExtractFormulas:
    def test_extracts_formula_blocks(self):
        doc = _make_canonical("F", [
            {"type": "formula", "text": "E = mc^2"},
            {"type": "paragraph", "text": "normal text"},
            {"type": "formula", "text": "F = ma"},
        ])
        result = _extract_formulas(doc)
        assert len(result) == 2
        assert "E = mc^2" in result
        assert "F = ma" in result

    def test_no_formulas(self):
        doc = _make_canonical("NF", [{"type": "paragraph", "text": "text"}])
        assert _extract_formulas(doc) == []


class TestExtractTables:
    def test_extracts_table_blocks(self):
        doc = _make_canonical("T", [
            {"type": "table", "rows": [["a", "b"]]},
            {"type": "paragraph", "text": "text"},
        ])
        assert len(_extract_tables(doc)) == 1

    def test_no_tables(self):
        doc = _make_canonical("NT", [{"type": "paragraph", "text": "text"}])
        assert _extract_tables(doc) == []


class TestSummarizeDocument:
    def test_summary_fields(self):
        doc = _make_canonical("Summary Test", SAMPLE_BLOCKS)
        summary = _summarize_document(doc)
        assert summary["title"] == "Summary Test"
        assert summary["block_count"] == 6
        assert summary["formula_count"] == 1
        assert summary["table_count"] == 1
        assert summary["blocks_by_type"]["paragraph"] == 1
        assert summary["text_length"] > 0


class TestCompareDocuments:
    def test_identical_documents(self):
        a = _make_canonical("Same", [
            {"type": "paragraph", "text": "Hello"},
            {"type": "formula", "text": "E = mc^2"},
        ])
        b = _make_canonical("Same", [
            {"type": "paragraph", "text": "Hello"},
            {"type": "formula", "text": "E = mc^2"},
        ])
        comp = _compare_documents(a, b)
        assert comp["text"]["jaccard_similarity"] == 1.0
        assert comp["structural"]["block_count"]["delta"] == 0
        assert comp["formulas"]["common_formulas"] == 1

    def test_different_documents(self):
        a = _make_canonical("A", [
            {"type": "paragraph", "text": "Hello world"},
            {"type": "table", "rows": [["x", "y"]]},
        ])
        b = _make_canonical("B", [
            {"type": "paragraph", "text": "Different content here"},
            {"type": "formula", "text": "F = ma"},
        ])
        comp = _compare_documents(a, b)
        assert comp["text"]["jaccard_similarity"] < 1.0
        assert comp["formulas"]["common_formulas"] == 0


class TestComputeVerdict:
    @staticmethod
    def _make_comparison(similarity: float = 1.0, block_delta: int = 0,
                         type_deltas: dict | None = None) -> dict:
        return {
            "text": {"jaccard_similarity": similarity},
            "structural": {
                "block_count": {"legacy": 10, "pddl_toolbox": 10 + block_delta, "delta": block_delta},
                "blocks_by_type_delta": type_deltas or {},
            },
        }

    def test_equivalent(self):
        comp = self._make_comparison(similarity=0.95, block_delta=2)
        verdict = _compute_verdict(comp)
        assert "EQUIVALENTE" in verdict

    def test_low_similarity(self):
        comp = self._make_comparison(similarity=0.5)
        verdict = _compute_verdict(comp)
        assert "DIVERGENTE" in verdict

    def test_large_block_delta(self):
        comp = self._make_comparison(similarity=0.95, block_delta=50)
        verdict = _compute_verdict(comp)
        assert "DIVERGENTE" in verdict

    def test_significant_type_delta(self):
        comp = self._make_comparison(
            similarity=0.95,
            type_deltas={"table": {"legacy": 10, "pddl_toolbox": 2}},
        )
        verdict = _compute_verdict(comp)
        assert "DIVERGENTE" in verdict