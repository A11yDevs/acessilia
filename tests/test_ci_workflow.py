"""The CI gate keeps its required name and runs the core suite in parallel (#448)."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
RULESETS = ROOT / ".github/rulesets"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_required_check_names_are_unchanged() -> None:
    jobs = _workflow()["jobs"]
    assert jobs["tests"]["name"] == "tests (Python 3.11)"
    assert jobs["sdk-isolated"]["name"] == "SDK alone (Python 3.11)"


def test_core_suite_runs_with_bounded_parallelism() -> None:
    steps = _workflow()["jobs"]["tests"]["steps"]
    names = [step.get("name") for step in steps]
    run = next(
        step["run"] for step in steps if step.get("name") == "Run complete test suite"
    )

    assert "-n 4" in run
    assert "--dist worksteal" in run
    assert "--junitxml=test-results.xml" in run
    assert "Collect complete test suite" not in names


def test_delivery_waits_for_tests_and_sdk_isolation() -> None:
    jobs = _workflow()["jobs"]
    assert set(jobs["delivery"]["needs"]) >= {"tests", "sdk-isolated"}
    assert "sdk-isolated" in jobs


def test_ruleset_templates_require_the_full_gate() -> None:
    expected = {"CI / tests (Python 3.11)", "CI / SDK alone (Python 3.11)"}
    for template in ("main.json.example", "develop.json.example"):
        ruleset = json.loads((RULESETS / template).read_text(encoding="utf-8"))
        checks = next(
            rule["parameters"]["required_status_checks"]
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        assert {check["context"] for check in checks} >= expected
