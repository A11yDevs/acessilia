"""scripts/ops.sh against a local git origin and stubbed system commands."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]

# Stands in for scripts/staging-update.sh: records how ops.sh invoked it.
_ENGINE = """#!/usr/bin/env bash
printf 'STAGING_DIR=%s DEPLOY_DIR=%s\\n' "$STAGING_DIR" "${DEPLOY_DIR:-}" >> "$STAGING_DIR/engine-calls.txt"
"""

_LOGGING_STUB = """#!/usr/bin/env bash
printf '%s %s\\n' "$(basename "$0")" "$*" >> "$OPS_LOG"
"""

_STUBS = {
    "docker": _LOGGING_STUB
    + """case "$*" in
  "inspect"*) [ -n "${DOCKER_PROJECT:-}" ] && printf '%s\\n' "$DOCKER_PROJECT" || exit 1 ;;
  *) [ "$1" = compose ] && printf 'TRACK_TAG=%s\\n' "${TRACK_TAG:-}" >> "$OPS_LOG" ;;
esac
exit 0
""",
    "systemctl": _LOGGING_STUB + "exit 0\n",
    "journalctl": _LOGGING_STUB + "exit 0\n",
    "loginctl": "#!/usr/bin/env bash\necho Linger=yes\n",
    "id": "#!/usr/bin/env bash\necho staff docker\n",
    "curl": "#!/usr/bin/env bash\nexit 7\n",
    "sudo": _LOGGING_STUB + 'exec "$@"\n',
}


def _git(*args: str, cwd: Path) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def server(tmp_path):
    """A clone of a repository whose develop and release/0.2.0 carry ops.sh."""
    home = tmp_path / "home"
    bin_dir = tmp_path / "bin"
    home.mkdir()
    bin_dir.mkdir()
    for name, content in _STUBS.items():
        (bin_dir / name).write_text(content)
        (bin_dir / name).chmod(0o755)

    env = os.environ.copy()
    env.pop("XDG_CONFIG_HOME", None)
    env.pop("TRACK_BRANCH", None)
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{bin_dir}:{env['PATH']}",
            "OPS_LOG": str(tmp_path / "ops.log"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
    )

    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, env=env)
    subprocess.run(["git", "init", "-q", "-b", "develop", str(seed)], check=True, env=env)
    (seed / "scripts").mkdir()
    shutil.copy(ROOT_DIR / "scripts" / "ops.sh", seed / "scripts" / "ops.sh")
    (seed / "scripts" / "staging-update.sh").write_text(_ENGINE)
    (seed / "scripts" / "staging-update.sh").chmod(0o755)
    (seed / ".gitignore").write_text(".env\nvar/\nengine-calls.txt\n")
    (seed / "docker-compose.staging.yml").write_text("services: {}\n")
    for args in (
        ["add", "-A"],
        ["commit", "-q", "-m", "seed"],
        ["remote", "add", "origin", str(origin)],
        ["push", "-q", "origin", "develop", "develop:release/0.2.0"],
    ):
        subprocess.run(["git", *args], cwd=seed, check=True, env=env)

    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", "-b", "develop", str(origin), str(clone)], check=True, env=env)
    (clone / ".env").write_text("GHCR_TOKEN=secret\n")

    def run(*args: str, check: bool = True, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [str(clone / "scripts" / "ops.sh"), *args],
            env={**env, **extra},
            check=check,
            capture_output=True,
            text=True,
        )

    return {"clone": clone, "origin": origin, "seed": seed, "home": home, "env": env, "run": run, "log": tmp_path / "ops.log"}


def _env_lines(clone: Path) -> list[str]:
    return (clone / ".env").read_text().splitlines()


def test_track_release_moves_clone_and_env_together(server):
    clone = server["clone"]

    server["run"]("track", "release/0.2.0")

    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "release/0.2.0"
    lines = _env_lines(clone)
    assert "TRACK_BRANCH=release/0.2.0" in lines
    assert "TRACK_TAG=release-0.2.0" in lines
    assert "GHCR_TOKEN=secret" in lines
    assert (clone / "engine-calls.txt").read_text().strip() == f"STAGING_DIR={clone} DEPLOY_DIR="


def test_track_develop_removes_the_override(server):
    clone = server["clone"]
    server["run"]("track", "release/0.2.0")

    server["run"]("track", "develop")

    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "develop"
    assert _env_lines(clone) == ["GHCR_TOKEN=secret"]


def test_track_without_branch_pulls_the_tracked_one(server):
    clone, seed, env = server["clone"], server["seed"], server["env"]
    server["run"]("track", "release/0.2.0")
    subprocess.run(["git", "checkout", "-q", "-b", "rel", "origin/release/0.2.0"], cwd=seed, check=True, env=env)
    (seed / "NEW").write_text("x")
    subprocess.run(["git", "add", "NEW"], cwd=seed, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "fix"], cwd=seed, check=True, env=env)
    subprocess.run(["git", "push", "-q", "origin", "HEAD:release/0.2.0"], cwd=seed, check=True, env=env)

    server["run"]("track")

    assert (clone / "NEW").exists()
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "release/0.2.0"


def test_track_refuses_local_changes_to_tracked_files(server):
    clone = server["clone"]
    (clone / "docker-compose.staging.yml").write_text("services: {edited: {}}\n")

    result = server["run"]("track", "release/0.2.0", check=False)

    assert result.returncode == 1
    assert "local changes" in result.stderr
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "develop"


def test_track_refuses_a_branch_without_ops(server):
    seed, env = server["seed"], server["env"]
    subprocess.run(["git", "checkout", "-q", "-b", "old"], cwd=seed, check=True, env=env)
    subprocess.run(["git", "rm", "-q", "scripts/ops.sh"], cwd=seed, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "old"], cwd=seed, check=True, env=env)
    subprocess.run(["git", "push", "-q", "origin", "old"], cwd=seed, check=True, env=env)

    result = server["run"]("track", "old", check=False)

    assert result.returncode == 1
    assert "has no scripts/ops.sh" in result.stderr
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=server["clone"]) == "develop"


def test_status_warns_when_clone_and_tracked_branch_differ(server):
    clone = server["clone"]
    server["run"]("track", "release/0.2.0")
    _git("checkout", "-q", "develop", cwd=clone)

    result = server["run"]("auto-update", "status")

    assert "Tracks:    release/0.2.0" in result.stdout
    assert "differs from the clone's branch" in result.stdout
    assert "(unreachable)" in result.stdout


def test_setup_installs_units_that_run_from_the_clone(server):
    clone, home = server["clone"], server["home"]
    server["run"]("track", "release/0.2.0")
    unit_dir = home / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True)
    (unit_dir / "staging-update.service").write_text(
        "[Unit]\nDescription=Update acessilia staging container\n"
    )
    (unit_dir / "staging-update.timer").write_text("[Timer]\n")

    server["run"]("auto-update", "setup")

    service = (unit_dir / "acessilia-staging-update.service").read_text()
    assert f"ExecStart={clone}/scripts/ops.sh auto-update start" in service
    assert (unit_dir / "acessilia-staging-update.timer").exists()
    assert not (unit_dir / "staging-update.service").exists()
    assert "COMPOSE_PROJECT_NAME=acessilia-staging" in _env_lines(clone)
    log = server["log"].read_text()
    assert "systemctl --user disable --now staging-update.timer" in log
    assert "systemctl --user enable --now acessilia-staging-update.timer" in log
    assert "docker compose -f docker-compose.staging.yml up -d\nTRACK_TAG=release-0.2.0" in log


def test_setup_requires_an_env_file(server):
    (server["clone"] / ".env").unlink()

    result = server["run"]("auto-update", "setup", check=False)

    assert result.returncode == 1
    assert "cp .env.example .env" in result.stderr


def test_migrate_keeps_project_name_env_and_data(server, tmp_path):
    clone = server["clone"]
    (clone / ".env").unlink()
    old = tmp_path / "opt-staging"
    (old / "var" / "data").mkdir(parents=True)
    (old / "var" / "data" / "jobs.db").write_text("data")
    (old / ".env").write_text("GHCR_TOKEN=old-secret\nTRACK_BRANCH=release/0.2.0\n")

    server["run"]("auto-update", "migrate", str(old), DOCKER_PROJECT="staging")

    lines = _env_lines(clone)
    assert "GHCR_TOKEN=old-secret" in lines
    assert "COMPOSE_PROJECT_NAME=staging" in lines
    assert "TRACK_TAG=release-0.2.0" in lines
    assert (clone / "var" / "data" / "jobs.db").read_text() == "data"
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=clone) == "release/0.2.0"
    assert (server["home"] / ".config/systemd/user/acessilia-staging-update.service").exists()
    assert (old / ".env").exists()


def test_migrate_refuses_a_different_env_in_the_clone(server, tmp_path):
    old = tmp_path / "opt-staging"
    old.mkdir()
    (old / ".env").write_text("GHCR_TOKEN=old-secret\n")

    result = server["run"]("auto-update", "migrate", str(old), check=False)

    assert result.returncode == 1
    assert "differs from" in result.stderr
    assert _env_lines(server["clone"]) == ["GHCR_TOKEN=secret"]


def test_bhs_start_cuts_the_release_with_the_version_bump(server, tmp_path):
    seed, env = server["seed"], server["env"]
    (seed / "pyproject.toml").write_text('[project]\nname = "acessilia"\nversion = "0.1.0"\n')
    (seed / "uv.lock").write_text('[[package]]\nname = "acessilia"\nversion = "0.1.0"\n')
    subprocess.run(["git", "add", "-A"], cwd=seed, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "project"], cwd=seed, check=True, env=env)
    subprocess.run(["git", "push", "-q", "origin", "develop"], cwd=seed, check=True, env=env)

    result = server["run"]("bhs", "start", "0.3.0", OPS_TOOLBOX_REPO=str(server["origin"]))

    origin = server["origin"]
    assert _git("log", "-1", "--format=%s", "release/0.3.0", cwd=origin) == "chore(release): bump to 0.3.0"
    assert 'version = "0.3.0"' in _git("show", "release/0.3.0:pyproject.toml", cwd=origin)
    assert 'version = "0.3.0"' in _git("show", "release/0.3.0:uv.lock", cwd=origin)
    assert "ops.sh track release/0.3.0" in result.stdout

    again = server["run"]("bhs", "start", "0.3.0", OPS_TOOLBOX_REPO=str(server["origin"]), check=False)
    assert again.returncode == 1
    assert "already exists" in again.stderr


def test_bhs_start_removes_its_temp_dir_when_the_worktree_fails(server, tmp_path):
    bin_dir = tmp_path / "bin"
    real_git = shutil.which("git")
    (bin_dir / "git").write_text(
        f"""#!/usr/bin/env bash
[ "$1 $2" = "worktree add" ] && exit 1
exec {real_git} "$@"
"""
    )
    (bin_dir / "git").chmod(0o755)
    temp = tmp_path / "temp"
    temp.mkdir()

    result = server["run"]("bhs", "start", "0.3.0", check=False, TMPDIR=str(temp))

    assert result.returncode != 0
    assert list(temp.iterdir()) == []


def test_bhs_rejects_an_invalid_version(server):
    result = server["run"]("bhs", "start", "v0.3.0", check=False)

    assert result.returncode == 1
    assert "expected a version x.y.z" in result.stderr
