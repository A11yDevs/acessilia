"""The SDK's generic catalog compilation and gettext lookup (#712)."""

from __future__ import annotations

from pathlib import Path

from acessilia_sdk.i18n.translation import (
    catalog_for,
    compile_catalog,
    gettext,
    ngettext,
    resolve_findings,
)

PO = """\
msgid ""
msgstr ""
"Content-Type: text/plain; charset=UTF-8\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"

msgid "Hello"
msgstr "Bonjour"

msgid "One file"
msgid_plural "%(count)d files"
msgstr[0] "Un fichier"
msgstr[1] "%(count)d fichiers"
"""


def _catalog_dir(tmp_path: Path) -> Path:
    root = tmp_path / "locales"
    messages = root / "fr_FR" / "LC_MESSAGES"
    messages.mkdir(parents=True)
    (messages / "messages.po").write_text(PO, encoding="utf-8")
    return root


def test_catalog_for_compiles_a_matching_locale(tmp_path: Path) -> None:
    root = _catalog_dir(tmp_path)

    translations = catalog_for(root, "fr_FR.UTF-8", "en_US")

    assert gettext(translations, "Hello") == "Bonjour"
    assert gettext(translations, "Missing") == "Missing"
    assert ngettext(translations, "One file", "%(count)d files", 1) == "Un fichier"
    assert ngettext(translations, "One file", "%(count)d files", 2) == "%(count)d fichiers"


def test_catalog_for_falls_back_to_the_default_and_identity(tmp_path: Path) -> None:
    root = _catalog_dir(tmp_path)

    assert gettext(catalog_for(root, "de_DE", "fr_FR"), "Hello") == "Bonjour"
    assert gettext(catalog_for(root, "de_DE", "en_US"), "Hello") == "Hello"


def test_catalog_for_uses_default_when_locale_normalizes_to_empty(tmp_path: Path) -> None:
    root = _catalog_dir(tmp_path)

    assert gettext(catalog_for(root, "...", "fr_FR"), "Hello") == "Bonjour"


class _BytesTranslations:
    def __init__(self, result: bytes) -> None:
        self._result = result

    def gettext(self, _message_id: str) -> bytes:
        return self._result

    def ngettext(self, _singular: str, _plural: str, _count: int) -> bytes:
        return self._result


def test_gettext_and_ngettext_normalize_bytes_results() -> None:
    assert gettext(_BytesTranslations(b"Bonjour"), "Hello") == "Bonjour"
    assert ngettext(_BytesTranslations(b"Bonjour"), "One", "Many", 2) == "Bonjour"
    assert gettext(_BytesTranslations(b"\xff"), "Hello") == str(b"\xff")


def test_resolve_findings_formats_structured_messages() -> None:
    findings = [
        ("Missing {field}", {"field": "title"}),
        ("Duplicate id: {block_id}", {"block_id": "s1"}),
    ]

    assert resolve_findings(findings, lambda msgid: f"<{msgid}>") == [
        "<Missing {field}>".format(field="title"),
        "<Duplicate id: {block_id}>".format(block_id="s1"),
    ]


def test_compile_catalog_returns_none_without_a_source(tmp_path: Path) -> None:
    assert compile_catalog(tmp_path / "missing", "pt_BR") is None


def test_a_broken_catalog_returns_none(tmp_path: Path) -> None:
    root = tmp_path / "locales"
    messages = root / "fr_FR" / "LC_MESSAGES"
    messages.mkdir(parents=True)
    (messages / "messages.po").write_bytes(b"\xff\xfe not a po file")

    assert compile_catalog(root, "fr_FR") is None
    assert gettext(catalog_for(root, "fr_FR", "en_US"), "Hello") == "Hello"
