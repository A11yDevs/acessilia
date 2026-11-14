"""Which pictures the vision step describes, and how an answer is folded in (#402).

Characterization written on develop before ``_enrich_picture_descriptions``
was split. The crop and the vision model are replaced; the other picture
tests run them against the fake Toolbox.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest

from backend.core.pipeline import orchestrator as pddl
from backend.agents.output_schemas import VisionOutput
from backend.core.manifest.models import PageDescriptor
from tests.pddl_support import build_element, build_manifest, build_obligation
from backend.core.pipeline.enrichment import pictures as picture_stage


class Vision:
    calls: ClassVar[list[dict]] = []
    answers: ClassVar[dict] = {}

    def __init__(self, mode: str) -> None:
        pass

    async def describe_region(self, *, image_bytes, errors=None, **kwargs):
        type(self).calls.append({"id": image_bytes.decode(), **kwargs})
        answer = type(self).answers.get(image_bytes.decode())
        if answer is None and errors is not None:
            errors.append("provider said no")
        return answer


@pytest.fixture(autouse=True)
def fakes(monkeypatch):
    Vision.calls, Vision.answers = [], {}
    monkeypatch.setattr(picture_stage, "VisionAgent", Vision)
    crops: dict = {}

    def crop(source, element, fallback, artifact_id, media_type):
        return crops.get(element.id, (element.id.encode(), element.page_number or fallback or 1))

    monkeypatch.setattr(picture_stage, "_extract_picture_bytes", crop)
    from backend.config.settings import settings
    monkeypatch.setattr(settings, "vision_retry_pass_delay_seconds", 0)
    return crops


def _describe(answer: str, **kwargs) -> VisionOutput:
    return VisionOutput(kind="description", description=answer, language="pt", confidence=0.8, **kwargs)


def _manifest(elements, pages=2):
    manifest = build_manifest(elements, [build_obligation("describe-image", [e.id for e in elements], ["vision-description", "human-review"])])
    manifest.pages = [PageDescriptor(page_number=n, width=600.0, height=800.0, element_ids=[]) for n in range(1, pages + 1)]
    return manifest


async def _run(manifest, **kwargs):
    await picture_stage._enrich_picture_descriptions(manifest, Path("doc.pdf"), mode="medio", **kwargs)


@pytest.mark.asyncio
async def test_undescribed_pictures_are_described_and_complete_ones_skipped() -> None:
    done = build_element("done", "picture", text="Ja descrita", metadata={"vision_description_complete": True})
    manifest = _manifest([build_element("pic", "picture"), done, build_element("p", "paragraph", text="Um texto longo de verdade")])
    Vision.answers = {"pic": _describe("Um grafico de barras", mentioned_elements=["eixo"], warnings=["borrado"])}

    await _run(manifest)

    pic = manifest.elements[0]
    assert [c["id"] for c in Vision.calls] == ["pic"]
    assert pic.text == "Um grafico de barras"
    assert pic.metadata["vision_language"] == "pt" and pic.metadata["vision_confidence"] == 0.8
    assert pic.metadata["vision_elements"] == ["eixo"] and pic.metadata["vision_warnings"] == ["borrado"]
    assert pic.metadata["vision_description_complete"] is True
    assert Vision.calls[0]["classification"] == "embedded_image"


@pytest.mark.asyncio
async def test_without_pictures_a_mostly_visual_document_describes_its_placeholders() -> None:
    manifest = _manifest([build_element("g", "group"), build_element("n", "paragraph", text="abc"),
                          build_element("h", "heading", text="ok")])
    Vision.answers = {"g": _describe("Uma foto"), "n": _describe("Um logotipo")}

    await _run(manifest)

    assert [c["id"] for c in Vision.calls] == ["g", "n"]
    assert [e.type for e in manifest.elements] == ["picture", "picture", "heading"]
    assert manifest.elements[0].metadata["original_type"] == "group"


@pytest.mark.asyncio
async def test_a_one_page_mostly_visual_document_describes_its_first_element() -> None:
    manifest = _manifest([build_element("h1", "heading", text="ok"), build_element("h2", "heading", text="xy")], pages=1)
    Vision.answers = {"h1": _describe("Uma pagina escaneada")}

    await _run(manifest)

    assert [c["id"] for c in Vision.calls] == ["h1"]
    assert manifest.elements[0].type == "picture"


@pytest.mark.asyncio
async def test_a_multi_page_document_without_candidates_is_left_alone() -> None:
    manifest = _manifest([build_element("h1", "heading", text="ok")], pages=2)

    await _run(manifest)

    assert Vision.calls == []


@pytest.mark.asyncio
async def test_a_formula_answer_retypes_a_picture() -> None:
    manifest = _manifest([build_element("pic", "picture")])
    Vision.answers = {"pic": VisionOutput(kind="formula", formula_latex="x^2", language="und", confidence=0.6)}

    await _run(manifest)

    pic = manifest.elements[0]
    assert (pic.type, pic.raw_label, pic.text) == ("formula", "formula", "x^2")
    assert pic.metadata["original_type"] == "picture"


@pytest.mark.asyncio
async def test_an_empty_answer_keeps_meaningful_extractor_text() -> None:
    manifest = _manifest([build_element("pic", "picture", text="Legenda que o extrator leu")])
    Vision.answers = {"pic": _describe("A")}
    Vision.answers["pic"] = Vision.answers["pic"].model_copy(update={"description": "  "})

    await _run(manifest)

    pic = manifest.elements[0]
    assert pic.text == "Legenda que o extrator leu"
    assert pic.metadata["vision_description_complete"] is True


@pytest.mark.asyncio
async def test_an_empty_answer_over_noise_is_an_empty_description() -> None:
    manifest = _manifest([build_element("pic", "picture", text="body")])
    Vision.answers = {"pic": _describe("A").model_copy(update={"description": ""})}

    await _run(manifest)

    pic = manifest.elements[0]
    assert pic.text == ""
    assert pic.metadata["vision_failure_reason"] == "empty_description"
    assert len(Vision.calls) == 2  # the retry pass asks once more


@pytest.mark.asyncio
async def test_failures_are_recorded_with_their_reason(fakes) -> None:
    manifest = _manifest([build_element("crop", "picture"), build_element("none", "picture"),
                          build_element("model", "picture")])
    fakes["crop"] = (None, 2)
    fakes["none"] = (None, 0)

    await _run(manifest)

    reasons = {e.id: (e.metadata.get("vision_failure_reason"), e.metadata.get("vision_failure_detail"))
               for e in manifest.elements}
    assert reasons == {"crop": ("crop_unavailable", None), "none": ("image_unavailable", None),
                       "model": ("model_failed", "provider said no")}
    assert [c["id"] for c in Vision.calls] == ["model", "model"]


@pytest.mark.asyncio
async def test_an_open_breaker_skips_the_calls_and_the_retry_probes_once() -> None:
    manifest = _manifest([build_element("a", "picture"), build_element("b", "picture")])
    breaker = pddl.ProviderBreaker(1)
    breaker.record(False)

    await _run(manifest, breaker=breaker)

    a, b = manifest.elements
    assert [c["id"] for c in Vision.calls] == ["a"]
    assert (a.metadata["vision_failure_reason"], a.metadata["vision_failure_detail"]) == ("model_failed", "provider said no")
    assert b.metadata["vision_failure_reason"] == "model_failed"
    assert b.metadata["vision_failure_detail"].startswith("skipped:")


@pytest.mark.asyncio
async def test_a_slide_gets_the_page_prompt_and_a_pageless_picture_its_page(fakes) -> None:
    slide = build_element("slide", "picture", metadata={"slide_visual": True})
    loose = build_element("loose", "picture")
    loose.page_number = None
    manifest = _manifest([slide, loose], pages=1)
    Vision.answers = {"slide": _describe("Um slide"), "loose": _describe("Uma foto")}

    await _run(manifest)

    assert [c["classification"] for c in Vision.calls] == ["full_page_image", "embedded_image"]
    assert manifest.elements[1].page_number == 1
