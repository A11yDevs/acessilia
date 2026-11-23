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


def test_suite_record_prefixes_nodeids_and_relativizes_the_log(tmp_path: Path) -> None:
    report = _write_report(tmp_path / "results.xml")
    log = tmp_path / "var" / "pytest.log"
    log.parent.mkdir(parents=True)
    log.write_text("log", encoding="utf-8")

    record = timings.suite_record(
        report,
        "sdk",
        root=tmp_path,
        log=log,
        log_root=tmp_path,
        nodeid_prefix=Path("libs/sdk"),
    )

    assert record["slowest"][0]["nodeid"] == (
        "libs/sdk/tests/test_sample.py::test_slow"
    )
    assert record["log"] == "var/pytest.log"


def test_suite_total_does_not_invent_wall_time(tmp_path: Path) -> None:
    report = _write_report(tmp_path / "results.xml")
    record = timings.suite_record(report, "app", root=tmp_path)

    total = timings._suite_total([record])

    assert total["wall_seconds"] is None
    assert total["junit_seconds"] == 2.5


def test_coverage_totals_tolerate_missing_and_broken_reports(tmp_path: Path) -> None:
    assert timings._coverage_totals(tmp_path / "absent.json") is None

    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    assert timings._coverage_totals(broken) is None

    unexpected = tmp_path / "unexpected.json"
    unexpected.write_text(json.dumps({"totals": []}), encoding="utf-8")
    assert timings._coverage_totals(unexpected) is None


def test_combine_runs_reports_median_and_range() -> None:
    runs = [
        {**_record("app", 9.0, 10.0, 86.0), "p50_seconds": 0.1},
        {**_record("app", 10.0, 12.0, 86.0), "p50_seconds": 0.2},
        {**_record("app", 11.0, 14.0, 86.0), "p50_seconds": 0.3},
    ]

    combined = timings.combine_runs(runs)

    assert combined["junit_seconds"] == 10.0
    assert combined["wall_seconds"] == 12.0
    assert combined["wall_seconds_min"] == 10.0
    assert combined["wall_seconds_max"] == 14.0
    assert combined["runs_count"] == 3
    assert combined["runs"] == runs

    summary = timings.render_summary(
        {
            "environment": {"revision": "a" * 40, "python": "3.12.13", "xdist_workers": 4},
            "suites": [combined],
            "totals": {"tests": 10, "junit_seconds": 10.0, "wall_seconds": 12.0},
        }
    )
    assert "12.00 (10.00–14.00)" in summary


def test_combine_runs_rejects_an_empty_list() -> None:
    with pytest.raises(ValueError, match="at least one run"):
        timings.combine_runs([])


def test_run_suite_without_a_junit_report_is_a_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Completed:
        returncode = 1
        stdout = ""
        stderr = "pytest crashed"

    def fake_run(*args, **kwargs):
        return Completed()

    monkeypatch.setattr(timings.subprocess, "run", fake_run)

    record = timings.run_suite(
        timings._spec("app"),
        root=tmp_path,
        work_dir=tmp_path / "work",
    )

    assert record["failed"] == 1
    assert "without a JUnit report" in record["error"]


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


def test_render_summary_marks_an_unmeasured_wall_time() -> None:
    baseline = {
        "environment": {"revision": "a" * 40, "python": "3.12.13", "xdist_workers": None},
        "suites": [{**_record("app", 10.0, 0.0, 86.0), "wall_seconds": None}],
        "totals": {"tests": 10, "junit_seconds": 10.0, "wall_seconds": None},
    }

    summary = timings.render_summary(baseline)

    assert "xdist workers: unknown" in summary
    assert "wall-clock time not measured" in summary
    assert "0.00s of wall-clock time" not in summary


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


def test_compare_does_not_invent_a_wall_delta() -> None:
    before = {
        "suites": [_record("app", 10.0, 12.0, 86.0)],
        "totals": {"tests": 10, "junit_seconds": 10.0, "wall_seconds": 12.0},
    }
    after = {
        "suites": [{**_record("app", 8.0, 0.0, 86.0), "wall_seconds": None}],
        "totals": {"tests": 10, "junit_seconds": 8.0, "wall_seconds": None},
    }

    comparison = timings.compare(before, after)

    assert comparison["totals"]["wall_seconds"] is None
    assert "wall-clock time not measured" in timings.render_comparison(comparison)
    assert "0.00s of wall-clock time" not in timings.render_comparison(comparison)


def test_suite_command_keeps_the_parallel_app_run_and_serial_libraries() -> None:
    app = timings._suite_command(
        timings._spec("app"), timings.ROOT, Path("r.xml"), Path("c.json"), xdist=4
    )
    sdk = timings._suite_command(
        timings._spec("sdk"), timings.ROOT, Path("r.xml"), Path("c.json"), xdist=4
    )

    assert "-n" in app and "4" in app and "--dist" in app and "worksteal" in app
    assert "-n" not in sdk
    assert "--cov=backend" in app and "--cov=frontend" in app
    assert "--cov=acessilia_sdk" in sdk
    assert "--cov-branch" in app and "--cov-branch" in sdk


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
    assert payload["totals"]["wall_seconds"] is None


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


def test_main_collect_rejects_a_truncated_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    report = tmp_path / "truncated.xml"
    report.write_text("<testsuites><testsuite><testcase", encoding="utf-8")

    status = timings.main(
        [
            "collect",
            "--report",
            f"app={report}",
            "--output",
            str(tmp_path / "baseline.json"),
        ]
    )

    assert status == 2
    assert "error:" in capsys.readouterr().err


def test_main_collect_rejects_a_non_positive_repeat(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = timings.main(
        [
            "collect",
            "--run",
            "--repeat",
            "0",
            "--output",
            str(tmp_path / "baseline.json"),
        ]
    )

    assert status == 2
    assert "--repeat must be at least 1" in capsys.readouterr().err


def test_main_collect_rejects_an_unknown_only_label(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    status = timings.main(
        [
            "collect",
            "--run",
            "--only",
            "app,bogus",
            "--work-dir",
            str(tmp_path),
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


def test_the_guide_table_matches_the_committed_baseline() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs" / "testing"
    baseline = json.loads((docs / "baseline.json").read_text(encoding="utf-8"))
    text = (docs / "optimization.md").read_text(encoding="utf-8")
    labels = {
        "Application (`tests/`)": "app",
        "docstruct": "docstruct",
        "SDK": "sdk",
        "core": "core",
    }
    rows = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and cells[0] in labels and len(cells) == 7:
            rows[labels[cells[0]]] = cells
    assert set(rows) == set(labels.values())
    for suite in baseline["suites"]:
        cells = rows[suite["label"]]
        assert int(cells[1].replace(",", "")) == suite["tests"]
        assert float(cells[2]) == pytest.approx(suite["junit_seconds"], abs=0.005)
        assert float(cells[3]) == pytest.approx(suite["wall_seconds"], abs=0.005)
        assert float(cells[4]) == pytest.approx(suite["p50_seconds"], abs=0.0005)
        assert float(cells[5]) == pytest.approx(suite["p95_seconds"], abs=0.0005)
        assert cells[6] == f"{suite['coverage']['percent_covered']:.1f}%"
