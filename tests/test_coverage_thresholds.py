"""Per-component coverage thresholds (#648)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import check_coverage_thresholds


def _report(root: Path, component: str, percent: float) -> None:
    path = root / component / "coverage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"totals": {"percent_covered": percent}}),
        encoding="utf-8",
    )


def test_each_component_at_or_above_its_floor_passes(tmp_path: Path) -> None:
    for component, minimum in check_coverage_thresholds.THRESHOLDS.items():
        _report(tmp_path, component, minimum)

    assert check_coverage_thresholds.check_coverage(tmp_path) == []


def test_a_component_below_its_floor_fails(tmp_path: Path) -> None:
    for component, minimum in check_coverage_thresholds.THRESHOLDS.items():
        _report(tmp_path, component, minimum)
    _report(tmp_path, "core", check_coverage_thresholds.THRESHOLDS["core"] - 0.1)

    failures = check_coverage_thresholds.check_coverage(tmp_path)

    assert len(failures) == 1
    assert failures[0].startswith("core:")
    assert "required" in failures[0]


def test_a_single_component_check_ignores_the_others(tmp_path: Path) -> None:
    _report(tmp_path, "docstruct", check_coverage_thresholds.THRESHOLDS["docstruct"])

    assert check_coverage_thresholds.check_coverage(tmp_path, ["docstruct"]) == []
    assert check_coverage_thresholds.main(
        ["--coverage-dir", str(tmp_path), "--components", "docstruct"]
    ) == 0


def test_an_unknown_component_is_refused(tmp_path: Path) -> None:
    failures = check_coverage_thresholds.check_coverage(tmp_path, ["frontend"])

    assert failures == ["unknown component: frontend"]


def test_a_missing_report_fails(tmp_path: Path) -> None:
    failures = check_coverage_thresholds.check_coverage(tmp_path)

    assert len(failures) == len(check_coverage_thresholds.THRESHOLDS)
    assert all("missing" in failure for failure in failures)


def test_main_reports_a_failure(tmp_path: Path, capsys) -> None:
    assert check_coverage_thresholds.main(["--coverage-dir", str(tmp_path)]) == 1
    assert "Coverage thresholds failed:" in capsys.readouterr().err


def test_main_reports_success(tmp_path: Path, capsys) -> None:
    for component, minimum in check_coverage_thresholds.THRESHOLDS.items():
        _report(tmp_path, component, minimum + 1)

    assert check_coverage_thresholds.main(["--coverage-dir", str(tmp_path)]) == 0
    assert "Coverage thresholds passed:" in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"totals": {}},
        {"totals": {"percent_covered": "n/a"}},
        {"totals": {"percent_covered": float("nan")}},
    ],
)
def test_an_unreadable_report_fails(tmp_path: Path, payload: dict) -> None:
    path = tmp_path / "core" / "coverage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")

    failures = check_coverage_thresholds.check_coverage(tmp_path)

    core = next(failure for failure in failures if failure.startswith("core:"))
    assert "unreadable report" in core
