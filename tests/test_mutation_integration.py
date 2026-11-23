"""Integration coverage for the #755 mutation harness contract."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.tests import mutation_report as mutation

pytestmark = pytest.mark.slow


def _project(tmp_path: Path, module_source: str, test_source: str) -> tuple[Path, Path, Path]:
    source_root = tmp_path / "src"
    package = source_root / "pkg"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "mod.py").write_text(module_source, encoding="utf-8")
    suite = tmp_path / "suite"
    tests = suite / "tests"
    tests.mkdir(parents=True)
    (tests / "test_mod.py").write_text(test_source, encoding="utf-8")
    return source_root, suite, package / "mod.py"


def test_the_baseline_and_mutants_run_against_the_temporary_copy(
    tmp_path: Path,
) -> None:
    source_root, suite, module = _project(
        tmp_path,
        "ORIGIN = __file__\n\ndef choose(value):\n    return 1 if value > 0 else 0\n",
        "from pkg.mod import ORIGIN, choose\n\n"
        "def test_positive():\n    assert choose(1) == 1\n\n"
        "def test_zero():\n    assert choose(0) == 0\n\n"
        "def test_temporary_copy():\n"
        "    assert 'acessilia-mutation-' in ORIGIN\n",
    )
    source = module.read_text(encoding="utf-8")
    mutants = mutation.generate_mutants(source)

    baseline, results = mutation.run_experiment(
        mutants,
        source=source,
        module_relative=Path("pkg/mod.py"),
        source_root=source_root,
        suite=suite,
        tests=["tests/test_mod.py"],
        timeout_seconds=20,
    )

    assert baseline["status"] == "survived"
    assert [result.killers for result in results] == [
        ["tests/test_mod.py::test_positive", "tests/test_mod.py::test_zero"],
        ["tests/test_mod.py::test_zero"],
    ]
    assert module.read_text(encoding="utf-8") == source


def test_an_import_error_is_invalid_without_a_pseudo_killer(tmp_path: Path) -> None:
    source_root, suite, module = _project(
        tmp_path,
        "if False:\n    missing_name\nVALUE = 1\n",
        "from pkg.mod import VALUE\n\ndef test_value():\n    assert VALUE == 1\n",
    )
    source = module.read_text(encoding="utf-8")
    mutants = mutation.generate_mutants(source)

    baseline, results = mutation.run_experiment(
        mutants,
        source=source,
        module_relative=Path("pkg/mod.py"),
        source_root=source_root,
        suite=suite,
        tests=["tests/test_mod.py"],
        timeout_seconds=20,
    )

    assert baseline["status"] == "survived"
    assert results
    for result in results:
        assert result.status == "invalid"
        assert result.killers == []
        assert result.error == ""
        assert result.exit_code == 2


def test_ambient_pytest_options_cannot_change_the_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTEST_ADDOPTS", "-k definitely-not-a-test")
    monkeypatch.setenv("PYTEST_PLUGINS", "ambient.plugin")
    monkeypatch.setenv("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "leak")
    monkeypatch.setenv("PYTEST_DEBUG", "1")
    source_root, suite, module = _project(
        tmp_path,
        "def value():\n    return 1\n",
        "from pkg.mod import value\n\ndef test_value():\n    assert value() == 1\n",
    )

    baseline, results = mutation.run_experiment(
        [],
        source=module.read_text(encoding="utf-8"),
        module_relative=Path("pkg/mod.py"),
        source_root=source_root,
        suite=suite,
        tests=["tests/test_mod.py"],
        timeout_seconds=20,
    )

    assert baseline["status"] == "survived"


def test_a_failing_baseline_is_refused(tmp_path: Path) -> None:
    source_root, suite, module = _project(
        tmp_path,
        "def value():\n    return 1\n",
        "from pkg.mod import value\n\ndef test_value():\n    assert value() == 2\n",
    )

    with pytest.raises(RuntimeError, match="do not pass before mutation"):
        mutation.run_experiment(
            mutation.generate_mutants(module.read_text(encoding="utf-8")),
            source=module.read_text(encoding="utf-8"),
            module_relative=Path("pkg/mod.py"),
            source_root=source_root,
            suite=suite,
            tests=["tests/test_mod.py"],
            timeout_seconds=20,
        )


def test_an_empty_mutant_set_still_validates_the_baseline(tmp_path: Path) -> None:
    source_root, suite, module = _project(
        tmp_path,
        "def value():\n    return 1\n",
        "from pkg.mod import value\n\ndef test_value():\n    assert value() == 1\n",
    )

    baseline, results = mutation.run_experiment(
        [],
        source=module.read_text(encoding="utf-8"),
        module_relative=Path("pkg/mod.py"),
        source_root=source_root,
        suite=suite,
        tests=["tests/test_mod.py"],
        timeout_seconds=20,
    )

    assert baseline["status"] == "survived"
    assert results == []


def test_a_subprocess_timeout_is_classified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []

    def timeout(*args, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired("pytest", 1)

    monkeypatch.setattr(mutation.subprocess, "run", timeout)

    outcome = mutation._run_pytest(
        ["tests/test_mod.py"],
        suite=tmp_path,
        junit=tmp_path / "junit.xml",
        timeout_seconds=1,
    )

    assert outcome["status"] == "timeout"
    assert outcome["killers"] == []
    assert outcome["exit_code"] is None
    assert calls[0]["timeout"] == 31


def test_a_missing_junit_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Completed:
        returncode = 4
        stdout = ""
        stderr = "usage error"

    monkeypatch.setattr(
        mutation.subprocess, "run", lambda *args, **kwargs: Completed()
    )

    outcome = mutation._run_pytest(
        ["tests/test_mod.py"],
        suite=tmp_path,
        junit=tmp_path / "missing.xml",
        timeout_seconds=1,
    )

    assert outcome["status"] == "invalid"
    assert outcome["killers"] == []
    assert "usage error" in outcome["error"]


def test_a_timeout_stays_out_of_the_killed_count() -> None:
    result = mutation.MutantResult(
        mutant=mutation.Mutant("M1", "compare", 1, 0, "timeout", "Compare"),
        status="timeout",
    )

    report = mutation.build_report(
        results=[result],
        module=Path("pkg/mod.py"),
        tests=["tests/test_mod.py"],
        baseline={"status": "survived"},
        covered_lines=None,
        overlap=None,
        settings={},
    )

    assert report["summary"]["timeout"] == 1
    assert report["summary"]["killed"] == 0
    assert report["summary"]["mutation_score"] == 0.0
