"""Placeholders that stand for content the extractor did not structure.

Pure: zero external dependencies, standard library only.

A page the extractor returned without any element is kept in the document
as a single placeholder element: raw label ``unstructured-page`` and the
``unstructured_page`` metadata flag. What to do with it (inspect, describe,
accept as blank) is the consumer's decision.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

UNSTRUCTURED_PAGE_LABEL = "unstructured-page"
UNSTRUCTURED_PAGE_FLAG = "unstructured_page"


def is_unstructured_page_placeholder(raw_label: str, metadata: Mapping[str, Any]) -> bool:
    """Whether an element with this raw label and metadata is such a placeholder.

    Both marks are required: the label alone or the flag alone is not one.
    """
    return raw_label == UNSTRUCTURED_PAGE_LABEL and bool(metadata.get(UNSTRUCTURED_PAGE_FLAG))


__all__ = [
    "UNSTRUCTURED_PAGE_FLAG",
    "UNSTRUCTURED_PAGE_LABEL",
    "is_unstructured_page_placeholder",
]
