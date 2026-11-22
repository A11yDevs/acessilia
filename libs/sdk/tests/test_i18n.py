"""The SDK's generic locale parsing, normalization and context (#712)."""

from __future__ import annotations

import asyncio

import pytest

from acessilia_sdk.i18n import normalize_locale, parse_locales
from acessilia_sdk.i18n.context import (
    request_locale,
    reset_request_locale,
    set_request_locale,
)
from acessilia_sdk.i18n.negotiation import (
    expand_locale_candidates,
    negotiate_locale,
    negotiate_server_locale,
    shell_locale_candidates,
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
    assert negotiate_server_locale({"LC_ALL": "pt_BR.UTF-8"}, ("en_US", "pt_BR"), "en_US") == "pt_BR"
    assert negotiate_server_locale({"LANG": "POSIX"}, ("en_US", "pt_BR"), "en_US") == "en_US"
    assert negotiate_server_locale({"LANG": "de_DE.UTF-8"}, ("en_US", "pt_BR"), "en_US") == "en_US"


def test_shell_candidates_keep_locale_colons_but_split_language_colons() -> None:
    assert shell_locale_candidates({"LOCALE": "pt:en"}, None, default="en_US") == ["pt:en"]
    assert shell_locale_candidates(
        {"LANGUAGE": "pt_BR:en_US"}, None, default="en_US"
    ) == ["pt_BR", "pt"]
    assert shell_locale_candidates({}, "pt_BR", default="en_US") == ["pt_BR", "pt"]
    assert shell_locale_candidates({}, None, default="en_US") == ["en_US"]


def test_negotiate_locale_falls_back_to_the_caller_default() -> None:
    assert negotiate_locale(["de"], ("en_US", "pt_BR"), "en_US") == "en_US"


def test_request_locale_context_resets() -> None:
    assert request_locale() is None

    token = set_request_locale("pt_BR")
    try:
        assert request_locale() == "pt_BR"
    finally:
        reset_request_locale(token)

    assert request_locale() is None


def test_request_locale_nested_tokens_and_empty_override() -> None:
    outer = set_request_locale("pt_BR")
    try:
        assert request_locale() == "pt_BR"
        inner = set_request_locale("")
        try:
            assert request_locale() == ""
        finally:
            reset_request_locale(inner)
        assert request_locale() == "pt_BR"
    finally:
        reset_request_locale(outer)

    assert request_locale() is None


@pytest.mark.asyncio
async def test_child_task_inherits_request_locale() -> None:
    token = set_request_locale("pt_BR")
    try:
        async def child() -> None:
            assert request_locale() == "pt_BR"

        await asyncio.create_task(child())
    finally:
        reset_request_locale(token)


@pytest.mark.asyncio
async def test_request_locale_is_task_local() -> None:
    async def worker(locale: str) -> None:
        token = set_request_locale(locale)
        try:
            await asyncio.sleep(0)
            assert request_locale() == locale
        finally:
            reset_request_locale(token)

    await asyncio.gather(worker("pt_BR"), worker("en_US"))

    assert request_locale() is None
