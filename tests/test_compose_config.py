from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_local_compose_builds_runtime_stage():
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.yml").read_text())

    build_config = compose["services"]["acessilia"]["build"]

    assert build_config["dockerfile"] == "infra/Dockerfile"
    assert "target" not in build_config


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


def test_release_workflow_publishes_semver_tags():
    workflow_text = (ROOT_DIR / ".github" / "workflows" / "release.yml").read_text()

    assert "type=semver,pattern={{version}}" in workflow_text
    assert "type=semver,pattern={{major}}.{{minor}}" in workflow_text
    assert "type=semver,pattern={{major}}" in workflow_text


def test_staging_reaches_the_toolbox_without_public_dns():
    """Staging must not depend on the host resolving its own public name.

    The Toolbox runs on the same host and publishes 8002. When
    TOOLBOX_BASE_URL pointed at the public reverse-proxy URL, every job failed
    with "Temporary failure in name resolution" because split-horizon DNS does
    not resolve the public name from inside the host, and no document was
    processed at all.
    """
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.staging.yml").read_text())
    service = compose["services"]["acessilia"]

    assert "host.docker.internal:host-gateway" in service["extra_hosts"]

    base_url = service["environment"]["TOOLBOX_BASE_URL"]
    assert "host.docker.internal" in base_url
    assert "acessilia3.inf.ufg.br" not in base_url


def test_staging_toolbox_url_survives_a_stale_env_file():
    """The staging .env is also the env_file, so it must not win over the default.

    Interpolating ``${TOOLBOX_BASE_URL:-...}`` reads the host shell env / project
    .env, so a stale ``TOOLBOX_BASE_URL`` in the staging .env shadowed the
    default and the container kept receiving the public URL. The override knob
    is therefore a distinct name, and the literal default has to be what the
    container actually gets.
    """
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.staging.yml").read_text())
    environment = compose["services"]["acessilia"]["environment"]

    assert environment["TOOLBOX_BASE_URL"] == (
        "${STAGING_TOOLBOX_BASE_URL:-http://host.docker.internal:8002}"
    )
    # Interpolating the same name the .env defines is what made the fix inert.
    assert "${TOOLBOX_BASE_URL" not in environment["TOOLBOX_BASE_URL"]
