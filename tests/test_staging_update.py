import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT_DIR = Path(__file__).resolve().parents[1]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


def test_staging_update_reads_track_branch_from_dotenv_with_env_token(tmp_path):
    staging_dir = tmp_path / "staging"
    bin_dir = tmp_path / "bin"
    staging_dir.mkdir()
    bin_dir.mkdir()
    (staging_dir / "var" / "data").mkdir(parents=True)
    (staging_dir / "docker-compose.staging.yml").write_text("services: {}\n")
    (staging_dir / ".env").write_text("TRACK_BRANCH=release/0.0.1\n")

    script_path = staging_dir / "staging-update.sh"
    shutil.copy(ROOT_DIR / "scripts" / "staging-update.sh", script_path)
    script_path.chmod(0o755)

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
printf '%s\n' "$*" > "$STAGING_DIR/curl-args.txt"
printf '{"sha":"1234567890abcdef"}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STAGING_DIR/docker-args.txt"
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "GHCR_TOKEN": "token-do-ambiente",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "STAGING_DIR": str(staging_dir),
        }
    )

    subprocess.run([str(script_path)], env=env, check=True, capture_output=True, text=True)

    assert "/commits/release/0.0.1" in (staging_dir / "curl-args.txt").read_text()
    assert "pull ghcr.io/a11ydevs/acessilia:release-0.0.1" in (
        staging_dir / "docker-args.txt"
    ).read_text()


def test_staging_update_env_track_branch_overrides_dotenv(tmp_path):
    staging_dir = tmp_path / "staging"
    bin_dir = tmp_path / "bin"
    staging_dir.mkdir()
    bin_dir.mkdir()
    (staging_dir / "var" / "data").mkdir(parents=True)
    (staging_dir / "docker-compose.staging.yml").write_text("services: {}\n")
    (staging_dir / ".env").write_text("TRACK_BRANCH=release/0.0.1\n")

    script_path = staging_dir / "staging-update.sh"
    shutil.copy(ROOT_DIR / "scripts" / "staging-update.sh", script_path)
    script_path.chmod(0o755)

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
printf '%s\n' "$*" > "$STAGING_DIR/curl-args.txt"
printf '{"sha":"1234567890abcdef"}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STAGING_DIR/docker-args.txt"
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "GHCR_TOKEN": "token-do-ambiente",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "STAGING_DIR": str(staging_dir),
            "TRACK_BRANCH": "release/0.0.2",
        }
    )

    subprocess.run([str(script_path)], env=env, check=True, capture_output=True, text=True)

    assert "/commits/release/0.0.2" in (staging_dir / "curl-args.txt").read_text()
    assert "pull ghcr.io/a11ydevs/acessilia:release-0.0.2" in (
        staging_dir / "docker-args.txt"
    ).read_text()


def test_staging_update_writes_digests_when_no_new_commit(tmp_path):
    """The health check needs both digests even when there is nothing to update.

    /api/v1/health derives `up_to_date` from `latest_digest` and
    `running_digest`; writing them only on the update path left the status file
    with empty digests, so "up to date" could never be reported. The published
    and running digests must also come from the same representation: the local
    image records the manifest-list digest, while `docker manifest inspect
    --verbose` returns the platform manifest digest.
    """
    staging_dir = tmp_path / "staging"
    bin_dir = tmp_path / "bin"
    staging_dir.mkdir()
    bin_dir.mkdir()
    (staging_dir / "var" / "data").mkdir(parents=True)
    (staging_dir / "docker-compose.staging.yml").write_text("services: {}\n")
    (staging_dir / ".env").write_text("TRACK_BRANCH=develop\n")

    image_digest = "sha256:" + "a" * 64
    platform_digest = "sha256:" + "b" * 64
    (staging_dir / "var" / "data" / ".last_sha").write_text(
        "develop 1234567890abcdef"
    )

    script_path = staging_dir / "staging-update.sh"
    shutil.copy(ROOT_DIR / "scripts" / "staging-update.sh", script_path)
    script_path.chmod(0o755)

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
printf '{"sha":"1234567890abcdef"}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        f"""#!/usr/bin/env bash
case "$*" in
  *"manifest inspect --verbose"*) printf '{{"Descriptor":{{"digest":"{platform_digest}"}}}}\\n' ;;
  *"image inspect"*) printf 'ghcr.io/a11ydevs/acessilia@{image_digest} {image_digest}\\n' ;;
esac
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "GHCR_TOKEN": "token-do-ambiente",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "STAGING_DIR": str(staging_dir),
        }
    )

    subprocess.run(
        [str(script_path)], env=env, check=True, capture_output=True, text=True
    )

    status = json.loads(
        (staging_dir / "var" / "data" / "staging-status.json").read_text()
    )
    assert status["latest_sha"] == "1234567890abcdef"
    assert status["running_sha"] == "1234567890abcdef"
    assert status["latest_digest"] == image_digest
    assert status["running_digest"] == image_digest


def test_staging_update_switches_image_when_track_branch_changes(tmp_path):
    """A new tracked branch at the cached commit still switches the image.

    At the start of BHS release/x.y.z can point at the same commit develop was
    deployed from; comparing only the SHA left staging on the develop image.
    """
    staging_dir = tmp_path / "staging"
    bin_dir = tmp_path / "bin"
    staging_dir.mkdir()
    bin_dir.mkdir()
    (staging_dir / "var" / "data").mkdir(parents=True)
    (staging_dir / "docker-compose.staging.yml").write_text("services: {}\n")
    (staging_dir / ".env").write_text("TRACK_BRANCH=release/0.0.1\n")
    cache_file = staging_dir / "var" / "data" / ".last_sha"
    cache_file.write_text("develop 1234567890abcdef")

    script_path = staging_dir / "staging-update.sh"
    shutil.copy(ROOT_DIR / "scripts" / "staging-update.sh", script_path)
    script_path.chmod(0o755)

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
printf '{"sha":"1234567890abcdef"}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STAGING_DIR/docker-args.txt"
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "GHCR_TOKEN": "token-do-ambiente",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "STAGING_DIR": str(staging_dir),
        }
    )

    subprocess.run([str(script_path)], env=env, check=True, capture_output=True, text=True)

    docker_calls = (staging_dir / "docker-args.txt").read_text()
    assert "pull ghcr.io/a11ydevs/acessilia:release-0.0.1" in docker_calls
    assert "pull ghcr.io/a11ydevs/acessilia:sha-" not in docker_calls
    assert "compose -f docker-compose.staging.yml up -d --no-deps acessilia" in docker_calls
    assert cache_file.read_text().strip() == "release/0.0.1 1234567890abcdef"


def test_staging_update_retries_a_transient_pull_failure(tmp_path):
    """A pull that fails once is retried, and the Docker error reaches stderr.

    006.pdf staging: the manifest for the sha tag existed, the branch tag had
    already been pulled, and the redundant sha-tag pull failed. The script now
    pulls once and retries a bad response instead of leaving the deployment
    behind on the first error.
    """
    staging_dir = tmp_path / "staging"
    bin_dir = tmp_path / "bin"
    staging_dir.mkdir()
    bin_dir.mkdir()
    (staging_dir / "var" / "data").mkdir(parents=True)
    (staging_dir / "docker-compose.staging.yml").write_text("services: {}\n")
    (staging_dir / ".env").write_text("TRACK_BRANCH=release/0.0.1\n")

    script_path = staging_dir / "staging-update.sh"
    shutil.copy(ROOT_DIR / "scripts" / "staging-update.sh", script_path)
    script_path.chmod(0o755)

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
printf '{"sha":"1234567890abcdef"}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
count_file="$STAGING_DIR/pull-count"
case "$*" in
  pull*)
    count=$(cat "$count_file" 2>/dev/null || echo 0)
    count=$((count + 1))
    printf '%s' "$count" > "$count_file"
    if [ "$count" -eq 1 ]; then
      echo "registry returned 500" >&2
      exit 1
    fi
    ;;
esac
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "GHCR_TOKEN": "token-do-ambiente",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PULL_RETRY_DELAY": "0",
            "STAGING_DIR": str(staging_dir),
        }
    )

    result = subprocess.run(
        [str(script_path)], env=env, check=True, capture_output=True, text=True
    )

    assert (staging_dir / "pull-count").read_text() == "2"
    assert "registry returned 500" in result.stderr
    assert "Falha ao puxar" in result.stderr


def test_staging_update_falls_back_when_github_request_fails(tmp_path):
    staging_dir = tmp_path / "staging"
    bin_dir = tmp_path / "bin"
    staging_dir.mkdir()
    bin_dir.mkdir()
    (staging_dir / "var" / "data").mkdir(parents=True)
    (staging_dir / "docker-compose.staging.yml").write_text("services: {}\n")
    (staging_dir / ".env").write_text("TRACK_BRANCH=release/0.0.1\n")

    script_path = staging_dir / "staging-update.sh"
    shutil.copy(ROOT_DIR / "scripts" / "staging-update.sh", script_path)
    script_path.chmod(0o755)

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
exit 22
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$STAGING_DIR/docker-args.txt"
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "GHCR_TOKEN": "token-do-ambiente",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "STAGING_DIR": str(staging_dir),
        }
    )

    subprocess.run([str(script_path)], env=env, check=True, capture_output=True, text=True)

    docker_calls = (staging_dir / "docker-args.txt").read_text()
    assert "pull ghcr.io/a11ydevs/acessilia:release-0.0.1" in docker_calls
    assert "compose -f docker-compose.staging.yml up -d --no-deps acessilia" in docker_calls


@pytest.mark.parametrize("mode", [
    "success", "pinned", "unhealthy", "compose-failed", "github-down", "wrong-revision", "wrong-image",
    "cached", "cached-vlm-down", "cached-drift", "cached-stopped", "cached-missing-status",
    "cached-wrong-sha", "cached-bad-digest", "cached-other-branch",
])
def test_production_update_accepts_only_verified_healthy_commit_images(tmp_path, mode):
    production_dir = tmp_path / "production"
    scripts_dir = tmp_path / "scripts"
    bin_dir = tmp_path / "bin"
    production_dir.mkdir()
    scripts_dir.mkdir()
    bin_dir.mkdir()
    (production_dir / "var/data").mkdir(parents=True)
    cache = production_dir / "var/data/.last_production_sha"
    status = production_dir / "var/data/production-status.json"
    cache.write_text("previous")
    status.write_text('{"previous":true}')
    if mode.startswith("cached"):
        cache.write_text(("develop " if mode == "cached-other-branch" else "main ") + "a" * 40)
        status.write_text(json.dumps({
            "running_sha": "c" * 40 if mode == "cached-wrong-sha" else "a" * 40,
            "running_digest": "invalid" if mode == "cached-bad-digest" else "sha256:" + "a" * 64,
            "last_update": "2026-10-30T10:00:00Z", "last_check": "2026-10-30T10:00:00Z",
        }))
        if mode == "cached-missing-status":
            status.unlink()
    pin = "ghcr.io/a11ydevs/acessilia@sha256:" + "a" * 64
    (production_dir / ".deploy.env").write_text(
        "PRODUCTION_IMAGE=" + (pin if mode == "pinned" else "") + "\n"
    )
    compose = yaml.safe_load((ROOT_DIR / "docker-compose.production.yml").read_text())
    compose["name"] = "production"
    service = compose["services"]["acessilia"]
    service["environment"] = {
        "AI_CLIENT": "toolbox", "PIPELINE_ENGINE": "pddl", "TOOLBOX_API_KEY": "test-only",
        "PDDL_EXECUTE_DRY_RUN": "false", "ENABLED_INTERFACES": "api",
        "API_HOST": "0.0.0.0", "API_PORT": "8000",
        "TEMP_DIR": "/app/var/temp", "DATA_DIR": "/app/var/data", "LOGS_DIR": "/app/var/logs",
        "MODEL_CALL_TIMEOUT_SECONDS": "3000", "DATA_AGENT_TIMEOUT_SECONDS": "3600",
        "TOOLBOX_TIMEOUT_SECONDS": "3600",
    }
    service["volumes"][0]["source"] = str(production_dir / "var")
    (production_dir / "resolved.json").write_text(json.dumps(compose))
    for name in ("staging-update.sh", "production-update.sh", "production_deploy.py"):
        shutil.copy(ROOT_DIR / "scripts" / name, scripts_dir / name)
        (scripts_dir / name).chmod(0o755)
    _write_executable(bin_dir / "curl", """#!/usr/bin/env bash
printf '%s\n' "$*" > "$DEPLOY_DIR/curl-args.txt"
[ "$TEST_MODE" != github-down ] || exit 1
printf '{"sha":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}'
""")
    _write_executable(bin_dir / "docker", r"""#!/usr/bin/env python3
import json, os, pathlib, sys
args = sys.argv[1:]
root = pathlib.Path(os.environ["DEPLOY_DIR"])
with (root / "docker-args.txt").open("a") as output:
    output.write(" ".join(args) + "\n")
mode = os.environ["TEST_MODE"]
started = (root / "started").exists()
if args[0] == "compose" and "config" in args:
    config = json.loads((root / "resolved.json").read_text())
    config["services"]["acessilia"]["image"] = os.environ.get("PRODUCTION_IMAGE") or "ghcr.io/a11ydevs/acessilia:main"
    print(json.dumps(config))
elif args[0] == "compose" and "up" in args:
    (root / "started").touch()
    sys.exit(1 if mode == "compose-failed" else 0)
elif args[:2] == ["image", "inspect"]:
    if "org.opencontainers.image.revision" in args[-1]:
        print("wrong" if mode == "wrong-revision" else "a" * 40)
    elif args[-1] == "{{.Id}}":
        print("sha256:" + "b" * 64)
    else:
        digest = "c" if args[2] == "sha256:" + "c" * 64 else "a"
        print("[ghcr.io/a11ydevs/acessilia@sha256:" + digest * 64 + "]")
elif args[0] == "inspect":
    if args[-1] == "{{.State.Running}}":
        print("false" if mode == "cached-stopped" and not started else "true")
    else:
        changed = mode == "wrong-image" or (mode in {"cached-drift", "unhealthy"} and not started)
        print("sha256:" + ("c" if changed else "b") * 64)
elif args[0] == "exec":
    sys.stdin.read()
    sys.exit(1 if mode in {"unhealthy", "cached-vlm-down"} else 0)
""")
    env = os.environ | {"PATH": f"{bin_dir}:{os.environ['PATH']}",
                       "PRODUCTION_DIR": str(production_dir), "TEST_MODE": mode}
    env.pop("PRODUCTION_IMAGE", None)
    result = subprocess.run([str(scripts_dir / "production-update.sh")], env=env,
                            capture_output=True, text=True)
    calls_file = production_dir / "docker-args.txt"
    calls = calls_file.read_text() if calls_file.exists() else ""
    if mode in {"cached", "cached-vlm-down"}:
        assert result.returncode == 0, result.stderr
        assert "pull " not in calls
        assert "manifest inspect" not in calls
        assert "up -d" not in calls
        assert "exec " not in calls
        assert calls.count("config --format json") == 1
        assert "Novo commit detectado" not in result.stdout
        assert cache.read_text() == "main " + "a" * 40
        current_status = json.loads(status.read_text())
        assert current_status["last_update"] == "2026-10-30T10:00:00Z"
        assert current_status["last_check"] != "2026-10-30T10:00:00Z"
        assert current_status["running_digest"] == "sha256:" + "a" * 64
    elif mode == "success" or mode.startswith("cached"):
        assert result.returncode == 0, result.stderr
        assert "/commits/main" in (production_dir / "curl-args.txt").read_text()
        assert "pull ghcr.io/a11ydevs/acessilia:sha-aaaaaaa" in calls
        assert "pull ghcr.io/a11ydevs/acessilia:main" not in calls
        assert "--wait --wait-timeout 120" in calls
        assert "image prune" not in calls
        assert cache.read_text().strip() == "main " + "a" * 40
        assert json.loads(status.read_text())["running_digest"] == "sha256:" + "a" * 64
    else:
        assert result.returncode != 0
        assert cache.read_text() == "previous"
        assert status.read_text() == '{"previous":true}'
        if mode in {"pinned", "github-down"}:
            assert "pull " not in calls
            assert "up -d" not in calls
        if mode in {"unhealthy", "compose-failed", "wrong-image"}:
            assert "new image may already be serving traffic" in result.stderr
            assert "manual rollback" in result.stderr
            assert "Previous image ID: sha256:" in result.stderr
            assert calls.count("up -d") == 1
        if mode == "unhealthy":
            assert "Previous image ID: sha256:" + "c" * 64 in result.stderr


def test_setup_producao_help_is_available():
    result = subprocess.run(
        [str(ROOT_DIR / "scripts" / "setup-producao.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--production-dir" in result.stdout
    assert "--no-timer" in result.stdout
    assert "--prepare-only" in result.stdout
