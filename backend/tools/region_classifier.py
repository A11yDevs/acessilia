"""Region classification heuristics.

Core migrated to docstruct.regions.classify; re-exported here for
compatibility with existing imports.
"""
from __future__ import annotations

from docstruct.regions.classify import (  # noqa: F401
    DOCLING_CLASSIFICATION,
    IMAGE_CONFIDENCE_THRESHOLD,
    SCANNED_MAX_DENSITY,
    TEXT_CLEAN_MIN_CHARS,
    TEXT_CLEAN_MIN_DENSITY,
    UNKNOWN_MIN_AREA,
    UNKNOWN_MIN_DIM,
    classify_region,
    formula_already_extracted,
    region_has_markers,
    region_needs_vision,
    region_prompt_key,
)
from docstruct.types import Region  # noqa: F401

__all__ = [
    "DOCLING_CLASSIFICATION",
    "IMAGE_CONFIDENCE_THRESHOLD",
    "SCANNED_MAX_DENSITY",
    "TEXT_CLEAN_MIN_CHARS",
    "TEXT_CLEAN_MIN_DENSITY",
    "UNKNOWN_MIN_AREA",
    "UNKNOWN_MIN_DIM",
    "Region",
    "classify_region",
    "formula_already_extracted",
    "region_has_markers",
    "region_needs_vision",
    "region_prompt_key",
]
