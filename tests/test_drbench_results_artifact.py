"""Tests for the frozen result artifacts.

The run outputs live outside the repository (on the cluster scratch). Without a
frozen artifact the numbers, the submission hashes and the composition of each
run would be lost, and the performance work could not be resumed.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = REPO_ROOT / "docs" / "drbench" / "experiments"
RESULTS = DOCS / "RESULTS.json"
LEADERBOARD = DOCS / "SUBMISSIONS-LEADERBOARD.md"


@pytest.fixture(scope="module")
def results() -> dict:
    return json.loads(RESULTS.read_text(encoding="utf-8"))


class TestResultsArtifact:
    def test_artifact_exists_and_is_valid_json(self, results):
        assert results["submissions"], "nenhuma submissão registrada"

    def test_every_submission_has_a_composition(self, results):
        for entry in results["submissions"]:
            assert entry.get("composition"), f"{entry['run']}: sem composição"
            assert entry.get("date"), f"{entry['run']}: sem data"
            assert entry.get("pages"), f"{entry['run']}: sem contagem de páginas"

    def test_every_submission_has_an_overall_score(self, results):
        for entry in results["submissions"]:
            assert "overall" in entry["evalai"], f"{entry['run']}: sem Overall"

    def test_overall_scores_are_in_range(self, results):
        for entry in results["submissions"]:
            score = entry["evalai"]["overall"]
            assert 0.0 <= score <= 100.0, f"{entry['run']}: Overall fora de [0,100]"

    def test_zip_hashes_are_sha256(self, results):
        for entry in results["submissions"]:
            digest = entry.get("zip_sha256")
            if digest is None:
                continue
            assert re.fullmatch(r"[a-f0-9]{64}", digest), (
                f"{entry['run']}: hash inválido ({digest})"
            )

    def test_exactly_one_confirmed_best(self, results):
        best = [s for s in results["submissions"] if s.get("confirmed_best")]
        assert len(best) == 1, "deve haver exatamente um melhor confirmado"

    def test_confirmed_best_is_the_highest_overall(self, results):
        best = next(s for s in results["submissions"] if s.get("confirmed_best"))
        highest = max(s["evalai"]["overall"] for s in results["submissions"])
        assert best["evalai"]["overall"] == highest

    def test_dev_best_is_marked_unconfirmed(self, results):
        dev = results["dev_best_unconfirmed"]
        assert dev["confirmed"] is False
        assert dev["dev_overall"] > results["gap_dev_to_test"]["confirmed_best_evalai"]

    def test_gap_is_consistent_with_the_scores(self, results):
        gap = results["gap_dev_to_test"]
        expected = gap["confirmed_best_dev986_md2md"] - gap["confirmed_best_evalai"]
        assert gap["delta"] == pytest.approx(expected, abs=0.01)


class TestResultsMatchTheLeaderboard:
    def test_confirmed_best_score_matches_the_leaderboard(self, results):
        text = LEADERBOARD.read_text(encoding="utf-8")
        best = next(s for s in results["submissions"] if s.get("confirmed_best"))
        assert f"Overall={best['evalai']['overall']}" in text

    def test_confirmed_best_hash_matches_the_leaderboard(self, results):
        text = LEADERBOARD.read_text(encoding="utf-8")
        best = next(s for s in results["submissions"] if s.get("confirmed_best"))
        assert best["zip_sha256"][:8] in text

    def test_every_recorded_hash_appears_in_the_leaderboard(self, results):
        text = LEADERBOARD.read_text(encoding="utf-8")
        for entry in results["submissions"]:
            digest = entry.get("zip_sha256")
            if digest is None:
                continue
            assert digest[:8] in text, f"{entry['run']}: hash ausente no leaderboard"


class TestNoGroundTruthIsStored:
    def test_artifact_holds_no_predictions_or_ground_truth(self, results):
        # A regra da PR: nada de GT nem predições no repositório.
        blob = json.dumps(results)
        for forbidden in ("layout_dets", "page_attribute", "mds/", "predictions/"):
            assert forbidden not in blob, f"artefato contém {forbidden!r}"
