"""The process setup is passed at startup, not read by the core (ADR-0016, step 3)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.config.settings import settings
from backend.core import i18n


@pytest.fixture
def unconfigured_locales(monkeypatch):
    """Each test starts from a process that has not configured its locales."""
    monkeypatch.setattr(i18n, "_ACTIVE_LOCALES", None)


def test_setup_process_passes_the_settings_to_the_logger_and_the_catalogs(
    monkeypatch, tmp_path, unconfigured_locales
) -> None:
    from backend.config import process_setup
    from backend.core import logger as core_logger

    received = {}

    def setup_logger(*, level, logs_dir):
        received["logger"] = (level, logs_dir)

    monkeypatch.setattr(core_logger, "setup_logger", setup_logger)
    custom = replace(
        settings, log_level="WARNING", logs_dir=tmp_path / "logs", i18n_locales_active=("pt_BR",)
    )

    process_setup.setup_process(custom)

    assert received["logger"] == ("WARNING", tmp_path / "logs")
    assert i18n.active_locales() == ("pt_BR",)


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

    from backend.core.logger import setup_logger

    try:
        setup_logger(level="INFO", logs_dir=tmp_path / "logs")
        logger.info("process setup")
        logger.complete()

        assert any((tmp_path / "logs").glob("bot_*.log"))
    finally:
        logger.remove()
        import sys

        logger.add(sys.stderr)
