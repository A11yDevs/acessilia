"""Catalog compilation and gettext lookup shared by Acessilia components.

The SDK owns the generic mechanics: compile a ``.po`` source in memory, fall
back to a default locale and then to the English identity, and normalize the
string returned by Babel. The owning component supplies the catalog directory,
default locale and active-locale policy. It also renders structured
``(msgid, kwargs)`` findings through a caller-supplied lookup
(:func:`resolve_findings`), which owns no catalog policy of its own.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from io import BytesIO
from pathlib import Path
from typing import Any

from babel.support import NullTranslations, Translations

from acessilia_sdk.i18n.locales import normalize_locale

__all__ = [
    "catalog_for",
    "compile_catalog",
    "gettext",
    "ngettext",
    "resolve_findings",
]


def compile_catalog(catalog_dir: Path, locale: str) -> Translations | None:
    """Compile ``locale``'s ``.po`` source in memory, or ``None`` without one.

    The catalogs ship as ``.po`` sources only. Compiling them in memory needs no
    write and no build step, so an installed package may be read-only. A source
    that cannot be read or decoded is skipped, so the caller can fall back to
    the default locale or to the English identity instead of crashing. A source
    that is decodable but malformed may still compile with entries dropped by
    Babel; only read/decoding failures return ``None``.

    Args:
        catalog_dir (Path): Root holding ``<locale>/LC_MESSAGES/messages.po``.
        locale (str): Catalog locale to compile.

    Returns:
        Translations | None: The compiled catalog, or ``None``.
    """
    po_path = catalog_dir / locale / "LC_MESSAGES" / "messages.po"
    if not po_path.is_file():
        return None
    try:
        from babel.messages.mofile import write_mo
        from babel.messages.pofile import read_po

        with open(po_path, "rb") as source:
            catalog = read_po(source, locale=locale)
        compiled = BytesIO()
        write_mo(compiled, catalog)
        compiled.seek(0)
        return Translations(fp=compiled, domain=Translations.DEFAULT_DOMAIN)
    except Exception:  # noqa: BLE001 - a broken catalog degrades to English
        return None


def catalog_for(
    catalog_dir: Path, locale: str, default_locale: str
) -> Translations | NullTranslations:
    """The catalog of ``locale``, else of ``default_locale``, else the identity.

    Locale variants are normalized first: ``pt_BR.UTF-8``, ``pt_br`` and
    ``pt-BR`` find the ``pt_BR`` catalog.

    The function itself does not cache; a caller that looks up many messages
    should cache per locale, as the core's ``_catalog_for`` does.

    Args:
        catalog_dir (Path): Root holding ``<locale>/LC_MESSAGES/messages.po``.
        locale (str): Candidate locale name.
        default_locale (str): Fallback locale when no catalog matches.

    Returns:
        Translations | NullTranslations: The first catalog found, or the
        English identity (``NullTranslations``).
    """
    for candidate in (normalize_locale(locale) or locale, default_locale):
        catalog = compile_catalog(catalog_dir, candidate)
        if catalog is not None:
            return catalog
    return NullTranslations()


def _decode(result: str | bytes | bytearray) -> str:
    if isinstance(result, (bytes, bytearray)):
        try:
            return result.decode("utf-8")
        except UnicodeDecodeError:
            return str(result)
    return str(result)


def gettext(translations: Translations | NullTranslations, message_id: str) -> str:
    """Translate one canonical message id, leaving placeholders untouched.

    Args:
        translations (Translations | NullTranslations): Catalog to query.
        message_id (str): Canonical English message id.

    Returns:
        str: Localized message, or the original msgid when missing.
    """
    return _decode(translations.gettext(message_id))


def ngettext(
    translations: Translations | NullTranslations,
    singular_msgid: str,
    plural_msgid: str,
    count: int,
) -> str:
    """Select the singular or plural form for ``count`` in the catalog grammar.

    Args:
        translations (Translations | NullTranslations): Catalog to query.
        singular_msgid (str): Canonical singular message id.
        plural_msgid (str): Canonical plural message id.
        count (int): Quantity selecting the form.

    Returns:
        str: Localized singular or plural message, or the original ids when
        missing.
    """
    return _decode(translations.ngettext(singular_msgid, plural_msgid, count))


def resolve_findings(
    findings: Iterable[tuple[str, Mapping[str, Any]]],
    translate: Callable[[str], str],
) -> list[str]:
    """Render structured ``(msgid, kwargs)`` findings through ``translate``.

    The producer keeps its msgids and arguments structured; the caller supplies
    the locale-aware lookup (for example the Core's active-locale ``t``). This
    avoids reconstructing arguments from already formatted strings.

    Placeholders in the msgid and its translations must use ``str.format``
    ``{name}`` syntax; they are substituted with ``kwargs``.

    Args:
        findings (Iterable[tuple[str, Mapping[str, Any]]]): Message id and
            format arguments for each finding.
        translate (Callable[[str], str]): Message-id lookup in the active
            locale.

    Returns:
        list[str]: One localized line per finding, in input order.
    """
    return [translate(msgid).format(**kwargs) for msgid, kwargs in findings]
