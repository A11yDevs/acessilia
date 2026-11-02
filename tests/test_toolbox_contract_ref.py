"""Which Toolbox ref the CI contract check reads for each core branch (#186)."""

import subprocess
import sys
from pathlib import Path

import pytest

from scripts.toolbox_contract_ref import _remote_refs, select_ref

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "toolbox_contract_ref.py"


@pytest.mark.parametrize(
    ("target", "expected"),
    [("main", "main"), ("develop", "develop"), ("fix/some-bug", "develop")],
)
def test_non_release_branches_need_no_toolbox_refs(target, expected):
    assert select_ref(target, set(), set()) == expected


def test_open_release_uses_the_paired_toolbox_branch():
    branches = {"main", "release/0.3.0"}

    assert select_ref("release/0.3.0", branches, {"v0.2.0"}) == "release/0.3.0"


def test_open_release_prefers_its_branch_over_an_existing_tag():
    """A fix merged after tagging is only on the branch."""
    assert select_ref("release/0.2.0", {"release/0.2.0"}, {"v0.2.0"}) == "release/0.2.0"


def test_closed_release_uses_the_toolbox_tag():
    """After bhs finish --cleanup the Toolbox branch is gone; its tag remains."""
    tags = {"v0.1.0", "v0.2.0"}

    assert select_ref("release/0.2.0", {"main", "develop"}, tags) == "v0.2.0"


def test_release_without_branch_or_tag_is_an_error_not_a_fallback():
    with pytest.raises(ValueError, match=r"neither release/0\.4\.0 nor v0\.4\.0"):
        select_ref("release/0.4.0", {"main", "develop"}, {"v0.2.0"})


def _bare_repository(tmp_path, *, branches=(), tags=()):
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    git = ["git", "-C", str(work), "-c", "user.name=t", "-c", "user.email=t@t"]
    subprocess.run([*git, "commit", "-q", "--allow-empty", "-m", "c"], check=True)
    for branch in branches:
        subprocess.run([*git, "branch", branch], check=True)
    for tag in tags:
        subprocess.run([*git, "tag", "-a", tag, "-m", tag], check=True)
    return work


def test_remote_refs_lists_branches_and_peeled_tags_once(tmp_path):
    repository = _bare_repository(tmp_path, branches=["release/0.3.0"], tags=["v0.2.0"])

    branches, tags = _remote_refs(str(repository))

    assert branches == {"main", "release/0.3.0"}
    assert tags == {"v0.2.0"}


def test_cli_prints_the_tag_of_a_closed_release(tmp_path):
    repository = _bare_repository(tmp_path, tags=["v0.2.0"])

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "release/0.2.0", "--repository", str(repository)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "v0.2.0"


def test_cli_fails_for_a_release_the_toolbox_does_not_have(tmp_path):
    repository = _bare_repository(tmp_path)

    result = subprocess.run(
        [sys.executable, str(SCRIPT), "release/0.9.0", "--repository", str(repository)],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "neither release/0.9.0 nor v0.9.0" in result.stderr
