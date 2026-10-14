"""Fused text must reach the output without corrupting references or artifacts."""

import hashlib
from pathlib import Path

import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.config.settings import settings
from backend.core.manifest.models import PageDescriptor, ProcessingManifest
from tests.test_pddl_actionability import _element, _manifest, _obligation, _orchestrator


def manifest():
    return _manifest(
        [_element("text", "paragraph", text="Original incomplete content")],
        [_obligation("fuse-providers", ["text"], ["dual-provider-fusion"])],
    )


def payload(text="Recovered content", page=1):
    return {"status": "succeeded", "provider": "docling+mineru",
            "document": {"elements": [{"type": "paragraph", "text": text, "page_number": page}]}}


def test_fusion_output_contains_recovered_text_and_valid_references(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(pddl, "_run_extract_fused", lambda path: payload())
    source = manifest()
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(source)
    updated, report = orchestrator.executor.execute(plan, source, dry_run=False)
    assert report.status == "completed"
    ProcessingManifest.model_validate(updated.model_dump())
    result = pddl.build_pddl_structured_payload(
        file_path=tmp_path / "doc.pdf", manifest=updated, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    assert "Recovered content" in result["text"]
    assert "Original incomplete" not in result["text"]
    assert updated.elements[0].id == "text"
    assert source.elements[0].text == "Original incomplete content"
    artifact = updated.artifacts[0]
    assert artifact.sha256 == hashlib.sha256(Path(artifact.path).read_bytes()).hexdigest()


def test_artifacts_are_isolated_across_documents_and_payloads(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    first, second = manifest(), manifest()
    second.manifest_id = "manifest-second"
    second.source.document_id = "document-second"
    monkeypatch.setattr(pddl, "_run_extract_fused", lambda path: payload(str(path)))
    one = pddl._handle_dual_provider_fusion_method(first, "o-1").artifacts[0]
    original = Path(one.path).read_bytes()
    two = pddl._handle_dual_provider_fusion_method(second, "o-1").artifacts[0]
    assert one.path != two.path
    assert one.id != two.id
    assert Path(one.path).read_bytes() == original
    monkeypatch.setattr(pddl, "_run_extract_fused", lambda path: payload("Different revision"))
    three = pddl._handle_dual_provider_fusion_method(first, "o-1").artifacts[0]
    assert three.path != one.path
    assert Path(one.path).read_bytes() == original


@pytest.mark.parametrize("invalid", [
    {"elements": []}, {"elements": [{"type": "paragraph", "text": ""}]},
    {"elements": [{"type": "paragraph", "text": "x", "page_number": 0}]},
    {"elements": [{"type": "table", "text": "table"}]},
])
def test_invalid_fusion_does_not_mutate_or_certify_manifest(monkeypatch, tmp_path, invalid):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    source = manifest()
    original = source.model_dump()
    monkeypatch.setattr(pddl, "_run_extract_fused", lambda path: {
        "status": "succeeded", "provider": "docling+mineru", "document": invalid,
    })
    result = pddl._handle_dual_provider_fusion_method(source, "o-1")
    assert not result.success
    assert source.model_dump() == original
    assert not result.artifacts


def test_text_fusion_does_not_flatten_structured_manifest(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    source = manifest()
    source.elements[0].type = "table"
    original = source.model_dump()
    monkeypatch.setattr(pddl, "_run_extract_fused", lambda path: payload())
    result = pddl._handle_dual_provider_fusion_method(source, "o-1")
    assert not result.success
    assert source.model_dump() == original


def test_recovered_pages_and_extra_blocks_reach_output(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    source = manifest()
    source.elements[0].page_number = 1
    other = _element("second", "paragraph", text="Old page two", reading_order=2)
    other.page_number = 2
    source.elements.append(other)
    source.obligations[0].target_ids.append("second")
    source.pages.append(PageDescriptor(page_number=2, element_ids=["second"]))
    fused = payload()
    fused["document"]["elements"].extend([
        {"type": "paragraph", "text": "Additional recovered block", "page_number": 1},
        {"type": "paragraph", "text": "Recovered page two", "page_number": 2},
    ])
    monkeypatch.setattr(pddl, "_run_extract_fused", lambda path: fused)
    assert pddl._handle_dual_provider_fusion_method(source, "o-1").success
    ProcessingManifest.model_validate(source.model_dump())
    assert len(source.elements) == 3
    assert [element.reading_order for element in source.elements] == [1, 2, 3]
    pages = pddl._manifest_pages_to_payload(source)
    assert [page["page_number"] for page in pages] == [1, 2]
    assert "Additional recovered block" in pages[0]["text"]
    assert "Recovered page two" in pages[1]["text"]


@pytest.mark.asyncio
async def test_fusion_preserves_processing_manifest_page_numbers(monkeypatch):
    from backend.pipeline.fusion import extract_fused

    class Client:
        def __init__(self, provider):
            self.provider = provider

        async def extract_structure(self, *args, **kwargs):
            return {"status": "succeeded", "provider": self.provider, "document": {
                "elements": [
                    {"type": "paragraph", "text": "Page one content", "page_number": 1},
                    {"type": "paragraph", "text": "Page two content", "page_number": 2},
                ]
            }}

    monkeypatch.setattr("backend.pipeline.fusion.ToolboxClient", Client)
    result = await extract_fused("doc.pdf", primary_provider="docling", secondary_provider="mineru")
    elements = result["document"]["elements"]
    assert {element["page_number"] for element in elements} == {1, 2}
    assert all("one" in element["text"] for element in elements if element["page_number"] == 1)
    assert all("two" in element["text"] for element in elements if element["page_number"] == 2)
    assert [element["reading_order"] for element in elements] == list(range(1, len(elements) + 1))
