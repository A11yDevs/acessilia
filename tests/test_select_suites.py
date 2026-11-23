"""The #644 shadow selector maps changed paths to suites without gating."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.tests import select_suites as selection


def test_a_docstruct_change_selects_its_consumers() -> None:
    result = selection.classify_paths(["libs/docstruct/src/docstruct/text/normalize.py"])

    assert result.suites == ("docstruct", "sdk", "core", "app")
    assert result.indicators["docstruct_changed"] is True
    assert "docstruct dependency" in result.reasons["core"][0]


def test_an_sdk_change_selects_the_core_and_the_service() -> None:
    result = selection.classify_paths(["libs/sdk/src/acessilia_sdk/cli.py"])

    assert result.suites == ("sdk", "core", "app")
    assert result.indicators["sdk_changed"] is True


def test_a_core_change_selects_the_core_and_the_service() -> None:
    result = selection.classify_paths(["libs/core/src/acessilia_core/config.py"])

    assert result.suites == ("core", "app")
    assert result.indicators["core_changed"] is True


def test_a_backend_change_selects_only_the_application_suite() -> None:
    result = selection.classify_paths(["backend/api/app.py"])

    assert result.suites == ("app",)
    assert result.indicators["app_changed"] is True


def test_documentation_is_checked_by_the_application_suite() -> None:
    result = selection.classify_paths(["docs/testing.md"])

    assert result.suites == ("app",)
    assert "documentation path" in result.reasons["app"][0]


def test_a_transversal_path_selects_every_suite_and_contracts() -> None:
    result = selection.classify_paths(["schemas/accessible_document.schema.json"])

    assert result.suites == ("docstruct", "sdk", "core", "app")
    assert result.infrastructure_changed is True
    assert result.contracts_required is True
    assert result.indicators["contracts_changed"] is True


def test_a_contract_fixture_does_not_override_the_component_rules() -> None:
    tests_fixture = selection.classify_paths(
        ["tests/fixtures/toolbox-schemas/dataset-item@1.json"]
    )
    core_fixture = selection.classify_paths(
        ["libs/core/tests/fixtures/toolbox-contract.json"]
    )
    backend_schema = selection.classify_paths(["backend/api/schemas/types.py"])

    assert tests_fixture.suites == ("app",)
    assert tests_fixture.contracts_required is False
    assert core_fixture.suites == ("core", "app")
    assert core_fixture.contracts_required is True
    assert backend_schema.suites == ("app",)
    assert backend_schema.contracts_required is False


def test_an_unknown_path_falls_back_conservatively() -> None:
    result = selection.classify_paths(["some/new/unknown.file"])

    assert result.suites == ("docstruct", "sdk", "core", "app")
    assert result.conservative is True
    assert result.infrastructure_changed is False
    assert result.indicators["unclassified_changed"] is True


def test_blank_paths_select_everything() -> None:
    result = selection.classify_paths(["", "   "])

    assert result.suites == ("docstruct", "sdk", "core", "app")
    assert result.conservative is True


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def test_changed_files_includes_deletions_and_both_sides_of_a_rename(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "review@example.org")
    _git(tmp_path, "config", "user.name", "Review")
    (tmp_path / "schemas").mkdir()
    (tmp_path / "schemas" / "document.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "libs" / "sdk").mkdir(parents=True)
    (tmp_path / "libs" / "sdk" / "cli.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "base")
    base = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True
    ).strip()
    (tmp_path / "schemas" / "document.json").unlink()
    (tmp_path / "libs" / "sdk" / "cli.py").rename(tmp_path / "libs" / "sdk" / "cli2.py")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-q", "-m", "change")

    changed = selection.changed_files(base, "HEAD", root=tmp_path)

    assert "schemas/document.json" in changed
    assert "libs/sdk/cli.py" in changed
    assert "libs/sdk/cli2.py" in changed


def test_a_docs_only_selector_does_not_hide_the_application_checks() -> None:
    report = selection.build_report(
        selection.classify_paths(["docs/testing.md"]),
        base_ref="origin/develop",
        head_ref="HEAD",
    )

    assert report["mode"] == "shadow"
    assert report["selected_suites"] == ["app"]
    assert report["skipped_suites"] == ["docstruct", "sdk", "core"]


def test_main_writes_json_and_markdown_for_explicit_paths(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "selection.json"
    summary = tmp_path / "selection.md"

    status = selection.main(
        [
            "--changed-file",
            "libs/sdk/src/acessilia_sdk/cli.py",
            "--output",
            str(output),
            "--summary",
            str(summary),
        ]
    )

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["kind"] == "impact-selection"
    assert payload["selected_suites"] == ["sdk", "core", "app"]
    assert summary.read_text(encoding="utf-8").startswith(
        "## Changed-component selection"
    )
    assert "does not skip anything" in summary.read_text(encoding="utf-8")
    assert "Selected suites" in capsys.readouterr().out


def test_main_treats_a_blank_explicit_path_conservatively(
    tmp_path: Path,
) -> None:
    output = tmp_path / "selection.json"

    assert selection.main(["--changed-file", "  ", "--output", str(output)]) == 0

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["selected_suites"] == ["docstruct", "sdk", "core", "app"]
    assert payload["conservative_fallback"] is True


def test_main_falls_back_when_git_diff_fails(tmp_path: Path) -> None:
    output = tmp_path / "selection.json"

    status = selection.main(
        [
            "--base-ref",
            "definitely-not-a-ref",
            "--output",
            str(output),
        ]
    )

    assert status == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["conservative_fallback"] is True
    assert payload["selected_suites"] == ["docstruct", "sdk", "core", "app"]
