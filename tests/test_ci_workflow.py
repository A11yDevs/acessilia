"""The CI gate keeps its required name and runs the core suite in parallel (#448)."""

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
SCHEDULED = ROOT / ".github/workflows/scheduled-tests.yml"
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
    jobs = _workflow()["jobs"]
    expected = {jobs["tests"]["name"], jobs["sdk-isolated"]["name"]}
    for template in ("main.json.example", "develop.json.example"):
        ruleset = json.loads((RULESETS / template).read_text(encoding="utf-8"))
        checks = next(
            rule["parameters"]["required_status_checks"]
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        assert {check["context"] for check in checks} == expected
        assert {check.get("integration_id") for check in checks} == {15368}


def test_scheduled_workflow_runs_serial_and_parallel() -> None:
    workflow = yaml.safe_load(SCHEDULED.read_text(encoding="utf-8"))
    runs = [
        step.get("run", "")
        for step in workflow["jobs"]["monitor"]["steps"]
        if step.get("run")
    ]
    assert any(
        "--junitxml=serial-results.xml" in run and "-n 4" not in run for run in runs
    )
    assert any(
        "-n 4 --dist worksteal" in run and "--junitxml=parallel-results.xml" in run
        for run in runs
    )
    assert any("scripts/test_report.py" in run for run in runs)
    assert "schedule:" in SCHEDULED.read_text(encoding="utf-8")


def test_scheduled_workflow_covers_both_branches_and_library_results() -> None:
    workflow = yaml.safe_load(SCHEDULED.read_text(encoding="utf-8"))
    monitor = workflow["jobs"]["monitor"]

    assert monitor["strategy"]["fail-fast"] is False
    assert monitor["strategy"]["matrix"]["ref"] == ["main", "develop"]
    steps = monitor["steps"]
    checkout = next(
        step for step in steps if step.get("name", "").startswith("Check out")
    )
    assert checkout["with"]["ref"] == "${{ matrix.ref }}"
    assert any(step.get("name") == "Check docstruct and SDK reports" for step in steps)
    for name in ("Run docstruct library test suite", "Run SDK library test suite"):
        step = next(step for step in steps if step.get("name") == name)
        assert step.get("continue-on-error") is True


def test_scheduled_workflow_notifies_scheduled_failures() -> None:
    workflow = yaml.safe_load(SCHEDULED.read_text(encoding="utf-8"))
    notify = workflow["jobs"]["notify"]

    assert "always()" in notify["if"]
    assert "failure()" in notify["if"]
    assert "github.event_name == 'schedule'" in notify["if"]
    assert set(notify["needs"]) >= {"monitor", "e2e"}
    assert notify["permissions"]["issues"] == "write"
    run = next(step["run"] for step in notify["steps"] if step.get("run"))
    assert "gh issue create" in run
    assert "gh issue comment" in run


def test_scheduled_workflow_runs_e2e_only_when_configured() -> None:
    workflow = yaml.safe_load(SCHEDULED.read_text(encoding="utf-8"))
    e2e = workflow["jobs"]["e2e"]

    assert "vars.TOOLBOX_BASE_URL" in e2e["if"]
    assert "vars.CORE_BASE_URL" in e2e["if"]
    step = next(
        step for step in e2e["steps"] if step.get("name") == "Run end-to-end tests"
    )
    assert step["env"]["TOOLBOX_BASE_URL"] == "${{ vars.TOOLBOX_BASE_URL }}"
    assert step["env"]["TOOLBOX_API_KEY"] == "${{ secrets.TOOLBOX_API_KEY }}"
    assert step["env"]["CORE_BASE_URL"] == "${{ vars.CORE_BASE_URL }}"
    assert "--timeout=900" in step["run"]


def test_ruleset_templates_keep_live_review_settings_and_one_bypass() -> None:
    ruleset = json.loads((RULESETS / "main.json.example").read_text(encoding="utf-8"))
    pull_request = next(
        rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
    )
    parameters = pull_request["parameters"]

    assert parameters["require_extra_approval_for_unattributed_changes"] is True
    assert parameters["dismissal_restriction"] == {
        "enabled": False,
        "allowed_actors": [],
    }
    for template in ("main.json.example", "develop.json.example"):
        data = json.loads((RULESETS / template).read_text(encoding="utf-8"))
        assert len(data["bypass_actors"]) == 1


def test_develop_template_keeps_parallel_pull_requests_mergeable() -> None:
    ruleset = json.loads(
        (RULESETS / "develop.json.example").read_text(encoding="utf-8")
    )
    status_checks = next(
        rule["parameters"]
        for rule in ruleset["rules"]
        if rule["type"] == "required_status_checks"
    )
    assert status_checks["strict_required_status_checks_policy"] is False
    assert not any(rule["type"] == "pull_request" for rule in ruleset["rules"])
