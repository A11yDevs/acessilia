from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_local_compose_builds_runtime_stage():
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.yml").read_text())

    build_config = compose["services"]["acessilia"]["build"]

    assert build_config["dockerfile"] == "infra/Dockerfile"
    assert build_config["target"] == "base"


def test_delivery_runs_only_after_successful_push_ci():
    workflow = yaml.safe_load(
        (ROOT_DIR / ".github" / "workflows" / "delivery.yml").read_text()
    )

    trigger = workflow[True]["workflow_run"]
    publish_job = workflow["jobs"]["publish"]
    workflow_text = (ROOT_DIR / ".github" / "workflows" / "delivery.yml").read_text()

    assert trigger["workflows"] == ["CI"]
    assert trigger["types"] == ["completed"]
    assert publish_job["if"] == (
        "github.event.workflow_run.conclusion == 'success' && "
        "github.event.workflow_run.event == 'push'"
    )
    assert "github.event.workflow_run.head_sha" in workflow_text
    assert "github.event.workflow_run.head_branch" in workflow_text
    assert "${{ github.sha }}" not in workflow_text
    assert "${{ github.ref_name }}" not in workflow_text
