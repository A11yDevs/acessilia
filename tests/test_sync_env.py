"""Tests for ``scripts/sync_env.py`` and the completeness of ``.env.example``.

``.env`` is not versioned, so ``.env.example`` is the only place a setting gets
documented. ``FUSION_MODE`` and other keys read by ``backend/config/settings.py``
were missing from it for weeks; the last test here fails when a new setting is
read without being declared in the example.
"""

from __future__ import annotations

import importlib.util
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "scripts" / "sync_env.py"
EXAMPLE_PATH = REPO_ROOT / ".env.example"
SETTINGS_PATH = REPO_ROOT / "backend" / "config" / "settings.py"

# Read by settings.py but deliberately left out of .env.example.
UNDOCUMENTED_SETTINGS = frozenset(
    {
        # Injected at image build (infra/Dockerfile); compose's env_file: .env
        # would overwrite them with blanks.
        "GIT_COMMIT",
        "IMAGE_TAG",
        "IMAGE_DIGEST",
        # Legacy aliases of the PDDL_* keys.
        "PMV_EXECUTE_DRY_RUN",
        "PMV_PLANNER_BACKEND",
        "PMV_PREFERRED_PLAN",
        "PMV_FAST_DOWNWARD",
        "PMV_FAST_DOWNWARD_ALIAS",
        "PMV_FAST_DOWNWARD_SEARCH",
        "PMV_MAX_REPLANS",
    }
)

EXAMPLE = """\
# API
API_HOST=0.0.0.0
API_PORT=8000

# Providers sharing one comment
# (second line of the comment)
PROVIDER_A=a
PROVIDER_B=b
# FOO=bar is prose, not a key
#LOCALE=pt_BR
"""


def _load_script():
    spec = importlib.util.spec_from_file_location("sync_env", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def sync_env():
    return _load_script()


@pytest.fixture
def files(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text(EXAMPLE, encoding="utf-8")
    return example, tmp_path / ".env"


def _run(sync_env, example, env, *extra):
    return sync_env.main(["--example", str(example), "--env", str(env), *extra])


class TestParsing:
    def test_commented_key_needs_the_key_right_after_the_hash(self, sync_env):
        keys = sync_env.declared_keys(EXAMPLE)
        assert keys["LOCALE"] is False
        assert "FOO" not in keys

    def test_set_and_commented_out_counts_as_set(self, sync_env):
        assert sync_env.declared_keys("#KEY=old\nKEY=new\n") == {"KEY": True}

    def test_export_prefix_is_accepted(self, sync_env):
        assert sync_env.declared_keys("export KEY=1\n") == {"KEY": True}

    def test_duplicates_ignore_commented_lines(self, sync_env):
        text = "A=1\n#A=2\nB=1\nB=2\n"
        assert sync_env.duplicated_keys(text) == ["B"]


class TestMissingKeys:
    def test_creates_env_from_the_example(self, sync_env, files):
        example, env = files
        assert _run(sync_env, example, env) == 0
        assert env.read_text(encoding="utf-8") == EXAMPLE

    def test_appends_missing_keys_with_their_comment(self, sync_env, files):
        example, env = files
        env.write_text("API_HOST=127.0.0.1\nPROVIDER_B=mine", encoding="utf-8")

        assert _run(sync_env, example, env) == 0

        text = env.read_text(encoding="utf-8")
        assert text.startswith("API_HOST=127.0.0.1\nPROVIDER_B=mine\n")
        added = text.split("review the values ---\n", 1)[1]
        assert added == (
            "# API\nAPI_PORT=8000\n\n"
            "# Providers sharing one comment\n# (second line of the comment)\n"
            "PROVIDER_A=a\n\n"
            "# FOO=bar is prose, not a key\n#LOCALE=pt_BR\n"
        )

    def test_commented_out_key_in_env_is_not_added_again(self, sync_env, files):
        example, env = files
        env.write_text(
            "API_HOST=x\nAPI_PORT=x\nPROVIDER_A=x\n#PROVIDER_B=x\n#LOCALE=x\n",
            encoding="utf-8",
        )
        before = env.read_text(encoding="utf-8")
        assert _run(sync_env, example, env) == 0
        assert env.read_text(encoding="utf-8") == before

    def test_check_reports_without_writing(self, sync_env, files, capsys):
        example, env = files
        env.write_text("API_HOST=x\n", encoding="utf-8")

        assert _run(sync_env, example, env, "--check") == 1

        assert env.read_text(encoding="utf-8") == "API_HOST=x\n"
        assert "+ API_PORT" in capsys.readouterr().out

    def test_check_without_env_fails(self, sync_env, files):
        example, env = files
        assert _run(sync_env, example, env, "--check") == 1
        assert not env.exists()


class TestExtraKeys:
    def test_classifies_by_references_in_versioned_files(
        self, sync_env, files, monkeypatch, capsys
    ):
        example, env = files
        env.write_text(EXAMPLE + "OLD_KEY=1\nTRACK_TAG=develop\n", encoding="utf-8")
        found = {"OLD_KEY": [], "TRACK_TAG": ["docker-compose.staging.yml"]}
        monkeypatch.setattr(sync_env, "references", lambda key, root: found[key])

        assert _run(sync_env, example, env) == 0

        out = capsys.readouterr().out
        deprecated, referenced = out.split("Still referenced")
        assert "- OLD_KEY" in deprecated
        assert "- TRACK_TAG: docker-compose.staging.yml" in referenced

    def test_references_searches_the_repository(self, sync_env):
        assert "backend/config/settings.py" in sync_env.references(
            "FUSION_MODE", REPO_ROOT
        )
        assert sync_env.references("NO_SUCH_KEY_ANYWHERE_42", REPO_ROOT) == []


class TestShellSafety:
    """The server scripts ``source`` .env in bash with ``set -euo pipefail``.

    ``PDDL_FAST_DOWNWARD_SEARCH=astar(blind())`` copied unquoted from the example
    stopped the staging auto-update timer with a syntax error.
    """

    def test_unquoted_spaces_and_shell_characters_are_flagged(self, sync_env):
        text = (
            "SMTP_NAME=A11y Acessibilidade\n"
            "SEARCH=astar(blind())\n"
            "QUOTED='astar(blind())'\n"
            'DOUBLE="A11y Acessibilidade"\n'
            "PLAIN=http://localhost:8000/v1?a=b\n"
            "WITH_COMMENT=docling  # the default\n"
            "#DISABLED=a b\n"
            "EMPTY=\n"
        )
        assert sync_env.shell_unsafe_keys(text) == ["SMTP_NAME", "SEARCH"]

    def test_check_fails_on_values_bash_cannot_source(self, sync_env, files, capsys):
        example, env = files
        env.write_text(EXAMPLE + "SMTP_NAME=A11y Acessibilidade\n", encoding="utf-8")

        assert _run(sync_env, example, env, "--check") == 1
        assert "! SMTP_NAME" in capsys.readouterr().out

    @pytest.mark.skipif(shutil.which("bash") is None, reason="bash not installed")
    def test_repository_example_sources_in_bash_like_the_server_scripts(self):
        result = subprocess.run(
            ["bash", "-c", 'set -euo pipefail; set -a; source "$1"; set +a', "_",
             str(EXAMPLE_PATH)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr

    def test_repository_example_has_no_unsafe_values(self, sync_env):
        assert sync_env.shell_unsafe_keys(EXAMPLE_PATH.read_text(encoding="utf-8")) == []


def test_repository_example_has_no_duplicates(sync_env):
    assert sync_env.duplicated_keys(EXAMPLE_PATH.read_text(encoding="utf-8")) == []


def test_every_setting_is_declared_in_the_example(sync_env):
    settings_source = SETTINGS_PATH.read_text(encoding="utf-8")
    read = set(re.findall(r"[\"']([A-Z][A-Z0-9]*_[A-Z0-9_]+)[\"']", settings_source))
    declared = set(sync_env.declared_keys(EXAMPLE_PATH.read_text(encoding="utf-8")))

    assert read - declared - UNDOCUMENTED_SETTINGS == set()


def test_script_runs_as_a_command(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("A=1\n", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("A=1\n", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--check", "--example", str(example),
         "--env", str(env)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
