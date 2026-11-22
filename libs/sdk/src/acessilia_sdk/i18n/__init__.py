"""Generic internationalization infrastructure shared by Acessilia components.

The SDK owns locale parsing and normalization
(:mod:`acessilia_sdk.i18n.locales`), negotiation
(:mod:`acessilia_sdk.i18n.negotiation`), the per-task request context
(:mod:`acessilia_sdk.i18n.context`) and catalog translation
(:mod:`acessilia_sdk.i18n.translation`). The core keeps its catalogs, message ids
and the policies that choose locales (#712).
"""

from acessilia_sdk.i18n.locales import normalize_locale, parse_locales

__all__ = ["normalize_locale", "parse_locales"]
