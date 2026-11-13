"""The scheduled monitoring report and its serial/parallel comparison."""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

from scripts import test_report


def _write_report(path: Path, cases: list[tuple[str, str, str, float]]) -> Path:
    suite = ElementTree.Element(
        "testsuite",
        name="pytest",
        tests=str(len(cases)),
        failures=str(sum(outcome == "failed" for _, _, outcome, _ in cases)),
        errors=str(sum(outcome == "error" for _, _, outcome, _ in cases)),
        skipped=str(sum(outcome == "skipped" for _, _, outcome, _ in cases)),
        time=str(sum(seconds for _, _, _, seconds in cases)),
    )
    for classname, name, outcome, seconds in cases:
        case = ElementTree.SubElement(
            suite,
            "testcase",
            classname=classname,
            name=name,
            time=str(seconds),
        )
        if outcome in {"failed", "error", "skipped"}:
            tag = "failure" if outcome == "failed" else outcome
            ElementTree.SubElement(case, tag, message=outcome)
    root = ElementTree.Element("testsuites")
    root.append(suite)
    path.write_bytes(ElementTree.tostring(root, encoding="utf-8"))
    return path


def test_parse_report_summarizes_outcomes_and_percentiles(tmp_path: Path) -> None:
    report = _write_report(
        tmp_path / "report.xml",
        [
            ("tests.test_a", "test_one", "passed", 1.0),
            ("tests.test_a", "test_two", "passed", 2.0),
            ("tests.test_a", "test_three", "passed", 3.0),
        ],
    )

    suite = test_report.parse_report(report, "serial")

    assert (suite.tests, suite.passed, suite.failed, suite.skipped) == (3, 3, 0, 0)
    assert suite.percentile(0.5) == 2.0
    assert suite.percentile(0.95) == 3.0
    assert suite.slowest(1)[0].nodeid == "tests/test_a.py::test_three"


def test_parse_report_turns_a_dotted_classname_into_a_runnable_nodeid(
    tmp_path: Path,
) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_a.py").write_text("", encoding="utf-8")
    report = _write_report(
        tmp_path / "report.xml",
        [("tests.test_a.TestFoo", "test_one", "passed", 1.0)],
    )

    suite = test_report.parse_report(report, "serial", root=tmp_path)

    assert set(suite.cases) == {"tests/test_a.py::TestFoo::test_one"}


def test_compare_reports_detects_outcome_and_missing_tests(tmp_path: Path) -> None:
    serial = test_report.parse_report(
        _write_report(
            tmp_path / "serial.xml",
            [
                ("tests.test_a", "test_one", "passed", 1.0),
                ("tests.test_a", "test_two", "failed", 2.0),
            ],
        ),
        "serial",
    )
    parallel = test_report.parse_report(
        _write_report(
            tmp_path / "parallel.xml",
            [
                ("tests.test_a", "test_one", "failed", 1.0),
                ("tests.test_a", "test_two", "failed", 2.0),
                ("tests.test_a", "test_three", "passed", 3.0),
            ],
        ),
        "four workers",
    )

    differences = test_report.compare(serial, parallel)

    assert differences == [
        {
            "nodeid": "tests/test_a.py::test_one",
            "serial": "passed",
            "parallel": "failed",
        },
        {
            "nodeid": "tests/test_a.py::test_three",
            "serial": "missing",
            "parallel": "passed",
        },
    ]


def test_main_writes_summary_and_fails_on_a_difference(tmp_path: Path, capsys) -> None:
    serial = _write_report(
        tmp_path / "serial.xml",
        [("tests.test_a", "test_one", "passed", 1.0)],
    )
    parallel = _write_report(
        tmp_path / "parallel.xml",
        [("tests.test_a", "test_one", "failed", 1.0)],
    )
    summary = tmp_path / "summary.md"
    payload = tmp_path / "summary.json"

    exit_code = test_report.main(
        [str(serial), str(parallel), "--summary", str(summary), "--json", str(payload)]
    )

    assert exit_code == 1
    assert "Outcome differences" in summary.read_text(encoding="utf-8")
    assert "tests/test_a.py::test_one" in payload.read_text(encoding="utf-8")
    assert "No outcome differences" not in capsys.readouterr().out


def test_main_passes_when_outcomes_match(tmp_path: Path, capsys) -> None:
    serial = _write_report(
        tmp_path / "serial.xml",
        [("tests.test_a", "test_one", "passed", 1.0)],
    )
    parallel = _write_report(
        tmp_path / "parallel.xml",
        [("tests.test_a", "test_one", "passed", 1.0)],
    )

    exit_code = test_report.main([str(serial), str(parallel)])

    assert exit_code == 0
    assert "No outcome differences" in capsys.readouterr().out


def test_main_can_reject_skips(tmp_path: Path, capsys) -> None:
    serial = _write_report(
        tmp_path / "serial.xml",
        [("tests.test_a", "test_one", "skipped", 0.0)],
    )
    parallel = _write_report(
        tmp_path / "parallel.xml",
        [("tests.test_a", "test_one", "skipped", 0.0)],
    )

    exit_code = test_report.main([str(serial), str(parallel), "--fail-on-skip"])

    assert exit_code == 1
    assert "must not skip" in capsys.readouterr().out


def test_main_fails_when_both_runs_have_the_same_failure(
    tmp_path: Path, capsys
) -> None:
    serial = _write_report(
        tmp_path / "serial.xml",
        [("tests.test_a", "test_one", "failed", 1.0)],
    )
    parallel = _write_report(
        tmp_path / "parallel.xml",
        [("tests.test_a", "test_one", "failed", 1.0)],
    )

    exit_code = test_report.main([str(serial), str(parallel)])

    assert exit_code == 1
    assert "At least one suite contains failures" in capsys.readouterr().out
