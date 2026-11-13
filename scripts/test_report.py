"""Summarize and compare pytest JUnit reports for scheduled monitoring.

The scheduled workflow runs the same non-E2E suite serially and with
``-n 4 --dist worksteal``. A test that passes in one mode and fails in the
other is an order or worker dependency, so the comparison exits non-zero.
"""

from __future__ import annotations

import argparse
import json
import math
import statistics
import sys
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class CaseResult:
    nodeid: str
    outcome: str
    seconds: float


@dataclass
class SuiteResult:
    label: str
    seconds: float
    cases: dict[str, CaseResult] = field(default_factory=dict)

    @property
    def tests(self) -> int:
        return len(self.cases)

    @property
    def passed(self) -> int:
        return sum(case.outcome == "passed" for case in self.cases.values())

    @property
    def failed(self) -> int:
        return sum(case.outcome == "failed" for case in self.cases.values())

    @property
    def errors(self) -> int:
        return sum(case.outcome == "error" for case in self.cases.values())

    @property
    def skipped(self) -> int:
        return sum(case.outcome == "skipped" for case in self.cases.values())

    @property
    def durations(self) -> list[float]:
        return [case.seconds for case in self.cases.values()]

    def percentile(self, fraction: float) -> float:
        values = sorted(self.durations)
        if not values:
            return 0.0
        index = max(0, math.ceil(fraction * len(values)) - 1)
        return values[min(index, len(values) - 1)]

    def slowest(self, limit: int = 5) -> list[CaseResult]:
        return sorted(self.cases.values(), key=lambda case: case.seconds, reverse=True)[
            :limit
        ]

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "tests": self.tests,
            "passed": self.passed,
            "failed": self.failed,
            "errors": self.errors,
            "skipped": self.skipped,
            "seconds": round(self.seconds, 3),
            "p50_seconds": round(statistics.median(self.durations), 3)
            if self.durations
            else 0.0,
            "p95_seconds": round(self.percentile(0.95), 3),
            "slowest": [
                {
                    "nodeid": case.nodeid,
                    "outcome": case.outcome,
                    "seconds": case.seconds,
                }
                for case in self.slowest()
            ],
        }


def _nodeid(case: ElementTree.Element) -> str:
    classname = case.get("classname", "")
    name = case.get("name", "")
    return f"{classname}::{name}" if classname else name


def _outcome(case: ElementTree.Element) -> str:
    if case.find("failure") is not None:
        return "failed"
    if case.find("error") is not None:
        return "error"
    if case.find("skipped") is not None:
        return "skipped"
    return "passed"


def parse_report(path: Path, label: str) -> SuiteResult:
    root = ElementTree.parse(path).getroot()
    suite_nodes = list(root.iter("testsuite"))
    if not suite_nodes:
        suite_nodes = [root]

    cases: dict[str, CaseResult] = {}
    for suite in suite_nodes:
        for case in suite.iter("testcase"):
            nodeid = _nodeid(case)
            unique = nodeid
            duplicate = 2
            while unique in cases:
                unique = f"{nodeid}#{duplicate}"
                duplicate += 1
            cases[unique] = CaseResult(
                nodeid=unique,
                outcome=_outcome(case),
                seconds=float(case.get("time", "0") or 0),
            )

    seconds = sum(float(suite.get("time", "0") or 0) for suite in suite_nodes)
    return SuiteResult(label=label, seconds=seconds, cases=cases)


def compare(serial: SuiteResult, parallel: SuiteResult) -> list[dict[str, str]]:
    differences: list[dict[str, str]] = []
    for nodeid in sorted(set(serial.cases) | set(parallel.cases)):
        serial_case = serial.cases.get(nodeid)
        parallel_case = parallel.cases.get(nodeid)
        if serial_case is None or parallel_case is None:
            differences.append(
                {
                    "nodeid": nodeid,
                    "serial": serial_case.outcome if serial_case else "missing",
                    "parallel": parallel_case.outcome if parallel_case else "missing",
                }
            )
        elif serial_case.outcome != parallel_case.outcome:
            differences.append(
                {
                    "nodeid": nodeid,
                    "serial": serial_case.outcome,
                    "parallel": parallel_case.outcome,
                }
            )
    return differences


def _summary_table(reports: list[SuiteResult]) -> list[str]:
    lines = [
        "| Suite | Tests | Passed | Failed | Errors | Skipped | JUnit time (s) | p50 (s) | p95 (s) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for report in reports:
        p50 = statistics.median(report.durations) if report.durations else 0.0
        lines.append(
            f"| {report.label} | {report.tests} | {report.passed} | {report.failed} "
            f"| {report.errors} | {report.skipped} | {report.seconds:.2f} "
            f"| {p50:.2f} | {report.percentile(0.95):.2f} |"
        )
    return lines


def render_summary(
    serial: SuiteResult,
    parallel: SuiteResult,
    differences: list[dict[str, str]],
    *,
    fail_on_skip: bool = False,
) -> str:
    lines = [
        "## Scheduled test monitoring",
        "",
        (
            "The same non-E2E core suite ran serially and with four workers "
            "(`--dist worksteal`)."
        ),
        "",
        *_summary_table([serial, parallel]),
        "",
        "### Outcome differences",
        "",
    ]
    if differences:
        lines += [
            (
                "A test with a different outcome between the runs is an order or "
                "worker dependency; this run fails."
            ),
            "",
            "| Test | Serial | Four workers |",
            "|---|---|---|",
        ]
        lines += [
            f"| `{item['nodeid']}` | {item['serial']} | {item['parallel']} |"
            for item in differences
        ]
    else:
        lines.append("No outcome differences between the serial and parallel runs.")

    if serial.failed or serial.errors or parallel.failed or parallel.errors:
        lines += [
            "",
            (
                "At least one suite contains failures; the run fails even when both "
                "modes agree."
            ),
        ]
    if fail_on_skip and (serial.skipped or parallel.skipped):
        lines += [
            "",
            (
                "At least one suite skipped a test; the run fails because the "
                "non-E2E gate must not skip."
            ),
        ]

    lines += ["", "### Slowest tests", ""]
    for report in (serial, parallel):
        lines.append(f"**{report.label}**")
        lines.append("")
        lines.append("| Test | Outcome | Seconds |")
        lines.append("|---|---|---:|")
        for case in report.slowest():
            lines.append(f"| `{case.nodeid}` | {case.outcome} | {case.seconds:.2f} |")
        lines.append("")

    lines.append(
        "JUnit time covers the tests; the job duration in GitHub Actions is the "
        "runner-consumption reference."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("serial", type=Path, help="JUnit XML from the serial run")
    parser.add_argument(
        "parallel", type=Path, help="JUnit XML from the four-worker run"
    )
    parser.add_argument("--json", type=Path, help="write a machine-readable summary")
    parser.add_argument(
        "--summary",
        type=Path,
        help="append the Markdown summary (use $GITHUB_STEP_SUMMARY in CI)",
    )
    parser.add_argument(
        "--fail-on-skip",
        action="store_true",
        help="fail when either suite skipped a test",
    )
    args = parser.parse_args(argv)

    try:
        serial = parse_report(args.serial, "serial")
        parallel = parse_report(args.parallel, "four workers / worksteal")
    except (OSError, ElementTree.ParseError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    differences = compare(serial, parallel)
    summary = render_summary(
        serial, parallel, differences, fail_on_skip=args.fail_on_skip
    )
    print(summary)

    if args.summary:
        with args.summary.open("a", encoding="utf-8") as handle:
            handle.write(summary)
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "serial": serial.to_dict(),
                    "parallel": parallel.to_dict(),
                    "differences": differences,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    has_failures = serial.failed + serial.errors + parallel.failed + parallel.errors > 0
    has_skips = serial.skipped + parallel.skipped > 0
    return 1 if differences or has_failures or (args.fail_on_skip and has_skips) else 0


if __name__ == "__main__":
    raise SystemExit(main())
