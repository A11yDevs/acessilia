"""Placeholder text, OCR noise and mostly visual documents (docstruct.placeholders).

Moved from the core's PDDL payload (#402); the core covers the same rules on
its own models in tests/test_pddl_visual_heuristics.py. Here they run on
docstruct's ``DocumentElement``.
"""

from __future__ import annotations

import pytest

from docstruct.manifest import DocumentElement
from docstruct.placeholders import (
    PLACEHOLDER_LABELS,
    PLACEHOLDER_TEXTS,
    TEXT_ELEMENT_TYPES,
    UNSTRUCTURED_PAGE_FLAG,
    UNSTRUCTURED_PAGE_LABEL,
    has_meaningful_text,
    is_mostly_visual,
    is_ocr_noise,
    is_placeholder_text,
    is_placeholder_visual,
)


def _element(kind: str, text: str | None = None, raw_label: str | None = None, metadata=None):
    return DocumentElement(
        id="e", type=kind, raw_label=raw_label or kind, reading_order=1, hierarchy_level=1,
        text=text, metadata=metadata or {},
    )


@pytest.mark.parametrize(
    ("text", "expected"),
    [("", True), ("abcd", True), ("abcdefgh", True), ("abcdefghi", False), ("ab cd", False),
     ("a b", True), ("  a b c  ", False)],
)
def test_ocr_noise_by_length_and_spaces(text, expected) -> None:
    assert is_ocr_noise(text) is expected


def test_every_placeholder_text_in_any_case() -> None:
    for text in PLACEHOLDER_TEXTS:
        assert is_placeholder_text(f"  {text.upper()} ")
    assert not is_placeholder_text("body text")


@pytest.mark.parametrize(
    ("text", "expected"),
    [(None, False), ("group", False), ("Logo", False), ("Uma figura com legenda", True)],
)
def test_meaningful_text(text, expected) -> None:
    assert has_meaningful_text(_element("picture", text)) is expected


@pytest.mark.parametrize("label", sorted(PLACEHOLDER_LABELS))
def test_a_placeholder_label_makes_a_paragraph_a_visual_placeholder(label) -> None:
    assert is_placeholder_visual(_element("paragraph", "Um texto de verdade aqui", raw_label=label.title()))


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        pytest.param(_element("group"), True, id="empty-group"),
        pytest.param(_element("unknown", "Um texto de verdade aqui"), False, id="unknown-with-text"),
        pytest.param(_element("paragraph", "_root_"), True, id="placeholder-text"),
        pytest.param(_element("picture"), False, id="picture"),
        pytest.param(_element("paragraph", raw_label=UNSTRUCTURED_PAGE_LABEL,
                              metadata={UNSTRUCTURED_PAGE_FLAG: True}), False, id="unstructured-page"),
    ],
)
def test_a_visual_placeholder(element, expected) -> None:
    assert is_placeholder_visual(element) is expected


@pytest.mark.parametrize("kind", sorted(TEXT_ELEMENT_TYPES))
def test_any_text_element_with_content_makes_a_document_not_mostly_visual(kind) -> None:
    assert not is_mostly_visual([_element("picture"), _element(kind, "Um texto de verdade aqui")])
    assert is_mostly_visual([_element(kind, "abc"), _element(kind, "group")])


def test_other_types_and_an_empty_document_are_mostly_visual() -> None:
    assert is_mostly_visual([])
    assert is_mostly_visual(iter([_element("caption", "Uma legenda longa o bastante"),
                                  _element("footnote", "Uma nota longa o bastante")]))
