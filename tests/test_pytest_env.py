"""The shared deterministic pytest environment for test tooling (#786)."""

from __future__ import annotations

from scripts.tests import pytest_env


def test_the_sanitized_environment_keeps_unrelated_variables() -> None:
    env = pytest_env.sanitized_environ(
        {
            "PATH": "/bin",
            "PYTEST_ADDOPTS": "-k nothing",
            "PYTEST_PLUGINS": "ambient",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_CURRENT_TEST": "outer",
            "PYTEST_DEBUG": "1",
        }
    )

    assert env == {"PATH": "/bin"}


def test_the_input_mapping_is_not_modified() -> None:
    source = {"PATH": "/bin", "PYTEST_ADDOPTS": "-k nothing"}

    env = pytest_env.sanitized_environ(source)

    assert env == {"PATH": "/bin"}
    assert source == {"PATH": "/bin", "PYTEST_ADDOPTS": "-k nothing"}


def test_every_documented_variable_is_sanitized() -> None:
    source = {name: "value" for name in pytest_env.PYTEST_ENV_VARS}

    assert pytest_env.sanitized_environ(source) == {}
