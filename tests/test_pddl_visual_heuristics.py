"""Which text counts as content, for the picture enrichment (#402).

Characterization of the orchestrator's text heuristics, written on develop
before they moved to docstruct: OCR noise, placeholder texts and labels,
meaningful text, and a manifest that is mostly visual.
"""

from __future__ import annotations

import pytest

from backend.agents import pddl_orchestrator as pddl
from tests.pddl_support import build_element, build_manifest


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("", True), ("   ", True), ("abcd", True), ("  abcd  ", True), ("abcde", True),
        ("abcdefgh", True), ("abcdefghi", False), ("ab cd", False), ("a b", True),
        ("Figura 1", False), ("Logotipo", True),
    ],
)
def test_ocr_noise(text, expected) -> None:
    assert pddl._is_ocr_noise(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("body", True), (" Body ", True), ("_ROOT_", True), ("root", True), ("unspecified", True),
     ("group", True), ("groups", False), ("", False), ("body text", False)],
)
def test_placeholder_text(text, expected) -> None:
    assert pddl._is_placeholder_text(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [(None, False), ("", False), ("  ", False), ("group", False), ("abcd", False),
     ("Logotipo", False), ("Uma figura com legenda", True), ("abcdefghi", True)],
)
def test_meaningful_text(text, expected) -> None:
    assert pddl._has_meaningful_text(build_element("p", "picture", text=text)) is expected


def _element(kind, text=None, raw_label=None, metadata=None):
    element = build_element("e", kind, text=text, metadata=metadata)
    if raw_label is not None:
        element.raw_label = raw_label
    return element


@pytest.mark.parametrize(
    ("element", "expected"),
    [
        pytest.param(_element("group"), True, id="empty-group"),
        pytest.param(_element("unknown", "Um texto de verdade aqui"), False, id="unknown-with-text"),
        pytest.param(_element("paragraph", "abc"), True, id="noise-paragraph"),
        pytest.param(_element("paragraph", "body"), True, id="placeholder-paragraph"),
        pytest.param(_element("paragraph", "Um texto de verdade aqui", raw_label=" Body "), True,
                     id="placeholder-label"),
        pytest.param(_element("paragraph", "Um texto de verdade aqui", raw_label="text"), False,
                     id="real-paragraph"),
        pytest.param(_element("picture"), False, id="picture"),
        pytest.param(_element("heading", "abc"), False, id="heading"),
        pytest.param(_element("paragraph", raw_label="unstructured-page",
                              metadata={"unstructured_page": True}), False, id="unstructured-page"),
        pytest.param(_element("paragraph", raw_label="unstructured-page"), True,
                     id="label-without-flag"),
    ],
)
def test_placeholder_visual_element(element, expected) -> None:
    assert pddl._is_placeholder_visual_element(element) is expected


@pytest.mark.parametrize(
    ("elements", "expected"),
    [
        pytest.param([], True, id="empty"),
        pytest.param([("picture", "Uma figura com legenda")], True, id="only-pictures"),
        pytest.param([("paragraph", "abc"), ("heading", "body")], True, id="noise-and-placeholders"),
        pytest.param([("paragraph", "abc"), ("formula", "x + y = z")], False, id="a-formula"),
        pytest.param([("caption", "Uma legenda longa o bastante")], True, id="caption-not-counted"),
        pytest.param([("title", "Relatorio anual")], False, id="title"),
        pytest.param([("code", None), ("table", "  ")], True, id="blank"),
    ],
)
def test_mostly_visual_manifest(elements, expected) -> None:
    manifest = build_manifest(
        [build_element(f"e{i}", kind, text=text) for i, (kind, text) in enumerate(elements)], []
    )
    assert pddl._is_mostly_visual_manifest(manifest) is expected
