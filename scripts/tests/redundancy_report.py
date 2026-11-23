"""Turn a coverage-overlap report into ranked redundancy candidates (#644).

The overlap report says which tests look alike; this script adds the evidence
the review needs before touching anything:

* the duration of each test, when a baseline JSON is available;
* which of the two tests adds no line the other does not cover;
* whether the pair is a parametrization of the same test;
* the estimated wall-clock saving if a candidate is consolidated.

The report is advisory. It never edits, deletes or skips a test.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Candidate:
    test: str
    subsumed_by: str
    similarity: float
    shared: int
    unshared_lines: int
    seconds: float
    classification: str


@dataclass(frozen=True)
class PairReview:
    test_a: str
    test_b: str
    similarity: float
    shared: int
    only_a: int
    only_b: int
    same_parameterized_family: bool
    classification: str
    candidate: str | None
    saved_seconds: float


def load_durations(baseline: Path | None) -> dict[str, float]:
    """Per-test seconds from a ``collect_timings`` baseline's slowest lists."""
    if baseline is None or not baseline.is_file():
        return {}
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    durations: dict[str, float] = {}
    for suite in payload.get("suites", []):
        for case in suite.get("slowest", []):
            try:
                durations[case["nodeid"]] = float(case["seconds"])
            except (KeyError, TypeError, ValueError):
                continue
    return durations


def load_junit_durations(reports: Sequence[str]) -> dict[str, float]:
    """Per-test seconds from complete JUnit reports (``LABEL=PATH``)."""
    from scripts.test_report import parse_report

    durations: dict[str, float] = {}
    for value in reports:
        label, separator, raw = value.partition("=")
        if not separator or not label or not raw:
            raise ValueError(f"expected LABEL=PATH, got {value!r}")
        report = Path(raw)
        if not report.is_file():
            raise FileNotFoundError(report)
        parsed = parse_report(report, label, root=ROOT)
        durations.update({case.nodeid: case.seconds for case in parsed.cases.values()})
    return durations


def classify(similarity: float, same_family: bool) -> str:
    if same_family and similarity >= 0.9999:
        return "identical-parameterization"
    if similarity >= 0.99:
        return "near-identical"
    return "high-overlap"


def _candidate(
    pair: Mapping[str, Any],
    durations: Mapping[str, float],
    *,
    same_family: bool,
) -> tuple[str | None, float]:
    if same_family:
        return None, 0.0
    only_a = int(pair.get("only_a", 0))
    only_b = int(pair.get("only_b", 0))
    if only_b == 0 and only_a > 0:
        return str(pair["test_b"]), durations.get(str(pair["test_b"]), 0.0)
    if only_a == 0 and only_b > 0:
        return str(pair["test_a"]), durations.get(str(pair["test_a"]), 0.0)
    return None, 0.0


def review_pair(
    pair: Mapping[str, Any], durations: Mapping[str, float]
) -> PairReview:
    similarity = float(pair["similarity"])
    same_family = bool(pair.get("same_parameterized_family"))
    candidate, saved = _candidate(pair, durations, same_family=same_family)
    return PairReview(
        test_a=str(pair["test_a"]),
        test_b=str(pair["test_b"]),
        similarity=similarity,
        shared=int(pair.get("shared", 0)),
        only_a=int(pair.get("only_a", 0)),
        only_b=int(pair.get("only_b", 0)),
        same_parameterized_family=same_family,
        classification=classify(similarity, same_family),
        candidate=candidate,
        saved_seconds=round(saved, 4),
    )


def build_report(
    overlap: Mapping[str, Any],
    durations: Mapping[str, float],
    *,
    duration_source: str = "unavailable",
) -> dict:
    """Rank pairs and candidates by estimated saving, then by similarity."""
    reviewed = [review_pair(pair, durations) for pair in overlap.get("pairs", [])]
    reviewed.sort(key=lambda pair: (-pair.saved_seconds, -pair.similarity, pair.test_a))

    candidates: dict[str, Candidate] = {}
    for pair in reviewed:
        if pair.candidate is None:
            continue
        subsumed_by = pair.test_b if pair.candidate == pair.test_a else pair.test_a
        candidate = Candidate(
            test=pair.candidate,
            subsumed_by=subsumed_by,
            similarity=pair.similarity,
            shared=pair.shared,
            unshared_lines=0,
            seconds=durations.get(pair.candidate, 0.0),
            classification=pair.classification,
        )
        previous = candidates.get(candidate.test)
        if previous is None or candidate.seconds > previous.seconds:
            candidates[candidate.test] = candidate

    ordered = sorted(candidates.values(), key=lambda item: (-item.seconds, item.test))
    zero_exclusive = [
        {
            "test": item["test"],
            "elements": int(item.get("elements", 0)),
            "seconds": durations.get(item["test"], 0.0),
        }
        for item in overlap.get("zero_exclusive", [])
    ]
    zero_exclusive.sort(key=lambda item: (-item["seconds"], -item["elements"], item["test"]))
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "redundancy-report",
        "source": overlap.get("kind", "coverage-overlap"),
        "summary": {
            "pairs": len(reviewed),
            "candidates": len(ordered),
            "zero_exclusive": len(zero_exclusive),
            "estimated_savings_seconds": round(
                sum(candidate.seconds for candidate in ordered), 3
            ),
            "duration_source": duration_source if durations else "unavailable",
        },
        "candidates": [asdict(candidate) for candidate in ordered],
        "zero_exclusive": zero_exclusive,
        "pairs": [asdict(pair) for pair in reviewed],
    }


def render_summary(report: dict) -> str:
    """Markdown review sheet for the redundancy candidates."""
    summary = report["summary"]
    lines = [
        "## Redundancy candidates (#644)",
        "",
        (
            f"{summary['pairs']} overlapping pairs; {summary['candidates']} "
            f"pairwise coverage-subsumed candidates with about "
            f"{summary['estimated_savings_seconds']:.2f}s of measured time; "
            f"{summary.get('zero_exclusive', 0)} tests without an exclusive "
            f"production line."
        ),
        "",
        (
            "This is a review sheet, not a deletion list. \"Coverage-subsumed\" "
            "means only that the other test covers every measured line of the "
            "candidate; contracts, diagnostics and failure modes still have to "
            "be checked by hand."
        ),
        "",
        "| Candidate | Covered by | Similarity | Shared | Seconds | Classification |",
        "|---|---|---:|---:|---:|---|",
    ]
    for candidate in report["candidates"]:
        lines.append(
            f"| `{candidate['test']}` | `{candidate['subsumed_by']}` "
            f"| {candidate['similarity']:.3f} | {candidate['shared']} "
            f"| {candidate['seconds']:.3f} | {candidate['classification']} |"
        )
    if not report["candidates"]:
        lines.append("| — | — | — | — | — | — |")

    lines += [
        "",
        "### Tests with no exclusive production line",
        "",
        (
            "Every measured line of these tests is also covered by another test. "
            "Coverage omits the test files themselves, so this does not say the "
            "assertions are redundant; it is the shortlist for the mutation "
            "experiment, where equal coverage can hide different detection."
        ),
        "",
        "| Test | Lines | Seconds |",
        "|---|---:|---:|",
    ]
    for item in report.get("zero_exclusive", []):
        lines.append(
            f"| `{item['test']}` | {item['elements']} | {item['seconds']:.3f} |"
        )
    if not report.get("zero_exclusive"):
        lines.append("| — | — | — |")

    lines += [
        "",
        "### Reviewed pairs",
        "",
        "| Test A | Test B | Similarity | Only A | Only B | Candidate | Saved (s) |",
        "|---|---|---:|---:|---:|---|---:|",
    ]
    for pair in report["pairs"]:
        candidate = pair["candidate"] or "—"
        lines.append(
            f"| `{pair['test_a']}` | `{pair['test_b']}` | {pair['similarity']:.3f} "
            f"| {pair['only_a']} | {pair['only_b']} | `{candidate}` "
            f"| {pair['saved_seconds']:.3f} |"
        )
    if not report["pairs"]:
        lines.append("| — | — | — | — | — | — | — |")
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("overlap", type=Path, help="coverage_overlap.py JSON report")
    parser.add_argument(
        "--baseline",
        type=Path,
        help="collect_timings.py baseline for the slowest tests' durations",
    )
    parser.add_argument(
        "--junit",
        action="append",
        default=[],
        metavar="LABEL=PATH",
        help="JUnit report with every test duration; repeat per suite",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, help="write the Markdown review sheet")
    args = parser.parse_args(argv)

    try:
        overlap = json.loads(args.overlap.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.overlap}: {exc}", file=sys.stderr)
        return 2
    try:
        durations = load_durations(args.baseline)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read {args.baseline}: {exc}", file=sys.stderr)
        return 2
    source = "baseline" if durations else "unavailable"
    if args.junit:
        try:
            durations.update(load_junit_durations(args.junit))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: cannot read the JUnit reports: {exc}", file=sys.stderr)
            return 2
        source = "junit"

    report = build_report(overlap, durations, duration_source=source)
    summary = render_summary(report)
    print(summary)
    _write(args.output, json.dumps(report, indent=2) + "\n")
    if args.summary:
        _write(args.summary, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
