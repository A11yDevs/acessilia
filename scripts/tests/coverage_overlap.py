"""Find tests that exercise overlapping code with Coverage.py contexts (#644).

Run a suite with ``--cov-context=test`` so Coverage.py records the test that
executed each line. This script reads that database and computes, for every
pair of tests that share enough lines:

* the Jaccard similarity ``|A ∩ B| / |A ∪ B|``;
* how many elements each test covers exclusively;
* whether the pair belongs to the same parametrized test.

The output is evidence for the redundancy review, never an automatic removal
decision. A high similarity can be a shared import or a common fixture; it does
not prove that either test is dispensable.

Example::

    uv run pytest -m "not e2e" -n 4 --dist worksteal \
      --cov=backend --cov=frontend --cov-branch --cov-context=test \
      --cov-config=pyproject.toml --cov-report= --cov-fail-under=0
    uv run python scripts/tests/coverage_overlap.py \
      --coverage-file .coverage --include backend --include frontend \
      --output var/overlap/app.json --summary var/overlap/app.md
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCHEMA_VERSION = 1

#: A line covered by more tests than this is shared infrastructure (an import,
#: a module-level constant) and would make every pair look similar.
DEFAULT_MAX_ELEMENT_TESTS = 50


@dataclass(frozen=True)
class Pair:
    test_a: str
    test_b: str
    similarity: float
    shared: int
    union: int
    only_a: int
    only_b: int
    exclusive_a: int
    exclusive_b: int
    same_parameterized_family: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Family:
    base: str
    variants: int
    union: int
    common: int
    identical: bool


@dataclass(frozen=True)
class CoverageSubset:
    """A coverage signature is a subset of another, with representative tests."""

    subsumed: str
    subsumer: str
    subsumed_tests: int
    subsumer_tests: int
    shared: int
    union: int
    similarity: float
    strict: bool
    same_parameterized_family: bool

    def to_dict(self) -> dict:
        return asdict(self)


def normalize_context(context: str) -> str:
    """A pytest-cov context is ``nodeid|phase``; the phase does not identify a test."""
    return context.split("|", 1)[0].strip()


def included_path(path: str, includes: Sequence[str]) -> bool:
    """Whether a measured file is under one of the repository-relative prefixes."""
    if not includes:
        return True
    normalized = path.replace("\\", "/")
    for include in includes:
        prefix = include.strip("/").replace("\\", "/")
        if normalized == prefix or normalized.startswith(prefix + "/"):
            return True
    return False


def _relative(filename: str, root: Path) -> str:
    path = Path(filename)
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return path.as_posix()


def load_test_coverage(
    coverage_file: Path,
    *,
    root: Path = ROOT,
    includes: Sequence[str] = (),
) -> dict[str, frozenset[str]]:
    """Map each test node id to the ``file:line`` elements it executed."""
    from coverage import CoverageData
    from coverage.exceptions import CoverageException

    data = CoverageData(basename=str(coverage_file))
    data.read()
    coverage: dict[str, set[str]] = defaultdict(set)
    for filename in data.measured_files():
        relative = _relative(filename, root)
        if not included_path(relative, includes):
            continue
        try:
            contexts_by_line = data.contexts_by_lineno(filename)
        except CoverageException:
            continue
        for line, contexts in contexts_by_line.items():
            element = f"{relative}:{line}"
            for context in contexts:
                test = normalize_context(context)
                if test:
                    coverage[test].add(element)
    return {test: frozenset(elements) for test, elements in coverage.items()}


def exclusive_counts(tests: dict[str, frozenset[str]]) -> dict[str, int]:
    """How many elements each test is the only one to cover."""
    frequency: Counter[str] = Counter()
    for elements in tests.values():
        frequency.update(elements)
    return {
        test: sum(1 for element in elements if frequency[element] == 1)
        for test, elements in tests.items()
    }


def _element_index(
    tests: dict[str, frozenset[str]], max_element_tests: int
) -> dict[str, list[str]]:
    index: dict[str, list[str]] = defaultdict(list)
    oversized: set[str] = set()
    for test, elements in tests.items():
        for element in elements:
            if element in oversized:
                continue
            bucket = index[element]
            bucket.append(test)
            if len(bucket) > max_element_tests:
                oversized.add(element)
                del index[element]
    return dict(index)


def similarity_pairs(
    tests: dict[str, frozenset[str]],
    *,
    threshold: float = 0.8,
    min_shared: int = 5,
    max_element_tests: int = DEFAULT_MAX_ELEMENT_TESTS,
) -> list[Pair]:
    """Pairs whose Jaccard similarity reaches ``threshold`` and share enough lines."""
    exclusive = exclusive_counts(tests)
    shared: Counter[tuple[str, str]] = Counter()
    for bucket in _element_index(tests, max_element_tests).values():
        if len(bucket) < 2:
            continue
        for first, second in combinations(sorted(bucket), 2):
            shared[(first, second)] += 1

    pairs: list[Pair] = []
    for first, second in shared:
        # The capped index only proposes candidates. All reported metrics use
        # the complete uncovered sets, so a capped line cannot inflate the
        # union or look exclusive to one side.
        intersection = tests[first] & tests[second]
        count = len(intersection)
        if count < min_shared:
            continue
        union = len(tests[first] | tests[second])
        similarity = count / union if union else 0.0
        if similarity < threshold:
            continue
        pairs.append(
            Pair(
                test_a=first,
                test_b=second,
                similarity=round(similarity, 4),
                shared=count,
                union=union,
                only_a=len(tests[first] - tests[second]),
                only_b=len(tests[second] - tests[first]),
                exclusive_a=exclusive[first],
                exclusive_b=exclusive[second],
                same_parameterized_family=base_nodeid(first) == base_nodeid(second),
            )
        )
    pairs.sort(key=lambda pair: (-pair.similarity, -pair.shared, pair.test_a, pair.test_b))
    return pairs


def coverage_subsets(tests: dict[str, frozenset[str]]) -> list[CoverageSubset]:
    """Every ``B ⊆ A`` relation between unique coverage signatures.

    Grouping tests by their complete signature keeps the relation meaningful:
    thousands of tests can share the same production lines, and listing every
    pair would hide the signal under quadratic noise. ``subsumed_tests`` and
    ``subsumer_tests`` carry the group sizes, and the representative node ids
    come from the first test of each group.
    """
    groups: dict[frozenset[str], list[str]] = defaultdict(list)
    for test, elements in tests.items():
        if elements:
            groups[elements].append(test)
    signatures = list(groups)
    buckets: dict[str, set[frozenset[str]]] = defaultdict(set)
    for signature in signatures:
        for element in signature:
            buckets[element].add(signature)

    subsets: list[CoverageSubset] = []
    for signature, group in groups.items():
        if len(group) < 2:
            continue
        ordered_group = sorted(group)
        subsets.append(
            CoverageSubset(
                subsumed=ordered_group[0],
                subsumer=ordered_group[1],
                subsumed_tests=len(group),
                subsumer_tests=len(group),
                shared=len(signature),
                union=len(signature),
                similarity=1.0,
                strict=False,
                same_parameterized_family=base_nodeid(ordered_group[0])
                == base_nodeid(ordered_group[1]),
            )
        )
    for subsumed_signature in signatures:
        ordered = sorted(
            subsumed_signature, key=lambda element: len(buckets[element])
        )
        candidates = set(buckets[ordered[0]])
        for element in ordered[1:]:
            candidates &= buckets[element]
            if not candidates:
                break
        for subsumer_signature in candidates:
            if not subsumed_signature < subsumer_signature:
                continue
            subsumed_group = sorted(groups[subsumed_signature])
            subsumer_group = sorted(groups[subsumer_signature])
            subsets.append(
                CoverageSubset(
                    subsumed=subsumed_group[0],
                    subsumer=subsumer_group[0],
                    subsumed_tests=len(subsumed_group),
                    subsumer_tests=len(subsumer_group),
                    shared=len(subsumed_signature),
                    union=len(subsumer_signature),
                    similarity=round(
                        len(subsumed_signature) / len(subsumer_signature), 4
                    ),
                    strict=True,
                    same_parameterized_family=base_nodeid(subsumed_group[0])
                    == base_nodeid(subsumer_group[0]),
                )
            )
    subsets.sort(
        key=lambda item: (-item.shared, -item.subsumed_tests, item.subsumed)
    )
    return subsets

def base_nodeid(nodeid: str) -> str:
    """The parameterless node id of a parametrized test."""
    return nodeid.split("[", 1)[0]


def parameterized_families(tests: dict[str, frozenset[str]]) -> list[Family]:
    """Parametrized tests whose variants cover the same (or almost the same) code."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for test in tests:
        if "[" in test:
            grouped[base_nodeid(test)].append(test)
    families: list[Family] = []
    for base, variants in sorted(grouped.items()):
        if len(variants) < 2:
            continue
        sets = [tests[variant] for variant in variants]
        union = set().union(*sets)
        common = set(sets[0])
        for variant_elements in sets[1:]:
            common &= variant_elements
        families.append(
            Family(
                base=base,
                variants=len(variants),
                union=len(union),
                common=len(common),
                identical=len(common) == len(union),
            )
        )
    families.sort(key=lambda family: (-family.variants, family.base))
    return families


def _summary(
    tests: dict[str, frozenset[str]],
    pairs: Sequence[Pair],
    subsets: Sequence[CoverageSubset],
) -> dict[str, int | float]:
    all_elements = set().union(*tests.values()) if tests else set()
    return {
        "tests": len(tests),
        "elements": len(all_elements),
        "pairs": len(pairs),
        "identical_pairs": sum(pair.shared == pair.union for pair in pairs),
        "mean_similarity": round(
            sum(pair.similarity for pair in pairs) / len(pairs), 4
        )
        if pairs
        else 0.0,
        "coverage_subsets": len(subsets),
        "strict_coverage_subsets": sum(subset.strict for subset in subsets),
        "equal_coverage_subsets": sum(not subset.strict for subset in subsets),
        "tests_with_identical_coverage": sum(
            subset.subsumed_tests for subset in subsets if not subset.strict
        ),
    }


def build_report(
    tests: dict[str, frozenset[str]],
    *,
    coverage_file: Path,
    coverage_label: str | None = None,
    threshold: float,
    min_shared: int,
    max_element_tests: int,
    top: int,
) -> dict:
    """The machine-readable overlap report."""
    pairs = similarity_pairs(
        tests,
        threshold=threshold,
        min_shared=min_shared,
        max_element_tests=max_element_tests,
    )
    exclusive = exclusive_counts(tests)
    families = parameterized_families(tests)
    subsets = coverage_subsets(tests)
    zero_exclusive = [
        {"test": test, "elements": len(elements)}
        for test, elements in sorted(
            ((test, elements) for test, elements in tests.items() if exclusive[test] == 0),
            key=lambda item: (-len(item[1]), item[0]),
        )
    ]
    summary = _summary(tests, pairs, subsets)
    summary.update(
        {
            "families": len(families),
            "identical_families": sum(family.identical for family in families),
            "zero_exclusive_tests": len(zero_exclusive),
            "pair_search_complete": False,
            "pair_search_cap": max_element_tests,
        }
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "coverage-overlap",
        "coverage_file": coverage_label or str(coverage_file),
        "settings": {
            "threshold": threshold,
            "min_shared": min_shared,
            "max_element_tests": max_element_tests,
            "top": top,
        },
        "summary": summary,
        "pairs": [pair.to_dict() for pair in pairs[:top]],
        "coverage_subsets": [subset.to_dict() for subset in subsets[:top]],
        "families": [asdict(family) for family in families[:top]],
        "zero_exclusive": zero_exclusive[:top],
    }


def render_summary(report: dict) -> str:
    """Markdown summary of an overlap report."""
    settings = report["settings"]
    summary = report["summary"]
    lines = [
        "## Coverage overlap (#644)",
        "",
        (
            f"{summary['tests']} tests, {summary['elements']} executed lines, "
            f"{summary['pairs']} pairs at Jaccard >= {settings['threshold']} "
            f"with at least {settings['min_shared']} shared lines."
        ),
        (
            f"{summary.get('identical_families', 0)} parametrized families with "
            f"identical line coverage; {summary.get('zero_exclusive_tests', 0)} "
            f"tests without an exclusive production line."
        ),
        (
            f"Coverage subsumption between unique signatures (independent of "
            f"the Jaccard threshold): {summary.get('coverage_subsets', 0)} "
            f"relations ({summary.get('strict_coverage_subsets', 0)} strict, "
            f"{summary.get('equal_coverage_subsets', 0)} identical)."
        ),
        "",
        "No test is removed by this report: high overlap is a review candidate.",
        "",
        "| Test A | Test B | Jaccard | Shared | Only A | Only B | Param. |",
        "|---|---|---:|---:|---:|---:|---|",
    ]
    for pair in report["pairs"]:
        parameterized = "yes" if pair["same_parameterized_family"] else ""
        lines.append(
            f"| `{pair['test_a']}` | `{pair['test_b']}` | {pair['similarity']:.3f} "
            f"| {pair['shared']} | {pair['only_a']} | {pair['only_b']} "
            f"| {parameterized} |"
        )
    if not report["pairs"]:
        lines.append("| — | — | — | — | — | — | — |")

    lines += [
        "",
        f"### Coverage subsumption (top {settings['top']} signatures)",
        "",
        "`Subsumed` covers no measured line that `Subsumer` does not. This is a "
        "coverage relation only; contracts and assertions still need review. "
        "`Tests` is the size of the group sharing that signature.",
        "",
        "| Subsumed | Tests | Subsumer | Tests | Lines | Jaccard | Strict |",
        "|---|---:|---|---:|---:|---:|---|",
    ]
    for subset in report.get("coverage_subsets", []):
        lines.append(
            f"| `{subset['subsumed']}` | {subset['subsumed_tests']} "
            f"| `{subset['subsumer']}` | {subset['subsumer_tests']} "
            f"| {subset['shared']} | {subset['similarity']:.3f} "
            f"| {'yes' if subset['strict'] else 'no'} |"
        )
    if not report.get("coverage_subsets"):
        lines.append("| — | — | — | — | — | — | — |")

    lines += [
        "",
        f"### Parametrized families with identical coverage (top {settings['top']})",
        "",
        "| Family | Variants | Lines |",
        "|---|---:|---:|",
    ]
    identical = [family for family in report["families"] if family["identical"]]
    for family in identical:
        lines.append(f"| `{family['base']}` | {family['variants']} | {family['union']} |")
    if not identical:
        lines.append("| — | — | — |")

    lines += [
        "",
        f"### Tests with no exclusive line (top {settings['top']} by lines)",
        "",
        (
            "These tests cover no line that another test in the same report does "
            "not also cover. They are the strongest overlap candidates, not a "
            "verdict: they can still be the only one checking a contract or an "
            "error message."
        ),
        "",
        "| Test | Lines |",
        "|---|---:|",
    ]
    for item in report["zero_exclusive"]:
        lines.append(f"| `{item['test']}` | {item['elements']} |")
    if not report["zero_exclusive"]:
        lines.append("| — | — |")
    return "\n".join(lines) + "\n"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage-file", type=Path, required=True)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--include",
        action="append",
        default=[],
        help="repository-relative prefix to include; repeatable",
    )
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--min-shared", type=int, default=5)
    parser.add_argument(
        "--max-element-tests",
        type=int,
        default=DEFAULT_MAX_ELEMENT_TESTS,
        help="ignore lines covered by more tests than this",
    )
    parser.add_argument("--top", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--summary", type=Path, help="write the Markdown summary")
    args = parser.parse_args(argv)

    if not args.coverage_file.is_file():
        print(f"error: {args.coverage_file} does not exist", file=sys.stderr)
        return 2
    try:
        tests = load_test_coverage(
            args.coverage_file, root=args.root, includes=args.include
        )
    except Exception as exc:  # coverage raises sqlite/schema errors
        print(f"error: cannot read {args.coverage_file}: {exc}", file=sys.stderr)
        return 2
    if not tests:
        print(
            "error: no per-test contexts; run pytest with --cov-context=test",
            file=sys.stderr,
        )
        return 2

    report = build_report(
        tests,
        coverage_file=args.coverage_file,
        coverage_label=_relative(str(args.coverage_file), args.root),
        threshold=args.threshold,
        min_shared=args.min_shared,
        max_element_tests=args.max_element_tests,
        top=args.top,
    )
    summary = render_summary(report)
    print(summary)
    _write(args.output, json.dumps(report, indent=2) + "\n")
    if args.summary:
        _write(args.summary, summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
