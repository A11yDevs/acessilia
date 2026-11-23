"""The #644 mutation proof of concept generates, applies and reports mutants."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from coverage import CoverageData

from scripts.tests import mutation_report as mutation

SOURCE = textwrap.dedent(
    """
    def choose(value, other):
        if not value and other:
            return 1
        if value == 0 or other:
            return 2
        total = 0
        total += 1
        return total if value else 3
    """
)


def _result(identifier: str, *killers: str) -> mutation.MutantResult:
    mutant = mutation.Mutant(
        id=identifier,
        operator="compare",
        line=1,
        column=0,
        description="test mutant",
        node_type="Compare",
    )
    return mutation.MutantResult(mutant=mutant, status="killed", killers=list(killers))


def test_generate_mutants_is_deterministic_and_covers_the_operators() -> None:
    first = mutation.generate_mutants(SOURCE)
    second = mutation.generate_mutants(SOURCE)

    assert first == second
    assert [mutant.id for mutant in first] == [
        f"M{index:03d}" for index in range(1, len(first) + 1)
    ]
    assert {mutant.operator for mutant in first} == {
        "boolop",
        "compare",
        "negate-condition",
        "remove-not",
        "augassign",
    }


def test_generate_mutants_honours_the_operator_filter() -> None:
    mutants = mutation.generate_mutants(SOURCE, operators=["compare"])

    assert mutants
    assert {mutant.operator for mutant in mutants} == {"compare"}


def test_mutate_source_applies_each_generated_mutation() -> None:
    mutations = mutation.generate_mutants(SOURCE)

    assert any(
        "!=" in mutation.mutate_source(SOURCE, mutant)
        for mutant in mutations
        if mutant.operator == "compare" and "Eq ->" in mutant.description
    )
    assert any(
        "or" in mutation.mutate_source(SOURCE, mutant)
        for mutant in mutations
        if mutant.operator == "boolop"
    )
    assert any(
        "if  value" in mutation.mutate_source(SOURCE, mutant)
        or "if value" in mutation.mutate_source(SOURCE, mutant)
        for mutant in mutations
        if mutant.operator == "remove-not"
    )
    assert any(
        "if not " in mutation.mutate_source(SOURCE, mutant)
        for mutant in mutations
        if mutant.operator == "negate-condition"
    )
    assert any(
        "-= 1" in mutation.mutate_source(SOURCE, mutant)
        for mutant in mutations
        if mutant.operator == "augassign"
    )
    for mutant in mutations:
        compile(mutation.mutate_source(SOURCE, mutant), "<mutant>", "exec")


def test_mutate_source_rejects_an_unknown_node() -> None:
    mutant = mutation.Mutant(
        id="M999",
        operator="compare",
        line=1,
        column=0,
        description="missing",
        node_type="NotARealNode",
    )

    with pytest.raises(ValueError, match="unsupported"):
        mutation.mutate_source(SOURCE, mutant)


def test_list_mutants_does_not_run_the_suite(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "src"
    module = source_root / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(SOURCE, encoding="utf-8")

    status = mutation.main(
        [
            "--module",
            str(module),
            "--tests",
            "tests/test_mod.py",
            "--suite",
            str(tmp_path),
            "--source-root",
            str(source_root),
            "--list-mutants",
            "--max-mutants",
            "2",
        ]
    )

    assert status == 0
    output = capsys.readouterr().out.splitlines()
    assert len(output) == 2
    assert output[0].startswith("M001 line ")


def test_list_mutants_rejects_a_module_outside_the_source_root(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = tmp_path / "mod.py"
    module.write_text(SOURCE, encoding="utf-8")

    status = mutation.main(
        [
            "--module",
            str(module),
            "--tests",
            "tests/test_mod.py",
            "--source-root",
            str(tmp_path / "src"),
            "--list-mutants",
        ]
    )

    assert status == 2
    assert "not under" in capsys.readouterr().err


def test_kill_sets_and_subsumption_follow_the_definition() -> None:
    results = [
        _result("M1", "test::a", "test::b"),
        _result("M2", "test::a"),
        _result("M3", "test::c"),
    ]
    overlap = {
        "pairs": [
            {
                "test_a": "test::a",
                "test_b": "test::b",
                "similarity": 0.9,
            }
        ]
    }

    pairs = mutation.subsumption_pairs(results, overlap=overlap)

    assert {
        (pair["subsumer"], pair["subsumed"], pair["equal"])
        for pair in pairs
    } == {
        ("test::a", "test::b", False),
    }
    assert pairs[0]["coverage_similarity"] == 0.9
    assert mutation._kill_sets(results) == {
        "test::a": {"M1", "M2"},
        "test::b": {"M1"},
        "test::c": {"M3"},
    }


def test_equal_kill_sets_are_reported_once() -> None:
    results = [
        _result("M1", "test::a", "test::b"),
        _result("M2", "test::a", "test::b"),
    ]

    pairs = mutation.subsumption_pairs(results)

    assert len(pairs) == 1
    assert pairs[0]["subsumer"] == "test::a"
    assert pairs[0]["subsumed"] == "test::b"
    assert pairs[0]["equal"] is True


def test_exclusive_mutants_name_the_only_detector() -> None:
    results = [
        _result("M1", "test::a", "test::b"),
        _result("M2", "test::a"),
        _result("M3", "test::c"),
    ]

    assert mutation.exclusive_mutants(results) == [
        {"test": "test::a", "mutants": ["M2"]},
        {"test": "test::c", "mutants": ["M3"]},
    ]


def test_unknown_operators_are_rejected(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source_root = tmp_path / "src"
    module = source_root / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(SOURCE, encoding="utf-8")

    status = mutation.main(
        [
            "--module",
            str(module),
            "--tests",
            "tests/test_mod.py",
            "--suite",
            str(tmp_path),
            "--source-root",
            str(source_root),
            "--operators",
            "compare,typo",
            "--list-mutants",
        ]
    )

    assert status == 2
    assert "unknown operators" in capsys.readouterr().err


def test_build_report_classifies_uncovered_mutants_and_scores() -> None:
    results = [
        mutation.MutantResult(
            mutant=mutation.Mutant("M1", "compare", 10, 0, "one", "Compare"),
            status="killed",
            killers=["test::a"],
        ),
        mutation.MutantResult(
            mutant=mutation.Mutant("M2", "compare", 20, 0, "two", "Compare"),
            status="survived",
        ),
    ]

    report = mutation.build_report(
        results=results,
        module=Path("pkg/mod.py"),
        tests=["tests/test_mod.py"],
        baseline={"status": "survived"},
        covered_lines={10},
        overlap=None,
        settings={},
    )

    assert [mutant["status"] for mutant in report["mutants"]] == ["killed", "uncovered"]
    assert report["summary"]["killed"] == 1
    assert report["summary"]["survived"] == 0
    assert report["summary"]["uncovered"] == 1
    assert report["summary"]["mutation_score"] == 1.0
    assert "Mutation experiment" in mutation.render_summary(report)


def test_build_report_records_the_subsumption_total_before_the_example_cap() -> None:
    results = [
        _result("M1", "test::a", "test::b", "test::c"),
        _result("M2", "test::a", "test::c"),
        _result("M3", "test::a"),
    ]

    report = mutation.build_report(
        results=results,
        module=Path("pkg/mod.py"),
        tests=["tests/test_mod.py"],
        baseline={"status": "survived"},
        covered_lines=None,
        overlap=None,
        settings={"max_subsumption": 1},
    )

    assert report["summary"]["subsumption_total"] == 3
    assert report["summary"]["subsumption_examples"] == 1
    assert len(report["subsumption"]) == 1
    assert all("exclusive" not in pair for pair in report["subsumption"])


def test_collection_errors_are_not_killing_tests(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    tests = suite / "tests"
    tests.mkdir(parents=True)
    (tests / "test_bad.py").write_text("import missing_module\n", encoding="utf-8")
    junit = tmp_path / "junit.xml"

    outcome = mutation._run_pytest(
        ["tests/test_bad.py"],
        suite=suite,
        junit=junit,
        timeout_seconds=20,
        known_tests={"tests/test_bad.py::test_real"},
    )

    assert outcome["status"] == "invalid"
    assert outcome["killers"] == []


def test_the_mutation_documentation_has_a_linked_mirror() -> None:
    docs = Path(__file__).resolve().parents[1] / "docs" / "testing"
    english = (docs / "mutation.md").read_text(encoding="utf-8")
    portuguese = (docs / "mutation.pt-br.md").read_text(encoding="utf-8")

    assert "(mutation.pt-br.md)" in english
    assert "(mutation.md)" in portuguese
    assert (docs / "mutation-flood.json").is_file()
    assert (docs / "mutation-equations.json").is_file()


def test_load_covered_lines_reads_the_module(tmp_path: Path) -> None:
    module = tmp_path / "pkg" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text("a = 1\nb = 2\n", encoding="utf-8")
    data = CoverageData(basename=str(tmp_path / ".coverage"))
    data.add_lines({str(module): {1}})
    data.write()

    assert mutation.load_covered_lines(tmp_path / ".coverage", module) == {1}
    assert mutation.load_covered_lines(None, module) is None
    assert mutation.load_covered_lines(tmp_path / "missing", module) is None

    foreign = tmp_path / "foreign.coverage"
    data = CoverageData(basename=str(foreign))
    data.add_lines({str(tmp_path / "other.py"): {1}})
    data.write()
    assert mutation.load_covered_lines(foreign, module) is None
