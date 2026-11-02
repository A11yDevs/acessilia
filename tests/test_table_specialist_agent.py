"""Tests for the TableSpecialistAgent (Agno tools over the table-specialist stack).

Dr.DocBench PR #125. The deterministic ``process_*`` methods are exercised
directly so the tests run without Agno installed.
"""
from __future__ import annotations

from backend.core.agents.table_specialist_agent import (
    TableSpecialistAgent,
    overlap_similarity,
)


def agent() -> TableSpecialistAgent:
    return TableSpecialistAgent()


def exact_sim(a: str, b: str) -> float:
    return 1.0 if a == b else 0.0


def record(kind_d: str = "table", kind_m: str = "table") -> dict:
    return {
        "kind_d": kind_d,
        "kind_m": kind_m,
        "md_d": "<table><tr><td>docling</td></tr></table>",
        "md_m": "<table><tr><td>mineru</td></tr></table>",
    }


class TestOverlapSimilarity:
    def test_identical(self):
        assert overlap_similarity("abc", "abc") == 1.0

    def test_both_empty(self):
        assert overlap_similarity("", "") == 1.0

    def test_one_empty(self):
        assert overlap_similarity("", "abc") == 0.0

    def test_disjoint(self):
        assert overlap_similarity("abc", "xyz") == 0.0

    def test_partial(self):
        assert 0.0 < overlap_similarity("abc", "abd") < 1.0


class TestExtractTable:
    def test_extracts_the_table(self):
        out = agent().extract_table("<p>x</p><table><tr><td>a</td></tr></table>")
        assert out["html"] == "<table><tr><td>a</td></tr></table>"

    def test_strips_code_fences(self):
        out = agent().extract_table("```html\n<table><tr><td>a</td></tr></table>\n```")
        assert out["html"] == "<table><tr><td>a</td></tr></table>"

    def test_no_table(self):
        assert agent().extract_table("just text")["html"] == ""


class TestNormalizeTable:
    def test_attributes_are_dropped(self):
        out = agent().normalize_table('<table border="1"><tr><td>a</td></tr></table>')
        assert out["html"] == "<table><tr><td>a</td></tr></table>"

    def test_th_becomes_td(self):
        out = agent().normalize_table("<table><tr><th>a</th></tr></table>")
        assert out["html"] == "<table><tr><td>a</td></tr></table>"

    def test_span_is_kept(self):
        out = agent().normalize_table('<table><tr><td colspan="2">a</td></tr></table>')
        assert 'colspan="2"' in out["html"]


class TestIsValidTable:
    def test_valid(self):
        assert agent().is_valid_table("<table><tr><td>a</td></tr></table>")["valid"] is True

    def test_no_rows(self):
        assert agent().is_valid_table("<table></table>")["valid"] is False

    def test_empty(self):
        assert agent().is_valid_table("")["valid"] is False


class TestBuildCandidates:
    def test_providers_are_included(self):
        out = agent().build_candidates(record())
        assert [c["name"] for c in out["candidates"]] == ["a", "b"]

    def test_non_table_provider_is_excluded(self):
        out = agent().build_candidates(record(kind_d="text"))
        assert [c["name"] for c in out["candidates"]] == ["b"]

    def test_generations_are_included(self):
        out = agent().build_candidates(
            record(),
            greedy="<table><tr><td>g</td></tr></table>",
            samples=["<table><tr><td>s</td></tr></table>"],
        )
        assert [c["name"] for c in out["candidates"]] == ["a", "b", "v0", "v1"]

    def test_max_chars_drops_long_generations(self):
        long_html = "<table><tr><td>" + "x" * 100 + "</td></tr></table>"
        out = agent().build_candidates(record(), greedy=long_html, max_chars=50)
        assert [c["name"] for c in out["candidates"]] == ["a", "b"]


class TestSelectTable:
    def test_no_candidates(self):
        out = agent().select_table({"kind_d": "text", "kind_m": "text"})
        assert out["decision"] is None
        assert out["stats"]["no-cand"] == 1

    def test_provider_medoid_selects_the_provider(self):
        out = agent().select_table(record(), greedy="<table><tr><td>vlm</td></tr></table>")
        assert out["decision"]["action"] in ("select_a", "select_b")

    def test_vlm_wins_when_providers_disagree(self):
        rec = {
            "kind_d": "table",
            "kind_m": "table",
            "md_d": "<table><tr><td>aaa</td></tr></table>",
            "md_m": "<table><tr><td>bbb</td></tr></table>",
        }
        a = TableSpecialistAgent(similarity=exact_sim)
        out = a.select_table(
            rec,
            greedy="<table><tr><td>vlm</td></tr></table>",
            samples=["<table><tr><td>vlm</td></tr></table>"],
        )
        assert out["decision"]["action"] == "replace"
        assert out["stats"]["medoid-v"] == 1


class TestSelectGreedy:
    def test_no_greedy(self):
        out = agent().select_greedy(record())
        assert out["decision"] is None
        assert out["stats"]["no-greedy"] == 1

    def test_greedy_replaces_when_different(self):
        out = agent().select_greedy(record(), greedy="<table><tr><td>vlm</td></tr></table>")
        assert out["decision"]["action"] == "replace"

    def test_greedy_close_to_a_provider_selects_it(self):
        rec = {
            "kind_d": "table",
            "kind_m": "table",
            "md_d": "<table><tr><td>same</td></tr></table>",
            "md_m": "<table><tr><td>other</td></tr></table>",
        }
        a = TableSpecialistAgent(similarity=exact_sim)
        out = a.select_greedy(rec, greedy="<table><tr><td>same</td></tr></table>")
        assert out["decision"]["action"] == "select_a"
        assert out["stats"]["greedy-select"] == 1
