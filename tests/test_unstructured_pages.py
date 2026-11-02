"""Pages the extractor returns without structure are planned, not dropped.

Each such page gets a placeholder element, a ``page-without-structure``
observation and the critical ``inspect-unstructured-page`` obligation. Its
``vision-page-inspection`` method renders the page on the Toolbox and asks the
vision model: a page with content becomes a described picture, a blank page is
accepted and left out of the document, and any failure fails the method.
"""

from __future__ import annotations

import base64
import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest
import respx

from backend.agents import pddl_orchestrator as pddl
from backend.agents.output_schemas import PageInspectionOutput
from backend.config.settings import settings
from backend.core.manifest.builder import (
    UNSTRUCTURED_PAGE_OBLIGATION_KIND,
    UNSTRUCTURED_PAGE_OBSERVATION_KIND,
    append_unstructured_page_needs,
    build_processing_manifest,
    is_unstructured_page_placeholder,
)
from backend.core.manifest.models import PageDescriptor
from backend.core.manifest.toolbox_extractor import ToolboxExtraction
from backend.core.planning import toolbox_gate
from tests.pddl_support import build_element, build_manifest
from tests.test_toolbox_manifest_extractor import SAMPLE_TOOLBOX_RESPONSE

NOW = datetime(2026, 10, 19, tzinfo=timezone.utc)
PNG = b"\x89PNG\r\n\x1a\nfake-page"


def _png_page() -> bytes:
    import fitz

    with fitz.open() as doc:
        return doc.new_page(width=200, height=100).get_pixmap(dpi=72).tobytes("png")


PNG_PAGE = _png_page()


def _extraction_with_empty_page() -> ToolboxExtraction:
    payload = deepcopy(SAMPLE_TOOLBOX_RESPONSE)
    payload["document"]["pages"].append(
        {"page_number": 2, "width": 595, "height": 842, "element_ids": []}
    )
    payload["document"]["summary"]["page_count"] = 2
    return ToolboxExtraction(
        document=payload,
        started_at=NOW,
        completed_at=NOW,
        duration_ms=1,
        version="test",
        configuration={"toolbox_provider": "docling"},
    )


@pytest.fixture
def source_pdf(tmp_path) -> Path:
    path = tmp_path / "doc.pdf"
    path.write_bytes(b"%PDF-1.4 two pages")
    return path


# ── Builder ─────────────────────────────────────────────────────────────


def test_builder_plans_every_page_without_elements(source_pdf):
    manifest = build_processing_manifest(source_pdf, _extraction_with_empty_page())

    page_two = next(page for page in manifest.pages if page.page_number == 2)
    [placeholder_id] = page_two.element_ids
    placeholder = next(e for e in manifest.elements if e.id == placeholder_id)
    assert is_unstructured_page_placeholder(placeholder)
    assert placeholder.type == "unknown" and placeholder.page_number == 2

    [observation] = [
        o for o in manifest.observations if o.kind == UNSTRUCTURED_PAGE_OBSERVATION_KIND
    ]
    assert observation.target_ids == [placeholder_id]
    assert observation.evidence == {"page_number": 2}

    [obligation] = [
        o for o in manifest.obligations if o.kind == UNSTRUCTURED_PAGE_OBLIGATION_KIND
    ]
    assert obligation.target_ids == [placeholder_id]
    assert obligation.admissible_methods == ["vision-page-inspection", "human-review"]
    # The placeholder is not also treated as an unknown region.
    assert not any(
        o.kind == "review-structure" and placeholder_id in o.target_ids
        for o in manifest.obligations
    )
    assert manifest.summary.obligation_count == len(manifest.obligations)
    # The page that has elements is untouched.
    page_one = next(page for page in manifest.pages if page.page_number == 1)
    assert not any(e.startswith("element-unstructured-page") for e in page_one.element_ids)


def test_planning_is_idempotent():
    manifest = build_manifest([build_element("el-1", "paragraph", text="x")], [])
    manifest.pages.append(PageDescriptor(page_number=2))

    append_unstructured_page_needs(manifest)
    append_unstructured_page_needs(manifest)

    assert [e.id for e in manifest.elements].count("element-unstructured-page-0002") == 1
    assert len(manifest.obligations) == 1


def test_a_page_whose_elements_point_at_it_by_page_number_is_not_empty():
    # Same rule as the payload builder, which falls back to page_number when a
    # page has no element_ids: the page's real content must not be replaced.
    manifest = build_manifest([build_element("el-1", "picture")], [])
    manifest.pages[0].element_ids = []

    append_unstructured_page_needs(manifest)

    assert manifest.obligations == []
    assert [e.id for e in manifest.elements] == ["el-1"]
    [page] = pddl._manifest_pages_to_payload(manifest)
    assert [block["type"] for block in page["blocks"]] == ["image"]


def test_the_obligation_kind_is_in_the_v23_catalog():
    from backend.core.manifest.builder import V23_OBLIGATION_BY_KIND
    from backend.core.planning.domain_bundle import V23_OBLIGATION_KINDS

    assert UNSTRUCTURED_PAGE_OBLIGATION_KIND in V23_OBLIGATION_KINDS
    assert V23_OBLIGATION_BY_KIND[UNSTRUCTURED_PAGE_OBLIGATION_KIND][1] == [
        "vision-page-inspection", "human-review",
    ]


def test_the_obligation_is_critical():
    assert UNSTRUCTURED_PAGE_OBLIGATION_KIND not in pddl.NON_CRITICAL_OBLIGATION_KINDS


def test_the_method_requires_pdf_render_on_the_toolbox():
    [requirement] = toolbox_gate.METHOD_TOOLBOX_REQUIREMENTS["vision-page-inspection"]()
    assert requirement.capability_id == "pdf.render"


def test_a_raster_input_also_requires_pdf_render():
    """pdf.render@2 renders raster inputs too, so images need it as well."""
    manifest = build_manifest([build_element("el-1", "paragraph", text="x")], [])
    manifest.pages.append(PageDescriptor(page_number=2))
    append_unstructured_page_needs(manifest)
    manifest.source.media_type = "image/png"

    assert "vision-page-inspection" in toolbox_gate.requested_methods(manifest)


# ── Handler ─────────────────────────────────────────────────────────────


def _planned_manifest(source: Path):
    manifest = build_manifest([build_element("el-1", "paragraph", text="Página 1")], [])
    manifest.source.path = str(source)
    manifest.source.sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest.pages.append(PageDescriptor(page_number=2))
    append_unstructured_page_needs(manifest)
    [obligation] = manifest.obligations
    return manifest, obligation.id, obligation.target_ids[0]


@pytest.fixture
def isolated_artifacts(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")


def _answer(monkeypatch, output=None, error=None):
    calls = []

    def inspect(image, number, total_pages, mode):
        calls.append((image, number, total_pages))
        if error:
            raise error
        return output

    monkeypatch.setattr(pddl, "_render_source_page", lambda *args: PNG)
    monkeypatch.setattr(pddl, "_inspect_page", inspect)
    return calls


def test_a_page_with_content_becomes_a_described_picture(
    monkeypatch, source_pdf, isolated_artifacts
):
    manifest, obligation_id, target = _planned_manifest(source_pdf)
    calls = _answer(
        monkeypatch,
        PageInspectionOutput(
            kind="content", description="Diagrama de um ciclo.", language="pt-BR",
            confidence=0.9,
        ),
    )

    result = pddl._handle_vision_page_inspection_method(manifest, obligation_id)

    assert result.success and result.validated, result.message
    assert calls == [(PNG, 2, 2)]
    element = next(e for e in manifest.elements if e.id == target)
    assert element.type == "picture"
    assert element.text == "Diagrama de um ciclo."
    assert element.metadata["vision_description_complete"] is True
    assert element.metadata["src"] == "data:image/png;base64," + base64.b64encode(PNG).decode()
    assert {a.kind for a in result.artifacts} == {"page-render", "page-inspection"}
    page_two = next(p for p in pddl._manifest_pages_to_payload(manifest) if p["page_number"] == 2)
    assert [block["type"] for block in page_two["blocks"]] == ["image"]


def test_a_blank_page_is_accepted_and_left_out_of_the_document(
    monkeypatch, source_pdf, isolated_artifacts
):
    manifest, obligation_id, target = _planned_manifest(source_pdf)
    _answer(
        monkeypatch,
        PageInspectionOutput(kind="blank", language="und", confidence=0.95),
    )

    result = pddl._handle_vision_page_inspection_method(manifest, obligation_id)

    assert result.success and result.validated, result.message
    assert "1 blank" in result.message
    element = next(e for e in manifest.elements if e.id == target)
    assert element.metadata["blank_page"] is True
    pages = {p["page_number"]: p for p in pddl._manifest_pages_to_payload(manifest)}
    assert pages[2]["blocks"] == [] and pages[2]["text"] == ""
    assert pages[1]["blocks"], "the page with content is kept"


def test_an_uninspected_placeholder_adds_nothing_to_the_document(source_pdf):
    # Dry-run returns the manifest unchanged, so the placeholder is still there;
    # its raw label must not reach the document as a paragraph.
    manifest, _, _ = _planned_manifest(source_pdf)

    pages = {p["page_number"]: p for p in pddl._manifest_pages_to_payload(manifest)}

    assert pages[2]["blocks"] == [] and pages[2]["text"] == ""
    manifest.pages = []
    texts = [b.get("text") for p in pddl._manifest_pages_to_payload(manifest) for b in p["blocks"]]
    assert "unstructured-page" not in texts


@pytest.mark.parametrize(
    "error",
    [RuntimeError("vision model unavailable"), ValueError("invalid structured output")],
)
def test_any_failure_fails_the_method_and_changes_nothing(
    monkeypatch, source_pdf, isolated_artifacts, error
):
    manifest, obligation_id, target = _planned_manifest(source_pdf)
    before = manifest.model_dump()
    _answer(monkeypatch, error=error)

    result = pddl._handle_vision_page_inspection_method(manifest, obligation_id)

    assert not result.success and not result.validated
    assert str(error) in result.message
    assert manifest.model_dump() == before


def test_a_changed_source_is_refused(monkeypatch, source_pdf, isolated_artifacts):
    manifest, obligation_id, _ = _planned_manifest(source_pdf)
    source_pdf.write_bytes(b"%PDF-1.4 changed")
    _answer(monkeypatch, PageInspectionOutput(kind="blank", language="und", confidence=1))

    result = pddl._handle_vision_page_inspection_method(manifest, obligation_id)

    assert not result.success and "differs" in result.message


# ── Vision agent contract ───────────────────────────────────────────────


def test_content_without_a_description_is_invalid():
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="description is required"):
        PageInspectionOutput(kind="content", language="pt-BR", confidence=0.9)
    assert PageInspectionOutput(kind="blank", language="und", confidence=1).description == ""


def test_inspect_page_asks_for_the_page_inspection_schema(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from agno.run.base import RunStatus

    from backend.agents import vision_agent
    from backend.agents.output_schemas import PAGE_INSPECTION_INSTRUCTION

    seen = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            seen["schema"] = kwargs["output_schema"]

        def run(self, input, images):
            seen["prompt"] = input
            seen["images"] = [image.content for image in images]
            return SimpleNamespace(
                status=RunStatus.completed,
                content={"kind": "blank", "language": "und", "confidence": 0.9},
            )

    monkeypatch.setattr(vision_agent, "Agent", FakeAgent)
    monkeypatch.setattr(vision_agent, "get_agno_model", lambda **_kwargs: None)

    output = asyncio.run(
        vision_agent.VisionAgent().inspect_page(image_bytes=PNG, page_num=2, total_pages=3)
    )

    assert seen["schema"] is PageInspectionOutput
    assert PAGE_INSPECTION_INSTRUCTION in seen["prompt"]
    assert seen["images"] == [PNG]
    assert isinstance(output, PageInspectionOutput) and output.kind == "blank"


def test_a_model_answer_of_content_without_description_is_refused(monkeypatch):
    import asyncio
    from types import SimpleNamespace

    from agno.run.base import RunStatus

    from backend.agents import vision_agent

    class FakeAgent:
        def __init__(self, **kwargs):
            pass

        def run(self, input, images):
            return SimpleNamespace(
                status=RunStatus.completed,
                content={"kind": "content", "language": "pt-BR", "confidence": 0.9},
            )

    monkeypatch.setattr(vision_agent, "Agent", FakeAgent)
    monkeypatch.setattr(vision_agent, "get_agno_model", lambda **_kwargs: None)

    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="description is required"):
        asyncio.run(
            vision_agent.VisionAgent().inspect_page(image_bytes=PNG, page_num=1, total_pages=1)
        )


# ── Rendering ───────────────────────────────────────────────────────────


def _real_pdf(path: Path, pages: int = 2) -> Path:
    import fitz

    with fitz.open() as pdf:
        for _ in range(pages):
            pdf.new_page(width=200, height=100)
        pdf.save(path)
    return path


def test_pdf_pages_are_rendered_by_the_toolbox(fake_toolbox_render, tmp_path):
    source = _real_pdf(tmp_path / "doc.pdf")

    image = pddl._render_source_page(source, "application/pdf", 2)

    assert image.startswith(b"\x89PNG")
    [request] = fake_toolbox_render.requests
    assert request["version"] == "2"
    assert request["parameters"] == {"page_number": 2, "dpi": settings.pdf_split_dpi}


def test_the_stored_source_is_referenced_instead_of_uploaded(fake_toolbox_render, tmp_path):
    source = _real_pdf(tmp_path / "doc.pdf")
    stored = "sha256:" + hashlib.sha256(source.read_bytes()).hexdigest()
    fake_toolbox_render.sources[stored] = (source.read_bytes(), "application/pdf")

    pddl._render_source_page(source, "application/pdf", 1, stored)

    [request] = fake_toolbox_render.requests
    assert request["artifact_id"] == stored


def test_a_source_the_toolbox_lost_is_sent_again(fake_toolbox_render, tmp_path):
    source = _real_pdf(tmp_path / "doc.pdf")

    image = pddl._render_source_page(source, "application/pdf", 1, "sha256:" + "0" * 64)

    assert image.startswith(b"\x89PNG")
    [request] = fake_toolbox_render.requests  # the 404 is not recorded as a render
    assert request["artifact_id"] is None and request["media_type"] == "application/pdf"


def test_a_raster_input_is_rendered_by_the_toolbox_as_its_single_page(
    fake_toolbox_render, tmp_path
):
    from backend.tools.toolbox_client import ToolboxCapabilityError

    image = tmp_path / "scan.png"
    image.write_bytes(PNG_PAGE)

    assert pddl._render_source_page(image, "image/png", 1).startswith(b"\x89PNG")
    assert fake_toolbox_render.requests[-1]["media_type"] == "image/png"
    with pytest.raises(ToolboxCapabilityError, match="out of range"):
        pddl._render_source_page(image, "image/png", 2)


@pytest.mark.parametrize("suffix, media_type", [(".tif", "image/tiff"), (".webp", "image/webp")])
def test_raster_formats_the_toolbox_does_not_render_are_refused_before_any_request(
    fake_toolbox_render, tmp_path, suffix, media_type
):
    # The pipeline accepts them, but pdf.render@2 opens PDF, PNG and JPEG only.
    image = tmp_path / f"scan{suffix}"
    image.write_bytes(b"raster")

    with pytest.raises(ValueError, match=f"not {media_type}"):
        pddl._render_source_page(image, media_type, 1)
    assert not fake_toolbox_render.requests


def test_a_source_sent_unlike_its_manifest_media_type_is_refused(
    fake_toolbox_render, tmp_path
):
    source = _real_pdf(tmp_path / "doc.pdf")

    with pytest.raises(ValueError, match="would be sent as application/pdf"):
        pddl._render_source_page(source, "image/png", 1)
    assert not fake_toolbox_render.requests


def test_a_render_without_an_image_is_a_contract_violation(monkeypatch, tmp_path):
    from backend.tools.toolbox_client import ToolboxContractViolation

    monkeypatch.setattr(settings, "toolbox_base_url", "http://toolbox.test")
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_retries", 0)
    source = _real_pdf(tmp_path / "doc.pdf")
    with respx.mock() as router:
        router.post("http://toolbox.test/v1/capabilities/pdf.render:execute").mock(
            return_value=httpx.Response(200, json={"status": "succeeded", "document": {}})
        )
        with pytest.raises(ToolboxContractViolation, match="no image artifact"):
            pddl._render_source_page(source, "application/pdf", 1)


# ── Coexistence with the pre-planning heuristics ────────────────────────


def test_the_heuristics_leave_the_placeholder_to_the_plan(source_pdf):
    manifest, _, target = _planned_manifest(source_pdf)
    placeholder = next(e for e in manifest.elements if e.id == target)
    obligations_before = len(manifest.obligations)

    assert not pddl._is_placeholder_visual_element(placeholder)
    pddl._inject_full_page_picture(
        manifest, {"is_image": True, "requires_visual_inspection": True}
    )

    assert not any(e.metadata.get("injected_picture") for e in manifest.elements)
    assert len(manifest.obligations) == obligations_before


# ── Planning and execution ──────────────────────────────────────────────


def _run(monkeypatch, tmp_path, manifest, *, max_replans=0):
    from types import SimpleNamespace

    from tests.pddl_support import build_orchestrator

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(settings, "toolbox_availability_gate", "off")
    monkeypatch.setattr(pddl, "inspect_source_media", noop)
    orchestrator = build_orchestrator(max_replans=max_replans)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    import asyncio

    return asyncio.run(
        orchestrator.executar(Path(manifest.source.path), tmp_path, structured_output=True)
    )


def test_the_plan_inspects_the_page_and_the_document_keeps_it(
    monkeypatch, source_pdf, isolated_artifacts, tmp_path
):
    manifest, _, _ = _planned_manifest(source_pdf)
    _answer(
        monkeypatch,
        PageInspectionOutput(
            kind="content", description="Foto de uma ponte.", language="pt-BR",
            confidence=0.8,
        ),
    )

    payload = _run(monkeypatch, tmp_path, manifest)

    pages = {page["page_number"]: page for page in payload["pages"]}
    assert [block["type"] for block in pages[2]["blocks"]] == ["image"]
    assert pages[2]["blocks"][0]["alt_text"] == "Foto de uma ponte."


def test_a_failed_inspection_fails_the_job(monkeypatch, source_pdf, isolated_artifacts, tmp_path):
    manifest, _, _ = _planned_manifest(source_pdf)
    _answer(monkeypatch, error=RuntimeError("vision model unavailable"))

    with pytest.raises(RuntimeError, match=r"inspect-unstructured-page \("):
        _run(monkeypatch, tmp_path, manifest, max_replans=1)
