"""Formula crops the extractor left without LaTeX are recognized before planning.

"Without LaTeX" includes text-layer text (``s(t) = s0 + v0t + 1 2 at2``): a
recognition replaces it only when it agrees with it.

``math.recognize`` (PP-FormulaNet) runs first and the vision model is the
fallback, so a Toolbox outage degrades to the previous behavior instead of
leaving the formula without content.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from acessilia_sdk.toolbox import ToolboxProviderUnavailable

from backend.agents import pddl_orchestrator as pddl
from backend.agents.output_schemas import VisionOutput
from backend.core.manifest.models import BoundingBox, ManifestElement, Provenance
from backend.i18n import t
from backend.stage_messages import (
    STAGE_ENRICHING_FORMULAS,
    STAGE_PAGE,
    STAGE_RECOGNIZING_FORMULA,
)
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
def fake_vision(monkeypatch):
    monkeypatch.setattr(pddl, "VisionAgent", FakeVision)


@pytest.fixture
def cropped(monkeypatch):
    """A crop for every formula, so no test needs a real PDF render."""
    monkeypatch.setattr(
        pddl, "_formula_recognition_crop", lambda *args, **kwargs: (b"png", 1)
    )


@pytest.mark.asyncio
async def test_formula_crop_is_recognized_by_math_recognize(monkeypatch, cropped):
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
async def test_unavailable_recognizer_falls_back_to_vision(monkeypatch, cropped):
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
async def test_an_outage_is_paid_once_per_document(monkeypatch, cropped):
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
async def test_an_outage_after_the_first_formula_falls_back_to_vision(monkeypatch, cropped):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "vision_concurrency", 1)
    manifest = _formula_manifest(None, None)
    FakeVision.output = VisionOutput(
        kind="formula", formula_latex="y", language="und", confidence=0.7
    )
    calls = []

    def recognize(image, *, raise_on_unavailable=False):
        calls.append(image)
        if len(calls) == 1:
            return [{"latex": "x", "confidence": 0.9}]
        raise MathCapabilityUnavailable(
            "math.recognize", ToolboxProviderUnavailable("offline")
        )

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    assert len(calls) == 2
    assert [
        element.metadata["formula_recognition"]["method"]
        for element in manifest.elements
    ] == ["math.recognize", "vision"]
    assert [element.text for element in manifest.elements] == ["x", "y"]


@pytest.mark.asyncio
async def test_formulas_that_already_have_latex_are_left_alone(monkeypatch, cropped):
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
async def test_a_vision_description_does_not_fill_the_formula(monkeypatch, cropped):
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


@pytest.mark.asyncio
async def test_formula_progress_reports_the_stage_and_each_formula(monkeypatch, cropped):
    manifest = _formula_manifest(None, None)
    monkeypatch.setattr(
        pddl,
        "toolbox_recognize_formula",
        lambda image, **kwargs: [{"latex": "x", "confidence": 1.0}],
    )
    messages: list[str] = []

    async def status_callback(message: str) -> None:
        messages.append(message)

    await pddl._enrich_formula_latex(
        manifest,
        Path("/tmp/doc.pdf"),
        mode="medio",
        status_callback=status_callback,
    )

    expected = [
        t(STAGE_RECOGNIZING_FORMULA).format(
            current=current,
            total=2,
            pages=t(STAGE_PAGE).format(page=1),
        )
        for current in (1, 2)
    ]
    # Concurrency leaves the per-formula order free; only the stage is first.
    assert messages[0] == t(STAGE_ENRICHING_FORMULAS)
    assert sorted(messages[1:]) == sorted(expected)


def _formula_with_bbox(*, page_number: int = 1) -> ManifestElement:
    element = build_element("formula-0", "formula")
    element.provenance = [
        Provenance(
            page_number=page_number,
            bbox=BoundingBox(
                left=10,
                top=20,
                right=110,
                bottom=70,
                coord_origin="TOPLEFT",
            ),
        )
    ]
    return element


def _rendered_page(*, image: bytes = b"rendered", clip=(10, 20, 110, 70)):
    return SimpleNamespace(image=image, clip=clip)


def test_a_saved_region_crop_is_reused_without_render(tmp_path, monkeypatch):
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"saved-crop")
    element = _formula_with_bbox()
    element.metadata["region_crop"] = str(crop)

    def unexpected(*args, **kwargs):
        pytest.fail("a saved crop must not be rendered again")

    monkeypatch.setattr(pddl, "_toolbox_render", unexpected)

    assert pddl._formula_recognition_crop(Path("/tmp/doc.pdf"), element) == (
        b"saved-crop",
        1,
    )


def test_an_unreadable_saved_crop_falls_back_to_the_render(tmp_path, monkeypatch):
    element = _formula_with_bbox()
    element.metadata["region_crop"] = str(tmp_path / "missing.png")
    calls = []

    def render(*args, **kwargs):
        calls.append((args, kwargs))
        return _rendered_page()

    monkeypatch.setattr(pddl, "_toolbox_render", render)

    assert pddl._formula_recognition_crop(Path("/tmp/doc.pdf"), element) == (
        b"rendered",
        1,
    )
    assert len(calls) == 1


def test_a_formula_without_a_page_is_not_rendered(monkeypatch):
    element = build_element("formula-0", "formula")
    element.page_number = None

    def unexpected(*args, **kwargs):
        pytest.fail("a formula without a page has nothing to render")

    monkeypatch.setattr(pddl, "_toolbox_render", unexpected)

    assert pddl._formula_recognition_crop(Path("/tmp/doc.pdf"), element) == (None, 0)


def test_a_formula_without_a_box_is_not_rendered(monkeypatch):
    element = build_element("formula-0", "formula")
    element.provenance = [Provenance(page_number=1, bbox=None)]

    def unexpected(*args, **kwargs):
        pytest.fail("a formula without a box must not fall back to the whole page")

    monkeypatch.setattr(pddl, "_toolbox_render", unexpected)

    assert pddl._formula_recognition_crop(Path("/tmp/doc.pdf"), element) == (None, 1)


def test_the_page_region_is_rendered_with_the_expected_arguments(monkeypatch):
    element = _formula_with_bbox()
    calls = []

    def render(*args, **kwargs):
        calls.append((args, kwargs))
        return _rendered_page()

    monkeypatch.setattr(pddl, "_toolbox_render", render)

    image, page_number = pddl._formula_recognition_crop(
        Path("/tmp/doc.pdf"),
        element,
        artifact_id="artifact-source",
        media_type="application/pdf",
    )

    assert (image, page_number) == (b"rendered", 1)
    assert calls == [
        (
            (Path("/tmp/doc.pdf"), 1),
            {
                "media_type": "application/pdf",
                "dpi": 200,
                "clip": (10.0, 20.0, 110.0, 70.0),
                "clip_origin": "TOPLEFT",
                "artifact_id": "artifact-source",
            },
        )
    ]


def test_a_sliver_of_a_region_is_not_a_formula_crop(monkeypatch):
    element = _formula_with_bbox()
    monkeypatch.setattr(
        pddl,
        "_toolbox_render",
        lambda *args, **kwargs: _rendered_page(clip=(10, 20, 12, 70)),
    )

    assert pddl._formula_recognition_crop(Path("/tmp/doc.pdf"), element) == (None, 1)


def test_a_failed_render_leaves_the_formula_without_a_crop(monkeypatch):
    element = _formula_with_bbox()

    def failed(*args, **kwargs):
        raise ValueError("pdf.render refused the box")

    monkeypatch.setattr(pddl, "_toolbox_render", failed)

    assert pddl._formula_recognition_crop(Path("/tmp/doc.pdf"), element) == (None, 1)


TEXT_LAYER = "s(t) = s0 + v0t + 1\n2\nat2, t > 0,"
FAITHFUL = r"s(t) = s_0 + v_0 t + \frac{1}{2} a t^2, \quad t > 0,"
MISREAD = r"x^2 + y^2 = 1"


def _recognizer(monkeypatch, latex):
    calls = []

    def recognize(image, *, raise_on_unavailable=False):
        calls.append(image)
        return [{"latex": latex}]

    monkeypatch.setattr(pddl, "toolbox_recognize_formula", recognize)
    return calls


@pytest.mark.asyncio
async def test_a_text_layer_formula_is_replaced_by_its_recognition(monkeypatch, cropped):
    manifest = _formula_manifest(TEXT_LAYER)
    calls = _recognizer(monkeypatch, FAITHFUL)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    assert calls == [b"png"]
    assert element.text == FAITHFUL
    # The replaced text exactly as the extractor delivered it, newlines included.
    assert element.metadata["formula_text_layer"] == TEXT_LAYER
    assert element.metadata["formula_recognition"] == {
        "method": "math.recognize",
        "confidence": None,
        "text_agreement": 1.0,
    }
    assert FakeVision.calls == []


@pytest.mark.asyncio
async def test_a_misread_falls_back_to_vision(monkeypatch, cropped):
    manifest = _formula_manifest(TEXT_LAYER)
    _recognizer(monkeypatch, MISREAD)
    FakeVision.output = VisionOutput(
        kind="formula", formula_latex=FAITHFUL, language="und", confidence=0.8
    )

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    recognition = element.metadata["formula_recognition"]
    assert element.text == FAITHFUL
    assert recognition["method"] == "vision"
    assert recognition["text_agreement"] == 1.0
    assert recognition["rejected"]["math.recognize"] < 0.5


@pytest.mark.asyncio
async def test_without_an_agreeing_recognition_the_text_layer_stays(monkeypatch, cropped):
    manifest = _formula_manifest(TEXT_LAYER)
    _recognizer(monkeypatch, MISREAD)
    FakeVision.output = VisionOutput(
        kind="formula", formula_latex=r"\int_0^1 f", language="und", confidence=0.8
    )

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    assert element.text == TEXT_LAYER
    assert "formula_text_layer" not in element.metadata
    recognition = element.metadata["formula_recognition"]
    assert recognition["method"] == "text-layer"
    assert set(recognition["rejected"]) == {"math.recognize", "vision"}


@pytest.mark.asyncio
async def test_the_agreement_floor_is_configurable(monkeypatch, cropped):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "formula_text_agreement_min", 0.0)
    manifest = _formula_manifest(TEXT_LAYER)
    _recognizer(monkeypatch, MISREAD)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    assert manifest.elements[0].text == MISREAD
    assert FakeVision.calls == []


@pytest.mark.asyncio
async def test_a_formula_without_text_has_nothing_to_agree_with(monkeypatch, cropped):
    manifest = _formula_manifest()
    _recognizer(monkeypatch, MISREAD)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    assert element.text == MISREAD
    assert "formula_text_layer" not in element.metadata
    assert "text_agreement" not in element.metadata["formula_recognition"]


@pytest.mark.asyncio
async def test_unicode_scripts_in_the_text_layer_agree(monkeypatch, cropped):
    """Word-exported text layers carry x² and v₀ for x^2 and v_0."""
    manifest = _formula_manifest("s(t) = s₀ + v₀t + ½at², t > 0")
    _recognizer(monkeypatch, r"s(t) = s_0 + v_0 t + \frac{1}{2} a t^2, \quad t > 0")

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    recognition = manifest.elements[0].metadata["formula_recognition"]
    assert recognition["method"] == "math.recognize"
    assert recognition["text_agreement"] >= 0.9


@pytest.mark.asyncio
async def test_a_recognition_without_evidence_is_refused(monkeypatch, cropped):
    """Text-layer text with no visible symbol gives no evidence either way."""
    manifest = _formula_manifest("( )")
    _recognizer(monkeypatch, "()")

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    assert element.text == "( )"
    assert element.metadata["formula_recognition"] == {
        "method": "text-layer",
        "rejected": {"math.recognize": None},
    }


@pytest.mark.asyncio
async def test_bare_scripts_in_the_text_layer_are_recognized(monkeypatch, cropped):
    """A caret in the text layer is not LaTeX: the formula is recognized and gated (#268)."""
    text_layer = "vm2(h) = (s(2 + h) − s(2)) / ((2 + h) − 2) = ((2 + h)^3 − 2^8) / h"
    recognized = r"vm_{2}(h)=\frac{s(2+h)-s(2)}{(2+h)-2}=\frac{(2+h)^{3}-2^{8}}{h}"
    manifest = _formula_manifest(text_layer)
    calls = _recognizer(monkeypatch, recognized)

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    element = manifest.elements[0]
    assert calls == [b"png"]
    assert element.text == recognized
    assert element.metadata["formula_text_layer"] == text_layer
    assert element.metadata["formula_recognition"]["text_agreement"] >= 0.9


@pytest.mark.asyncio
async def test_latex_with_grouped_scripts_is_left_alone(monkeypatch, cropped):
    """Grouped scripts are markup: the formula keeps its LaTeX without a call (#268)."""
    manifest = _formula_manifest("x^{2} + y_{1}")
    calls = _recognizer(monkeypatch, "anything")

    await pddl._enrich_formula_latex(manifest, Path("/tmp/doc.pdf"), mode="medio")

    assert calls == []
    assert manifest.elements[0].text == "x^{2} + y_{1}"
