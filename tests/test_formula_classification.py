"""Extractor formula labels are checked before mathematical recognition."""
from pathlib import Path

import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.agents.output_schemas import VisionOutput
from tests.pddl_support import build_element, build_manifest, build_obligation


def manifest_for(text=None):
    element = build_element("element-1", "formula", text=text)
    obligation = build_obligation(
        "verbalize-formula", [element.id], ["mathml", "latex-verbalizer", "human-review"],
    )
    return build_manifest([element], [obligation])


def install_vision(monkeypatch, output):
    calls = []

    class Vision:
        def __init__(self, mode):
            pass

        async def describe_region(self, **kwargs):
            calls.append(kwargs)
            return output

    monkeypatch.setattr(pddl, "VisionAgent", Vision)
    monkeypatch.setattr(pddl, "_formula_recognition_crop", lambda *a, **k: (b"crop", 1))
    return calls


@pytest.mark.asyncio
async def test_drawing_is_reclassified_and_description_is_not_requested_twice(monkeypatch):
    manifest = manifest_for("extractor placeholder")
    calls = install_vision(monkeypatch, VisionOutput(
        kind="description", description="A ring with labelled oxygen atoms.", language="en", confidence=0.9,
    ))
    breaker = pddl.ProviderBreaker(3)
    await pddl._classify_formula_regions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)

    def unexpected(*args, **kwargs):
        pytest.fail("A drawing must never reach mathematical recognition")

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", unexpected)
    await pddl._enrich_formula_latex(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    await pddl._enrich_picture_descriptions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    element = manifest.elements[0]
    assert element.type == "picture"
    assert element.text == "A ring with labelled oxygen atoms."
    assert element.metadata["original_type"] == "formula"
    assert element.metadata["original_text"] == "extractor placeholder"
    assert element.metadata["vision_description_complete"] is True
    assert [o.kind for o in manifest.obligations] == ["describe-image"]
    assert len(calls) == 1
    assert pddl._element_to_block(element)["alt_text"] == element.text


@pytest.mark.asyncio
async def test_mathematical_formula_still_uses_math_recognize(monkeypatch):
    manifest = manifest_for()
    calls = install_vision(monkeypatch, VisionOutput(kind="formula", formula_latex="x=1", language="und", confidence=0.9))
    recognized = []

    def recognize(image, **kwargs):
        recognized.append(image)
        return [{"latex": r"x=\frac{a}{b}", "confidence": 0.9}]

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)
    breaker = pddl.ProviderBreaker(3)
    await pddl._classify_formula_regions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    await pddl._enrich_formula_latex(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    assert manifest.elements[0].type == "formula"
    assert manifest.elements[0].text == r"x=\frac{a}{b}"
    assert recognized == [b"crop"]
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("output", [None, VisionOutput(kind="description", description="Unclear region.", language="und", confidence=0.9, classification_uncertain=True)])
async def test_unresolved_classification_keeps_source_and_requires_review(monkeypatch, output):
    manifest = manifest_for("original text")
    install_vision(monkeypatch, output)

    def unexpected(*args, **kwargs):
        pytest.fail("An unresolved region must not reach mathematical recognition")

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", unexpected)
    breaker = pddl.ProviderBreaker(3)
    await pddl._classify_formula_regions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    await pddl._enrich_formula_latex(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    assert manifest.elements[0].text == "original text"
    assert manifest.elements[0].metadata["formula_classification"]["status"] == "unresolved"
    assert manifest.obligations[0].admissible_methods == ["human-review"]
    result = pddl._handle_human_review_method(manifest, manifest.obligations[0].id)
    assert result.success is False
    assert result.validated is False


@pytest.mark.asyncio
async def test_existing_latex_does_not_pay_for_classification(monkeypatch):
    manifest = manifest_for(r"\frac{a}{b}")
    calls = install_vision(monkeypatch, None)
    await pddl._classify_formula_regions(
        manifest, Path("source.pdf"), mode="medio", breaker=pddl.ProviderBreaker(3),
    )
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["open_breaker", "missing_crop"])
async def test_unavailable_classification_cannot_silently_enable_math(monkeypatch, failure):
    manifest = manifest_for("original text")
    calls = install_vision(monkeypatch, None)
    breaker = pddl.ProviderBreaker(1)
    if failure == "open_breaker":
        breaker.record(False)
    else:
        monkeypatch.setattr(pddl, "_formula_recognition_crop", lambda *a, **k: (None, 1))
    await pddl._classify_formula_regions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    assert calls == []
    assert manifest.elements[0].text == "original text"
    assert manifest.elements[0].metadata["formula_classification"]["status"] == "unresolved"
    expected_reason = "provider_blocked" if failure == "open_breaker" else "crop_unavailable"
    assert manifest.elements[0].metadata["formula_classification"]["reason"] == expected_reason
    assert manifest.obligations[0].admissible_methods == ["human-review"]
