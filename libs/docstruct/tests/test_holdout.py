"""Testes da disciplina de holdout (``docstruct.evaluation.holdout``).

Espelham a disciplina do loop do Dr.DocBench (PR #125): split por documento e
critério de aceite tune/holdout.
"""
import hashlib

import pytest

from docstruct.evaluation.holdout import (
    LOOP_METRICS,
    document_id,
    evaluate_candidate,
    partition,
    score,
)


def window(doc: str, page: int = 1) -> str:
    return f"{doc}_page_{page}"


def windows(n_docs: int = 9, **values) -> dict[str, dict]:
    base = {"text": 80.0, "reading_order": 80.0, "teds": 60.0}
    base.update(values)
    return {window(f"doc{i}"): dict(base) for i in range(n_docs)}


class TestDocumentId:
    def test_extracts_the_document(self):
        assert document_id("abc_page_12") == "abc"

    def test_no_page_suffix(self):
        assert document_id("abc") == "abc"


class TestPartition:
    def test_is_deterministic(self):
        assert partition("doc1_page_1") == partition("doc1_page_1")

    def test_same_document_same_partition(self):
        # O split é por documento: páginas do mesmo doc não se separam.
        assert partition("doc1_page_1") == partition("doc1_page_99")

    def test_uses_md5_mod_3(self):
        for i in range(50):
            doc = f"doc{i}"
            expected = (
                "hold"
                if int(hashlib.md5(doc.encode()).hexdigest(), 16) % 3 == 0
                else "tune"
            )
            assert partition(window(doc)) == expected

    def test_both_partitions_are_populated(self):
        parts = {partition(window(f"doc{i}")) for i in range(30)}
        assert parts == {"tune", "hold"}


class TestScore:
    def test_means_per_metric(self):
        w = {"doc1_page_1": {"text": 80.0, "reading_order": 90.0, "teds": 70.0}}
        out = score(w, "all")
        assert out["text"] == 80.0
        assert out["evalai"] == pytest.approx(80.0)

    def test_missing_metrics_are_skipped(self):
        w = {"doc1_page_1": {"text": 80.0, "reading_order": None, "teds": 60.0}}
        out = score(w, "all")
        assert out["reading_order"] != out["reading_order"]  # nan

    def test_subset_filters_by_partition(self):
        w = windows(9)
        tune = score(w, "tune")
        hold = score(w, "hold")
        assert tune["text"] == 80.0
        assert hold["text"] == 80.0

    def test_empty_subset_is_nan(self):
        out = score({}, "tune")
        assert out["text"] != out["text"]


class TestEvaluateCandidate:
    def test_improvement_on_both_subsets_is_accepted(self):
        base = windows(9)
        cand = {k: {**v, "text": v["text"] + 1.0} for k, v in base.items()}
        verdict = evaluate_candidate(base, cand)
        assert verdict.accepted is True
        assert verdict.tune_delta == pytest.approx(1 / 3)
        assert verdict.holdout_delta == pytest.approx(1 / 3)

    def test_no_tune_gain_is_rejected(self):
        base = windows(9)
        verdict = evaluate_candidate(base, base)
        assert verdict.accepted is False
        assert "Δtune" in verdict.reason

    def test_holdout_loss_is_rejected(self):
        base = windows(9)
        cand = {}
        for k, v in base.items():
            if partition(k) == "hold":
                cand[k] = {**v, "text": v["text"] - 5.0}
            else:
                cand[k] = {**v, "text": v["text"] + 5.0}
        verdict = evaluate_candidate(base, cand)
        assert verdict.accepted is False
        assert "Δhold" in verdict.reason

    def test_single_metric_collapse_is_rejected(self):
        # A média sobe (Δtune e Δhold positivos), mas o TEDS colapsa.
        base = windows(9)
        cand = {
            k: {**v, "text": v["text"] + 5.0, "reading_order": v["reading_order"] + 5.0,
                "teds": v["teds"] - 5.0}
            for k, v in base.items()
        }
        verdict = evaluate_candidate(base, cand)
        assert verdict.accepted is False
        assert "teds" in verdict.reason
        assert verdict.tune_delta > 0 and verdict.holdout_delta > 0

    def test_metric_deltas_are_reported(self):
        base = windows(9)
        cand = {k: {**v, "text": v["text"] + 1.0} for k, v in base.items()}
        verdict = evaluate_candidate(base, cand)
        assert set(verdict.metric_deltas) == {
            f"{subset}_{m}" for subset in ("tune", "hold") for m in LOOP_METRICS
        }

    def test_thresholds_are_configurable(self):
        base = windows(9)
        cand = {k: {**v, "text": v["text"] + 0.05} for k, v in base.items()}
        assert evaluate_candidate(base, cand).accepted is False
        assert evaluate_candidate(base, cand, min_tune_gain=0.0).accepted is True
