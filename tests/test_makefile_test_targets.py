"""The local test entry points in the Makefile (#448).

The targets are intentionally thin, so a dry run (`make -n`) shows the exact
commands without starting a suite.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _dry_run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-n", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_help_lists_the_supported_commands() -> None:
    completed = _dry_run()
    assert completed.returncode == 0, completed.stderr
    assert "make test-file F=tests/test_example.py" in completed.stdout
    assert "make test-failed" in completed.stdout
    assert "make test-all" in completed.stdout


def test_test_file_runs_one_path_without_e2e() -> None:
    completed = _dry_run("test-file", "F=tests/test_example.py")
    assert completed.returncode == 0, completed.stderr
    assert "pytest" in completed.stdout
    assert "not e2e" in completed.stdout
    assert "tests/test_example.py" in completed.stdout
    assert "--durations=25" in completed.stdout
    assert "-n 4" not in completed.stdout


def test_test_all_covers_core_docstruct_and_sdk() -> None:
    completed = _dry_run("test-all")
    assert completed.returncode == 0, completed.stderr
    for expected in (
        "libs/docstruct",
        "libs/sdk",
        "not e2e",
        "-n 4",
        "--dist worksteal",
        "--durations=25",
    ):
        assert expected in completed.stdout
    assert completed.stdout.count("pytest") >= 3


def test_test_all_lets_the_core_worker_count_be_overridden() -> None:
    completed = _dry_run("test-all", "CORE_JOBS=2")
    assert completed.returncode == 0, completed.stderr
    assert "-n 2" in completed.stdout
    assert "-n 4" not in completed.stdout


def test_test_all_lets_the_core_distribution_be_overridden() -> None:
    completed = _dry_run("test-all", "CORE_DIST=load")
    assert completed.returncode == 0, completed.stderr
    assert "--dist load" in completed.stdout
    assert "--dist worksteal" not in completed.stdout


def test_test_file_without_a_path_is_refused() -> None:
    completed = subprocess.run(
        ["make", "test-file"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 2
    assert "usage: make test-file" in completed.stderr
