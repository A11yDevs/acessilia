import os
import shutil
import subprocess
from pathlib import Path


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


def test_production_update_tracks_main_with_production_compose(tmp_path):
    production_dir = tmp_path / "production"
    scripts_dir = tmp_path / "scripts"
    bin_dir = tmp_path / "bin"
    production_dir.mkdir()
    scripts_dir.mkdir()
    bin_dir.mkdir()
    (production_dir / "var" / "data").mkdir(parents=True)
    (production_dir / "docker-compose.production.yml").write_text("services: {}\n")

    update_script = scripts_dir / "staging-update.sh"
    production_script = scripts_dir / "production-update.sh"
    shutil.copy(ROOT_DIR / "scripts" / "staging-update.sh", update_script)
    shutil.copy(ROOT_DIR / "scripts" / "production-update.sh", production_script)
    update_script.chmod(0o755)
    production_script.chmod(0o755)

    _write_executable(
        bin_dir / "curl",
        """#!/usr/bin/env bash
printf '%s\n' "$*" > "$DEPLOY_DIR/curl-args.txt"
printf '{"sha":"abcdef1234567890"}'
""",
    )
    _write_executable(
        bin_dir / "docker",
        """#!/usr/bin/env bash
printf '%s\n' "$*" >> "$DEPLOY_DIR/docker-args.txt"
exit 0
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "GHCR_TOKEN": "token-do-ambiente",
            "PATH": f"{bin_dir}:{env['PATH']}",
            "PRODUCTION_DIR": str(production_dir),
        }
    )

    subprocess.run([str(production_script)], env=env, check=True, capture_output=True, text=True)

    assert "/commits/main" in (production_dir / "curl-args.txt").read_text()
    docker_calls = (production_dir / "docker-args.txt").read_text()
    assert "pull ghcr.io/a11ydevs/acessilia:main" in docker_calls
    assert "compose -f docker-compose.production.yml up -d --no-deps acessilia" in docker_calls


def test_setup_producao_help_is_available():
    result = subprocess.run(
        [str(ROOT_DIR / "scripts" / "setup-producao.sh"), "--help"],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "--production-dir" in result.stdout
    assert "--no-timer" in result.stdout
    assert "GITHUB_USER, GHCR_TOKEN, PRODUCTION_DIR" in result.stdout
