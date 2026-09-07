from pathlib import Path

import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


def test_local_compose_builds_runtime_stage():
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.yml").read_text())

    build_config = compose["services"]["acessilia"]["build"]

    assert build_config["dockerfile"] == "infra/Dockerfile"
    assert build_config["target"] == "base"
