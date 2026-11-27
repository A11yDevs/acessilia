"""Shared deprecation shim for pipeline compatibility modules."""

from __future__ import annotations

import warnings
from collections.abc import Mapping
from typing import Any


def _deprecated_attribute(
    module_name: str,
    name: str,
    replacement: str | Mapping[str, str],
    values: dict[str, Any],
) -> Any:
    """Return a deprecated module attribute, warning once per access.

    ``replacement`` is either the module every name moved to, or a mapping from
    each name to the exact import text (a name, possibly with its module), for
    shims whose replacements do not share one fixed module.
    """
    if name not in values:
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
    if isinstance(replacement, Mapping):
        message = f"{module_name}.{name} is deprecated; import {replacement[name]}"
    else:
        message = f"{module_name}.{name} is deprecated; import it from {replacement}"
    warnings.warn(message, DeprecationWarning, stacklevel=3)
    return values[name]
