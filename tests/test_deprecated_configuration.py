"""The deprecated PMV configuration names warn before they are removed.

"PMV" (a minimum viable product) named the first iterations of the PDDL
pipeline. Its configuration aliases (``PMV_*`` variables,
``PIPELINE_ENGINE=pmv``, ``Settings.pmv_*``) still work, and each use is
reported: at startup in the log, or as a ``DeprecationWarning``.
"""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.config.settings import (
    DEPRECATED_ENV_ALIASES,
    deprecated_configuration,
    settings,
)

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def startup(monkeypatch) -> list[str]:
    """``setup_process`` with the logger and the locales stubbed: the
    warnings it logs, and no process state changed for other tests."""
    from acessilia_core import i18n
    from acessilia_core import logger as core_logger
    from backend.config import process_setup

    warned: list[str] = []
    monkeypatch.setattr(process_setup, "_LOGGED_DEPRECATIONS", set())
    monkeypatch.setattr(core_logger, "setup_logger", lambda **_kwargs: None)
    monkeypatch.setattr(core_logger, "logger", SimpleNamespace(warning=warned.append))
    monkeypatch.setattr(i18n, "configure_locales", lambda *_args: None)
    monkeypatch.setattr(i18n, "configure_server_locale", lambda *_args: None)
    return warned


def _pmv_names_read(source: str) -> set[str]:
    """Every ``PMV_*`` string in ``source``, whatever its quotes, outside the
    ``DEPRECATED_ENV_ALIASES`` table itself (review of #586)."""
    tree = ast.parse(source)
    table = {
        id(node)
        for statement in ast.walk(tree)
        if isinstance(statement, (ast.Assign, ast.AnnAssign))
        and any(
            isinstance(target, ast.Name) and target.id == "DEPRECATED_ENV_ALIASES"
            for target in (statement.targets if isinstance(statement, ast.Assign) else [statement.target])
        )
        for node in ast.walk(statement)
    }
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith("PMV_")
        and id(node) not in table
    }


def test_every_pmv_variable_settings_reads_is_listed_as_deprecated() -> None:
    source = (ROOT / "backend" / "config" / "settings.py").read_text(encoding="utf-8")

    # Both ways: a read missing from the table, and a key nothing reads.
    assert _pmv_names_read(source) == set(DEPRECATED_ENV_ALIASES)
    assert all(new == "PDDL_" + old.removeprefix("PMV_") for old, new in DEPRECATED_ENV_ALIASES.items())


def test_the_name_scan_sees_any_quotes_and_skips_the_table() -> None:
    source = (
        "DEPRECATED_ENV_ALIASES = {'PMV_ORPHAN': 'PDDL_ORPHAN'}\n"
        "a = os.getenv('PMV_SINGLE')\n"
        'b = os.getenv("PMV_DOUBLE", os.getenv("PDDL_DOUBLE"))\n'
    )

    assert _pmv_names_read(source) == {"PMV_SINGLE", "PMV_DOUBLE"}


def test_a_current_configuration_has_nothing_deprecated() -> None:
    assert deprecated_configuration({"PDDL_PLANNER_BACKEND": "internal"}, "pddl") == []


def test_an_alias_alone_is_to_be_renamed() -> None:
    assert deprecated_configuration({"PMV_MAX_REPLANS": "3"}, "pddl") == [
        "PMV_MAX_REPLANS is deprecated: rename it to PDDL_MAX_REPLANS"
    ]


def test_an_alias_next_to_its_replacement_is_ignored_and_to_be_removed() -> None:
    environ = {"PMV_PLANNER_BACKEND": "fast-downward", "PDDL_PLANNER_BACKEND": "internal"}

    assert deprecated_configuration(environ, "pddl") == [
        "PMV_PLANNER_BACKEND is deprecated and ignored, since PDDL_PLANNER_BACKEND is set: "
        "remove PMV_PLANNER_BACKEND"
    ]


@pytest.mark.parametrize("engine", ["pmv", " PMV "])
def test_the_pmv_engine_is_deprecated(engine) -> None:
    assert deprecated_configuration({}, engine) == [
        "PIPELINE_ENGINE=pmv is deprecated: set PIPELINE_ENGINE=pddl"
    ]


def test_setup_process_logs_each_deprecated_name(startup, tmp_path) -> None:
    from backend.config import process_setup

    custom = replace(settings, pipeline_engine="pmv", logs_dir=tmp_path)

    process_setup.setup_process(custom, environ={"PMV_FAST_DOWNWARD": "/usr/bin/downward"})

    assert startup == [
        "PMV_FAST_DOWNWARD is deprecated: rename it to PDDL_FAST_DOWNWARD",
        "PIPELINE_ENGINE=pmv is deprecated: set PIPELINE_ENGINE=pddl",
    ]


def test_setup_process_logs_nothing_for_a_current_configuration(startup, tmp_path) -> None:
    from backend.config import process_setup

    process_setup.setup_process(replace(settings, pipeline_engine="pddl", logs_dir=tmp_path), environ={})

    assert startup == []


def test_each_deprecation_is_logged_once_per_process(startup, tmp_path) -> None:
    """The runner and the API both set the process up (review of #586)."""
    from backend.config import process_setup

    custom = replace(settings, pipeline_engine="pmv", logs_dir=tmp_path)

    process_setup.setup_process(custom, environ={})
    process_setup.setup_process(custom, environ={})

    assert startup == ["PIPELINE_ENGINE=pmv is deprecated: set PIPELINE_ENGINE=pddl"]


def test_the_pipeline_cli_logs_the_deprecations(startup, monkeypatch, tmp_path) -> None:
    """It reads the settings without the process setup (review of #586)."""
    from scripts import pddl_pipeline

    monkeypatch.setenv("PMV_MAX_REPLANS", "3")
    monkeypatch.delenv("PDDL_MAX_REPLANS", raising=False)
    monkeypatch.setattr(pddl_pipeline, "_run_manifest", lambda *_args: None)

    assert pddl_pipeline.main(["manifest", "doc.pdf", "-o", str(tmp_path / "m.json")]) == 0
    assert "PMV_MAX_REPLANS is deprecated: rename it to PDDL_MAX_REPLANS" in startup
