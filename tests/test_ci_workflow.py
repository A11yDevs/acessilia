"""The CI gate keeps its required name and runs the main suite in parallel (#448)."""

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/ci.yml"
SECURITY = ROOT / ".github/workflows/security.yml"
SCHEDULED = ROOT / ".github/workflows/scheduled-tests.yml"
PRODUCTION = ROOT / ".github/workflows/production-deployment.yml"
RULESETS = ROOT / ".github/rulesets"
SETUP_ACTION = ROOT / ".github/actions/setup-root/action.yml"
BYPASS_FILTER = ROOT / "scripts/rulesets-bypass.jq"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _apply_bypass(payload: dict) -> dict:
    jq = shutil.which("jq")
    if jq is None:
        pytest.skip("jq is required by scripts/setup-rulesets.sh")
    completed = subprocess.run(
        [jq, "-f", str(BYPASS_FILTER)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
    )
    return json.loads(completed.stdout)


def _rendered_job_names(job: dict) -> set[str]:
    template = job["name"]
    versions = (
        job.get("strategy", {}).get("matrix", {}).get("python-version") or []
    )
    if not versions:
        return {template}
    return {
        template.replace("${{ matrix.python-version }}", str(v))
        for v in versions
    }


def test_ci_jobs_use_python_312() -> None:
    jobs = _workflow()["jobs"]
    for job_id in ("sdk-isolated", "core-isolated", "docstruct-isolated"):
        assert jobs[job_id]["strategy"]["matrix"]["python-version"] == ["3.12"]
        assert jobs[job_id]["env"]["UV_PYTHON"] == "${{ matrix.python-version }}"
    assert jobs["quality"]["env"]["UV_PYTHON"] == "3.12"
    assert jobs["component-tests"]["env"]["UV_PYTHON"] == "3.12"
    assert _rendered_job_names(jobs["tests"]) == {"tests (Python 3.12)"}
    assert _rendered_job_names(jobs["sdk-isolated"]) == {"SDK alone (Python 3.12)"}


def test_the_container_scan_builds_without_layer_cache() -> None:
    """A cached apt layer can hide Debian security updates (#750)."""
    workflow = yaml.safe_load(SECURITY.read_text(encoding="utf-8"))
    steps = {
        step["name"]: step
        for step in workflow["jobs"]["container-scan"]["steps"]
    }

    assert steps["Build the production image"]["with"]["no-cache"] is True


def test_quality_gates_run_once_in_the_quality_job() -> None:
    """Lint, types and contracts run once, independently of the four suites."""
    quality = _workflow()["jobs"]["quality"]
    steps = {step.get("name"): step for step in quality["steps"]}

    for name in (
        "Run Ruff against the shrinking baseline",
        "Run Mypy on the configured scope",
        "Run Mypy on the libraries with Python 3.11",
        "Check the Toolbox capability contract",
        "Report the Toolbox's docstruct pin",
    ):
        assert "if" not in steps[name], name
    assert "scripts/check_ruff_baseline.py" in steps[
        "Run Ruff against the shrinking baseline"
    ]["run"]
    assert "scripts/check_docstruct_pin.py" in steps[
        "Report the Toolbox's docstruct pin"
    ]["run"]


def test_the_tests_check_aggregates_all_component_jobs() -> None:
    """The required name stays, but it is green only when every provider succeeded."""
    job = _workflow()["jobs"]["tests"]

    assert set(job["needs"]) == {"quality", "component-tests"}
    assert job["if"] == "always()"
    steps = {step.get("name"): step for step in job["steps"]}
    verify = steps["Verify provider jobs"]
    assert "needs.quality.result" in verify["env"]["QUALITY"]
    assert "needs.component-tests.result" in verify["env"]["COMPONENTS"]
    assert '!= "success"' in verify["run"]
    assert "scripts/check_coverage_thresholds.py" in steps[
        "Check per-component coverage thresholds"
    ]["run"]


def test_component_jobs_keep_the_bounded_app_parallelism() -> None:
    job = _workflow()["jobs"]["component-tests"]
    steps = {step.get("name"): step for step in job["steps"]}
    run = steps["Run ${{ matrix.component }} test suite"]["run"]

    assert 'app) args=(-m "not e2e" -n 4 --dist worksteal)' in run
    assert "coverage=(backend frontend)" in run
    assert '--junitxml="$GITHUB_WORKSPACE/var/test-results/$COMPONENT.xml"' in run
    assert "Collect complete test suite" not in steps


def test_ci_publishes_the_test_timing_baseline_without_changing_the_gate() -> None:
    """#644 instruments the same JUnit reports; the summary never masks a failure."""
    job = _workflow()["jobs"]["tests"]
    steps = {step.get("name"): step for step in job["steps"]}

    timing = steps["Summarize test timings"]
    assert timing["continue-on-error"] is True
    assert "scripts/tests/collect_timings.py" in timing["run"]
    for label in ("app", "docstruct", "sdk", "core"):
        assert f"--report {label}=var/test-results/" in timing["run"]
    assert "--coverage-dir var/coverage" in timing["run"]
    assert "--output var/timings/baseline.json" in timing["run"]

    upload = steps["Upload timing baseline"]
    assert upload["with"]["path"] == "var/timings/baseline.json"


def test_component_jobs_pin_the_matrix_thresholds_and_artifacts() -> None:
    jobs = _workflow()["jobs"]
    component = jobs["component-tests"]
    include = component["strategy"]["matrix"]["include"]
    assert {(item["component"], item["directory"]) for item in include} == {
        ("app", "."),
        ("docstruct", "libs/docstruct"),
        ("sdk", "libs/sdk"),
        ("core", "libs/core"),
    }
    steps = {step.get("name"): step for step in component["steps"]}
    assert '--components "$COMPONENT"' in steps[
        "Check ${{ matrix.component }} coverage threshold"
    ]["run"]
    assert steps["Upload component test report"]["with"]["name"] == (
        "test-report-${{ matrix.component }}"
    )
    assert steps["Upload component coverage report"]["with"]["name"] == (
        "coverage-${{ matrix.component }}"
    )
    assert steps["Upload component test report"]["if"] == "always()"
    assert steps["Upload component coverage report"]["if"] == "always()"

    aggregate = {step.get("name"): step for step in jobs["tests"]["steps"]}
    assert "--components" not in aggregate[
        "Check per-component coverage thresholds"
    ]["run"]
    assert aggregate["Download component coverage reports"]["with"]["pattern"] == (
        "coverage-*"
    )
    assert aggregate["Download component test reports"]["with"]["pattern"] == (
        "test-report-*"
    )
    assert aggregate["Download component coverage reports"]["with"][
        "merge-multiple"
    ] is True


def test_the_aggregator_publishes_evidence_even_when_a_provider_fails() -> None:
    steps = _workflow()["jobs"]["tests"]["steps"]
    names = [step.get("name") for step in steps]
    assert names[-1] == "Verify provider jobs"
    by_name = {step.get("name"): step for step in steps}
    for name in (
        "Download component coverage reports",
        "Download component test reports",
        "Check per-component coverage thresholds",
        "Summarize test timings",
        "Summarize per-component coverage",
        "Upload combined reports",
        "Upload combined coverage reports",
        "Upload timing baseline",
        "Verify provider jobs",
    ):
        assert by_name[name]["if"] == "always()", name
def test_the_impact_selection_runs_in_shadow_mode_without_touching_the_gate() -> None:
    jobs = _workflow()["jobs"]
    job = jobs["detect-changes"]
    steps = {step.get("name"): step for step in job["steps"]}

    assert job["if"] == "github.event_name == 'pull_request'"
    assert steps["Check out repository"]["with"]["fetch-depth"] == 0
    assert steps["Fetch the base branch"]["continue-on-error"] is True
    assert steps["Select impacted suites in shadow mode"]["continue-on-error"] is True
    assert "scripts/tests/select_suites.py" in steps[
        "Select impacted suites in shadow mode"
    ]["run"]
    assert "--summary" in steps["Select impacted suites in shadow mode"]["run"]
    assert steps["Upload the shadow selection"]["with"]["name"] == (
        "test-selection-shadow"
    )
    assert "detect-changes" not in jobs["tests"].get("needs", [])
    assert "detect-changes" not in jobs["delivery"]["needs"]





def test_delivery_waits_for_tests_and_isolation_jobs() -> None:
    """Images are published only after the core, SDK-alone and docstruct-alone jobs."""
    jobs = _workflow()["jobs"]
    assert set(jobs["delivery"]["needs"]) >= {
        "tests", "sdk-isolated", "core-isolated", "docstruct-isolated",
    }
    assert "sdk-isolated" in jobs
    assert "docstruct-isolated" in jobs


def test_docstruct_runs_alone_from_its_wheel() -> None:
    """docstruct installs from its wheel and its own lock, on the standard library alone."""
    job = _workflow()["jobs"]["docstruct-isolated"]
    steps = {step.get("name"): step for step in job["steps"]}

    assert _rendered_job_names(job) == {"docstruct alone (Python 3.12)"}
    install = steps["Install docstruct alone from its lock"]["run"]
    assert "uv lock --check --project libs/docstruct" in install
    assert (
        "uv sync --locked --extra dev --project libs/docstruct --no-editable" in install
    )
    assert "libs/sdk" not in install and '".[dev]"' not in install
    check = steps["Check that no other project package or accelerator is importable"]
    assert check["working-directory"] == "libs/docstruct"
    assert "uv run --locked --extra dev --no-editable" in check["run"]
    assert '--project "$GITHUB_WORKSPACE/libs/docstruct"' in check["run"]
    for name in ("backend", "acessilia_core", "acessilia_sdk", "acessilia_toolbox", "rapidfuzz"):
        assert f'"{name}"' in check["run"]
    assert "site-packages" in check["run"]
    suite = steps["Run the docstruct test suite"]
    assert suite["working-directory"] == "libs/docstruct"
    assert "--junitxml=docstruct-isolated-results.xml" in suite["run"]
    assert "skipped" in steps["Reject unexpected skipped tests"]["run"]


def test_sdk_runs_alone_with_docstruct_only() -> None:
    """The SDK installs with docstruct, its one project dependency (ADR-0017), and nothing else."""
    job = _workflow()["jobs"]["sdk-isolated"]
    steps = {step.get("name"): step for step in job["steps"]}

    install = steps["Install the SDK alone from its lock"]["run"]
    assert "uv lock --check --project libs/sdk" in install
    assert "uv sync --locked --extra dev --project libs/sdk --no-editable" in install
    assert '".[dev]"' not in install
    check = steps["Check that the core is not importable"]["run"]
    assert '"$GITHUB_WORKSPACE/libs/sdk"' in check
    for name in ("backend", "acessilia_core", "acessilia_toolbox", "agno", "fastapi"):
        assert f'"{name}"' in check
    assert '"docstruct"' not in check
    assert "skipped" in steps["Reject unexpected skipped tests"]["run"]


def test_core_runs_alone_from_its_wheel() -> None:
    """The core installs from its own lock, without the service, and its full
    suite plus the smoke test run from the wheel (ADR-0016, step 6)."""
    job = _workflow()["jobs"]["core-isolated"]
    steps = {step.get("name"): step for step in job["steps"]}

    install = steps["Install the core alone from its lock"]["run"]
    assert "uv lock --check --project libs/core" in install
    assert "uv sync --locked --extra dev --project libs/core --no-editable" in install
    check = steps["Check that the service is not importable"]
    for name in ("backend", "frontend", "fastapi", "acessilia_toolbox"):
        assert f'"{name}"' in check["run"]
    assert "site-packages" in check["run"]
    suite = steps["Run the core library test suite from the wheel"]
    assert suite["working-directory"] == "libs/core"
    assert "pytest -rs --junitxml=core-isolated-results.xml tests" in suite["run"]
    smoke = steps["Run the smoke test outside the checkout"]["run"]
    assert '"$RUNNER_TEMP/core-smoke"' in smoke and "cp libs/core/tests/test_smoke.py" in smoke
    assert '--project "$GITHUB_WORKSPACE/libs/core"' in smoke
    assert "skipped" in steps["Reject unexpected skipped tests"]["run"]
    example = steps["Run the table stage from a script"]["run"]
    assert "libs/core/examples/table_stage.py" in example
    assert "tables_manifest.json" in example and "text-heuristic" in example


def test_ci_installs_the_root_environment_from_the_lock() -> None:
    """The component and quality jobs use the shared root environment (#405)."""
    action = yaml.safe_load(SETUP_ACTION.read_text(encoding="utf-8"))
    assert action["runs"]["using"] == "composite"
    assert action["inputs"]["lock-hash"]["required"] is True
    steps = {step.get("name"): step for step in action["runs"]["steps"]}
    assert "Set up Python ${{ inputs.python-version }}" in steps
    uv = steps["Set up uv"]
    assert uv["uses"].startswith("astral-sh/setup-uv@")
    assert uv["with"]["version"] == "0.11.17"
    assert uv["with"]["enable-cache"] is True
    assert "Restore uv cache" not in steps
    install = steps["Check the lock and install from it"]["run"]
    assert "lock-hash is empty" in install
    assert "uv lock --check" in install
    assert "uv sync --locked --extra dev" in install

    jobs = _workflow()["jobs"]
    for job_id in ("quality", "component-tests"):
        steps = {step.get("name"): step for step in jobs[job_id]["steps"]}
        setup = steps["Set up root environment"]
        assert setup["uses"] == "./.github/actions/setup-root"
        assert setup["with"]["python-version"] == "3.12"
        assert setup["with"]["lock-hash"] == "${{ hashFiles('uv.lock') }}"
        assert not any("pip install" in (step.get("run") or "") for step in jobs[job_id]["steps"])

    component = jobs["component-tests"]
    steps = {step.get("name"): step for step in component["steps"]}
    run = steps["Run ${{ matrix.component }} test suite"]["run"]
    assert "uv run --locked --extra dev" in run
    assert '--project "$GITHUB_WORKSPACE"' in run

    aggregate = {step.get("name"): step for step in jobs["tests"]["steps"]}
    assert "Set up uv" not in aggregate
    assert "Set up root environment" not in aggregate


def test_production_container_installs_dev_deps_into_the_uv_venv() -> None:
    """The runtime venv has no pip; install test deps with the base pip."""
    workflow = yaml.safe_load(PRODUCTION.read_text(encoding="utf-8"))
    step = next(
        step
        for step in workflow["jobs"]["container-tests"]["steps"]
        if step.get("name", "").startswith("Run the main, core library")
    )
    run = step["run"]

    assert "BASE_PYTHON=/usr/local/bin/python3" in run
    assert '"$BASE_PYTHON" -m pip --python /app/.venv/bin/python install' in run
    assert "python -m pytest libs/core/tests" in run
    assert "core-library-results.xml" in run


def test_ruleset_templates_require_the_full_gate() -> None:
    jobs = _workflow()["jobs"]
    rendered = _rendered_job_names(jobs["tests"]) | _rendered_job_names(
        jobs["sdk-isolated"]
    )
    expected = {"tests (Python 3.12)", "SDK alone (Python 3.12)"}
    assert expected <= rendered
    for template in ("main.json.example", "develop.json.example"):
        ruleset = json.loads((RULESETS / template).read_text(encoding="utf-8"))
        checks = next(
            rule["parameters"]["required_status_checks"]
            for rule in ruleset["rules"]
            if rule["type"] == "required_status_checks"
        )
        assert {check["context"] for check in checks} == expected
        assert {check.get("integration_id") for check in checks} == {15368}


def test_scheduled_workflow_installs_from_the_lock() -> None:
    """The weekly monitor uses the same shared root environment as the gate (#405)."""
    workflow = yaml.safe_load(SCHEDULED.read_text(encoding="utf-8"))
    for name in ("monitor", "e2e"):
        steps = {step.get("name"): step for step in workflow["jobs"][name]["steps"]}
        setup = steps["Set up root environment"]
        assert setup["uses"] == "./.github/actions/setup-root"
        assert setup["with"]["python-version"] == "3.12"
        assert setup["with"]["lock-hash"] == "${{ hashFiles('uv.lock') }}"
        runs = [step.get("run", "") for step in workflow["jobs"][name]["steps"]]
        assert not any("pip install" in run for run in runs)
        assert all("uv run --locked" in run for run in runs if "pytest" in run)


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
    assert any(step.get("name") == "Check library reports" for step in steps)
    for name in (
        "Run docstruct library test suite",
        "Run SDK library test suite",
        "Run core library test suite",
    ):
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


def test_ruleset_templates_keep_live_review_settings() -> None:
    ruleset = json.loads((RULESETS / "main.json.example").read_text(encoding="utf-8"))
    pull_request = next(
        rule for rule in ruleset["rules"] if rule["type"] == "pull_request"
    )

    assert pull_request["parameters"] == {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews_on_push": True,
        "required_reviewers": [],
        "require_code_owner_review": False,
        "dismissal_restriction": {"enabled": False, "allowed_actors": []},
        "require_last_push_approval": True,
        "required_review_thread_resolution": True,
        "require_extra_approval_for_unattributed_changes": True,
        "allowed_merge_methods": ["merge", "squash", "rebase"],
    }


def test_ruleset_bypass_filter_is_idempotent_and_keeps_template_mode() -> None:
    for template in ("main.json.example", "develop.json.example"):
        transformed = _apply_bypass(
            json.loads((RULESETS / template).read_text(encoding="utf-8"))
        )
        admins = [
            actor
            for actor in transformed["bypass_actors"]
            if actor["actor_id"] == 5 and actor["actor_type"] == "RepositoryRole"
        ]
        assert len(admins) == 1
        assert admins[0]["bypass_mode"] == "always"

    added = _apply_bypass({"bypass_actors": []})
    assert added["bypass_actors"] == [
        {
            "actor_id": 5,
            "actor_type": "RepositoryRole",
            "bypass_mode": "always",
        }
    ]

    preferred = [
        {
            "actor_id": 5,
            "actor_type": "RepositoryRole",
            "bypass_mode": "pull_request",
        }
    ]
    assert _apply_bypass({"bypass_actors": preferred})["bypass_actors"] == preferred


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


def test_docstruct_pin_is_reported_in_pull_requests_and_enforced_on_schedule() -> None:
    """Only the Toolbox can move its docstruct pin (#470, P8): warn, then enforce weekly."""
    steps = _workflow()["jobs"]["quality"]["steps"]
    report = next(step for step in steps if step.get("name") == "Report the Toolbox's docstruct pin")
    assert "scripts/check_docstruct_pin.py" in report["run"]
    assert "--report-only" in report["run"]
    assert report["env"]["TARGET_BRANCH"] == "${{ github.base_ref || github.ref_name }}"

    workflow = yaml.safe_load(SCHEDULED.read_text(encoding="utf-8"))
    monitor = workflow["jobs"]["monitor"]["steps"]
    strict = next(step for step in monitor if step.get("name") == "Check the Toolbox's docstruct pin")
    assert "scripts/check_docstruct_pin.py" in strict["run"]
    assert "--report-only" not in strict["run"]
    assert strict["if"] == "always()"
    assert strict["env"]["TARGET_BRANCH"] == "${{ matrix.ref }}"


def test_the_security_audit_pins_uv_and_checks_the_lock() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    )
    steps = {
        step.get("name"): step
        for step in workflow["jobs"]["dependency-audit"]["steps"]
    }
    uv = steps["Set up uv"]
    assert uv["uses"].startswith("astral-sh/setup-uv@")
    assert uv["with"]["version"] == "0.11.17"
    assert "uv lock --check" in steps["Check the lock is current"]["run"]
    assert "uv export --locked" in steps["Export locked dependencies"]["run"]


def test_the_container_scan_is_conditional_on_image_paths() -> None:
    workflow = yaml.safe_load(SECURITY.read_text(encoding="utf-8"))
    changes = workflow["jobs"]["image-changes"]
    scan = workflow["jobs"]["container-scan"]

    assert changes["if"] == "github.event_name == 'pull_request'"
    filter_step = changes["steps"][1]
    assert filter_step["uses"].startswith("dorny/paths-filter@")
    filters = filter_step["with"]["filters"]
    for path in ("infra/**", "pyproject.toml", "uv.lock", ".trivyignore"):
        assert path in filters
    assert scan["needs"] == "image-changes"
    assert scan["if"] == (
        "always() && (github.event_name != 'pull_request' || "
        "needs.image-changes.outputs.image == 'true')"
    )


def test_the_image_scan_reads_the_recorded_exception() -> None:
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8")
    )
    scans = [
        step
        for step in workflow["jobs"]["container-scan"]["steps"]
        if step.get("uses", "").startswith("aquasecurity/trivy-action@")
    ]
    assert len(scans) == 2
    assert all(step["with"]["trivyignores"] == ".trivyignore" for step in scans)
