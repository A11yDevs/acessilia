from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_local_compose_builds_runtime_stage():
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.yml").read_text())

    build_config = compose["services"]["acessilia"]["build"]

    assert build_config["dockerfile"] == "infra/Dockerfile"
    assert build_config["target"] == "base"


def test_production_compose_uses_main_image_and_production_container():
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.production.yml").read_text())

    service = compose["services"]["acessilia"]

    assert service["image"] == "ghcr.io/a11ydevs/acessilia:${TRACK_TAG:-main}"
    assert service["container_name"] == "acessilia-production"
    assert service["restart"] == "unless-stopped"


def test_delivery_is_reusable_with_explicit_commit_reference():
    workflow = yaml.safe_load(
        (ROOT_DIR / ".github" / "workflows" / "delivery.yml").read_text()
    )

    workflow_call = workflow[True]["workflow_call"]
    workflow_text = (ROOT_DIR / ".github" / "workflows" / "delivery.yml").read_text()

    assert set(workflow_call["inputs"]) == {"ref", "branch", "sha"}
    assert all(
        workflow_call["inputs"][name]["required"]
        for name in ("ref", "branch", "sha")
    )
    assert workflow[True]["workflow_dispatch"]["inputs"] == workflow_call["inputs"]
    assert "github.event.workflow_run" not in workflow_text
    assert "${{ inputs.ref }}" in workflow_text
    assert "${{ inputs.branch }}" in workflow_text
    assert "${{ inputs.sha }}" in workflow_text


def test_release_workflow_publishes_slim_semver_tags_with_suffix():
    workflow_text = (ROOT_DIR / ".github" / "workflows" / "release.yml").read_text()

    assert "tag_suffix: -slim" in workflow_text
    assert "type=semver,pattern={{version}},suffix=${{ matrix.tag_suffix }}" in workflow_text
    assert "type=semver,pattern={{major}}.{{minor}},suffix=${{ matrix.tag_suffix }}" in workflow_text
    assert "type=semver,pattern={{major}},suffix=${{ matrix.tag_suffix }}" in workflow_text
