"""Generic internationalization infrastructure shared by Acessilia components.

The SDK owns locale parsing, normalization and the per-task request context
(:mod:`acessilia_sdk.i18n.context`). The core keeps its translation catalogs and
the policies that choose locales; the full extraction of the remaining
infrastructure is tracked in #712.
"""

from acessilia_sdk.i18n.locales import normalize_locale, parse_locales

__all__ = ["normalize_locale", "parse_locales"]
