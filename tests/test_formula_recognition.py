"""Formula crops the extractor left without LaTeX are recognized before planning.

``math.recognize`` (PP-FormulaNet) runs first and the vision model is the
fallback, so a Toolbox outage degrades to the previous behavior instead of
leaving the formula without content.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from acessilia_sdk.toolbox import ToolboxProviderUnavailable

from backend.agents import pddl_orchestrator as pddl
from backend.agents.output_schemas import VisionOutput
from backend.tools.toolbox_math_tools import MathCapabilityUnavailable
from tests.pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
)


def _formula_manifest(*texts: str | None, metadata: dict | None = None):
    if not texts:
        texts = (None,)
    elements = [
        build_element(
            f"formula-{index}",
            "formula",
            text=text,
            metadata=dict(metadata or {}),
            reading_order=index + 1,
        )
        for index, text in enumerate(texts)
    ]
    return build_manifest(
        elements,
        [
            build_obligation(
                "verbalize-formula",
                [element.id for element in elements],
                ["mathml", "latex-verbalizer", "human-review"],
            )
        ],
    )


class FakeVision:
    """Stands in for ``VisionAgent``; records the calls the enrichment makes."""

    calls: ClassVar[list[dict]] = []
    output: ClassVar[VisionOutput | None] = None

    def __init__(self, mode: str) -> None:
        self.mode = mode

    async def describe_region(self, **kwargs):
        type(self).calls.append(kwargs)
        return type(self).output


@pytest.fixture(autouse=True)
def reset_vision():
    FakeVision.calls = []
    FakeVision.output = None
    yield
    FakeVision.calls = []
    FakeVision.output = None


@pytest.fixture(autouse=True)
def cropped(monkeypatch):
    """A crop for every formula, so no test needs a real PDF render."""
    monkeypatch.setattr(
        pddl, "_formula_recognition_crop", lambda *args, **kwargs: (b"png", 1)
    )
    monkeypatch.setattr(pddl, "VisionAgent", FakeVision)


@pytest.mark.asyncio
async def test_formula_crop_is_recognized_by_math_recognize(monkeypatch):
    manifest = _formula_manifest()
    calls = []

    def recognize(image, *, raise_on_unavailable=False):
        calls.append((image, raise_on_unavailable))
        return [{"latex": "$E=mc^2$", "confidence": 0.97}]

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    assert element.text == "E=mc^2"
    assert element.metadata["formula_recognition"] == {
        "method": "math.recognize",
        "confidence": 0.97,
    }
    assert calls == [(b"png", True)]
    assert FakeVision.calls == []


@pytest.mark.asyncio
async def test_unavailable_recognizer_falls_back_to_vision(monkeypatch):
    manifest = _formula_manifest()
    FakeVision.output = VisionOutput(
        kind="formula", formula_latex=r"\frac{a}{b}", language="und", confidence=0.8
    )

    def recognize(image, *, raise_on_unavailable=False):
        raise MathCapabilityUnavailable(
            "math.recognize", ToolboxProviderUnavailable("offline")
        )

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    assert element.text == r"\frac{a}{b}"
    assert element.metadata["formula_recognition"]["method"] == "vision"
    assert len(FakeVision.calls) == 1
    assert FakeVision.calls[0]["classification"] == "formula"
    assert FakeVision.calls[0]["full_budget"] is True


@pytest.mark.asyncio
async def test_an_outage_is_paid_once_per_document(monkeypatch):
    manifest = _formula_manifest(None, None)
    calls = []
    FakeVision.output = VisionOutput(
        kind="formula", formula_latex="x^2", language="und", confidence=0.7
    )

    def recognize(image, *, raise_on_unavailable=False):
        calls.append(image)
        raise MathCapabilityUnavailable(
            "math.recognize", ToolboxProviderUnavailable("offline")
        )

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    assert calls == [b"png"]
    assert [element.text for element in manifest.elements] == ["x^2", "x^2"]
    assert len(FakeVision.calls) == 2


@pytest.mark.asyncio
async def test_formulas_that_already_have_latex_are_left_alone(monkeypatch):
    manifest = _formula_manifest("$x=1$")
    calls = []

    def recognize(image, *, raise_on_unavailable=False):
        calls.append(image)
        return []

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    assert calls == []
    assert FakeVision.calls == []
    assert manifest.elements[0].text == "$x=1$"
    assert "formula_recognition" not in manifest.elements[0].metadata


@pytest.mark.asyncio
async def test_a_formula_without_a_crop_is_skipped(monkeypatch):
    manifest = _formula_manifest()
    monkeypatch.setattr(
        pddl, "_formula_recognition_crop", lambda *args, **kwargs: (None, 1)
    )

    def unexpected(*args, **kwargs):
        pytest.fail("recognition must not run without a crop")

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", unexpected)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    assert manifest.elements[0].text is None
    assert FakeVision.calls == []


@pytest.mark.asyncio
async def test_a_vision_description_does_not_fill_the_formula(monkeypatch):
    manifest = _formula_manifest()
    FakeVision.output = VisionOutput(
        kind="description", description="A chart", language="en", confidence=0.9
    )

    monkeypatch.setattr(
        pddl,
        "toolbox_recognize_formula",
        lambda image, **kwargs: [{"latex": "", "confidence": 0.1}],
    )

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    assert manifest.elements[0].text is None
    assert "formula_recognition" not in manifest.elements[0].metadata


def test_best_candidate_prefers_the_highest_confidence():
    best = pddl._best_formula_candidate(
        [
            {"latex": "$a$", "confidence": 0.4},
            {"latex": "$$b$$", "confidence": 0.9},
            {"latex": "   ", "confidence": 1.0},
        ]
    )

    assert best is not None
    assert best["latex"] == "b"
    assert pddl._best_formula_candidate([]) is None
    assert pddl._best_formula_candidate([{"latex": ""}]) is None
