"""Unit tests for the shrinking docstruct allowlist check (scripts/check_docstruct_allowlist.py, #764)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts import check_docstruct_allowlist as check

ROOT = Path(__file__).resolve().parents[1]

BASE = {
    "docstruct.manifest": {"class": "contract"},
    "docstruct.fusion.judge": {
        "class": "algorithm",
        "files": {"a.py": ["decide_pair", "should_judge"], "b.py": ["should_judge"]},
    },
}


def _head(**changes) -> dict:
    head = json.loads(json.dumps(BASE))
    head.update(changes)
    return head


def test_the_same_allowlist_does_not_widen() -> None:
    assert check.widenings(BASE, BASE) == []


def test_removals_do_not_widen() -> None:
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": {"a.py": ["should_judge"]}}})
    del head["docstruct.manifest"]
    assert check.widenings(BASE, head) == []


def test_a_new_module_widens() -> None:
    head = _head(**{"docstruct.text.latex": {"class": "algorithm", "files": {"a.py": ["bare_latex"]}}})
    assert check.widenings(BASE, head) == ["new module docstruct.text.latex (algorithm)"]


def test_a_new_importer_widens() -> None:
    files = {**BASE["docstruct.fusion.judge"]["files"], "c.py": ["should_judge"]}
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge: new importer c.py"]


def test_a_new_name_widens() -> None:
    files = {**BASE["docstruct.fusion.judge"]["files"], "b.py": ["debias", "should_judge"]}
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge: b.py adds debias"]


def test_replacing_a_wildcard_with_names_does_not_widen() -> None:
    base = _head(**{"docstruct.text.latex": {"class": "algorithm", "files": {"a.py": ["*"]}}})
    head = _head(**{"docstruct.text.latex": {"class": "algorithm", "files": {"a.py": ["bare_latex"]}}})
    assert check.widenings(base, head) == []


def test_adding_a_wildcard_widens() -> None:
    files = {**BASE["docstruct.fusion.judge"]["files"], "b.py": ["*", "should_judge"]}
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge: b.py adds *"]


def test_reclassifying_as_contract_widens() -> None:
    head = _head(**{"docstruct.fusion.judge": {"class": "contract"}})
    assert check.widenings(BASE, head) == ["docstruct.fusion.judge reclassified algorithm -> contract"]


def test_reclassifying_between_pinned_classes_does_not_widen() -> None:
    head = _head(**{"docstruct.fusion.judge": {**BASE["docstruct.fusion.judge"], "class": "policy"}})
    assert check.widenings(BASE, head) == []


def test_pinning_a_contract_module_does_not_widen() -> None:
    head = _head(**{"docstruct.manifest": {"class": "algorithm", "files": {"a.py": ["StructuredDocument"]}}})
    assert check.widenings(BASE, head) == []


def test_the_fixture_does_not_grow_against_head() -> None:
    """The script runs end to end on this repository: against HEAD, nothing grows."""
    result = subprocess.run(
        ["python", "scripts/check_docstruct_allowlist.py", "--base", "HEAD"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


# Integration: a temporary repository with distinct revisions.


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", *args],
        cwd=repo, check=True, capture_output=True,
    )


def _write_fixture(repo: Path, content: dict | str) -> None:
    path = repo / check.FIXTURE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")


def _repo(tmp_path: Path, base: dict | str | None) -> Path:
    """A repository whose commit ``base`` holds ``base`` as the fixture (none for ``None``)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README").write_text("x", encoding="utf-8")
    if base is not None:
        _write_fixture(repo, base)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "base")
    _git(repo, "tag", "base")
    return repo


def _run(repo: Path, *args: str, capsys) -> tuple[int, str]:
    code = check.main(["--base", "base", "--repo", str(repo), *args])
    return code, capsys.readouterr().out


def test_a_revision_without_growth_passes(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, BASE)
    head = _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": {"a.py": ["should_judge"]}}})
    _write_fixture(repo, head)
    assert _run(repo, capsys=capsys) == (0, "The docstruct allowlist does not grow against base.\n")


def test_a_revision_that_adds_a_name_fails(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, BASE)
    files = {**BASE["docstruct.fusion.judge"]["files"], "b.py": ["debias", "should_judge"]}
    _write_fixture(repo, _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}}))
    code, out = _run(repo, capsys=capsys)
    assert code == 1
    assert "::error::docstruct allowlist grows: docstruct.fusion.judge: b.py adds debias" in out


def test_an_allowed_exception_passes_with_a_warning(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, BASE)
    files = {**BASE["docstruct.fusion.judge"]["files"], "c.py": ["should_judge"]}
    _write_fixture(repo, _head(**{"docstruct.fusion.judge": {"class": "algorithm", "files": files}}))
    code, out = _run(repo, "--allow-exceptions", capsys=capsys)
    assert code == 0
    assert "::warning::docstruct allowlist grows: docstruct.fusion.judge: new importer c.py" in out


def test_an_unknown_ref_fails_closed(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, BASE)
    code = check.main(["--base", "origin/missing", "--repo", str(repo)])
    assert code == 2
    assert "::error::docstruct allowlist baseline" in capsys.readouterr().out


def test_a_base_commit_without_the_fixture_has_nothing_to_compare(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, None)
    _write_fixture(repo, BASE)
    code, out = _run(repo, capsys=capsys)
    assert code == 0
    assert "nothing to compare" in out


def test_an_invalid_base_fixture_fails_closed(tmp_path, capsys) -> None:
    repo = _repo(tmp_path, "{not json")
    _write_fixture(repo, BASE)
    code, out = _run(repo, capsys=capsys)
    assert code == 2
    assert "is not valid JSON" in out
