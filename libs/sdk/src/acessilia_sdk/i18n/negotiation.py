"""Generic locale negotiation shared by Acessilia components.

The SDK owns candidate expansion, shell/environment hints and the final Babel
negotiation. The caller supplies the available locales and the default, so the
SDK does not impose an application policy or a fixed locale list.
"""

from __future__ import annotations

from collections.abc import Mapping

from babel import negotiate_locale as _babel_negotiate_locale

from acessilia_sdk.i18n.locales import normalize_locale

__all__ = [
    "expand_locale_candidates",
    "negotiate_locale",
    "negotiate_server_locale",
    "shell_locale_candidates",
]


def expand_locale_candidates(raw_values: list[str]) -> list[str]:
    """Expand raw locale tokens into ordered negotiation candidates.

    Each token contributes its normalized form and, when present, its base
    language form. Candidates are de-duplicated while preserving order; blank
    tokens contribute nothing.

    Args:
        raw_values (list[str]): Raw locale tokens from an environment or a
            caller; they may carry encoding suffixes or use hyphens.

    Returns:
        list: Normalized candidates, most specific first.
    """
    candidates: list[str] = []
    for raw in raw_values:
        normalized = normalize_locale(raw)
        for candidate in (normalized, normalized.split("_")[0] if normalized else ""):
            if candidate and candidate not in candidates:
                candidates.append(candidate)
    return candidates


def shell_locale_candidates(
    environ: Mapping[str, str], c_locale: str | None, *, default: str
) -> list[str]:
    """Collect locale hints from a process environment in priority order.

    Args:
        environ (Mapping[str, str]): The environment to read; the caller passes
            its own.
        c_locale (str | None): The process C locale's language, the last hint.
        default (str): Locale returned when no hint yields a candidate.

    Returns:
        list: Candidates from ``LOCALE``, ``LANGUAGE``, ``LC_ALL`` and ``LANG``,
        most specific first, skipping blank and ``C``/``POSIX`` values, then
        ``c_locale``; ``[default]`` when nothing is set.
    """
    raw_variables: list[str] = []
    for env_var in ("LOCALE", "LANGUAGE", "LC_ALL", "LANG"):
        value = (environ.get(env_var) or "").strip()
        if value and value not in ("C", "POSIX"):
            raw_variables.append(value if env_var == "LOCALE" else value.split(":")[0])
    candidates = expand_locale_candidates(raw_variables)
    if candidates:
        return candidates
    if c_locale and c_locale not in ("C", "POSIX"):
        return expand_locale_candidates([c_locale])
    return [default]


def negotiate_locale(
    preferred: list[str], available: tuple[str, ...] | list[str], default: str
) -> str:
    """Negotiate the best available locale for ``preferred``.

    Args:
        preferred (list[str]): Candidate locales, most specific first.
        available (tuple[str, ...] | list[str]): Locales the caller supports.
        default (str): Locale returned when negotiation finds no match.

    Returns:
        str: The negotiated locale, or ``default``.
    """
    return _babel_negotiate_locale(preferred, list(available)) or default


def negotiate_server_locale(
    environ: Mapping[str, str],
    available: tuple[str, ...] | list[str],
    default: str,
    c_locale: str | None = None,
) -> str:
    """Negotiate a process/server locale from environment hints and a policy.

    ``LOCALE`` is preferred, then the shell hints and ``c_locale``, then
    ``default``. The caller supplies ``available`` and ``default`` because they
    are application policy, not SDK policy.
    """
    preferred: list[str] = []
    env_locale = (environ.get("LOCALE") or "").strip()
    if env_locale:
        preferred.append(env_locale)
    preferred.extend(shell_locale_candidates(environ, c_locale, default=default))
    preferred.append(default)
    return negotiate_locale(preferred, available, default)
