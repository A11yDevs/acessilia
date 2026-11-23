"""The #644 overlap and redundancy reports are evidence, not deletion lists."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from coverage import CoverageData

from scripts.tests import coverage_overlap as overlap, redundancy_report as redundancy


def _coverage_file(path: Path, root: Path) -> Path:
    source = root / "backend" / "sample.py"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
    data = CoverageData(basename=str(path))
    data.set_context("tests/test_sample.py::test_first|run")
    data.add_lines({str(source): {1, 2}})
    data.set_context("tests/test_sample.py::test_second[1]|setup")
    data.add_lines({str(source): {3, 4}})
    data.set_context("tests/test_sample.py::test_second[2]|teardown")
    data.add_lines({str(source): {4}})
    data.write()
    return path


def test_contexts_drop_the_pytest_phase() -> None:
    assert overlap.normalize_context("tests/test_x.py::test_a[1]|run") == (
        "tests/test_x.py::test_a[1]"
    )
    assert overlap.normalize_context("tests/test_x.py::test_a|setup") == (
        "tests/test_x.py::test_a"
    )
    assert overlap.normalize_context("") == ""


def test_include_prefixes_are_repository_relative() -> None:
    assert overlap.included_path("backend/api/app.py", ["backend"])
    assert overlap.included_path("backend", ["backend"])
    assert not overlap.included_path("frontend/app.py", ["backend"])
    assert not overlap.included_path("backend_extra/app.py", ["backend"])
    assert overlap.included_path("libs/core/src/x.py", ["libs/core/src"])


def test_load_test_coverage_reads_contexts_and_filters_prefixes(tmp_path: Path) -> None:
    coverage_file = _coverage_file(tmp_path / ".coverage", tmp_path)

    tests = overlap.load_test_coverage(
        coverage_file, root=tmp_path, includes=["backend"]
    )

    assert set(tests) == {
        "tests/test_sample.py::test_first",
        "tests/test_sample.py::test_second[1]",
        "tests/test_sample.py::test_second[2]",
    }
    assert tests["tests/test_sample.py::test_first"] == frozenset(
        {"backend/sample.py:1", "backend/sample.py:2"}
    )
    assert tests["tests/test_sample.py::test_second[2]"] == frozenset(
        {"backend/sample.py:4"}
    )
    assert overlap.load_test_coverage(
        coverage_file, root=tmp_path, includes=["frontend"]
    ) == {}


def test_exclusive_counts_identify_shared_lines() -> None:
    tests = {
        "a": frozenset({"f:1", "f:2"}),
        "b": frozenset({"f:2", "f:3"}),
    }
    assert overlap.exclusive_counts(tests) == {"a": 1, "b": 1}


def test_similarity_pairs_use_jaccard_and_minimum_shared() -> None:
    tests = {
        "tests::test_a": frozenset({"f:1", "f:2", "f:3", "f:4"}),
        "tests::test_b": frozenset({"f:1", "f:2", "f:3", "f:5"}),
        "tests::test_c": frozenset({"f:1", "f:2", "f:9"}),
        "tests::test_d": frozenset({"f:8"}),
    }

    pairs = overlap.similarity_pairs(
        tests, threshold=0.6, min_shared=2, max_element_tests=50
    )

    assert [(pair.test_a, pair.test_b, pair.similarity) for pair in pairs] == [
        ("tests::test_a", "tests::test_b", 0.6)
    ]
    assert pairs[0].shared == 3
    assert pairs[0].exclusive_a == 1
    assert pairs[0].exclusive_b == 1


def test_pair_search_is_marked_incomplete_only_when_a_line_is_capped() -> None:
    tests = {
        f"tests::test_{index}": frozenset({"common", f"own:{index}"})
        for index in range(55)
    }
    report = overlap.build_report(
        tests,
        coverage_file=Path(".coverage"),
        threshold=0.8,
        min_shared=1,
        max_element_tests=50,
        top=10,
    )

    assert report["summary"]["pair_search_complete"] is False


def test_a_line_covered_by_too_many_tests_is_ignored() -> None:
    tests = {
        f"tests::test_{index}": frozenset({"common:1", f"own:{index}"})
        for index in range(60)
    }

    assert overlap.similarity_pairs(
        tests, threshold=0.8, min_shared=1, max_element_tests=50
    ) == []


def test_capped_lines_do_not_distort_the_metrics() -> None:
    tests = {f"tests::other_{index}": frozenset({"common"}) for index in range(49)}
    tests["tests::a"] = frozenset({"common", "x1", "x2", "x3", "x4"})
    tests["tests::b"] = frozenset({"common", "x1", "x2", "x3", "x4"})

    pairs = overlap.similarity_pairs(
        tests, threshold=0.8, min_shared=1, max_element_tests=50
    )

    pair = next(pair for pair in pairs if pair.test_a == "tests::a")
    assert pair.shared == 5
    assert pair.union == 5
    assert pair.similarity == 1.0
    assert pair.only_a == pair.only_b == 0


def test_coverage_subsets_are_independent_of_the_jaccard_threshold() -> None:
    tests = {
        "tests::big": frozenset({"f:1", "f:2", "f:3", "f:4", "f:5"}),
        "tests::small": frozenset({"f:1", "f:2"}),
        "tests::same_a": frozenset({"f:9"}),
        "tests::same_b": frozenset({"f:9"}),
    }

    subsets = overlap.coverage_subsets(tests)

    assert {
        (subset.subsumed, subset.subsumer, subset.strict) for subset in subsets
    } == {
        ("tests::small", "tests::big", True),
        ("tests::same_a", "tests::same_b", False),
    }
    small = next(subset for subset in subsets if subset.subsumed == "tests::small")
    assert small.similarity == 0.4


def test_parameterized_families_detect_identical_variants() -> None:
    tests = {
        "tests::test_x[1]": frozenset({"f:1", "f:2"}),
        "tests::test_x[2]": frozenset({"f:1", "f:2"}),
        "tests::test_y[1]": frozenset({"f:1"}),
        "tests::test_y[2]": frozenset({"f:3"}),
        "tests::test_plain": frozenset({"f:4"}),
    }

    families = overlap.parameterized_families(tests)

    assert [(family.base, family.variants, family.identical) for family in families] == [
        ("tests::test_x", 2, True),
        ("tests::test_y", 2, False),
    ]


def test_build_report_keeps_the_top_pairs_and_zero_exclusive_tests() -> None:
    tests = {
        "tests::test_a": frozenset({"f:1", "f:2"}),
        "tests::test_b": frozenset({"f:1", "f:2"}),
    }

    report = overlap.build_report(
        tests,
        coverage_file=Path(".coverage"),
        threshold=0.8,
        min_shared=2,
        max_element_tests=50,
        top=10,
    )

    assert report["summary"]["tests"] == 2
    assert report["summary"]["pairs"] == 1
    assert report["summary"]["coverage_subsets"] == 1
    assert report["summary"]["pair_search_complete"] is True
    assert report["summary"]["pair_search_cap"] == 50
    assert report["pairs"][0]["similarity"] == 1.0
    assert report["coverage_subsets"][0]["subsumed"] == "tests::test_a"
    assert report["zero_exclusive"] == [
        {"test": "tests::test_a", "elements": 2},
        {"test": "tests::test_b", "elements": 2},
    ]
    summary = overlap.render_summary(report)
    assert "No test is removed by this report" in summary
    assert "`tests::test_a`" in summary


def test_main_writes_an_overlap_report(tmp_path: Path) -> None:
    coverage_file = _coverage_file(tmp_path / ".coverage", tmp_path)
    output = tmp_path / "overlap.json"
    summary = tmp_path / "overlap.md"

    status = overlap.main(
        [
            "--coverage-file",
            str(coverage_file),
            "--root",
            str(tmp_path),
            "--include",
            "backend",
            "--threshold",
            "0.5",
            "--min-shared",
            "1",
            "--output",
            str(output),
            "--summary",
            str(summary),
        ]
    )

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["kind"] == "coverage-overlap"
    assert payload["summary"]["tests"] == 3
    assert summary.read_text(encoding="utf-8").startswith("## Coverage overlap")


def test_the_overlap_documentation_has_a_linked_mirror() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs" / "testing"
    english = (docs / "overlap.md").read_text(encoding="utf-8")
    portuguese = (docs / "overlap.pt-br.md").read_text(encoding="utf-8")

    assert "(overlap.pt-br.md)" in english
    assert "(overlap.md)" in portuguese
    assert (docs / "overlap-app.json").is_file()
    assert (docs / "redundancy-app.json").is_file()


def test_main_rejects_a_missing_coverage_file(tmp_path: Path) -> None:
    status = overlap.main(
        [
            "--coverage-file",
            str(tmp_path / "missing"),
            "--output",
            str(tmp_path / "out.json"),
        ]
    )

    assert status == 2


def test_main_rejects_coverage_without_contexts(tmp_path: Path) -> None:
    source = tmp_path / "backend" / "sample.py"
    source.parent.mkdir(parents=True)
    source.write_text("one\n", encoding="utf-8")
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.add_lines({str(source): {1}})
    data.write()

    status = overlap.main(
        [
            "--coverage-file",
            str(tmp_path / ".coverage"),
            "--root",
            str(tmp_path),
            "--output",
            str(tmp_path / "out.json"),
        ]
    )

    assert status == 2


def _overlap_payload() -> dict:
    return {
        "kind": "coverage-overlap",
        "summary": {"coverage_subsets": 3, "zero_exclusive_tests": 2},
        "pairs": [
            {
                "test_a": "tests::test_a",
                "test_b": "tests::test_b",
                "similarity": 1.0,
                "shared": 10,
                "only_a": 2,
                "only_b": 0,
                "same_parameterized_family": False,
            }
        ],
        "coverage_subsets": [
            {
                "subsumed": "tests::test_b",
                "subsumer": "tests::test_a",
                "similarity": 0.8,
                "shared": 8,
                "union": 10,
                "strict": True,
                "same_parameterized_family": False,
            },
            {
                "subsumed": "tests::test_c[1]",
                "subsumer": "tests::test_c[2]",
                "similarity": 1.0,
                "shared": 5,
                "union": 5,
                "strict": False,
                "same_parameterized_family": True,
            },
            {
                "subsumed": "tests::test_d",
                "subsumer": "tests::test_e",
                "similarity": 0.5,
                "shared": 5,
                "union": 10,
                "strict": True,
                "same_parameterized_family": False,
            },
        ],
        "zero_exclusive": [
            {"test": "tests::test_a", "elements": 12},
            {"test": "tests::test_b", "elements": 3},
        ],
    }


def test_review_pair_describes_the_pair_without_choosing_a_candidate() -> None:
    pair = _overlap_payload()["pairs"][0]

    review = redundancy.review_pair(pair)

    assert review.classification == "near-identical"
    assert (review.only_a, review.only_b) == (2, 0)


def test_subset_classification_distinguishes_strict_and_parameterized() -> None:
    strict = _overlap_payload()["coverage_subsets"][0]
    parameterized = _overlap_payload()["coverage_subsets"][1]

    assert redundancy.subset_classification(strict) == "coverage-subset"
    assert (
        redundancy.subset_classification(parameterized)
        == "identical-parameterization"
    )


def test_build_report_ranks_coverage_subset_candidates() -> None:
    durations = {"tests::test_b": 2.0, "tests::test_d": 1.0}
    report = redundancy.build_report(
        _overlap_payload(), durations, duration_source="baseline"
    )

    assert [candidate["test"] for candidate in report["candidates"]] == [
        "tests::test_b",
        "tests::test_d",
        "tests::test_c[1]",
    ]
    assert report["summary"]["candidates"] == 3
    assert report["summary"]["coverage_subset_total"] == 3
    assert report["summary"]["estimated_savings_seconds"] == 3.0
    assert report["summary"]["duration_source"] == "baseline"
    summary = redundancy.render_summary(report)
    assert "review sheet, not a deletion list" in summary
    assert "presentation sample" in summary


def test_a_test_without_an_exclusive_line_uses_the_global_total() -> None:
    payload = _overlap_payload()

    report = redundancy.build_report(payload, {"tests::test_a": 2.0})

    assert report["zero_exclusive"] == [
        {"test": "tests::test_a", "elements": 12, "seconds": 2.0},
        {"test": "tests::test_b", "elements": 3, "seconds": 0.0},
    ]
    assert report["summary"]["zero_exclusive"] == 2
    assert report["summary"]["zero_exclusive_examples"] == 2
    assert "no exclusive production line" in redundancy.render_summary(report)


def test_load_junit_durations_reads_every_case(tmp_path: Path) -> None:
    report = tmp_path / "results.xml"
    report.write_text(
        "<testsuites><testsuite>"
        '<testcase classname="tests.test_x" name="test_a" time="1.5"/>'
        '<testcase classname="tests.test_x" name="test_b" time="0.25"/>'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )

    assert redundancy.load_junit_durations([f"app={report}"]) == {
        "tests/test_x.py::test_a": 1.5,
        "tests/test_x.py::test_b": 0.25,
    }


def test_load_junit_durations_rejects_bad_arguments(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="LABEL=PATH"):
        redundancy.load_junit_durations(["results.xml"])
    with pytest.raises(FileNotFoundError):
        redundancy.load_junit_durations([f"app={tmp_path / 'missing.xml'}"])


def test_load_durations_reads_the_baseline(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {
                "suites": [
                    {
                        "slowest": [
                            {"nodeid": "tests::test_a", "seconds": 1.5},
                            {"nodeid": "tests::test_b", "seconds": "broken"},
                        ]
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    assert redundancy.load_durations(baseline) == {"tests::test_a": 1.5}
    assert redundancy.load_durations(None) == {}
    assert redundancy.load_durations(tmp_path / "missing.json") == {}


def test_main_writes_a_redundancy_report(tmp_path: Path) -> None:
    source = tmp_path / "overlap.json"
    source.write_text(json.dumps(_overlap_payload()), encoding="utf-8")
    baseline = tmp_path / "baseline.json"
    baseline.write_text(
        json.dumps(
            {"suites": [{"slowest": [{"nodeid": "tests::test_b", "seconds": 2.0}]}]}
        ),
        encoding="utf-8",
    )
    output = tmp_path / "redundancy.json"
    summary = tmp_path / "redundancy.md"

    status = redundancy.main(
        [
            str(source),
            "--baseline",
            str(baseline),
            "--output",
            str(output),
            "--summary",
            str(summary),
        ]
    )

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["kind"] == "redundancy-report"
    assert payload["summary"]["candidates"] == 3
    assert summary.read_text(encoding="utf-8").startswith("## Redundancy candidates")


def test_main_rejects_unreadable_inputs(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")

    assert (
        redundancy.main([str(broken), "--output", str(tmp_path / "out.json")]) == 2
    )
    assert (
        redundancy.main(
            [
                str(broken),
                "--baseline",
                str(broken),
                "--output",
                str(tmp_path / "out.json"),
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    ("similarity", "same_family", "expected"),
    [
        (1.0, True, "identical-parameterization"),
        (1.0, False, "near-identical"),
        (0.95, False, "high-overlap"),
    ],
)
def test_classification(similarity: float, same_family: bool, expected: str) -> None:
    assert redundancy.classify(similarity, same_family) == expected
