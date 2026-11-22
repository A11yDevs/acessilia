"""Locale parsing and normalization shared by Acessilia components.

These functions are deliberately independent of Babel, catalogs and process
state: they turn raw locale hints into stable identifiers. Policies (which
locales are offered, negotiation) and translation resources stay with the
consuming component; the full migration is #712.
"""

from __future__ import annotations

import re

__all__ = ["normalize_locale", "parse_locales"]


def normalize_locale(raw_value: str) -> str:
    """Normalize a raw locale token to a bare language_region form.

    ``pt_BR.UTF-8`` becomes ``pt_BR``; ``pt-BR`` becomes ``pt_BR``; ``pt``
    stays ``pt``. Blank input normalizes to an empty string. The character-set
    tail is dropped and numeric or mixed region tails are ignored.

    Args:
        raw_value (str): Candidate locale from an environment variable, a
            remote user's language code or a bare identifier.

    Returns:
        str: Lower-cased language code, optionally joined with an upper-cased
        alphabetic region code; empty when the input has no usable language.
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


def parse_locales(raw_value: str) -> tuple[str, ...]:
    """Split a comma-separated locale list into a de-duplicated, ordered tuple.

    Blank entries are dropped and duplicates keep their first occurrence.

    Args:
        raw_value (str): Raw comma-separated locale identifiers.

    Returns:
        tuple: Locale identifiers in first-seen order; empty when no usable
        entry exists.
    """
    seen: list[str] = []
    for entry in raw_value.split(","):
        candidate = entry.strip()
        if candidate and candidate not in seen:
            seen.append(candidate)
    return tuple(seen)
