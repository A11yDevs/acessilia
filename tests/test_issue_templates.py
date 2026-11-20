"""Validate the GitHub issue form templates under ``.github/ISSUE_TEMPLATE/`` (#323)."""
from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_DIR = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
VALID_ELEMENT_TYPES = frozenset({"markdown", "textarea", "input", "dropdown", "checkboxes"})


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
    for item in body:
        assert item["type"] in VALID_ELEMENT_TYPES
        if item["type"] == "markdown":
            assert item["attributes"]["value"].strip()
            continue
        field_id = item["id"]
        assert isinstance(field_id, str) and field_id.strip()
        assert field_id not in fields, f"Duplicate field id: {field_id}"
        assert item["attributes"]["label"].strip()
        fields[field_id] = item
    return fields


def test_config_keeps_blank_issues_enabled() -> None:
    config = _load("config.yml")
    assert config.get("blank_issues_enabled") is True


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


def test_feature_request_template_contract() -> None:
    form = _load("feature_request.yml")

    assert form["name"].strip()
    assert form["description"].strip()
    assert "enhancement" in (form.get("labels") or [])

    fields = _fields_by_id(form)
    assert {"problem", "proposal"} <= set(fields)
    assert fields["problem"]["validations"]["required"] is True
    assert fields["proposal"]["validations"]["required"] is True
