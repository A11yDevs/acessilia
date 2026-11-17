"""The process's setup from the service's settings (ADR-0016, steps 3 and 5).

The logger, the translation catalogs and the server-side locale are set up
once per process, not per run. ``setup_process`` passes them the settings and
the environment at startup, so the core reads neither: each entry point (the
API, the CLI, the frontends' runner, the Telegram bot) calls it first.
"""

from __future__ import annotations

import locale
import os
from collections.abc import Mapping

from backend.config.settings import Settings
from backend.config.settings import settings as default_settings


def setup_process(
    settings: Settings | None = None, environ: Mapping[str, str] | None = None
) -> None:
    """Set up the logger (``LOG_LEVEL``, ``LOGS_DIR``), the offered locales
    (``I18N_LOCALES_ACTIVE``) and the server-side locale from ``settings``
    (the service's, by default) and ``environ`` (the process's): ``LOCALE``,
    then the shell's ``LANGUAGE``/``LC_ALL``/``LANG`` and C locale. The core
    reads no environment (ADR-0016, step 5)."""
    from backend.core.i18n import (
        configure_locales,
        configure_server_locale,
        negotiate_server_locale,
    )
    from backend.core.logger import setup_logger

    s = default_settings if settings is None else settings
    hints = dict(os.environ if environ is None else environ)
    if s.locale:
        hints["LOCALE"] = s.locale
    configure_locales(s.i18n_locales_active)
    configure_server_locale(negotiate_server_locale(hints, _process_c_locale()))
    setup_logger(level=s.log_level, logs_dir=s.logs_dir)


def _process_c_locale() -> str | None:
    """The language of the process C locale inherited from the shell, read
    without side effects (``locale.getlocale`` only reads the current state).

    ``getlocale(LC_ALL)`` returns a composite of the categories when they
    differ (``"C/pt_BR"``, or ``"C/C"`` when none is set), so each category
    is tried, then ``LC_CTYPE`` (review of #568).
    """
    for category in (locale.LC_ALL, locale.LC_CTYPE):
        try:
            raw, _ = locale.getlocale(category)
        except Exception:  # noqa: BLE001, S112 - a locale hint never fails the startup
            continue
        language = _first_language(raw)
        if language:
            return language
    return None


def _first_language(raw: str | None) -> str | None:
    """The first category of a ``getlocale`` value that names a language."""
    for part in (raw or "").split("/"):
        part = part.strip()
        if part and part not in ("C", "POSIX"):
            return part
    return None


__all__ = ["setup_process"]
