"""Repository governance configuration: Dependabot and CODEOWNERS (#367)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEPENDABOT = ROOT / ".github" / "dependabot.yml"
CODEOWNERS = ROOT / ".github" / "CODEOWNERS"
CONTRIBUTING = ROOT / "CONTRIBUTING.md"
CONTRIBUTING_PT = ROOT / "CONTRIBUTING.pt-br.md"
GOVERNANCE_PATHS = frozenset(
    {
        "/.github/",
        "/schemas/",
        "/libs/",
        "/libs/core/",
        "/libs/sdk/",
        "/libs/docstruct/",
        "/docs/adr/",
    }
)
EXPECTED_UPDATES = frozenset(
    {
        ("github-actions", "/"),
        ("uv", "/"),
        ("uv", "/libs/core"),
        ("uv", "/libs/docstruct"),
        ("uv", "/libs/sdk"),
        ("docker", "/infra"),
    }
)


def _dependabot_updates() -> list[dict]:
    return yaml.safe_load(DEPENDABOT.read_text(encoding="utf-8"))["updates"]


def _codeowners() -> dict[str, list[str]]:
    entries: dict[str, list[str]] = {}
    for raw in CODEOWNERS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        entries[pattern] = owners
    return entries


def test_dependabot_targets_develop_and_uses_existing_labels() -> None:
    updates = _dependabot_updates()
    entries = {(update["package-ecosystem"], update["directory"]) for update in updates}
    assert entries == EXPECTED_UPDATES
    for update in updates:
        assert update["target-branch"] == "develop", update["directory"]
        labels = set(update["labels"])
        assert "dependencies" in labels, update["directory"]
        assert "ci" not in labels, update["directory"]
        assert labels <= {"dependencies", "ci-cd", "security"}, update["directory"]


def test_codeowners_covers_the_governance_paths() -> None:
    patterns = [
        raw.split("#", 1)[0].strip().split()[0]
        for raw in CODEOWNERS.read_text(encoding="utf-8").splitlines()
        if raw.split("#", 1)[0].strip()
    ]
    assert len(patterns) == len(set(patterns)), "duplicate CODEOWNERS patterns"
    entries = _codeowners()
    for path in GOVERNANCE_PATHS:
        assert path in entries, path
        assert entries[path], path
        assert all(owner.startswith("@") for owner in entries[path]), path
        assert (ROOT / path.strip("/")).exists(), path


def test_contributing_points_at_codeowners_in_both_languages() -> None:
    for document in (CONTRIBUTING, CONTRIBUTING_PT):
        assert ".github/CODEOWNERS" in document.read_text(encoding="utf-8")
