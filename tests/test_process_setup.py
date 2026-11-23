"""The process setup is passed at startup, not read by the core (ADR-0016, steps 3 and 5)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from acessilia_core import i18n
from backend.config.settings import settings


@pytest.fixture
def unconfigured_locales(monkeypatch):
    """Each test starts from a process that has not configured its locales."""
    monkeypatch.setattr(i18n, "_ACTIVE_LOCALES", None)


def test_setup_process_passes_the_settings_to_the_logger_and_the_catalogs(
    monkeypatch, tmp_path, unconfigured_locales
) -> None:
    from acessilia_core import logger as core_logger
    from backend.config import process_setup

    received = {}

    def setup_logger(*, level, logs_dir):
        received["logger"] = (level, logs_dir)

    monkeypatch.setattr(core_logger, "setup_logger", setup_logger)
    custom = replace(
        settings, log_level="WARNING", logs_dir=tmp_path / "logs", i18n_locales_active=("pt_BR",)
    )

    process_setup.setup_process(custom, environ={})

    assert received["logger"] == ("WARNING", tmp_path / "logs")
    assert i18n.active_locales() == ("pt_BR",)


@pytest.mark.parametrize(
    ("setting", "environ", "c_locale", "expected"),
    [
        ("", {"LANG": "pt_BR.UTF-8"}, None, "pt_BR"),
        ("", {"LOCALE": "pt_BR", "LANG": "en_US.UTF-8"}, None, "pt_BR"),
        ("pt_BR", {"LANG": "en_US.UTF-8"}, None, "pt_BR"),
        ("en_US", {"LOCALE": "pt_BR"}, None, "en_US"),
        ("", {}, "pt_BR", "pt_BR"),
        ("", {"LANG": "C"}, None, "en_US"),
    ],
    ids=["shell", "env-locale", "setting-over-shell", "setting-over-env", "c-locale", "nothing"],
)
def test_setup_process_negotiates_the_server_locale(
    monkeypatch, tmp_path, setting, environ, c_locale, expected
) -> None:
    """The service reads its environment and the core gets the result: the
    ``LOCALE`` setting, then the shell's hints, then the C locale."""
    from acessilia_core import logger as core_logger
    from backend.config import process_setup

    monkeypatch.setattr(core_logger, "setup_logger", lambda **_kwargs: None)
    monkeypatch.setattr(process_setup, "_process_c_locale", lambda: c_locale)

    process_setup.setup_process(replace(settings, locale=setting), environ=environ)

    assert i18n.server_locale() == expected
    assert i18n.active_locale() == expected


def test_an_unconfigured_process_uses_the_default_server_locale(monkeypatch) -> None:
    """A script or a test that skips the setup gets en_US, whatever its shell says."""
    monkeypatch.setenv("LANG", "pt_BR.UTF-8")
    monkeypatch.setenv("LOCALE", "pt_BR")

    assert i18n.server_locale() == i18n.DEFAULT_LOCALE == "en_US"


def test_an_unconfigured_process_offers_every_supported_locale(unconfigured_locales) -> None:
    """A script or a test that skips the setup still gets locales."""
    assert i18n.active_locales() == tuple(i18n.SUPPORTED_LOCALES)


@pytest.mark.parametrize(
    ("configured", "offered"),
    [
        (("pt_BR",), ("pt_BR",)),
        (("pt_BR", "xx_XX"), ("pt_BR",)),
        ((), None),
        (("xx_XX",), None),
    ],
    ids=["one", "unsupported-dropped", "empty", "none-usable"],
)
def test_configure_locales_keeps_the_supported_ones(
    unconfigured_locales, configured, offered
) -> None:
    i18n.configure_locales(configured)

    assert i18n.active_locales() == (offered or tuple(i18n.SUPPORTED_LOCALES))


def test_a_user_locale_is_negotiated_against_the_configured_locales(
    monkeypatch, unconfigured_locales
) -> None:
    """A bare ``en`` hint does not reach English once only pt_BR is offered:
    it falls back to the server locale."""
    monkeypatch.setattr(i18n, "_active_locale", lambda: "server-locale")
    i18n.configure_locales(("pt_BR",))

    assert i18n.locale_for_user("pt") == "pt_BR"
    assert i18n.locale_for_user("en") == "server-locale"


def test_setting_the_locales_after_startup_does_not_change_them(
    monkeypatch, unconfigured_locales
) -> None:
    """The core reads no settings: the setup at startup is what counts."""
    i18n.configure_locales(("pt_BR",))
    monkeypatch.setattr(settings, "i18n_locales_active", ("en_US",))

    assert i18n.active_locales() == ("pt_BR",)


def test_setup_logger_writes_under_the_given_directory(tmp_path) -> None:
    from loguru import logger

    from acessilia_core.logger import setup_logger

    try:
        setup_logger(level="INFO", logs_dir=tmp_path / "logs")
        logger.info("process setup")
        logger.complete()

        assert any((tmp_path / "logs").glob("bot_*.log"))
    finally:
        logger.remove()
        import sys

        logger.add(sys.stderr)


@pytest.mark.parametrize(
    ("all_categories", "ctype", "expected"),
    [
        ("C/pt_BR", "pt_BR", "pt_BR"),
        ("C/C", "pt_BR", "pt_BR"),
        ("C/C", "C", None),
        ("pt_BR", "pt_BR", "pt_BR"),
        (None, None, None),
    ],
    ids=["composite", "composite-without-language", "c-only", "plain", "unset"],
)
def test_the_c_locale_hint_reads_the_composite_getlocale_returns(
    monkeypatch, all_categories, ctype, expected
) -> None:
    """``getlocale(LC_ALL)`` gives ``"C/pt_BR"`` or ``"C/C"`` when the categories
    differ, as Python does on macOS and glibc (review of #568)."""
    import locale

    from backend.config import process_setup

    values = {locale.LC_ALL: (all_categories, "UTF-8"), locale.LC_CTYPE: (ctype, "UTF-8")}
    monkeypatch.setattr(locale, "getlocale", lambda category=locale.LC_CTYPE: values[category])

    assert process_setup._process_c_locale() == expected


def test_a_composite_c_locale_reaches_the_server_locale(monkeypatch) -> None:
    import locale

    from acessilia_core import logger as core_logger
    from backend.config import process_setup

    monkeypatch.setattr(core_logger, "setup_logger", lambda **_kwargs: None)
    monkeypatch.setattr(locale, "getlocale", lambda category=locale.LC_CTYPE: ("C/pt_BR", "UTF-8"))

    process_setup.setup_process(replace(settings, locale=""), environ={})

    assert i18n.server_locale() == "pt_BR"


def test_the_entry_point_sets_up_the_process_before_the_lock() -> None:
    """The lock's messages are translated, so the setup comes first (review of #568)."""
    import ast
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "frontend/run.py").read_text(
        encoding="utf-8"
    )
    calls = [
        node.func.id
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"setup_process", "acquire_lock"}
    ]

    assert calls == ["setup_process", "acquire_lock"]


def test_agent_os_sets_up_the_process_before_its_descriptions() -> None:
    """uvicorn imports the module for ``app``; its agents' descriptions are
    translated at import, so the setup runs first (review of #568)."""
    import ast
    from pathlib import Path

    tree = ast.parse((Path(__file__).resolve().parents[1] / "frontend/agent_os.py").read_text())
    lines = {
        name: min(
            node.lineno for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id == name
        )
        for name in ("setup_process", "t")
    }

    assert lines["setup_process"] < lines["t"]
