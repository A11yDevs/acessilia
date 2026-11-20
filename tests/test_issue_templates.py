"""Validate the GitHub issue form templates under ``.github/ISSUE_TEMPLATE/`` (#323)."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
VALID_ELEMENT_TYPES = frozenset(
    {"checkboxes", "dropdown", "input", "markdown", "textarea", "upload"}
)
FIELD_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
VALID_ISSUE_TYPES = frozenset({"Bug", "Feature", "Task"})


def _load(name: str) -> dict:
    path = TEMPLATE_DIR / name
    assert path.is_file(), f"Missing issue template file: {path}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _fields_by_id(form: dict) -> dict[str, dict]:
    body = form.get("body")
    assert isinstance(body, list) and body
    fields: dict[str, dict] = {}
    labels: set[str] = set()
    for item in body:
        assert item["type"] in VALID_ELEMENT_TYPES
        if item["type"] == "markdown":
            assert item["attributes"]["value"].strip()
            continue
        field_id = item["id"]
        assert isinstance(field_id, str) and FIELD_ID_RE.match(field_id), (
            f"Invalid GitHub form field id: {field_id!r}"
        )
        assert field_id not in fields, f"Duplicate field id: {field_id}"
        label = item["attributes"]["label"].strip()
        assert label
        assert label not in labels, f"Duplicate field label: {label!r}"
        labels.add(label)
        fields[field_id] = item
    return fields


def test_config_keeps_blank_issues_enabled_and_links_security_reporting() -> None:
    config = _load("config.yml")
    assert config.get("blank_issues_enabled") is True
    contact_links = config.get("contact_links") or []
    assert isinstance(contact_links, list) and contact_links
    for link in contact_links:
        assert link["name"].strip()
        assert link["url"].startswith("https://")
        assert link["about"].strip()
    assert any("/security/advisories/new" in link["url"] for link in contact_links)


def test_all_issue_templates_have_unique_names() -> None:
    names: list[str] = []
    for path in sorted(TEMPLATE_DIR.iterdir()):
        if path.name == "config.yml":
            continue
        if path.suffix in {".yml", ".yaml"}:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            assert isinstance(data, dict)
            name = data["name"].strip()
            assert name
            if "type" in data:
                assert data["type"] in VALID_ISSUE_TYPES
            names.append(name)
        elif path.suffix == ".md":
            text = path.read_text(encoding="utf-8")
            match = re.search(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
            assert match, f"Markdown template missing frontmatter: {path}"
            front = yaml.safe_load(match.group(1))
            assert isinstance(front, dict) and front["name"].strip()
            names.append(front["name"].strip())
    assert len(names) == len(set(names)), f"Duplicate template names: {names}"


def test_bug_report_template_contract() -> None:
    form = _load("bug_report.yml")

    assert form["name"].strip()
    assert form["description"].strip()
    assert form.get("type") == "Bug"
    assert "bug" in (form.get("labels") or [])

    fields = _fields_by_id(form)
    expected_required = {
        "summary": True,
        "version": True,
        "environment": True,
        "providers_and_models": False,
        "input": True,
        "steps": True,
        "expected": True,
        "actual": True,
        "assistive_technology": False,
        "reproducibility": True,
        "suspected_cause": False,
    }
    assert set(fields) == set(expected_required)
    for field_id, should_be_required in expected_required.items():
        actual_required = bool((fields[field_id].get("validations") or {}).get("required", False))
        assert actual_required is should_be_required, field_id

    env_placeholder = fields["environment"]["attributes"].get("placeholder", "")
    assert "LEGACY_UNICODE_REPAIR=auto" not in env_placeholder
    assert "LEGACY_UNICODE_REPAIR=repair" in env_placeholder


def test_feature_request_template_contract() -> None:
    form = _load("feature_request.yml")

    assert form["name"].strip()
    assert form["description"].strip()
    assert form.get("type") == "Feature"
    assert "feature" in (form.get("labels") or [])

    fields = _fields_by_id(form)
    assert {"problem", "proposal"} <= set(fields)
    assert fields["problem"]["validations"]["required"] is True
    assert fields["proposal"]["validations"]["required"] is True
