"""The #644 baseline instrumentation parses reports and compares baselines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.tests import collect_timings as timings

REPORT = """\
<testsuites>
  <testsuite name="pytest" tests="3" failures="1" errors="0" skipped="1" time="2.5">
    <testcase classname="tests.test_sample" name="test_fast" time="0.1"/>
    <testcase classname="tests.test_sample" name="test_slow" time="2.0">
      <failure message="boom"/>
    </testcase>
    <testcase classname="tests.test_sample" name="test_skipped" time="0.0">
      <skipped message="not here"/>
    </testcase>
  </testsuite>
</testsuites>
"""


def _write_report(path: Path) -> Path:
    path.write_text(REPORT, encoding="utf-8")
    return path


def _coverage(path: Path, percent: float = 91.5) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "totals": {
                    "percent_covered": percent,
                    "covered_lines": 183,
                    "num_statements": 200,
                    "covered_branches": 40,
                    "num_branches": 50,
                    "ignored": 4,
                }
            }
        ),
        encoding="utf-8",
    )
    return path


def _record(label: str, seconds: float, wall: float, percent: float) -> dict:
    return {
        "label": label,
        "tests": 10,
        "failed": 0,
        "errors": 0,
        "skipped": 0,
        "junit_seconds": seconds,
        "wall_seconds": wall,
        "p95_seconds": seconds / 2,
        "coverage": {"percent_covered": percent},
        "slowest": [{"nodeid": f"{label}::test", "outcome": "passed", "seconds": seconds}],
    }


def test_suite_record_summarizes_counts_timings_and_coverage(tmp_path: Path) -> None:
    report = _write_report(tmp_path / "results.xml")
    coverage = _coverage(tmp_path / "coverage.json")

    record = timings.suite_record(
        report,
        "app",
        root=tmp_path,
        coverage_report=coverage,
        wall_seconds=3.25,
        log=tmp_path / "pytest.log",
    )

    assert record["tests"] == 3
    assert record["passed"] == 1
    assert record["failed"] == 1
    assert record["skipped"] == 1
    assert record["junit_seconds"] == 2.5
    assert record["wall_seconds"] == 3.25
    assert record["p95_seconds"] == 2.0
    assert record["coverage"]["percent_covered"] == 91.5
    assert record["coverage"]["covered_lines"] == 183
    assert "ignored" not in record["coverage"]
    assert record["slowest"][0]["nodeid"].endswith("::test_slow")


def test_coverage_totals_tolerate_missing_and_broken_reports(tmp_path: Path) -> None:
    assert timings._coverage_totals(tmp_path / "absent.json") is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert timings._coverage_totals(broken) is None

    unexpected = tmp_path / "unexpected.json"
    unexpected.write_text(json.dumps({"totals": []}), encoding="utf-8")
    assert timings._coverage_totals(unexpected) is None


def test_render_summary_lists_every_suite_and_total() -> None:
    baseline = {
        "environment": {"revision": "a" * 40, "python": "3.12.13", "xdist_workers": 4},
        "suites": [_record("app", 10.0, 12.0, 86.0), _record("core", 2.0, 3.0, 83.0)],
        "totals": {"tests": 20, "junit_seconds": 12.0, "wall_seconds": 15.0},
    }

    summary = timings.render_summary(baseline)

    assert "`" + "a" * 40 + "`" in summary
    assert "| app | 10 | 0 | 10.00 | 12.00 |" in summary
    assert "| core | 10 | 0 | 2.00 | 3.00 |" in summary
    assert "20 tests, 12.00s of JUnit time and 15.00s of wall-clock time" in summary


def test_compare_reports_signed_deltas() -> None:
    before = {
        "environment": {"revision": "before"},
        "suites": [_record("app", 10.0, 12.0, 86.0)],
        "totals": {"tests": 10, "junit_seconds": 10.0, "wall_seconds": 12.0},
    }
    after = {
        "environment": {"revision": "after"},
        "suites": [{**_record("app", 7.5, 9.0, 85.5), "tests": 9}],
        "totals": {"tests": 9, "junit_seconds": 7.5, "wall_seconds": 9.0},
    }

    comparison = timings.compare(before, after)

    suite = comparison["suites"][0]
    assert suite["label"] == "app"
    assert suite["tests"] == -1
    assert suite["junit_seconds"] == -2.5
    assert suite["wall_seconds"] == -3.0
    assert suite["coverage_percent"] == -0.5
    assert comparison["totals"] == {
        "tests": -1,
        "junit_seconds": -2.5,
        "wall_seconds": -3.0,
    }

    summary = timings.render_comparison(comparison)
    assert "| app | -1.000 | -2.500 | -3.000 | -1.250 | -0.500 |" in summary


def test_main_collect_reads_junit_reports_and_writes_the_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = _write_report(tmp_path / "app.xml")
    _coverage(tmp_path / "coverage" / "app" / "coverage.json")
    output = tmp_path / "baseline.json"
    summary = tmp_path / "summary.md"

    status = timings.main(
        [
            "collect",
            "--report",
            f"app={report}",
            "--coverage-dir",
            str(tmp_path / "coverage"),
            "--output",
            str(output),
            "--summary",
            str(summary),
        ]
    )

    assert status == 1  # the synthetic report contains a failure
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["schema_version"] == timings.SCHEMA_VERSION
    assert payload["kind"] == "junit"
    assert payload["suites"][0]["label"] == "app"
    assert payload["suites"][0]["coverage"]["percent_covered"] == 91.5
    assert summary.read_text(encoding="utf-8").startswith("## Test suite baseline")
    assert "Total: 3 tests" in capsys.readouterr().out


def test_main_collect_rejects_a_missing_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = timings.main(
        [
            "collect",
            "--report",
            f"app={tmp_path / 'missing.xml'}",
            "--output",
            str(tmp_path / "baseline.json"),
        ]
    )

    assert status == 2
    assert "missing reports" in capsys.readouterr().err


def test_main_collect_rejects_an_unknown_suite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = timings.main(
        [
            "collect",
            "--report",
            f"unknown={tmp_path / 'results.xml'}",
            "--output",
            str(tmp_path / "baseline.json"),
        ]
    )

    assert status == 2
    assert "unknown suite" in capsys.readouterr().err


def test_main_compare_writes_json_and_summary(tmp_path: Path) -> None:
    before = tmp_path / "before.json"
    after = tmp_path / "after.json"
    before.write_text(
        json.dumps({"suites": [_record("app", 10.0, 12.0, 86.0)], "totals": {}}),
        encoding="utf-8",
    )
    after.write_text(
        json.dumps({"suites": [_record("app", 8.0, 9.0, 86.0)], "totals": {}}),
        encoding="utf-8",
    )
    comparison = tmp_path / "comparison.json"
    summary = tmp_path / "comparison.md"

    status = timings.main(
        [
            "compare",
            str(before),
            str(after),
            "--json",
            str(comparison),
            "--summary",
            str(summary),
        ]
    )

    assert status == 0
    assert json.loads(comparison.read_text(encoding="utf-8"))["suites"][0][
        "junit_seconds"
    ] == -2.0
    assert summary.read_text(encoding="utf-8").startswith("## Baseline comparison")


def test_main_compare_rejects_an_unreadable_baseline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    status = timings.main(["compare", str(broken), str(broken)])

    assert status == 2
    assert "error:" in capsys.readouterr().err


def test_the_optimization_documentation_has_a_linked_mirror() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs" / "testing"
    english = (docs / "optimization.md").read_text(encoding="utf-8")
    portuguese = (docs / "optimization.pt-br.md").read_text(encoding="utf-8")

    assert "(optimization.pt-br.md)" in english
    assert "(optimization.md)" in portuguese
    assert (docs / "baseline.json").is_file()


def test_only_known_suite_labels_are_accepted() -> None:
    assert timings._spec("app").label == "app"
    with pytest.raises(ValueError, match="unknown suite"):
        timings._spec("frontend")
