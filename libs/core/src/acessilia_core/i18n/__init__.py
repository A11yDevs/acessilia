"""Internationalization module backed by Babel locale strings files.

Generic locale parsing and normalization live in ``acessilia_sdk.i18n``; this
module keeps the core's catalogs, policies and request context, and re-exports
``parse_locales`` as a temporary compatibility facade (#712).
"""

import contextvars
from collections.abc import Mapping
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from babel.support import NullTranslations, Translations

from acessilia_sdk.i18n import normalize_locale, parse_locales as parse_locales
from acessilia_sdk.i18n.negotiation import (
    expand_locale_candidates,
    negotiate_server_locale as _negotiate_server_locale,
)

BASE_DIR = Path(__file__).resolve().parent
LOCALE_CATALOGS_DIR = BASE_DIR / "locales"

#: Locales supported by the runtime; each maps to one Babel strings file under LOCALE_CATALOGS_DIR.
SUPPORTED_LOCALES: tuple[str, ...] = ("en_US", "pt_BR")

#: Locale used when environment negotiation yields nothing useful (default en_US).
DEFAULT_LOCALE: str = "en_US"

#: Per-task override for the locale that t()/n() resolve against. Remote-user
#: handlers set this before emitting user-facing text so that, within a single
#: asyncio task (and its child tasks), every lookup honours that user's
#: detected locale even though the server-wide locale may differ.
_REQUEST_LOCALE_VAR: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "acessilia_request_locale", default=None
)


#: Locales the process offers remote users, set once at startup by
#: :func:`configure_locales`; ``None`` until then, which offers every
#: supported locale.
_ACTIVE_LOCALES: tuple[str, ...] | None = None


def configure_locales(locales: tuple[str, ...] | list[str]) -> None:
    """Set the locales the process offers remote users (``I18N_LOCALES_ACTIVE``).

    Process setup, not part of a run: the service calls it at startup
    (``backend/config/process_setup.py``; ADR-0016, step 3), so the core reads
    no settings. Unsupported entries are dropped; an empty list offers every
    supported locale, so the bot always has at least one.
    """
    global _ACTIVE_LOCALES
    _ACTIVE_LOCALES = tuple(loc for loc in locales if loc in SUPPORTED_LOCALES) or tuple(
        SUPPORTED_LOCALES
    )


def active_locales() -> tuple[str, ...]:
    """Locales the software advertises to remote users, as set by :func:`configure_locales`.

    Returns:
        tuple: The configured locales in declared order; every supported locale when the process has not configured them (a script, a test) or configured none usable.
    """
    return _ACTIVE_LOCALES if _ACTIVE_LOCALES is not None else tuple(SUPPORTED_LOCALES)


def negotiate_server_locale(environ: Mapping[str, str], c_locale: str | None = None) -> str:
    """Negotiate the server-side locale for local logging and default outputs.

    Negotiation order: the LOCALE value (if set), then the shell locale hints
    (LANGUAGE/LC_ALL/LANG), then ``c_locale``, then :data:`DEFAULT_LOCALE`.
    The core reads no environment (ADR-0016, step 5): the service passes its
    own at startup (``backend/config/process_setup.py``). The generic
    mechanism lives in :mod:`acessilia_sdk.i18n.negotiation`; this wrapper
    supplies the core's locale policy.

    Returns:
        str: Negotiated locale identifier restricted to :data:`SUPPORTED_LOCALES`; falls back to DEFAULT_LOCALE when no input yields a supported locale.
    """
    return _negotiate_server_locale(
        environ, SUPPORTED_LOCALES, DEFAULT_LOCALE, c_locale
    )


#: The server-side locale, set once at startup by
#: :func:`configure_server_locale`; ``None`` until then, which is
#: :data:`DEFAULT_LOCALE`.
_SERVER_LOCALE: str | None = None


def configure_server_locale(locale: str) -> None:
    """Set the server-side locale (process setup, like :func:`configure_locales`).

    An unsupported value falls back to :data:`DEFAULT_LOCALE`.
    """
    global _SERVER_LOCALE
    _SERVER_LOCALE = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE


def server_locale() -> str:
    """The server-side locale: as configured at startup, else :data:`DEFAULT_LOCALE`."""
    return _SERVER_LOCALE if _SERVER_LOCALE is not None else DEFAULT_LOCALE


def set_request_locale(locale: str) -> contextvars.Token:
    """Override the lookup locale for the current task (and its child tasks).

    Args:
        locale (str): Locale identifier to force for t()/n() lookups in the current task; pass server-side locales from :func:`locale_for_user` so remote users get their own language.

    Returns:
        contextvars.Token: Reset token returned by ContextVar.set; callers may ignore it for task-scoped use or pass it to :func:`reset_request_locale` when the override must end before the task does.
    """
    return _REQUEST_LOCALE_VAR.set(locale)


def reset_request_locale(token: contextvars.Token) -> None:
    """Restore the previously active per-task locale override.

    Args:
        token (contextvars.Token): Token captured by an earlier :func:`set_request_locale` call in the same task; no default (required).
    """
    _REQUEST_LOCALE_VAR.reset(token)


def _active_locale() -> str:
    """Return the lookup locale for t()/n(): the per-task override if set, else the server-side locale."""
    override = _REQUEST_LOCALE_VAR.get()
    if override:
        return override
    return server_locale()


def active_locale() -> str:
    """Public accessor for the lookup locale t()/n() currently resolve against.

    Returns:
        str: The per-task override locale when one is in effect for the calling task, otherwise the server-side locale from :func:`server_locale`.
    """
    return _active_locale()


def locale_for_user(raw_locale: str | None) -> str:
    """Pick the best supported locale for a remote user who advertises ``raw_locale``.

    Matching is lenient: a base language code (e.g. Telegram's ``pt``) resolves
    to the offered regional locale (``pt_BR``), and full codes such as ``pt-BR``
    or ``pt_BR.UTF-8`` normalize to the offered regional form. Only locales listed
    in :func:`active_locales` are ever returned.

    Args:
        raw_locale (str | None): Locale hint from the remote user's client (e.g. Telegram ``from_user.language_code``); ``None`` or blank means "no hint".

    Returns:
        str: An offered locale that matches the hint, or the server-side locale from :func:`_active_locale` when the hint is absent or matches no offered locale.
    """
    if raw_locale:
        normalized = normalize_locale(raw_locale)
        if normalized:
            available = list(active_locales())
            # Exact regional-form match first (e.g. "pt_BR" -> "pt_BR").
            for candidate in expand_locale_candidates([normalized]):
                if candidate in available:
                    return candidate
            # Lenient base-language match so Telegram's bare "pt" resolves to the
            # offered regional locale "pt_BR" (and "en" to "en_US").
            target_language = normalized.split("_")[0]
            for offered in available:
                if offered.split("_")[0] == target_language:
                    return offered
    return _active_locale()


def _compiled_catalog(locale: str) -> Translations | None:
    """Compile ``locale``'s ``.po`` source in memory, or ``None`` without one.

    The catalogs ship as ``.po`` sources only. They used to be compiled to
    ``messages.mo`` next to the sources, at import; an installed package may
    be read-only, and a failed write silently left every message in English.
    Compiling in memory needs no write and no build step (ADR-0016, step 6).
    A source that cannot be read or compiled is skipped, so the runtime
    degrades to the English-identity path instead of crashing.
    """
    po_path = LOCALE_CATALOGS_DIR / locale / "LC_MESSAGES" / "messages.po"
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


@lru_cache(maxsize=None)
def _catalog_for(locale: str) -> Translations | NullTranslations:
    """The catalog of ``locale``, else of :data:`DEFAULT_LOCALE`, else the
    English identity (``NullTranslations``), like ``Translations.load``.

    Args:
        locale (str): Candidate locale name.

    Returns:
        Translations | NullTranslations: The first catalog found.
    """
    # Normalized like ``Translations.load`` did: ``pt_BR.UTF-8``, ``pt_br``
    # and ``pt-BR`` find the ``pt_BR`` catalog (review of #569).
    for candidate in (normalize_locale(locale) or locale, DEFAULT_LOCALE):
        catalog = _compiled_catalog(candidate)
        if catalog is not None:
            return catalog
    return NullTranslations()


def get_translations(locale: str | None = None) -> Translations | NullTranslations:
    """Return a Babel catalog for a locale (or the active one when ``None`` is given);
    the English identity (``NullTranslations``) when no catalog is found."""
    if locale is None:
        locale = _active_locale()
    return _catalog_for(locale)


def t(message_id: str) -> str:
    """Translate a canonical English message id using the active runtime locale strings file.

    Args:
        message_id (str): Canonical gettext identifier for an internal static UI/runtime string.

    Returns:
        str: Localized message from the Babel catalog; leaves placeholders like ``%d``/``%(foo)s`` untouched since callers perform standard printf-style or .format()-style substitution after lookup when they need variable values inserted.
            Falls back to returning the original English msgid unchanged when this locale's strings file does not hold that translation yet.
    """
    trans = get_translations()
    result = trans.gettext(message_id)
    if isinstance(result, (bytes, bytearray)):
        try:
            result = result.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return str(result)


def n(singular_msgid: str, plural_msgid: str, count: int) -> str:
    """N-function form returning singular or plural localized text per Babel grammar for the active locale.

    Args:
        singular_msgid (str): Canonical English string selected when per-locale N-plurals rule indicates an individual-item case (e.g., ``count == 1`` under GNU two-form headers stored in .mo).
        plural_msgid (str): English message used for other counts; Babel indexes into the correct msgstr slot according to its locale header rules.
        count (int): Numeric quantity driving lookup selection through the runtime catalog's N-plurals definitions; zero is included in the normal rule set too depending on locale config within N file.

    Returns:
        str: Chosen localized string via Babel ngettext(); identity/fallback to the original English strings when the message pair has not been translated yet for this locale environment state. Placeholder (%d etc) substitution remains caller-side after text extraction here, as before gettext design intent keeps formatting separate from lookup resolution step in stack-level separation policy (per N-function contract pattern documented by chosen OSS i18n module per project guidelines).
    """
    trans = get_translations()
    result = trans.ngettext(singular_msgid, plural_msgid, count)
    if isinstance(result, (bytes, bytearray)):
        try:
            result = result.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return str(result)
