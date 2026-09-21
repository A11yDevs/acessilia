"""Semantic block classification heuristics.

Core migrated to docstruct.blocks.classify; re-exported here for
compatibility with existing imports.
"""
from __future__ import annotations

from docstruct.blocks.classify import (  # noqa: F401
    classify_text_block,
    extract_plain_heading,
    looks_like_upper_heading,
    starts_with_list_marker,
)

__all__ = [
    "classify_text_block",
    "extract_plain_heading",
    "looks_like_upper_heading",
    "starts_with_list_marker",
]
