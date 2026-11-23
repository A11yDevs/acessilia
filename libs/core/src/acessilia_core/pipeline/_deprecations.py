"""Shared deprecation shim for pipeline compatibility modules."""

from __future__ import annotations

import warnings
from typing import Any


def _deprecated_attribute(
    module_name: str,
    name: str,
    replacement: str,
    values: dict[str, Any],
) -> Any:
    """Return a deprecated module attribute, warning once per access."""
    if name in values:
        warnings.warn(
            f"{module_name}.{name} is deprecated; import it from {replacement}",
            DeprecationWarning,
            stacklevel=3,
        )
        return values[name]
    raise AttributeError(f"module {module_name!r} has no attribute {name!r}")
