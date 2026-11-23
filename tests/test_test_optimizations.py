"""The #644 optimization records stay linked and machine-readable."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs" / "testing"


def test_the_optimization_documentation_has_a_linked_mirror() -> None:
    english = (DOCS / "optimizations.md").read_text(encoding="utf-8")
    portuguese = (DOCS / "optimizations.pt-br.md").read_text(encoding="utf-8")

    assert "(optimizations.pt-br.md)" in english
    assert "(optimizations.md)" in portuguese


def test_the_after_baseline_covers_all_four_suites() -> None:
    payload = json.loads((DOCS / "baseline-after.json").read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert {suite["label"] for suite in payload["suites"]} == {
        "app",
        "docstruct",
        "sdk",
        "core",
    }
    assert payload["totals"]["tests"] == sum(
        suite["tests"] for suite in payload["suites"]
    )
    assert all(suite["failed"] == 0 for suite in payload["suites"])
    assert all(suite["skipped"] == 0 for suite in payload["suites"])


def test_the_after_mutation_report_has_no_survivors() -> None:
    payload = json.loads(
        (DOCS / "mutation-flood-after.json").read_text(encoding="utf-8")
    )

    assert payload["summary"]["total"] == 17
    assert payload["summary"]["killed"] == 17
    assert payload["summary"]["survived"] == 0
    assert payload["summary"]["mutation_score"] == 1.0
    assert {mutant["status"] for mutant in payload["mutants"]} == {"killed"}
    exclusive = sorted(
        mutant["id"]
        for mutant in payload["mutants"]
        if len(mutant["killers"]) == 1
    )
    assert exclusive == ["M005", "M006", "M011", "M016"]
    english = (DOCS / "optimizations.md").read_text(encoding="utf-8")
    portuguese = (DOCS / "optimizations.pt-br.md").read_text(encoding="utf-8")
    assert "M005, M006, M011, M016" in english
    assert "M005, M006, M011, M016" in portuguese
