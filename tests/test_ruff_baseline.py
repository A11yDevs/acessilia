"""Unit tests for the shrinking Ruff baseline guard (scripts/check_ruff_baseline.py)."""

from __future__ import annotations

import subprocess
import tomllib
from pathlib import Path

import pytest

from scripts import check_ruff_baseline

ROOT = Path(__file__).resolve().parents[1]


def _diag(filename: str, code: str, row: int = 1, col: int = 1, message: str = "msg") -> dict:
    return {
        "filename": filename,
        "code": code,
        "location": {"row": row, "column": col},
        "message": message,
    }


def test_lint_config_selects_import_sorting_at_zero_baseline_violations() -> None:
    config = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lint = config["tool"]["ruff"]["lint"]
    baseline = check_ruff_baseline.load_baseline(
        ROOT / "tests" / "fixtures" / "ruff_baseline.json"
    )

    assert {"F", "I", "E"} <= set(lint["select"])
    assert "E501" in lint["ignore"]
    assert lint["isort"]["combine-as-imports"] is True
    assert not any(code.startswith("I") for codes in baseline.values() for code in codes)


def test_summarize_diagnostics_groups_by_relative_posix_path(tmp_path: Path) -> None:
    diags = [
        _diag(str(tmp_path / "backend" / "a.py"), "F401"),
        _diag(str(tmp_path / "backend" / "a.py"), "F401"),
        _diag(str(tmp_path / "backend" / "a.py"), "I001"),
        _diag(str(tmp_path / "libs" / "b.py"), "E741"),
    ]
    assert check_ruff_baseline.summarize_diagnostics(diags, root=tmp_path) == {
        "backend/a.py": {"F401": 2, "I001": 1},
        "libs/b.py": {"E741": 1},
    }


def test_compare_baselines_detects_regressions_and_stale_entries() -> None:
    allowed = {
        "a.py": {"I001": 2, "F401": 1},
        "b.py": {"E741": 1},
    }
    current = {
        "a.py": {"I001": 3},  # I001 regressed (2->3), F401 shrank (1->0)
        "c.py": {"F401": 1},  # new file violation (0->1)
        # b.py became clean (1->0)
    }

    comparison = check_ruff_baseline.compare_baselines(current, allowed)

    assert not comparison.ok
    assert comparison.regressions == [
        ("a.py", "I001", 2, 3),
        ("c.py", "F401", 0, 1),
    ]
    assert comparison.stale == [
        ("a.py", "F401", 1, 0),
        ("b.py", "E741", 1, 0),
    ]


def test_main_passes_when_counts_match_baseline(tmp_path: Path, monkeypatch, capsys) -> None:
    baseline = tmp_path / "ruff_baseline.json"
    check_ruff_baseline.write_baseline(baseline, {"backend/a.py": {"I001": 1}})
    monkeypatch.setattr(check_ruff_baseline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        check_ruff_baseline,
        "run_ruff",
        lambda paths, *, root: [_diag(str(tmp_path / "backend" / "a.py"), "I001")],
    )

    code = check_ruff_baseline.main(["--baseline", str(baseline)])

    assert code == 0
    assert "0 new violations" in capsys.readouterr().out


def test_main_fails_on_new_violation_with_diagnostic_location(tmp_path: Path, monkeypatch, capsys) -> None:
    baseline = tmp_path / "ruff_baseline.json"
    check_ruff_baseline.write_baseline(baseline, {})
    monkeypatch.setattr(check_ruff_baseline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        check_ruff_baseline,
        "run_ruff",
        lambda paths, *, root: [_diag(str(tmp_path / "backend" / "new.py"), "F401", 12, 5, "unused import")],
    )

    code = check_ruff_baseline.main(["--baseline", str(baseline)])

    assert code == 1
    stderr = capsys.readouterr().err
    assert "backend/new.py [F401]: 1 found, 0 allowed" in stderr
    assert "backend/new.py:12:5: F401 unused import" in stderr


def test_main_fails_when_baseline_can_shrink(tmp_path: Path, monkeypatch, capsys) -> None:
    baseline = tmp_path / "ruff_baseline.json"
    check_ruff_baseline.write_baseline(baseline, {"backend/a.py": {"I001": 2}})
    monkeypatch.setattr(check_ruff_baseline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        check_ruff_baseline,
        "run_ruff",
        lambda paths, *, root: [_diag(str(tmp_path / "backend" / "a.py"), "I001")],
    )

    code = check_ruff_baseline.main(["--baseline", str(baseline)])

    assert code == 1
    stderr = capsys.readouterr().err
    assert "Ruff baseline can shrink" in stderr
    assert "backend/a.py [I001]: 2 -> 1" in stderr


def test_update_shrinks_baseline_and_refuses_increases(tmp_path: Path, monkeypatch, capsys) -> None:
    baseline = tmp_path / "ruff_baseline.json"
    check_ruff_baseline.write_baseline(baseline, {"backend/a.py": {"I001": 2}})
    monkeypatch.setattr(check_ruff_baseline, "REPO_ROOT", tmp_path)

    # Attempting to increase fails without --allow-increase.
    monkeypatch.setattr(
        check_ruff_baseline,
        "run_ruff",
        lambda paths, *, root: [
            _diag(str(tmp_path / "backend" / "a.py"), "I001"),
            _diag(str(tmp_path / "backend" / "a.py"), "I001"),
            _diag(str(tmp_path / "backend" / "a.py"), "I001"),
        ],
    )
    assert check_ruff_baseline.main(["--baseline", str(baseline), "--update"]) == 1
    assert "Refusing to increase" in capsys.readouterr().err

    # Shrinking succeeds and rewrites the file.
    monkeypatch.setattr(
        check_ruff_baseline,
        "run_ruff",
        lambda paths, *, root: [_diag(str(tmp_path / "backend" / "a.py"), "I001")],
    )
    assert check_ruff_baseline.main(["--baseline", str(baseline), "--update"]) == 0
    assert check_ruff_baseline.load_baseline(baseline) == {"backend/a.py": {"I001": 1}}


def test_run_ruff_raises_when_exit_1_produces_no_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="No module named ruff",
        ),
    )

    with pytest.raises(RuntimeError, match="No module named ruff"):
        check_ruff_baseline.run_ruff(root=tmp_path)


def test_run_ruff_allows_empty_stdout_on_exit_0(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args=args[0], returncode=0, stdout="", stderr=""
        ),
    )

    assert check_ruff_baseline.run_ruff(root=tmp_path) == []


def test_update_handles_relative_and_external_baseline_paths(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside" / "probe.json"
    monkeypatch.setattr(check_ruff_baseline, "REPO_ROOT", repo)
    monkeypatch.setattr(check_ruff_baseline, "run_ruff", lambda paths, *, root: [])

    # External absolute path outside REPO_ROOT must not crash.
    assert check_ruff_baseline.main(["--baseline", str(outside), "--update"]) == 0
    assert outside.exists()
    assert str(outside) in capsys.readouterr().out

    # Relative path from cwd inside REPO_ROOT must not crash.
    monkeypatch.chdir(repo)
    rel = Path("tests/fixtures/probe.json")
    assert check_ruff_baseline.main(["--baseline", str(rel), "--update"]) == 0
    assert (repo / rel).exists()
    assert "tests/fixtures/probe.json" in capsys.readouterr().out


def test_update_refuses_positional_paths(tmp_path: Path, monkeypatch) -> None:
    baseline = tmp_path / "ruff_baseline.json"
    monkeypatch.setattr(check_ruff_baseline, "REPO_ROOT", tmp_path)

    with pytest.raises(SystemExit) as exc_info:
        check_ruff_baseline.main(["--baseline", str(baseline), "--update", "backend"])
    assert exc_info.value.code == 2


def test_check_with_positional_path_scopes_baseline(tmp_path: Path, monkeypatch, capsys) -> None:
    baseline = tmp_path / "ruff_baseline.json"
    check_ruff_baseline.write_baseline(
        baseline,
        {
            "backend/a.py": {"F401": 1},
            "tests/test_other.py": {"F401": 2},
        },
    )
    monkeypatch.setattr(check_ruff_baseline, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(
        check_ruff_baseline,
        "run_ruff",
        lambda paths, *, root: [_diag(str(tmp_path / "backend" / "a.py"), "F401")],
    )

    code = check_ruff_baseline.main(["--baseline", str(baseline), "backend"])

    assert code == 0
    assert "0 new violations" in capsys.readouterr().out
