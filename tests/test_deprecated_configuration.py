"""The deprecated PMV configuration names warn before they are removed.

"PMV" (a minimum viable product) named the first iterations of the PDDL
pipeline. Its configuration aliases (``PMV_*`` variables,
``PIPELINE_ENGINE=pmv``, ``Settings.pmv_*``) still work, and each use is
reported: at startup in the log, or as a ``DeprecationWarning``.
"""

from __future__ import annotations

import re
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

    warned: list[str] = []
    monkeypatch.setattr(core_logger, "setup_logger", lambda **_kwargs: None)
    monkeypatch.setattr(core_logger, "logger", SimpleNamespace(warning=warned.append))
    monkeypatch.setattr(i18n, "configure_locales", lambda *_args: None)
    monkeypatch.setattr(i18n, "configure_server_locale", lambda *_args: None)
    return warned


def test_every_pmv_variable_settings_reads_is_listed_as_deprecated() -> None:
    source = (ROOT / "backend" / "config" / "settings.py").read_text(encoding="utf-8")
    read = set(re.findall(r'"(PMV_\w+)"', source))

    assert read == set(DEPRECATED_ENV_ALIASES)
    assert all(new == "PDDL_" + old.removeprefix("PMV_") for old, new in DEPRECATED_ENV_ALIASES.items())


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
