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


def test_the_obligation_is_critical():
    assert UNSTRUCTURED_PAGE_OBLIGATION_KIND not in pddl.NON_CRITICAL_OBLIGATION_KINDS


def test_the_method_requires_pdf_render_on_the_toolbox():
    [requirement] = toolbox_gate.METHOD_TOOLBOX_REQUIREMENTS["vision-page-inspection"]()
    assert requirement.capability_id == "pdf.render"


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

    monkeypatch.setattr(pddl, "_render_source_page", lambda source, media, number: PNG)
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


# ── Rendering ───────────────────────────────────────────────────────────


@pytest.fixture
def toolbox(monkeypatch):
    monkeypatch.setattr(settings, "toolbox_base_url", "http://toolbox.test")
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "")
    monkeypatch.setattr(settings, "toolbox_retries", 0)


def test_pdf_pages_are_rendered_by_the_toolbox(toolbox, source_pdf):
    with respx.mock() as router:
        route = router.post(
            "http://toolbox.test/v1/capabilities/pdf.render:execute"
        ).mock(
            return_value=httpx.Response(
                200,
                json={
                    "status": "succeeded",
                    "document": {"image_bytes_base64": base64.b64encode(PNG).decode()},
                },
            )
        )
        assert pddl._render_source_page(source_pdf, "application/pdf", 2) == PNG
    assert b'{"page_number": 2' in route.calls.last.request.content


def test_a_render_without_an_image_is_a_contract_violation(toolbox, source_pdf):
    from backend.tools.toolbox_client import ToolboxContractViolation

    with respx.mock() as router:
        router.post("http://toolbox.test/v1/capabilities/pdf.render:execute").mock(
            return_value=httpx.Response(200, json={"status": "succeeded", "document": {}})
        )
        with pytest.raises(ToolboxContractViolation):
            pddl._render_source_page(source_pdf, "application/pdf", 1)


def test_a_raster_input_is_its_own_single_page(tmp_path):
    image = tmp_path / "scan.png"
    image.write_bytes(PNG)

    assert pddl._render_source_page(image, "image/png", 1) == PNG
    with pytest.raises(ValueError, match="one page"):
        pddl._render_source_page(image, "image/png", 2)


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
    manifest, obligation_id, _ = _planned_manifest(source_pdf)
    _answer(monkeypatch, error=RuntimeError("vision model unavailable"))

    with pytest.raises(RuntimeError, match=obligation_id):
        _run(monkeypatch, tmp_path, manifest, max_replans=1)
