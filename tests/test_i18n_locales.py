"""The locale-list parser is shared by the core and the service (#656 PR 2).

Before this consolidation, `backend/config/settings.py::_locales_from_env` and
`libs/core/src/acessilia_core/i18n/__init__.py::_locales_from_raw` implemented
the same comma-separated, order-preserving parser. The generic parser and
normalizer now live in the SDK; the core no longer re-exports the parser
(#712).
"""

from __future__ import annotations

import acessilia_core.i18n as core_i18n
from acessilia_sdk.i18n import context as sdk_context, normalize_locale, parse_locales
from backend.config.settings import Settings


def test_parse_locales_drops_blanks_and_duplicates_in_first_seen_order() -> None:
    assert parse_locales("pt_BR, en_US,pt_BR, ,fr_FR,en_US") == (
        "pt_BR",
        "en_US",
        "fr_FR",
    )
    assert parse_locales("   ") == ()
    assert parse_locales("") == ()


def test_normalize_locale_handles_encodings_and_separators() -> None:
    assert normalize_locale("pt_BR.UTF-8") == "pt_BR"
    assert normalize_locale("pt-BR") == "pt_BR"
    assert normalize_locale("pt") == "pt"
    assert normalize_locale("pt.BR") == "pt"
    assert normalize_locale("pt-1234") == "pt"
    assert normalize_locale("") == ""


def test_the_core_no_longer_re_exports_the_shared_parser() -> None:
    assert not hasattr(core_i18n, "parse_locales")


def test_the_core_re_exports_the_sdk_request_context_unchanged() -> None:
    assert core_i18n.set_request_locale is sdk_context.set_request_locale
    assert core_i18n.reset_request_locale is sdk_context.reset_request_locale


def test_settings_defaults_to_the_supported_locales(monkeypatch) -> None:
    monkeypatch.delenv("I18N_LOCALES_ACTIVE", raising=False)

    assert Settings().i18n_locales_active == ("en_US", "pt_BR")


def test_settings_reads_i18n_locales_active_with_the_shared_parser(monkeypatch) -> None:
    monkeypatch.setenv("I18N_LOCALES_ACTIVE", "pt_BR, en_US,pt_BR, ,fr_FR")

    settings = Settings()

    assert settings.i18n_locales_active == ("pt_BR", "en_US", "fr_FR")
