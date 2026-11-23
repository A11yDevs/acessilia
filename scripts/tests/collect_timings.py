"""Collect and compare a reproducible baseline of the four test suites (#644).

The baseline records the same measurements the project uses in CI: JUnit
durations per suite, the slowest tests, the wall-clock time of each suite run
and the branch-coverage totals. It is deliberately tooling-only: it belongs to
the development infrastructure under ``scripts/tests/`` and changes no test or
production code.

Two ways to produce a baseline:

* ``collect --run`` executes the application, docstruct, SDK and core suites
  from the root environment, writing JUnit and coverage reports under
  ``var/timings/``.
* ``collect --report app=test-results.xml ...`` reads reports produced by CI,
  so a run does not have to repeat the suites.

``compare`` subtracts a previous baseline from a new one; ``--summary`` writes
the Markdown used in pull requests and in ``docs/testing/optimization.md``.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Any, Sequence
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    # Running the file directly puts scripts/tests/ on sys.path, not the root.
    sys.path.insert(0, str(ROOT))

from scripts.test_report import parse_report  # noqa: E402
from scripts.tests.pytest_env import sanitized_environ  # noqa: E402

SCHEMA_VERSION = 1
DEFAULT_WORK_DIR = Path("var/timings")
DEFAULT_COVERAGE_DIR = Path("var/coverage")


@dataclass(frozen=True)
class SuiteSpec:
    """How to run one suite and which source tree its coverage measures."""

    label: str
    directory: Path
    coverage: tuple[str, ...]
    args: tuple[str, ...] = ()
    parallel: bool = False


SUITES: tuple[SuiteSpec, ...] = (
    SuiteSpec("app", Path("."), ("backend", "frontend"), ("-m", "not e2e"), True),
    SuiteSpec("docstruct", Path("libs/docstruct"), ("docstruct",)),
    SuiteSpec("sdk", Path("libs/sdk"), ("acessilia_sdk",)),
    SuiteSpec("core", Path("libs/core"), ("acessilia_core",)),
)
SUITE_LABELS = tuple(spec.label for spec in SUITES)


def _git_revision(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def environment(root: Path = ROOT, *, xdist: int | None = 4) -> dict[str, Any]:
    """The environment that makes a baseline comparable with another run."""
    versions: dict[str, str] = {}
    for package in ("pytest", "pytest-xdist", "coverage", "pytest-cov"):
        try:
            versions[package] = metadata.version(package)
        except metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "revision": _git_revision(root),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "xdist_workers": xdist,
        "packages": versions,
    }


def _coverage_totals(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    totals = payload.get("totals")
    if not isinstance(totals, dict):
        return None
    keys = (
        "percent_covered",
        "covered_lines",
        "num_statements",
        "covered_branches",
        "num_branches",
    )
    return {key: totals[key] for key in keys if key in totals}


def _nodeid(nodeid: str, prefix: Path | None) -> str:
    if prefix is None or prefix == Path("."):
        return nodeid
    return f"{prefix.as_posix().strip('/')}/{nodeid}"


def _display_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def suite_record(
    report: Path,
    label: str,
    *,
    root: Path = ROOT,
    coverage_report: Path | None = None,
    wall_seconds: float | None = None,
    log: Path | None = None,
    nodeid_prefix: Path | None = None,
    log_root: Path = ROOT,
) -> dict[str, Any]:
    """Summarize one suite's JUnit report, coverage totals and wall time.

    ``root`` is the directory the JUnit class names are relative to (the suite
    directory). ``nodeid_prefix`` turns those node ids into repository-relative
    ones, so the same test name cannot be confused between suites.
    """
    result = parse_report(report, label, root=root)
    record: dict[str, Any] = {
        "label": label,
        "tests": result.tests,
        "passed": result.passed,
        "failed": result.failed,
        "errors": result.errors,
        "skipped": result.skipped,
        "junit_seconds": round(result.seconds, 3),
        "p50_seconds": round(result.percentile(0.5), 4),
        "p95_seconds": round(result.percentile(0.95), 4),
        "slowest": [
            {
                "nodeid": _nodeid(case.nodeid, nodeid_prefix),
                "outcome": case.outcome,
                "seconds": round(case.seconds, 4),
            }
            for case in result.slowest(10)
        ],
    }
    if wall_seconds is not None:
        record["wall_seconds"] = round(wall_seconds, 3)
    if coverage_report is not None:
        record["coverage"] = _coverage_totals(coverage_report)
    if log is not None:
        record["log"] = _display_path(log, log_root)
    return record


def _suite_command(
    spec: SuiteSpec,
    root: Path,
    report: Path,
    coverage: Path,
    *,
    xdist: int,
) -> list[str]:
    command = [
        sys.executable,
        "-m",
        "pytest",
        *spec.args,
        f"--junitxml={report}",
        *[f"--cov={name}" for name in spec.coverage],
        "--cov-branch",
        f"--cov-config={root / 'pyproject.toml'}",
        f"--cov-report=json:{coverage}",
        "--durations=25",
        "-q",
    ]
    if spec.parallel and xdist > 0:
        command += ["-n", str(xdist), "--dist", "worksteal"]
    return command


def run_suite(
    spec: SuiteSpec,
    *,
    root: Path = ROOT,
    work_dir: Path = DEFAULT_WORK_DIR,
    xdist: int = 4,
    iteration: int | None = None,
) -> dict[str, Any]:
    """Run one suite, keeping its JUnit report, coverage JSON and full log."""
    if not work_dir.is_absolute():
        work_dir = root / work_dir
    suite_dir = work_dir / spec.label
    if iteration is not None:
        suite_dir /= f"run-{iteration}"
    suite_dir.mkdir(parents=True, exist_ok=True)
    report = suite_dir / "results.xml"
    coverage_dir = work_dir / "coverage" / spec.label
    if iteration is not None:
        coverage_dir /= f"run-{iteration}"
    coverage_dir.mkdir(parents=True, exist_ok=True)
    coverage = coverage_dir / "coverage.json"
    log = suite_dir / "pytest.log"
    command = _suite_command(spec, root, report, coverage, xdist=xdist)
    env = sanitized_environ()
    env["COVERAGE_FILE"] = str(coverage_dir / ".coverage")
    start = time.monotonic()
    completed = subprocess.run(
        command,
        cwd=root / spec.directory,
        env=env,
        text=True,
        capture_output=True,
    )
    wall_seconds = time.monotonic() - start
    log.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    if not report.is_file():
        return {
            "label": spec.label,
            "tests": 0,
            "failed": 1,
            "errors": 0,
            "skipped": 0,
            "junit_seconds": 0.0,
            "wall_seconds": round(wall_seconds, 3),
            "log": str(log),
            "error": f"pytest exited {completed.returncode} without a JUnit report",
        }
    record = suite_record(
        report,
        spec.label,
        root=root / spec.directory,
        coverage_report=coverage,
        wall_seconds=wall_seconds,
        log=log,
        nodeid_prefix=spec.directory,
        log_root=root,
    )
    record["exit_code"] = completed.returncode
    return record


def _spec(label: str) -> SuiteSpec:
    for spec in SUITES:
        if spec.label == label:
            return spec
    raise ValueError(f"unknown suite {label!r}; expected one of {', '.join(SUITE_LABELS)}")


def _parse_reports(values: Sequence[str]) -> dict[str, Path]:
    reports: dict[str, Path] = {}
    for value in values:
        label, separator, raw = value.partition("=")
        if not separator or not label or not raw:
            raise ValueError(f"expected LABEL=PATH, got {value!r}")
        _spec(label)
        reports[label] = Path(raw)
    return reports


def _median(values: Sequence[float]) -> float | None:
    return round(statistics.median(values), 4) if values else None


def combine_runs(runs: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """One suite record from repeated runs: median metrics plus dispersion."""
    if not runs:
        raise ValueError("at least one run is required")
    record = dict(runs[0])
    for key in ("junit_seconds", "wall_seconds", "p50_seconds", "p95_seconds"):
        values = [
            float(run[key]) for run in runs if isinstance(run.get(key), (int, float))
        ]
        median = _median(values)
        if median is None:
            record.pop(key, None)
        else:
            record[key] = median
    walls = [
        float(run["wall_seconds"])
        for run in runs
        if isinstance(run.get("wall_seconds"), (int, float))
    ]
    if walls:
        record["wall_seconds_min"] = round(min(walls), 3)
        record["wall_seconds_max"] = round(max(walls), 3)
    record["runs_count"] = len(runs)
    record["runs"] = list(runs)
    record["failed"] = max(int(run.get("failed", 0)) for run in runs)
    record["errors"] = max(int(run.get("errors", 0)) for run in runs)
    errors = [run["error"] for run in runs if run.get("error")]
    if errors:
        record["error"] = errors[0]
    exit_codes = []
    for run in runs:
        code = run.get("exit_code")
        if code is None and (run.get("failed") or run.get("errors")):
            code = 1
        if code:
            exit_codes.append(int(code))
    if exit_codes:
        record["exit_code"] = max(exit_codes)
    else:
        record.pop("exit_code", None)
    coverage = runs[-1].get("coverage")
    if coverage is not None:
        record["coverage"] = coverage
    return record


def _suite_total(records: Sequence[dict[str, Any]]) -> dict[str, float | int | None]:
    walls = [
        float(record["wall_seconds"])
        for record in records
        if isinstance(record.get("wall_seconds"), (int, float))
    ]
    return {
        "tests": sum(int(record.get("tests", 0)) for record in records),
        "junit_seconds": round(
            sum(float(record.get("junit_seconds", 0)) for record in records), 3
        ),
        "wall_seconds": round(sum(walls), 3) if walls else None,
    }


def render_summary(baseline: dict[str, Any]) -> str:
    """Markdown summary of one baseline, ready for a pull request body."""
    suites = baseline.get("suites", [])
    xdist = baseline.get("environment", {}).get("xdist_workers")
    lines = [
        "## Test suite baseline (#644)",
        "",
        f"- Revision: `{baseline.get('environment', {}).get('revision', 'unknown')}`",
        f"- Python: {baseline.get('environment', {}).get('python', 'unknown')}",
        f"- xdist workers: {xdist if xdist is not None else 'unknown'}",
        "",
        "| Suite | Tests | Failed | JUnit (s) | Wall (s) | p95 (s) | Coverage |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for record in suites:
        coverage = record.get("coverage") or {}
        percent = coverage.get("percent_covered")
        coverage_text = f"{percent:.1f}%" if isinstance(percent, (int, float)) else "—"
        wall = record.get("wall_seconds")
        if isinstance(wall, (int, float)) and record.get("runs_count", 1) > 1:
            wall_text = (
                f"{wall:.2f} ({record.get('wall_seconds_min', wall):.2f}–"
                f"{record.get('wall_seconds_max', wall):.2f})"
            )
        else:
            wall_text = f"{wall:.2f}" if isinstance(wall, (int, float)) else "—"
        p95 = record.get("p95_seconds")
        p95_text = f"{p95:.2f}" if isinstance(p95, (int, float)) else "—"
        lines.append(
            f"| {record['label']} | {record.get('tests', 0)} "
            f"| {record.get('failed', 0) + record.get('errors', 0)} "
            f"| {record.get('junit_seconds', 0):.2f} "
            f"| {wall_text} "
            f"| {p95_text} | {coverage_text} |"
        )
    totals = baseline.get("totals", {})
    wall = totals.get("wall_seconds")
    wall_text = (
        f"{wall:.2f}s of wall-clock time"
        if isinstance(wall, (int, float))
        else "wall-clock time not measured"
    )
    lines += [
        "",
        (
            f"Total: {int(totals.get('tests', 0))} tests, "
            f"{totals.get('junit_seconds', 0):.2f}s of JUnit time and {wall_text}."
        ),
        "",
        "### Slowest tests",
        "",
        "| Suite | Test | Seconds |",
        "|---|---|---:|",
    ]
    for record in suites:
        for case in record.get("slowest", [])[:5]:
            lines.append(
                f"| {record['label']} | `{case['nodeid']}` | {case['seconds']:.3f} |"
            )
    return "\n".join(lines) + "\n"


def _delta(before: Any, after: Any) -> float | None:
    if isinstance(before, (int, float)) and isinstance(after, (int, float)):
        return round(float(after) - float(before), 3)
    return None


def compare(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """Per-suite and total deltas; positive values mean ``after`` is slower."""
    old = {record["label"]: record for record in before.get("suites", [])}
    new = {record["label"]: record for record in after.get("suites", [])}
    suites: list[dict[str, Any]] = []
    for label in sorted(set(old) | set(new)):
        previous = old.get(label, {})
        current = new.get(label, {})
        suites.append(
            {
                "label": label,
                "tests": _delta(previous.get("tests"), current.get("tests")),
                "junit_seconds": _delta(
                    previous.get("junit_seconds"), current.get("junit_seconds")
                ),
                "wall_seconds": _delta(
                    previous.get("wall_seconds"), current.get("wall_seconds")
                ),
                "p95_seconds": _delta(
                    previous.get("p95_seconds"), current.get("p95_seconds")
                ),
                "coverage_percent": _delta(
                    (previous.get("coverage") or {}).get("percent_covered"),
                    (current.get("coverage") or {}).get("percent_covered"),
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "before": before.get("environment", {}),
        "after": after.get("environment", {}),
        "suites": suites,
        "totals": {
            "tests": _delta(
                before.get("totals", {}).get("tests"),
                after.get("totals", {}).get("tests"),
            ),
            "junit_seconds": _delta(
                before.get("totals", {}).get("junit_seconds"),
                after.get("totals", {}).get("junit_seconds"),
            ),
            "wall_seconds": _delta(
                before.get("totals", {}).get("wall_seconds"),
                after.get("totals", {}).get("wall_seconds"),
            ),
        },
    }


def render_comparison(comparison: dict[str, Any]) -> str:
    """Markdown table of the ``compare`` result."""
    lines = [
        "## Baseline comparison (#644)",
        "",
        "Positive deltas mean the later run is slower or larger.",
        "",
        "| Suite | Tests | JUnit (s) | Wall (s) | p95 (s) | Coverage (pp) |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for record in comparison.get("suites", []):
        values = []
        for key in ("tests", "junit_seconds", "wall_seconds", "p95_seconds", "coverage_percent"):
            value = record.get(key)
            values.append("—" if value is None else f"{value:+.3f}")
        lines.append(f"| {record['label']} | " + " | ".join(values) + " |")
    totals = comparison.get("totals", {})

    def _signed(value: Any, digits: int) -> str:
        if not isinstance(value, (int, float)):
            return "—"
        return f"{value:+.{digits}f}"

    wall = totals.get("wall_seconds")
    wall_text = (
        f"{wall:+.2f}s of wall-clock time"
        if isinstance(wall, (int, float))
        else "wall-clock time not measured"
    )
    lines += [
        "",
        (
            f"Total: {_signed(totals.get('tests'), 0)} tests, "
            f"{_signed(totals.get('junit_seconds'), 2)}s of JUnit time and "
            f"{wall_text}."
        ),
        "",
    ]
    return "\n".join(lines)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _collect_reports(
    args: argparse.Namespace, reports: dict[str, Path]
) -> dict[str, Any]:
    records = []
    missing = []
    for label in SUITE_LABELS:
        report = reports.get(label)
        if report is None:
            continue
        if not report.is_file():
            missing.append(str(report))
            continue
        spec = _spec(label)
        records.append(
            suite_record(
                report,
                label,
                root=ROOT / spec.directory,
                coverage_report=args.coverage_dir / label / "coverage.json",
                nodeid_prefix=spec.directory,
            )
        )
    if missing:
        raise FileNotFoundError("missing reports: " + ", ".join(missing))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "junit",
        "environment": environment(ROOT, xdist=None),
        "suites": records,
        "totals": _suite_total(records),
    }


def _collect_run(args: argparse.Namespace) -> dict[str, Any]:
    selected = [label.strip() for label in args.only.split(",") if label.strip()]
    if not selected:
        selected = list(SUITE_LABELS)
    for label in selected:
        _spec(label)
    records = []
    for label in selected:
        spec = _spec(label)
        runs = [
            run_suite(
                spec,
                root=ROOT,
                work_dir=args.work_dir,
                xdist=args.xdist,
                iteration=index if args.repeat > 1 else None,
            )
            for index in range(1, args.repeat + 1)
        ]
        records.append(combine_runs(runs) if args.repeat > 1 else runs[0])
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "run",
        "environment": environment(ROOT, xdist=args.xdist),
        "suites": records,
        "totals": _suite_total(records),
    }


def _failing(records: Sequence[dict[str, Any]]) -> bool:
    return any(
        record.get("failed", 0) or record.get("errors", 0) or record.get("exit_code")
        for record in records
    )


def _collect_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("collect", help="collect a new baseline")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--run", action="store_true", help="execute the four suites")
    mode.add_argument(
        "--report",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="read a JUnit report produced elsewhere; repeat per suite",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, help="write the Markdown summary here")
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--coverage-dir", type=Path, default=DEFAULT_COVERAGE_DIR)
    parser.add_argument("--xdist", type=int, default=4)
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="run each selected suite N times and report median/dispersion",
    )
    parser.add_argument(
        "--only",
        default="",
        help="comma-separated suites for --run (default: all four)",
    )
    parser.set_defaults(handler=_handle_collect)


def _compare_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("compare", help="compare two baselines")
    parser.add_argument("before", type=Path)
    parser.add_argument("after", type=Path)
    parser.add_argument("--json", type=Path, help="write the comparison as JSON")
    parser.add_argument("--summary", type=Path, help="write the Markdown comparison")
    parser.set_defaults(handler=_handle_compare)


def _append_summary(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(text)


def _handle_collect(args: argparse.Namespace) -> int:
    if not args.run and args.repeat != 1:
        print("error: --repeat is only valid with --run", file=sys.stderr)
        return 2
    if args.run and args.repeat < 1:
        print("error: --repeat must be at least 1", file=sys.stderr)
        return 2
    try:
        if args.run:
            baseline = _collect_run(args)
        else:
            reports = _parse_reports(args.report)
            baseline = _collect_reports(args, reports)
    except (
        ElementTree.ParseError,
        FileNotFoundError,
        OSError,
        ValueError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    summary = render_summary(baseline)
    print(summary)
    _write_json(args.output, baseline)
    if args.summary:
        _append_summary(args.summary, summary)
    return 1 if _failing(baseline["suites"]) else 0


def _handle_compare(args: argparse.Namespace) -> int:
    try:
        before = json.loads(args.before.read_text(encoding="utf-8"))
        after = json.loads(args.after.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    comparison = compare(before, after)
    summary = render_comparison(comparison)
    print(summary)
    if args.json:
        _write_json(args.json, comparison)
    if args.summary:
        _append_summary(args.summary, summary)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(required=True)
    _collect_parser(subparsers)
    _compare_parser(subparsers)
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
