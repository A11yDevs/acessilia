"""The SDK's generic locale parsing and normalization (#712, PR #711)."""

from __future__ import annotations

from acessilia_sdk.i18n import normalize_locale, parse_locales
from acessilia_sdk.i18n.negotiation import (
    expand_locale_candidates,
    negotiate_server_locale,
)


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


def test_expand_locale_candidates_adds_base_languages_and_deduplicates() -> None:
    assert expand_locale_candidates(["pt_BR.UTF-8", "en_US", "pt_BR"]) == [
        "pt_BR",
        "pt",
        "en_US",
        "en",
    ]


def test_negotiate_server_locale_uses_the_caller_policy() -> None:
    assert (
        negotiate_server_locale({"LANG": "pt_BR.UTF-8"}, ("en_US", "pt_BR"), "en_US")
        == "pt_BR"
    )
    assert negotiate_server_locale({}, ("en_US", "pt_BR"), "en_US") == "en_US"
    assert negotiate_server_locale({}, ("fr_FR",), "fr_FR") == "fr_FR"
    assert (
        negotiate_server_locale(
            {"LANGUAGE": "pt_BR:en_US", "LANG": "en_US.UTF-8"},
            ("en_US", "pt_BR"),
            "en_US",
        )
        == "pt_BR"
    )
    assert (
        negotiate_server_locale({"LANG": "C"}, ("en_US", "pt_BR"), "en_US", "pt_BR")
        == "pt_BR"
    )
