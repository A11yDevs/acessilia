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
async def test_unresolved_classification_keeps_source_and_requires_review(monkeypatch):
    manifest = manifest_for("original text")
    install_vision(monkeypatch, VisionOutput(
        kind="description", description="Unclear region.", language="und",
        confidence=0.9, classification_uncertain=True,
    ))

    def unexpected(*args, **kwargs):
        pytest.fail("An unresolved region must not reach mathematical recognition")

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", unexpected)
    breaker = pddl.ProviderBreaker(3)
    await pddl._classify_formula_regions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    await pddl._enrich_formula_latex(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    assert manifest.elements[0].text == "original text"
    classification = manifest.elements[0].metadata["formula_classification"]
    assert (classification["status"], classification["reason"]) == (
        "unresolved", "classification_uncertain"
    )
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
@pytest.mark.parametrize("failure", ["open_breaker", "missing_crop", "model_failed"])
async def test_a_classification_without_an_answer_keeps_the_formula_path(monkeypatch, failure):
    """An outage is no evidence against mathematics: the candidate is recorded
    as unclassified and takes the recognition path it took before the check,
    instead of sending every formula of the document to human review."""
    manifest = manifest_for("original text")
    calls = install_vision(monkeypatch, None)
    breaker = pddl.ProviderBreaker(1)
    if failure == "open_breaker":
        breaker.record(False)
    elif failure == "missing_crop":
        monkeypatch.setattr(pddl, "_formula_recognition_crop", lambda *a, **k: (None, 1))
    await pddl._classify_formula_regions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)

    assert len(calls) == (1 if failure == "model_failed" else 0)
    element = manifest.elements[0]
    assert element.type == "formula" and element.text == "original text"
    expected_reason = {
        "open_breaker": "provider_blocked",
        "missing_crop": "crop_unavailable",
        "model_failed": "model_failed",
    }[failure]
    assert element.metadata["formula_classification"]["status"] == "unclassified"
    assert element.metadata["formula_classification"]["reason"] == expected_reason
    assert manifest.obligations[0].admissible_methods == [
        "mathml", "latex-verbalizer", "human-review"
    ]

    recognized = []

    def recognize(image, **kwargs):
        recognized.append(image)
        return [{"latex": r"x=\frac{a}{b}", "confidence": 0.9}]

    monkeypatch.setattr(pddl, "_formula_recognition_crop", lambda *a, **k: (b"crop", 1))
    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)
    await pddl._enrich_formula_latex(
        manifest, Path("source.pdf"), mode="medio", breaker=pddl.ProviderBreaker(3)
    )
    assert recognized == [b"crop"]


@pytest.mark.asyncio
async def test_a_reclassified_drawing_leaves_no_formula_obligation_behind(monkeypatch):
    from backend.core.manifest.builder import _derive_v23_processing_needs

    manifest = manifest_for("Na+ + Cl-")
    observations, obligations = _derive_v23_processing_needs(manifest.elements)
    manifest.observations.extend(observations)
    manifest.obligations.extend(obligations)
    assert {o.kind for o in manifest.obligations} == {"verbalize-formula", "normalize-formula"}
    install_vision(monkeypatch, VisionOutput(
        kind="description", description="A drawn sodium chloride lattice.",
        language="en", confidence=0.8,
    ))

    await pddl._classify_formula_regions(
        manifest, Path("source.pdf"), mode="medio", breaker=pddl.ProviderBreaker(3)
    )

    assert [o.kind for o in manifest.obligations] == ["describe-image"]
    assert not [o for o in manifest.observations if o.kind.startswith("normalize-formula")]
    element = manifest.elements[0]
    # The crop the model described is the picture the export shows.
    assert element.metadata["src"] == "data:image/png;base64,Y3JvcA=="
    assert 'src="data:image/png;base64,Y3JvcA=="' in _html_of(element)
    assert element.metadata["formula_classification"] == {
        "status": "picture",
        "reason": "candidate_inspection",
        "confidence": 0.8,
        "warnings": [],
    }


@pytest.mark.asyncio
async def test_an_unresolved_region_drops_its_normalization(monkeypatch):
    from backend.core.manifest.builder import _derive_v23_processing_needs

    manifest = manifest_for("OH-")
    _, obligations = _derive_v23_processing_needs(manifest.elements)
    manifest.obligations.extend(obligations)
    install_vision(monkeypatch, VisionOutput(
        kind="description", description="Unclear.", language="und",
        confidence=0.4, classification_uncertain=True,
    ))

    await pddl._classify_formula_regions(
        manifest, Path("source.pdf"), mode="medio", breaker=pddl.ProviderBreaker(3)
    )

    assert [(o.kind, o.admissible_methods) for o in manifest.obligations] == [
        ("verbalize-formula", ["human-review"])
    ]


@pytest.mark.asyncio
async def test_the_recognition_fallback_records_its_own_reclassification(monkeypatch):
    manifest = manifest_for()
    install_vision(monkeypatch, VisionOutput(
        kind="formula", formula_latex="x", language="und", confidence=0.9,
    ))
    breaker = pddl.ProviderBreaker(3)
    await pddl._classify_formula_regions(manifest, Path("source.pdf"), mode="medio", breaker=breaker)
    assert manifest.elements[0].metadata["formula_classification"]["status"] == "math"

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", lambda *a, **k: [])
    install_vision(monkeypatch, VisionOutput(
        kind="description", description="A benzene ring.", language="en", confidence=0.7,
    ))
    await pddl._enrich_formula_latex(manifest, Path("source.pdf"), mode="medio", breaker=breaker)

    element = manifest.elements[0]
    assert element.type == "picture"
    assert element.metadata["formula_classification"]["status"] == "picture"
    assert element.metadata["formula_classification"]["reason"] == "recognition_fallback"
    assert element.metadata["src"].startswith("data:image/png;base64,")


def _html_of(element):
    from docstruct.export.html import document_to_html

    block = pddl._element_to_block(element)
    return document_to_html({"sections": [{"blocks": [block]}]})


def test_a_missing_candidate_prompt_falls_back_to_the_system_prompt(monkeypatch):
    from backend.agents import vision_agent

    monkeypatch.setattr(vision_agent, "load_region_prompt", lambda key: "")
    agent = vision_agent.VisionAgent(mode="medio")
    captured = {}

    async def fake_run(prompt, *args, **kwargs):
        captured["prompt"] = prompt
        return VisionOutput(kind="description", description="x", language="und", confidence=0.5)

    monkeypatch.setattr(vision_agent, "_run_with_retry", fake_run)
    import asyncio

    asyncio.run(agent.describe_region(b"img", "formula_candidate", page_num=1))
    assert captured["prompt"].startswith(agent.system_prompt)
