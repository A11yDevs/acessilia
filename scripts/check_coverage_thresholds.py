"""Enforce the per-component branch-coverage thresholds (#648).

Each suite writes ``var/coverage/<component>/coverage.json``; this script
checks the numeric ``percent_covered`` total against the component's floor.
The thresholds sit a little below the measured release baseline so ordinary
changes have room, while a real drop fails the run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

#: Component directory -> minimum branch coverage percentage.
THRESHOLDS: dict[str, float] = {
    "app": 85.0,
    "docstruct": 86.0,
    "sdk": 96.0,
    "core": 82.0,
}


def _failure(component: str, reason: str) -> str:
    return f"{component}: {reason}"


def check_coverage(coverage_dir: Path) -> list[str]:
    """Return one message per missing or below-threshold report."""
    failures: list[str] = []
    for component, minimum in THRESHOLDS.items():
        report = coverage_dir / component / "coverage.json"
        if not report.is_file():
            failures.append(_failure(component, f"missing {report}"))
            continue
        try:
            payload = json.loads(report.read_text(encoding="utf-8"))
            percent = float(payload["totals"]["percent_covered"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            failures.append(_failure(component, f"unreadable report: {exc}"))
            continue
        if percent < minimum:
            failures.append(
                _failure(
                    component,
                    f"{percent:.1f}% < {minimum:.1f}% required",
                )
            )
    return failures


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage-dir",
        type=Path,
        default=Path("var/coverage"),
        help="Directory holding <component>/coverage.json",
    )
    args = parser.parse_args(argv)

    failures = check_coverage(args.coverage_dir)
    if failures:
        print("Coverage thresholds failed:", file=sys.stderr)
        for failure in failures:
            print(f"  {failure}", file=sys.stderr)
        return 1
    print(
        "Coverage thresholds passed: "
        + ", ".join(f"{name} >= {minimum:.1f}%" for name, minimum in THRESHOLDS.items())
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
