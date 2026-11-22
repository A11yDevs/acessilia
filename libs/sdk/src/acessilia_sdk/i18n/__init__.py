"""Generic internationalization infrastructure shared by Acessilia components.

The SDK owns locale parsing and normalization. The core keeps its translation
catalogs, the policies that choose locales and the request context; the full
extraction of the remaining infrastructure is tracked in #712.
"""

from acessilia_sdk.i18n.locales import normalize_locale, parse_locales

__all__ = ["normalize_locale", "parse_locales"]
