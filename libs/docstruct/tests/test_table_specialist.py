"""Testes do especialista de tabela (``docstruct.fusion.table_specialist``).

Espelham a semântica de ``vlm_tables.py`` do Dr.DocBench (PR #125). A
similaridade (TEDS no script) é injetada; aqui usa-se uma similaridade simples
baseada em igualdade de HTML normalizado.
"""
from collections import Counter

import pytest

from docstruct.fusion.table_specialist import (
    build_candidates,
    extract_table,
    is_valid_table,
    medoid_index,
    norm_table,
    pairwise_similarity,
    select_greedy,
    select_table,
)


def exact_sim(a: str, b: str) -> float:
    return 1.0 if a == b else 0.0


def overlap_sim(a: str, b: str) -> float:
    """Similaridade simples: fração de caracteres em comum (para testes de medoide)."""
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    common = sum(1 for c in set(a) if c in b)
    return common / len(set(a) | set(b))


class TestExtractTable:
    def test_extracts_the_table(self):
        assert extract_table("<p>x</p><table><tr><td>a</td></tr></table>") == "<table><tr><td>a</td></tr></table>"

    def test_strips_code_fences(self):
        assert extract_table("```html\n<table><tr><td>a</td></tr></table>\n```") == "<table><tr><td>a</td></tr></table>"

    def test_no_table(self):
        assert extract_table("just text") == ""

    def test_empty(self):
        assert extract_table("") == ""


class TestNormTable:
    def test_table_attributes_are_dropped(self):
        assert norm_table('<table border="1"><tr><td>a</td></tr></table>') == "<table><tr><td>a</td></tr></table>"

    def test_th_becomes_td(self):
        assert norm_table("<table><tr><th>a</th></tr></table>") == "<table><tr><td>a</td></tr></table>"

    def test_non_structural_tags_are_dropped(self):
        assert norm_table("<table><tbody><tr><td>a</td></tr></tbody></table>") == "<table><tr><td>a</td></tr></table>"

    def test_span_attributes_are_kept(self):
        out = norm_table('<table><tr><td colspan="2" class="x">a</td></tr></table>')
        assert 'colspan="2"' in out
        assert "class" not in out

    def test_rowspan_is_kept(self):
        out = norm_table('<table><tr><td rowspan="3">a</td></tr></table>')
        assert 'rowspan="3"' in out


class TestIsValidTable:
    def test_valid_table(self):
        assert is_valid_table("<table><tr><td>a</td></tr></table>") is True

    def test_no_rows(self):
        assert is_valid_table("<table></table>") is False

    def test_no_cells(self):
        assert is_valid_table("<table><tr></tr></table>") is False

    def test_empty(self):
        assert is_valid_table("") is False


class TestBuildCandidates:
    def _record(self, kind_d: str = "table", kind_m: str = "table") -> dict:
        return {
            "kind_d": kind_d,
            "kind_m": kind_m,
            "md_d": "<table><tr><td>docling</td></tr></table>",
            "md_m": "<table><tr><td>mineru</td></tr></table>",
        }

    def test_providers_are_included(self):
        names = [n for n, _ in build_candidates(self._record())]
        assert names == ["a", "b"]

    def test_non_table_provider_is_excluded(self):
        names = [n for n, _ in build_candidates(self._record(kind_d="text"))]
        assert names == ["b"]

    def test_generations_are_included(self):
        names = [
            n for n, _ in build_candidates(
                self._record(), greedy="<table><tr><td>g</td></tr></table>",
                samples=["<table><tr><td>s</td></tr></table>"],
            )
        ]
        assert names == ["a", "b", "v0", "v1"]

    def test_invalid_generation_is_dropped(self):
        names = [n for n, _ in build_candidates(self._record(), greedy="not a table")]
        assert names == ["a", "b"]

    def test_max_chars_drops_long_generations(self):
        long_html = "<table><tr><td>" + "x" * 100 + "</td></tr></table>"
        names = [n for n, _ in build_candidates(self._record(), greedy=long_html, max_chars=50)]
        assert names == ["a", "b"]

    def test_no_candidates(self):
        assert build_candidates({"kind_d": "text", "kind_m": "text"}) == []


class TestMedoidIndex:
    def test_single_candidate(self):
        assert medoid_index([("a", "<table></table>")], exact_sim) == 0

    def test_identical_candidates_prefer_the_first(self):
        c = [("a", "<table><tr><td>x</td></tr></table>")] * 3
        assert medoid_index(c, exact_sim) == 0

    def test_medoid_is_the_most_similar(self):
        # dois iguais e um diferente -> o medoide é um dos iguais (índice 0)
        c = [
            ("a", "<table><tr><td>same</td></tr></table>"),
            ("b", "<table><tr><td>same</td></tr></table>"),
            ("v0", "<table><tr><td>other</td></tr></table>"),
        ]
        assert medoid_index(c, exact_sim) == 0

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            medoid_index([], exact_sim)


class TestPairwiseSimilarity:
    def test_all_pairs(self):
        c = [("a", "<table><tr><td>x</td></tr></table>"),
             ("b", "<table><tr><td>x</td></tr></table>"),
             ("v0", "<table><tr><td>y</td></tr></table>")]
        sim = pairwise_similarity(c, exact_sim)
        assert sim[(0, 1)] == 1.0
        assert sim[(0, 2)] == 0.0
        assert sim[(1, 2)] == 0.0

    def test_single_candidate_has_no_pairs(self):
        assert pairwise_similarity([("a", "<table></table>")], exact_sim) == {}


class TestSelectTable:
    def _record(self) -> dict:
        return {
            "kind_d": "table",
            "kind_m": "table",
            "md_d": "<table><tr><td>docling</td></tr></table>",
            "md_m": "<table><tr><td>mineru</td></tr></table>",
        }

    def test_no_candidates(self):
        decision, stats = select_table({"kind_d": "text", "kind_m": "text"}, "", None, exact_sim)
        assert decision is None
        assert stats["no-cand"] == 1

    def test_provider_medoid_selects_the_provider(self):
        # a greedy é diferente dos dois providers -> o medoide é um provider
        decision, stats = select_table(
            self._record(), "<table><tr><td>vlm</td></tr></table>", None, exact_sim
        )
        assert decision["action"] in ("select_a", "select_b")
        assert stats["medoid-a"] + stats["medoid-b"] == 1

    def test_vlm_medoid_replaces(self):
        # dois providers iguais e uma greedy igual a eles -> medoide é o provider
        record = {
            "kind_d": "table",
            "kind_m": "table",
            "md_d": "<table><tr><td>same</td></tr></table>",
            "md_m": "<table><tr><td>same</td></tr></table>",
        }
        decision, _ = select_table(
            record, "<table><tr><td>same</td></tr></table>", None, exact_sim
        )
        assert decision["action"] == "select_a"

    def test_vlm_wins_when_providers_disagree(self):
        # providers diferentes entre si; duas gerações iguais -> medoide é a geração
        record = {
            "kind_d": "table",
            "kind_m": "table",
            "md_d": "<table><tr><td>aaa</td></tr></table>",
            "md_m": "<table><tr><td>bbb</td></tr></table>",
        }
        decision, stats = select_table(
            record,
            "<table><tr><td>vlm</td></tr></table>",
            ["<table><tr><td>vlm</td></tr></table>"],
            exact_sim,
        )
        assert decision["action"] == "replace"
        assert decision["text"] == "<table><tr><td>vlm</td></tr></table>"
        assert stats["medoid-v"] == 1


class TestSelectGreedy:
    def _record(self) -> dict:
        return {
            "kind_d": "table",
            "kind_m": "table",
            "md_d": "<table><tr><td>docling</td></tr></table>",
            "md_m": "<table><tr><td>mineru</td></tr></table>",
        }

    def test_no_greedy(self):
        decision, stats = select_greedy(self._record(), "", None, exact_sim)
        assert decision is None
        assert stats["no-greedy"] == 1

    def test_greedy_replaces_when_different(self):
        decision, stats = select_greedy(
            self._record(), "<table><tr><td>vlm</td></tr></table>", None, exact_sim
        )
        assert decision["action"] == "replace"
        assert stats["greedy-replace"] == 1

    def test_greedy_close_to_a_provider_selects_it(self):
        record = {
            "kind_d": "table",
            "kind_m": "table",
            "md_d": "<table><tr><td>same</td></tr></table>",
            "md_m": "<table><tr><td>other</td></tr></table>",
        }
        decision, stats = select_greedy(
            record, "<table><tr><td>same</td></tr></table>", None, exact_sim
        )
        assert decision["action"] == "select_a"
        assert stats["greedy-select"] == 1
