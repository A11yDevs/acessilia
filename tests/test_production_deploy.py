import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
import yaml

from scripts import production_deploy as deploy

ROOT = Path(__file__).resolve().parents[1]
PIN = "ghcr.io/a11ydevs/acessilia@sha256:" + "a" * 64


@pytest.fixture
def config(tmp_path):
    runtime = dict(line.split("=", 1) for line in
                   (ROOT / "deploy/production.runtime.env.example").read_text().splitlines()
                   if line and not line.startswith("#"))
    runtime.update(TOOLBOX_API_KEY="test-only", BOT_TOKEN="test-only")
    service = yaml.safe_load((ROOT / "docker-compose.production.yml").read_text())["services"]["acessilia"]
    service["image"] = PIN
    service["environment"] = runtime | service["environment"]
    service["volumes"][0]["source"] = str(tmp_path / "var")
    return {"name": "production", "services": {"acessilia": service}}


@pytest.mark.parametrize("flag", ["--prepare-only", "--no-timer"])
def test_prepare_creates_no_runtime_data_or_external_actions(tmp_path, flag):
    directory = tmp_path / "core"
    result = subprocess.run(["bash", str(ROOT / "scripts/setup-producao.sh"), flag,
                             "--production-dir", str(directory)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert not (directory / "var").exists()
    assert (directory / ".env").stat().st_mode & 0o777 == 0o600
    assert "GHCR_TOKEN=" not in (directory / ".env").read_text()
    assert "GHCR_TOKEN=" in (directory / ".deploy.env").read_text()
    old_runtime = (directory / ".env").read_bytes()
    second = subprocess.run(["bash", str(ROOT / "scripts/setup-producao.sh"), flag,
                             "--production-dir", str(directory)], capture_output=True, text=True)
    assert second.returncode != 0
    assert (directory / ".env").read_bytes() == old_runtime
    assert not (directory / "var").exists()


def test_setup_requires_explicit_preparation(tmp_path):
    result = subprocess.run(["bash", str(ROOT / "scripts/setup-producao.sh"),
                             "--production-dir", str(tmp_path / "core")], capture_output=True)
    assert result.returncode != 0
    assert not (tmp_path / "core").exists()


def test_prepare_refuses_a_symlink_without_touching_its_target(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symlinks"):
        deploy.prepare(link, ROOT)
    assert list(target.iterdir()) == []


def test_check_requires_verified_data_before_activation(config, tmp_path):
    assert deploy.check_config(config, tmp_path, require_data=False) == PIN
    with pytest.raises(ValueError, match="migrate and verify"):
        deploy.check_config(config, tmp_path, require_data=True)
    assert not (tmp_path / "var").exists()
    (tmp_path / "var").mkdir()
    assert deploy.check_config(config, tmp_path, require_data=True) == PIN


@pytest.mark.parametrize("change, message", [
    ({"image": "ghcr.io/a11ydevs/acessilia:main"}, "approved"),
    ({"environment": {"GHCR_TOKEN": "must-stay-private"}}, "deployment/update"),
    ({"environment": {"AI_CLIENT": "openrouter"}}, "AI_CLIENT"),
    ({"environment": {"TOOLBOX_API_KEY": ""}}, "Toolbox API key"),
    ({"environment": {"PDDL_EXECUTE_DRY_RUN": "true"}}, "DRY_RUN"),
    ({"environment": {"MODEL_CALL_TIMEOUT_SECONDS": "600"}}, "timeout chain"),
    ({"environment": {"TOOLBOX_TIMEOUT_SECONDS": "2700"}}, "TOOLBOX_TIMEOUT_SECONDS"),
    ({"environment": {"TOOLBOX_TIMEOUT_SECONDS": "2819"}}, "TOOLBOX_TIMEOUT_SECONDS"),
    ({"environment": {"DATA_DIR": "/tmp/data"}}, "DATA_DIR"),
    ({"environment": {"API_PORT": "9000"}}, "0.0.0.0:8000"),
])
def test_check_rejects_unsafe_configuration(config, tmp_path, change, message):
    service = config["services"]["acessilia"]
    change = copy.deepcopy(change)
    service["environment"].update(change.pop("environment", {}))
    service.update(change)
    with pytest.raises(ValueError, match=message) as error:
        deploy.check_config(config, tmp_path, require_data=False)
    assert "must-stay-private" not in str(error.value)


def test_check_refuses_automatic_empty_volume_creation(config, tmp_path):
    config["services"]["acessilia"]["volumes"][0]["bind"]["create_host_path"] = True
    with pytest.raises(ValueError, match="empty data"):
        deploy.check_config(config, tmp_path, require_data=False)


def test_check_accepts_toolbox_timeout_covering_gateway_wait(config, tmp_path):
    config["services"]["acessilia"]["environment"]["TOOLBOX_TIMEOUT_SECONDS"] = "3000"
    assert deploy.check_config(config, tmp_path, require_data=False) == PIN


@pytest.mark.parametrize("ready, reachable, succeeds", [(True, True, True), (False, True, False), (True, False, False)])
def test_running_probe_distinguishes_http_success_from_dependency_health(ready, reachable, succeeds):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.endswith("/ready"):
                self.send_response(200 if ready else 503)
                payload = {"status": "ready" if ready else "unavailable"}
            else:
                self.send_response(200)
                payload = {"status": "ok", "model_reachable": reachable}
            self.end_headers()
            self.wfile.write(json.dumps(payload).encode())

        def log_message(self, *_args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        env = os.environ | {"API_PORT": str(server.server_port), "ENABLED_INTERFACES": "api"}
        result = subprocess.run([sys.executable, "-c", deploy.RUNNING_PROBE], env=env, capture_output=True, timeout=10)
        assert (result.returncode == 0) is succeeds
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_wrong_running_image_is_rejected_before_health_probe(monkeypatch):
    ids = iter(["expected", "different"])
    monkeypatch.setattr(deploy.subprocess, "check_output", lambda *_args, **_kwargs: next(ids))
    monkeypatch.setattr(deploy.subprocess, "run", lambda *_args, **_kwargs: pytest.fail("Unexpected health probe"))
    with pytest.raises(ValueError, match="selected production image"):
        deploy.verify_running(PIN, "acessilia-production")
