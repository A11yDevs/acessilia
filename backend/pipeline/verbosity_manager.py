"""Export profiles and verbosity mapping.

Core migrated to docstruct.profiles; re-exported here for compatibility
with existing imports.
"""
from __future__ import annotations

from docstruct.profiles import (  # noqa: F401
    MODE_TO_VERBOSITY,
    OUTPUT_PROFILES,
    filter_blocks_for_profile,
    normalize_profile,
    verbosity_for_mode,
)

__all__ = [
    "MODE_TO_VERBOSITY",
    "OUTPUT_PROFILES",
    "filter_blocks_for_profile",
    "normalize_profile",
    "verbosity_for_mode",
]
