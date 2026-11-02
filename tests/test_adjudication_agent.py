"""Tests for the AdjudicationAgent (Agno tools over the docstruct adjudication protocol).

Dr.DocBench PR #125. The deterministic ``process_*`` methods are exercised
directly so the tests run without Agno installed.
"""
from __future__ import annotations

from backend.core.agents.adjudication_agent import AdjudicationAgent


def agent() -> AdjudicationAgent:
    return AdjudicationAgent()


class TestRoutePage:
    def test_v1_default_prefers_docling_text(self):
        out = agent().route_page("a" * 200, "b" * 200)
        assert out == {"choice": "docling", "reason": "default_docling"}

    def test_v1_prefers_mineru_when_only_it_has_a_table(self):
        table = "<table><tr><td>" + "content " * 20 + "</td></tr></table>"
        out = agent().route_page("a" * 200, table)
        assert out["choice"] == "mineru"
        assert out["reason"] == "only_mineru_table"

    def test_v0_prefers_mineru_when_it_has_a_table(self):
        out = agent().route_page("a" * 200, "<table></table>", rule="v0")
        assert out == {"choice": "mineru", "reason": "mineru_has_table"}

    def test_near_empty_page_loses(self):
        out = agent().route_page("", "b" * 200)
        assert out["choice"] == "mineru"

    def test_invalid_rule(self):
        import pytest

        with pytest.raises(ValueError):
            agent().route_page("a", "b", rule="nope")


class TestDecideFromTranscription:
    def _record(self, a: str, b: str, i: int = 0, j: int = 0) -> dict:
        return {"page": "p", "i": i, "j": j, "md_d": a, "md_m": b}

    def test_transcription_matching_a_selects_a(self):
        out = agent().decide_from_transcription(
            self._record("hello world", "other text"), "hello world"
        )
        assert out["decision"] == {"action": "select_a"}

    def test_transcription_matching_b_selects_b(self):
        out = agent().decide_from_transcription(
            self._record("other text", "hello world"), "hello world"
        )
        assert out["decision"] == {"action": "select_b"}

    def test_plausible_different_transcription_replaces(self):
        out = agent().decide_from_transcription(
            self._record("hello world", "other text"), "hello there"
        )
        assert out["decision"]["action"] == "replace"

    def test_implausible_transcription_keeps_the_rule(self):
        out = agent().decide_from_transcription(
            self._record("hello world", "other text"), "x" * 500
        )
        assert out["decision"] is None

    def test_code_fences_are_stripped(self):
        out = agent().decide_from_transcription(
            self._record("hello world", "other text"), "```\nhello world\n```"
        )
        assert out["decision"] == {"action": "select_a"}

    def test_empty_marker_is_treated_as_empty(self):
        out = agent().decide_from_transcription(
            self._record("hello world", "other text"), "<EMPTY>"
        )
        assert out["decision"] is None


class TestFilterDecisions:
    def _record(self, a: str, b: str) -> dict:
        return {"page": "p", "i": 0, "j": 0, "md_d": a, "md_m": b}

    def test_replace_over_a_structural_block_is_dropped(self):
        out = agent().filter_decisions(
            [{"page": "p", "i": 0, "j": 0, "action": "replace", "text": "plain"}],
            [self._record("<table></table>", "text")],
            kind="notab",
        )
        assert out["kept"] == 0
        assert out["dropped"] == 1

    def test_replace_over_text_is_kept(self):
        out = agent().filter_decisions(
            [{"page": "p", "i": 0, "j": 0, "action": "replace", "text": "plain"}],
            [self._record("text a", "text b")],
            kind="notab",
        )
        assert out["kept"] == 1

    def test_sel_never_injects_text(self):
        out = agent().filter_decisions(
            [{"page": "p", "i": 0, "j": 0, "action": "replace", "text": "plain"}],
            [self._record("text a", "text b")],
            kind="sel",
        )
        assert out["kept"] == 0

    def test_decision_without_a_record_is_dropped(self):
        out = agent().filter_decisions(
            [{"page": "other", "i": 0, "j": 0, "action": "drop"}],
            [self._record("text a", "text b")],
        )
        assert out["kept"] == 0


class TestJudgePair:
    def test_new_wins_above_the_threshold(self):
        assert agent().judge_pair(0.6, 0.0)["take_new"] is True

    def test_old_judge_can_still_win(self):
        assert agent().judge_pair(0.4, 0.3)["take_new"] is True

    def test_neither_convinces(self):
        assert agent().judge_pair(0.4, 0.1)["take_new"] is False


class TestShouldJudge:
    def test_divergent_pages_are_judged(self):
        assert agent().should_judge("alpha beta gamma", "completely different")["should_judge"] is True

    def test_identical_pages_are_not_judged(self):
        assert agent().should_judge("same text here", "same text here")["should_judge"] is False

    def test_empty_candidate_is_not_judged(self):
        assert agent().should_judge("", "some text")["should_judge"] is False


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
        out = agent().select_page(
            "short", "vlm text", "same text", "same text", "stop"
        )
        assert out["swapped"] is False


class TestSwapLowAgreement:
    def test_low_agreement_swaps(self):
        out = agent().swap_low_agreement(
            "base text here", "alt text here", "aaa", "zzz"
        )
        assert out["swapped"] is True
        assert out["text"] == "alt text here"

    def test_missing_alternative_keeps_the_base(self):
        out = agent().swap_low_agreement("base", None, "d", "m")
        assert out["swapped"] is False

    def test_high_agreement_keeps_the_base(self):
        out = agent().swap_low_agreement("base", "alt", "same", "same")
        assert out["swapped"] is False


class TestOracleHeadroom:
    def test_oracle_picks_the_better_provider(self):
        gt = ["hello world this is long enough"]
        out = agent().oracle_headroom(
            gt, ["hello world this is long enough"], ["zzz"], ["zzz"]
        )
        assert out["oracle"] == 1.0
        assert out["headroom"] == 1.0

    def test_differ_at_oracle_has_no_headroom(self):
        gt = ["hello world this is long enough"]
        out = agent().oracle_headroom(
            gt, ["hello world this is long enough"], ["zzz"],
            ["hello world this is long enough"],
        )
        assert out["headroom"] == 0.0
