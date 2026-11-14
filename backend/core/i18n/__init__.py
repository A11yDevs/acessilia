"""Internationalization module backed by Babel locale strings files."""

import contextvars
import locale as _c_locale
import os
import re
from functools import lru_cache
from pathlib import Path

from babel import negotiate_locale
from babel.support import Translations

from backend.config.settings import settings


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


def _normalize_locale(raw_value: str) -> str:
    """Normalize a raw locale token to a bare language_region form (e.g. ``pt_BR.UTF-8`` -> ``pt_BR``).

    Args:
        raw_value (str): Candidate locale such as an environment LANG value, a Telegram language code with hyphen, or a bare identifier; blank input normalizes to empty string.

    Returns:
        str: Lower-cased language code optionally joined with an upper-cased region code, with character-set encoding tails dropped; empty string when the input carried no usable language code.
    """
    cleaned = raw_value.strip()
    if not cleaned:
        return ""
    # Drop the character-set / encoding tail (e.g. ".UTF-8", ".utf8") before
    # splitting the language and region codes, which may be separated by "_",
    # "-" or "." (e.g. "pt-BR", "pt_BR.UTF-8", "pt.BR").
    head = cleaned.split(".", 1)[0]
    parts = [part for part in re.split(r"[-_.]+", head) if part]
    if not parts:
        return ""
    language = parts[0].lower()
    # A region part must be purely alphabetic; numeric or mixed tails are ignored.
    region = parts[1].upper() if len(parts) > 1 and parts[1].isalpha() else ""
    return f"{language}_{region}" if region else language


def _locales_from_raw(raw_value: str) -> tuple[str, ...]:
    """Split a comma-separated locale list into a de-duplicated, order-preserving tuple.

    Args:
        raw_value (str): Raw comma-separated locale identifiers; blank entries are dropped.

    Returns:
        tuple: Locale identifiers in first-seen order with duplicates removed.
    """
    seen: list[str] = []
    for entry in raw_value.split(","):
        candidate = entry.strip()
        if candidate and candidate not in seen:
            seen.append(candidate)
    return tuple(seen)


def active_locales() -> tuple[str, ...]:
    """Locales the software advertises to remote users, per I18N_LOCALES_ACTIVE in .env.

    Returns:
        tuple: Locally supported locale identifiers in declared settings order; falls back to :data:`SUPPORTED_LOCALES` when the setting lists no usable entry so the bot always has at least one offered locale.
    """
    locales = settings.i18n_locales_active
    if not locales:
        locales = SUPPORTED_LOCALES
    return tuple(loc for loc in locales if loc in SUPPORTED_LOCALES) or tuple(SUPPORTED_LOCALES)


def _expand_candidates(raw_values: list[str]) -> list[str]:
    """Expand raw locale tokens into ordered negotiation candidates (full form plus base language form).

    Args:
        raw_values (list[str]): Raw locale tokens (e.g. from one environment variable) that may carry encoding suffixes or use hyphens.

    Returns:
        list: Normalized candidate identifiers, most specific first, de-duplicated while preserving order; blank tokens contribute no candidates.
    """
    candidates: list[str] = []
    for raw in raw_values:
        normalized = _normalize_locale(raw)
        for candidate in (normalized, normalized.split("_")[0] if normalized else ""):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def _shell_locale_candidates() -> list[str]:
    """Collect locale hints from the process environment in priority order.

    Returns:
        list: Normalized candidate locale identifiers from LOCALE, LANGUAGE, LC_ALL and LANG, most specific first, skipping blank and C/POSIX values; falls back to DEFAULT_LOCALE when nothing is set.
    """
    raw_variables: list[str] = []
    for env_var in ("LOCALE", "LANGUAGE", "LC_ALL", "LANG"):
        value = (os.getenv(env_var) or "").strip()
        if value and value not in ("C", "POSIX"):
            raw_variables.append(value if env_var == "LOCALE" else value.split(":")[0])
    candidates = _expand_candidates(raw_variables)
    if candidates:
        return candidates
    # Last hint: the process C locale inherited from the shell, queried
    # without side effects (locale.getlocale only reads the current
    # category state); C/POSIX identities carry no translatable language.
    try:
        language, _ = _c_locale.getlocale(_c_locale.LC_ALL)
        if not language:
            language, _ = _c_locale.getlocale()
        if language and language not in ("C", "POSIX"):
            return _expand_candidates([language])
    except Exception:
        pass
    return [DEFAULT_LOCALE]


def _locale_from_env() -> str:
    """Resolve the server-side locale for local logging and default outputs.

    Negotiation order: the .env LOCALE value (if set), then the shell
    environment locale hints (LANGUAGE/LC_ALL/LANG), then :data:`DEFAULT_LOCALE`.

    Returns:
        str: Negotiated locale identifier restricted to :data:`SUPPORTED_LOCALES`; falls back to DEFAULT_LOCALE when no input yields a supported locale.
    """
    preferred: list[str] = []
    env_locale = (os.getenv("LOCALE") or "").strip()
    if env_locale:
        preferred.append(env_locale)
    preferred.extend(_shell_locale_candidates())
    preferred.append(DEFAULT_LOCALE)

    available_languages = list(SUPPORTED_LOCALES)
    negotiated_locale = negotiate_locale(preferred, available_languages)
    return negotiated_locale or DEFAULT_LOCALE


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
    return _locale_from_env()


def active_locale() -> str:
    """Public accessor for the lookup locale t()/n() currently resolve against.

    Returns:
        str: The per-task override locale when one is in effect for the calling task, otherwise the server-side locale from :func:`_locale_from_env`.
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
        normalized = _normalize_locale(raw_locale)
        if normalized:
            available = list(active_locales())
            # Exact regional-form match first (e.g. "pt_BR" -> "pt_BR").
            for candidate in _expand_candidates([normalized]):
                if candidate in available:
                    return candidate
            # Lenient base-language match so Telegram's bare "pt" resolves to the
            # offered regional locale "pt_BR" (and "en" to "en_US").
            target_language = normalized.split("_")[0]
            for offered in available:
                if offered.split("_")[0] == target_language:
                    return offered
    return _active_locale()


def _ensure_compiled_catalogs() -> None:
    """Compile any missing or stale Babel ``.mo`` binaries in place from their ``.po`` sources.

    The compiled ``messages.mo`` binaries are build artifacts and are not
    checked into git, so a fresh checkout (or a CI environment) runs without
    them and lookups would silently fall back to English msgids. Rebuilding
    here, once at import time, lets every runtime path (bot/API/web startup,
    tests, docker) resolve real catalogs without a separate compilation step.
    A locale whose sources cannot be read or compiled is skipped so the
    runtime degrades to the English-identity path instead of crashing.

    Args:
        (none)

    Returns:
        None: Always returns; individual catalog failures are absorbed intentionally.
    """
    try:
        from babel.messages.mofile import write_mo
        from babel.messages.pofile import read_po
    except Exception:
        return
    for locale in SUPPORTED_LOCALES:
        lmessages = LOCALE_CATALOGS_DIR / locale / "LC_MESSAGES"
        po_path = lmessages / "messages.po"
        mo_path = lmessages / "messages.mo"
        if not po_path.is_file():
            continue
        try:
            # Skip when the binary is present, non-empty, and not older than its source.
            if (
                mo_path.is_file()
                and mo_path.stat().st_size > 0
                and po_path.stat().st_mtime <= mo_path.stat().st_mtime
            ):
                continue
            with open(po_path, "rb") as source_stream:
                catalog = read_po(source_stream, locale=locale)
            with open(mo_path, "wb") as mo_stream:
                write_mo(mo_stream, catalog)
        except Exception:
            continue


# Self-heal once at import time so every consumer of this module (test runs,
# bot/API/web startup, docker containers) starts with compiled catalogs even
# on a checkout that only carries the tracked .po sources.
_ensure_compiled_catalogs()


@lru_cache(maxsize=None)
def _catalog_for(locale: str) -> Translations | None:
    """Load a Babel message catalog directory (or ``None`` when none could be found).

    Args:
        locale (str): Candidate locale name; loader falls back to DEFAULT_LOCALE when the raw lookup would otherwise miss the file tree at all.

    Returns:
        Translations | None: Loaded Babel catalog via ::Translations.load(...) or a plain Null-like value representing English identity fallback so t()/n() behave like before i18n wiring is fully populated per locale.
    """
    return Translations.load(
        dirname=str(LOCALE_CATALOGS_DIR),
        locales=[locale, DEFAULT_LOCALE],
        domain=Translations.DEFAULT_DOMAIN,
    )


def get_translations(locale: str | None = None) -> Translations | None:
    """Return a Babel catalog for a locale (or the active one when ``None`` is given)."""
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
    if trans is None:
        return message_id
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
    if trans is None:
        return singular_msgid if count == 1 else plural_msgid
    result = trans.ngettext(singular_msgid, plural_msgid, count)
    if isinstance(result, (bytes, bytearray)):
        try:
            result = result.decode("utf-8")
        except UnicodeDecodeError:
            pass
    return str(result)
