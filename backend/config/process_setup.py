"""The process's setup from the service's settings (ADR-0016, step 3).

The logger and the translation catalogs are set up once per process, not per
run. ``setup_process`` passes them the settings at startup, so the core reads
no settings: each entry point (the API, the CLI, the frontends' runner, the
Telegram bot) calls it first.
"""

from __future__ import annotations

from backend.config.settings import Settings, settings as default_settings


def setup_process(settings: Settings | None = None) -> None:
    """Set up the logger (``LOG_LEVEL``, ``LOGS_DIR``) and the offered locales
    (``I18N_LOCALES_ACTIVE``) from ``settings`` (the service's, by default)."""
    from backend.core.i18n import configure_locales
    from backend.core.logger import setup_logger

    s = default_settings if settings is None else settings
    configure_locales(s.i18n_locales_active)
    setup_logger(level=s.log_level, logs_dir=s.logs_dir)


__all__ = ["setup_process"]
