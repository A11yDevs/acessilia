"""The locale-list parser is shared by the core and the service (#656 PR 2).

Before this consolidation, `backend/config/settings.py::_locales_from_env` and
`libs/core/src/acessilia_core/i18n/__init__.py::_locales_from_raw` implemented
the same comma-separated, order-preserving parser.
"""

from __future__ import annotations

from acessilia_core.i18n import parse_locales as core_parse_locales
from acessilia_sdk.i18n import normalize_locale, parse_locales
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
    assert normalize_locale("") == ""


def test_the_core_re_exports_the_shared_parser_as_a_temporary_facade() -> None:
    assert core_parse_locales is parse_locales


def test_settings_reads_i18n_locales_active_with_the_shared_parser(monkeypatch) -> None:
    monkeypatch.setenv("I18N_LOCALES_ACTIVE", "pt_BR, en_US,pt_BR, ,fr_FR")

    settings = Settings()

    assert settings.i18n_locales_active == ("pt_BR", "en_US", "fr_FR")
