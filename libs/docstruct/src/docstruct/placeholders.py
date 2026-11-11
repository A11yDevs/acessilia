"""Placeholders that stand for content the extractor did not structure.

Pure: zero external dependencies, standard library only.

A page the extractor returned without any element is kept in the document
as a single placeholder element: raw label ``unstructured-page`` and the
``unstructured_page`` metadata flag. What to do with it (inspect, describe,
accept as blank) is the consumer's decision.

Extractors also leave placeholder text behind (a node labelled ``body`` or
``group``) and short OCR fragments. ``is_placeholder_text``, ``is_ocr_noise``
and ``has_meaningful_text`` tell them from content, so a picture whose only
text is such a fragment still counts as undescribed, and a document whose
text elements hold nothing else is ``is_mostly_visual``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

UNSTRUCTURED_PAGE_LABEL = "unstructured-page"
UNSTRUCTURED_PAGE_FLAG = "unstructured_page"


def is_unstructured_page_placeholder(raw_label: str, metadata: Mapping[str, Any]) -> bool:
    """Whether an element with this raw label and metadata is such a placeholder.

    Both marks are required: the label alone or the flag alone is not one.
    """
    return raw_label == UNSTRUCTURED_PAGE_LABEL and bool(metadata.get(UNSTRUCTURED_PAGE_FLAG))


#: Texts an extractor leaves on a structural node, compared stripped and lowercased.
PLACEHOLDER_TEXTS = frozenset({"body", "_root_", "root", "unspecified", "group"})
#: Raw labels of structural nodes, compared stripped and lowercased.
PLACEHOLDER_LABELS = frozenset({"body", "unspecified", "group"})
#: Element types whose own text makes a document not mostly visual.
TEXT_ELEMENT_TYPES = frozenset({"heading", "title", "paragraph", "list_item", "table", "code", "formula"})


class ExtractedElement(Protocol):
    """What these heuristics read of an element (read-only)."""

    @property
    def type(self) -> str: ...

    @property
    def raw_label(self) -> str: ...

    @property
    def text(self) -> str | None: ...

    @property
    def metadata(self) -> Mapping[str, Any]: ...


def is_placeholder_text(text: str) -> bool:
    """Whether ``text`` is an extractor's placeholder (``PLACEHOLDER_TEXTS``)."""
    normalized = text.strip().lower()
    return normalized in PLACEHOLDER_TEXTS


def is_ocr_noise(text: str) -> bool:
    """Whether ``text`` looks like OCR noise rather than language.

    Blank text, text of at most 4 characters, and a single word of at most 8
    characters are noise; they do not count as content when telling whether
    a document is mostly visual.
    """
    normalized = text.strip()
    if not normalized:
        return True
    # Text of 4 characters or fewer is almost always OCR noise.
    if len(normalized) <= 4:
        return True
    # Text without spaces and of 8 characters or fewer is suspect too.
    if " " not in normalized and len(normalized) <= 8:
        return True
    return False


def has_meaningful_text(element: ExtractedElement) -> bool:
    """Whether ``element`` holds text that is neither OCR noise nor a placeholder.

    Used to keep pictures that came from the extractor with a valid textual
    description.
    """
    text = (element.text or "").strip()
    if not text:
        return False
    if is_placeholder_text(text):
        return False
    if is_ocr_noise(text):
        return False
    return True


def is_placeholder_visual(element: ExtractedElement) -> bool:
    """Whether ``element`` is a structural node standing in for visual content.

    An unstructured-page placeholder is not one: a page inspection reads it.
    Otherwise a group, unknown or paragraph element is one when its text is
    empty, a placeholder or OCR noise, or its raw label is a placeholder's.
    """
    if is_unstructured_page_placeholder(element.raw_label, element.metadata):
        # Inspected by the planned vision-page-inspection method instead.
        return False
    if element.type not in {"group", "unknown", "paragraph"}:
        return False
    text = (element.text or "").strip()
    raw_label = (element.raw_label or "").strip().lower()
    return (not text) or is_placeholder_text(text) or is_ocr_noise(text) or raw_label in PLACEHOLDER_LABELS


def is_mostly_visual(elements: Iterable[ExtractedElement]) -> bool:
    """Whether no text element (``TEXT_ELEMENT_TYPES``) holds content.

    Content is text that is neither a placeholder nor OCR noise; an empty
    document is mostly visual.
    """
    for element in elements:
        if element.type in TEXT_ELEMENT_TYPES:
            text = (element.text or "").strip()
            if text and not is_placeholder_text(text) and not is_ocr_noise(text):
                return False
    return True


__all__ = [
    "PLACEHOLDER_LABELS",
    "PLACEHOLDER_TEXTS",
    "TEXT_ELEMENT_TYPES",
    "UNSTRUCTURED_PAGE_FLAG",
    "UNSTRUCTURED_PAGE_LABEL",
    "ExtractedElement",
    "has_meaningful_text",
    "is_mostly_visual",
    "is_ocr_noise",
    "is_placeholder_text",
    "is_placeholder_visual",
    "is_unstructured_page_placeholder",
]
