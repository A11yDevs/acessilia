"""Real page rendering and plan execution with a simulated structured vision response.

Regions are rendered by the Toolbox (``pdf.render@2``); the fake in
``tests/toolbox_render_fake.py`` renders real pixels behind the mocked HTTP.
"""

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.agents.output_schemas import VisionOutput
from backend.core.manifest.models import BoundingBox, PageDescriptor, ProcessingManifest, Provenance
from tests.pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)


@pytest.fixture
def inspection(monkeypatch, tmp_path, fake_toolbox_render):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    source = tmp_path / "source.pdf"
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        page.insert_text((15, 40), "Region content")
        pdf.new_page(width=200, height=100)
        pdf.save(source)
    element = _element("unknown", "unknown", text="Unrecognized content needing inspection")
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=10, top=20, right=90, bottom=70, coord_origin="TOPLEFT",
    ))]
    manifest = _manifest([element], [_obligation(
        "review-structure", ["unknown"], ["pymupdf-region", "human-review"],
    )])
    manifest.obligations[0].method_costs = {"pymupdf-region": 1, "human-review": 100}
    manifest.source.path = str(source)
    manifest.source.byte_size = source.stat().st_size
    manifest.source.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest.pages.append(PageDescriptor(page_number=2))
    manifest.summary.page_count = 2
    calls = []
    response = VisionOutput(kind="description", description="A map", language="en", confidence=0.9)

    class Vision:
        def __init__(self, mode):
            self.mode = mode

        async def describe_region(self, **kwargs):
            calls.append(kwargs)
            return Vision.response

    Vision.response = response
    monkeypatch.setattr(pddl, "VisionAgent", Vision)
    return manifest, calls, Vision


@pytest.mark.parametrize("kind", ["description", "formula"])
def test_real_region_inspection_updates_output_and_records_evidence(inspection, tmp_path, kind):
    manifest, calls, vision = inspection
    if kind == "formula":
        vision.response = VisionOutput(kind="formula", formula_latex="x^2", language="und", confidence=0.9)
    original = manifest.model_dump()
    orchestrator = _orchestrator()
    assert not orchestrator._unavailable_methods(manifest)
    plan, _ = orchestrator._build_plan(manifest)
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status == "completed"
    assert manifest.model_dump() == original
    assert len(calls) == 1
    assert calls[0]["page_num"] == 1
    assert calls[0]["total_pages"] == 2
    assert calls[0]["image_bytes"].startswith(b"\x89PNG")
    image = fitz.Pixmap(calls[0]["image_bytes"])
    assert image.width < 200 * 160 / 72
    assert image.height < 100 * 160 / 72
    element = updated.elements[0]
    assert element.id == "unknown"
    assert element.type == ("formula" if kind == "formula" else "picture")
    assert updated.obligations[0].status == "satisfied"
    assert len(updated.artifacts) == 2
    for artifact in updated.artifacts:
        assert artifact.sha256 == hashlib.sha256(Path(artifact.path).read_bytes()).hexdigest()
    evidence = json.loads(Path(updated.artifacts[1].path).read_text())
    assert evidence["source_sha256"] == manifest.source.sha256
    assert evidence["crop_sha256"] == updated.artifacts[0].sha256
    assert evidence["bbox"] == [10, 20, 90, 70]
    assert evidence["result"]["kind"] == kind
    ProcessingManifest.model_validate(updated.model_dump())
    payload = pddl.build_pddl_structured_payload(
        file_path=Path(manifest.source.path), manifest=updated, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    assert ("x^2" if kind == "formula" else "A map") in payload["text"]


@pytest.mark.parametrize("crop", [True, "missing.png", {"path": "missing.png"}])
def test_provider_crop_metadata_never_bypasses_inspection(inspection, crop):
    manifest, calls, _ = inspection
    manifest.elements[0].metadata["region_crop"] = crop
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert result.success
    assert len(calls) == 1
    assert Path(manifest.elements[0].metadata["region_crop"]).is_file()


@pytest.mark.parametrize("failure", ["missing-source", "changed-source", "target-type", "page", "page-index", "ambiguous-page", "outside", "zero", "nan", "origin"])
def test_invalid_source_or_region_fails_without_model_call(inspection, failure):
    manifest, calls, _ = inspection
    element = manifest.elements[0]
    if failure == "missing-source":
        manifest.source.path += ".missing"
    elif failure == "changed-source":
        manifest.source.sha256 = "a" * 64
    elif failure == "target-type":
        element.type = "table"
    elif failure == "page":
        element.provenance[0].page_number = 10
        element.page_number = 10
    elif failure == "page-index":
        manifest.pages[0].element_ids = []
        manifest.pages[1].element_ids = [element.id]
    elif failure == "ambiguous-page":
        element.page_number = None
        element.provenance = []
    else:
        bbox = element.provenance[0].bbox
        if failure == "outside":
            bbox.left, bbox.right = 300, 400
        elif failure == "zero":
            bbox.right = bbox.left
        elif failure == "nan":
            bbox.top = float("nan")
        elif failure == "origin":
            bbox.coord_origin = "UNKNOWN"
    before = manifest.model_dump_json()
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert not result.success
    assert not result.validated
    assert not calls
    assert manifest.model_dump_json() == before


@pytest.mark.parametrize("response", [None, "unstructured text", VisionOutput.model_construct(
    kind="description", description="   ", language="en", confidence=0.5,
)])
def test_failed_or_invalid_model_result_does_not_certify_inspection(inspection, response):
    manifest, calls, vision = inspection
    vision.response = response
    before = manifest.model_dump()
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert not result.success
    assert not result.artifacts
    assert calls
    assert manifest.model_dump() == before


def test_bottom_left_coordinates_render_same_region(inspection):
    manifest, _, _ = inspection
    source = Path(manifest.source.path)
    element = manifest.elements[0]
    top_left, _, _ = pddl._render_inspection_region(source, element)
    bbox = element.provenance[0].bbox
    bbox.top, bbox.bottom, bbox.coord_origin = 80, 30, "BOTTOMLEFT"
    bottom_left, _, rectangle = pddl._render_inspection_region(source, element)
    assert top_left == bottom_left
    assert rectangle == [10, 20, 90, 70]


def test_page_without_bbox_can_be_inspected_as_full_page(inspection):
    manifest, calls, _ = inspection
    manifest.elements[0].provenance = []
    assert pddl._handle_pymupdf_region_method(manifest, "o-1").success
    image = fitz.Pixmap(calls[0]["image_bytes"])
    assert image.width >= 200 * 160 / 72


def test_all_targets_must_validate_before_mutating_manifest(inspection):
    manifest, calls, _ = inspection
    second = manifest.elements[0].model_copy(deep=True)
    second.id = "invalid-second"
    second.provenance[0].page_number = 10
    second.page_number = 10
    manifest.elements.append(second)
    manifest.obligations[0].target_ids.append(second.id)
    original = manifest.model_dump()
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert not result.success
    assert not result.artifacts
    assert len(calls) == 1
    assert manifest.model_dump() == original


def test_artifact_failure_cannot_certify_or_mutate_inspection(inspection, monkeypatch):
    manifest, calls, _ = inspection
    original = manifest.model_dump()

    def fail(*args):
        raise OSError("Simulated disk failure")

    monkeypatch.setattr(pddl, "_save_region_artifact", fail)
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert not result.success
    assert not result.artifacts
    assert calls
    assert manifest.model_dump() == original


def test_a_render_over_the_pixel_limit_fails_the_method(inspection, fake_toolbox_render):
    manifest, calls, _ = inspection
    source = Path(manifest.source.path).with_name("large.pdf")
    with fitz.open() as document:
        document.new_page(width=10000, height=10000)
        document.save(source)
    manifest.source.path = str(source)
    manifest.source.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest.elements[0].provenance = []
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert not result.success
    # The core has no pixel guard of its own: the Toolbox refuses (HTTP 400)
    # and the refusal reaches the method as a capability error.
    assert len(fake_toolbox_render.requests) == 1
    assert "ToolboxCapabilityError" in result.message
    assert not calls


def test_an_element_without_a_page_is_inspected_only_in_a_one_page_document(inspection):
    manifest, calls, _ = inspection
    manifest.elements[0].provenance = []
    manifest.elements[0].page_number = None
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert not result.success
    assert "Region page is missing or out of range" in result.message
    assert not calls


def test_a_page_beyond_the_document_is_refused_by_the_toolbox(inspection, fake_toolbox_render):
    manifest, calls, _ = inspection
    manifest.elements[0].provenance[0].page_number = 3
    manifest.elements[0].page_number = 3
    result = pddl._handle_pymupdf_region_method(manifest, "o-1")
    assert not result.success
    assert "out of range" in result.message
    assert fake_toolbox_render.requests[0]["parameters"]["page_number"] == 3
    assert not calls


@pytest.mark.parametrize("same_document", [True, False])
def test_the_stored_source_is_referenced_only_when_it_is_this_document(
    inspection, fake_toolbox_render, same_document
):
    manifest, _, _ = inspection
    source = Path(manifest.source.path)
    digest = manifest.source.sha256 if same_document else "0" * 64
    stored = f"sha256:{digest}"
    fake_toolbox_render.sources[stored] = (source.read_bytes(), "application/pdf")
    manifest.extractor.configuration["artifact_id"] = stored

    assert pddl._handle_pymupdf_region_method(manifest, "o-1").success

    [request] = fake_toolbox_render.requests
    assert request["artifact_id"] == (stored if same_document else None)


@pytest.mark.asyncio
async def test_complete_orchestration_uses_region_method_and_requested_mode(inspection, monkeypatch, tmp_path):
    manifest, calls, _ = inspection
    paragraph = _element("paragraph", "paragraph", text="Ordinary readable document content", reading_order=2)
    manifest.elements.append(paragraph)
    manifest.summary.element_count = 2
    manifest.summary.element_types = {"unknown": 1, "paragraph": 1}
    manifest.pages[0].element_ids.append(paragraph.id)
    orchestrator = _orchestrator()
    orchestrator.information_structural = SimpleNamespace(process=lambda *args, **kwargs: manifest)

    async def no_media(*args):
        return None

    monkeypatch.setattr(pddl, "inspect_source_media", no_media)
    result = await orchestrator.executar(
        Path(manifest.source.path), tmp_path, mode="baixo", structured_output=True,
    )
    assert result["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert "A map" in result["text"]
    assert len(calls) == 1
    assert calls[0]["mode"] == "baixo"


def _pixels(png: bytes) -> tuple[int, int, bytes]:
    """Size and samples; the PNG metadata (e.g. resolution) may differ."""
    pixmap = fitz.Pixmap(png)
    return pixmap.width, pixmap.height, pixmap.samples


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("origin", ["TOPLEFT", "BOTTOMLEFT"])
def test_rotated_picture_provenance_renders_only_source_region(
    tmp_path, rotation, origin, fake_toolbox_render
):
    source = tmp_path / "rotated.pdf"
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    image.clear_with(0)
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        page.insert_image(fitz.Rect(120, 20, 190, 80), stream=image.tobytes("png"), keep_proportion=False)
        page.insert_text((120, 95), "TARGET", fontsize=10)
        page.set_rotation(rotation)
        pdf.save(source)
    with fitz.open(source) as pdf:
        page = pdf[0]
        # Provenance is declared in the displayed (rotated) coordinate space.
        expected = page.get_image_rects(page.get_images()[0][0])[0] * page.rotation_matrix
        expected_png = page.get_pixmap(clip=expected, dpi=160).tobytes("png")
        height = page.rect.height
    element = _element("picture", "unknown")
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=expected.x0, right=expected.x1,
        top=expected.y0 if origin == "TOPLEFT" else height-expected.y0,
        bottom=expected.y1 if origin == "TOPLEFT" else height-expected.y1,
        coord_origin=origin,
    ))]
    rendered, number, rectangle = pddl._render_inspection_region(source, element)
    assert number == 1
    assert rectangle == pytest.approx(list(expected))
    assert _pixels(rendered) == _pixels(expected_png)
    enriched, number = pddl._extract_picture_bytes(source, element, 1)
    assert _pixels(enriched) == _pixels(expected_png)
    assert max(fitz.Pixmap(rendered).samples) == 0  # black picture, no white page margin


def _one_page_pdf(path: Path) -> Path:
    with fitz.open() as pdf:
        pdf.new_page(width=200, height=100)
        pdf.save(path)
    return path


def _picture(left, top, right, bottom):
    element = _element("picture", "picture")
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=left, top=top, right=right, bottom=bottom, coord_origin="TOPLEFT",
    ))]
    return element


@pytest.mark.parametrize(
    "box",
    [
        (300, 200, 400, 300),  # outside the page: refused by the Toolbox
        (10, 10, 12, 60),  # a sliver
    ],
)
def test_a_picture_box_that_is_not_a_picture_falls_back_to_the_page(
    tmp_path, fake_toolbox_render, box
):
    source = _one_page_pdf(tmp_path / "doc.pdf")

    image, number = pddl._extract_picture_bytes(source, _picture(*box), 1)

    assert number == 1
    assert fitz.Pixmap(image).width >= 200 * 160 / 72  # the whole page
    first, page = fake_toolbox_render.parameters
    assert "clip" in first and "clip" not in page


def test_a_non_finite_picture_box_renders_the_page_once(tmp_path, fake_toolbox_render):
    source = _one_page_pdf(tmp_path / "doc.pdf")

    image, _ = pddl._extract_picture_bytes(source, _picture(10, float("nan"), 90, 60), 1)

    assert image is not None
    [parameters] = fake_toolbox_render.parameters
    assert "clip" not in parameters


def test_an_unavailable_toolbox_is_not_retried_as_a_page(tmp_path, monkeypatch):
    from acessilia_sdk.toolbox import ToolboxProviderUnavailable

    attempts = []

    def unavailable(*args, **kwargs):
        attempts.append(kwargs.get("clip"))
        raise ToolboxProviderUnavailable("down")

    monkeypatch.setattr(pddl, "_toolbox_render", unavailable)
    source = _one_page_pdf(tmp_path / "doc.pdf")

    assert pddl._extract_picture_bytes(source, _picture(10, 10, 90, 60), 1) == (None, 1)
    assert attempts == [(10.0, 10.0, 90.0, 60.0)]
