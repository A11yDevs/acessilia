"""Configurations for the core's tests (ADR-0016, step 3).

The core has no defaults of its own: a test starts from the service's
settings and replaces only the fields it exercises, group by group.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from backend.config.core_config import core_config_from_settings
from backend.core.config import CoreConfig, DocumentConfig


def core_config(**groups: dict[str, Any]) -> CoreConfig:
    """The service's configuration, with fields replaced per group.

    ``core_config(document={"max_pages": 2})`` changes only ``max_pages``.
    """
    base = core_config_from_settings()
    return replace(
        base,
        **{name: replace(getattr(base, name), **fields) for name, fields in groups.items()},
    )


def document_config(**fields: Any) -> DocumentConfig:
    """The service's ``DocumentConfig``, with ``fields`` replaced."""
    return core_config(document=fields).document
