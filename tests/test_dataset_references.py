"""Offline checks for the historical pipeline fixtures."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.bench.pipeline_fixtures import load_pipeline_fixtures

PINNED_CASES = Path(__file__).resolve().parent / "fixtures" / "pipeline-comparison"


def test_core_owned_pipeline_fixtures_keep_source_hashes_and_schema() -> None:
    manifest_path = PINNED_CASES / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["purpose"].startswith("Historical regression snapshots")
    assert manifest["source_revision"] == "9ed07b28aeddb69721228f2dd66de6f9794c0001"
    assert manifest["canonical_schema_version"] == "1.0.0"
    assert manifest["protocol"] == "historical-heuristic-v1"
    assert [case["id"] for case in manifest["cases"]] == ["001", "004", "005", "007", "008"]

    checked = load_pipeline_fixtures(PINNED_CASES)
    for case in checked:
        canonical_path = case["canonical_path"]
        assert hashlib.sha256(canonical_path.read_bytes()).hexdigest() == case["canonical_sha256"]
        canonical = json.loads(canonical_path.read_text(encoding="utf-8"))
        assert canonical["schema_version"] == manifest["canonical_schema_version"]


def test_missing_core_owned_fixture_fails_instead_of_skipping(tmp_path: Path) -> None:
    # The fixture verifier is intentionally strict: a missing copied baseline
    # is a broken Core checkout, not an optional Dataset E2E skip.
    with pytest.raises(FileNotFoundError):
        load_pipeline_fixtures(tmp_path)
