#!/usr/bin/env python3
"""Prepare and check production configuration without starting or migrating it."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

IMAGE = re.compile(r"ghcr\.io/a11ydevs/acessilia@sha256:[0-9a-f]{64}\Z")
DEPLOYMENT_KEYS = {
    "GHCR_TOKEN", "GITHUB_USER", "TRACK_BRANCH", "TRACK_TAG", "PRODUCTION_IMAGE",
    "PRODUCTION_DIR", "DEPLOY_DIR", "COMPOSE_FILE", "CONTAINER_NAME",
    "STAGING_DIR", "STAGING_UPDATE_CACHE", "STAGING_STATUS_FILE",
}
RUNNING_PROBE = '''
import json, os, urllib.request
interfaces = os.environ.get("ENABLED_INTERFACES", "telegram,web,api").split(",")
if "api" not in [item.strip() for item in interfaces]:
    raise SystemExit("Production verification requires the API interface")
base = "http://127.0.0.1:" + os.environ.get("API_PORT", "8000") + "/api/v1"
with urllib.request.urlopen(base + "/ready", timeout=15) as response:
    if json.load(response).get("status") != "ready":
        raise SystemExit("Structural providers are not ready")
with urllib.request.urlopen(base + "/health", timeout=15) as response:
    if json.load(response).get("model_reachable") is not True:
        raise SystemExit("VLM is unavailable through the production Toolbox")
print("Structural providers and Toolbox VLM health verified")
'''


def prepare(directory: Path, repository: Path) -> None:
    """Create private configuration exclusively; preserve existing files/data."""
    sources = {
        "docker-compose.production.yml": "docker-compose.production.yml",
        ".env": "deploy/production.runtime.env.example",
        ".deploy.env": "deploy/production.deploy.env.example",
        "ops/production-update.sh": "scripts/production-update.sh",
        "ops/staging-update.sh": "scripts/staging-update.sh",
        "ops/production_deploy.py": "scripts/production_deploy.py",
    }
    if directory.is_symlink() or (directory / "ops").is_symlink():
        raise ValueError("Deployment directories must not be symlinks")
    for name in sources:
        if os.path.lexists(directory / name):
            raise ValueError(f"Destination already exists; nothing overwritten: {directory / name}")
    payloads = {name: (repository / source).read_bytes() for name, source in sources.items()}
    os.umask(0o077)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    (directory / "ops").mkdir(exist_ok=True, mode=0o700)
    for name, payload in payloads.items():
        path = directory / name
        with path.open("xb") as output:
            output.write(payload)
        path.chmod(0o700 if name.endswith(".sh") else 0o600)
    print("Prepared configuration only. No data directory, containers or timers created.")
    print("Fill runtime credentials in .env and the approved digest in .deploy.env.")


def compose_command(directory: Path) -> list[str]:
    return ["docker", "compose", "-p", "production", "--env-file", str(directory / ".deploy.env"),
            "-f", str(directory / "docker-compose.production.yml")]


def check_config(config: dict, directory: Path, *, require_data: bool) -> str:
    service = config["services"]["acessilia"]
    image = service["image"]
    if not IMAGE.fullmatch(image):
        raise ValueError("Activation requires an approved ghcr.io/a11ydevs/acessilia@sha256 digest")
    environment = service.get("environment", {})
    if DEPLOYMENT_KEYS.intersection(environment):
        raise ValueError("Move deployment/update settings out of runtime .env into .deploy.env")
    if environment.get("AI_CLIENT") != "toolbox" or environment.get("PIPELINE_ENGINE") != "pddl":
        raise ValueError("Production must use AI_CLIENT=toolbox and PIPELINE_ENGINE=pddl")
    if not environment.get("TOOLBOX_API_KEY"):
        raise ValueError("Set the production Toolbox API key in runtime .env")
    if str(environment.get("PDDL_EXECUTE_DRY_RUN", "true")).lower() != "false":
        raise ValueError("Production requires PDDL_EXECUTE_DRY_RUN=false")
    interfaces = [value.strip() for value in environment.get("ENABLED_INTERFACES", "").split(",")]
    if "api" not in interfaces:
        raise ValueError("Enable API for production readiness and health verification")
    if "telegram" in interfaces and not environment.get("BOT_TOKEN"):
        raise ValueError("Set the production bot token or disable the Telegram interface")
    if environment.get("API_HOST") != "0.0.0.0" or environment.get("API_PORT") != "8000":
        raise ValueError("Production API must listen on 0.0.0.0:8000 inside the container")
    if "web" in interfaces and environment.get("WEB_PORT") != "8001":
        raise ValueError("Production web must listen on port 8001 inside the container")
    for key, expected in {
        "TEMP_DIR": "/app/var/temp", "DATA_DIR": "/app/var/data", "LOGS_DIR": "/app/var/logs",
    }.items():
        if environment.get(key) != expected:
            raise ValueError(f"Production {key} must stay under the migrated /app/var mount")
    volumes = [volume for volume in service.get("volumes", []) if volume.get("target") == "/app/var"]
    if len(volumes) != 1 or volumes[0].get("type") != "bind":
        raise ValueError("Production requires one bind mount at /app/var")
    volume = volumes[0]
    if volume.get("bind", {}).get("create_host_path", False):
        raise ValueError("The runtime bind must not create an empty data directory")
    if Path(volume["source"]).resolve() != (directory / "var").resolve():
        raise ValueError("The runtime bind must reference this deployment's var directory")
    if require_data and not (directory / "var").is_dir():
        raise ValueError("Runtime var is missing; migrate and verify data before activation")
    # Covers the environment Toolbox's 120 s slot wait + 2700 s gateway call.
    for key in ("MODEL_CALL_TIMEOUT_SECONDS", "DATA_AGENT_TIMEOUT_SECONDS", "TOOLBOX_TIMEOUT_SECONDS"):
        if int(environment.get(key, "0")) < 3000:
            raise ValueError(f"{key} must cover the Toolbox/gateway timeout chain (at least 3000 s)")
    if service.get("container_name") != "acessilia-production" or config.get("name") != "production":
        raise ValueError("Keep the existing production project/container identity")
    return image


def check(directory: Path, *, require_data: bool = False) -> str:
    result = subprocess.run(compose_command(directory) + ["config", "--format", "json"],
                            capture_output=True, text=True, check=False)
    if result.returncode:
        raise ValueError("Compose configuration failed; inspect the files privately")
    image = check_config(json.loads(result.stdout), directory, require_data=require_data)
    print("Production configuration verified; no services started.")
    return image


def verify_running(image: str, container: str) -> None:
    expected = subprocess.check_output(["docker", "image", "inspect", image, "--format", "{{.Id}}"], text=True).strip()
    actual = subprocess.check_output(["docker", "inspect", container, "--format", "{{.Image}}"], text=True).strip()
    if not expected or actual != expected:
        raise ValueError("Running container does not use the selected production image")
    subprocess.run(["docker", "exec", "-i", container, "python3", "-"],
                   input=RUNNING_PROBE, text=True, check=True, timeout=40)
    print("Running image and dependency health verified. Real-document acceptance is still required.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("prepare", "check"):
        part = commands.add_parser(command)
        part.add_argument("--directory", type=Path, default=Path("/opt/acessilia/core"))
        if command == "check":
            part.add_argument("--require-data", action="store_true")
    running = commands.add_parser("verify-running")
    running.add_argument("--image", required=True)
    running.add_argument("--container", default="acessilia-production")
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            prepare(args.directory.absolute(), Path(__file__).resolve().parents[1])
        elif args.command == "check":
            check(args.directory.resolve(), require_data=args.require_data)
        else:
            verify_running(args.image, args.container)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(f"Production check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
