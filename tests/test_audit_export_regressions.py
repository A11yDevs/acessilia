"""Regression coverage for planning and portable accessible exports."""
import base64
import re
from pathlib import Path

import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.core.manifest.builder import _derive_processing_needs
from backend.export.pandoc_exporter import export_accessible_document
from backend.pipeline.canonical_builder import build_canonical_document
from docstruct.export.html import document_to_html
from docstruct.validation import (
    audit_canonical_document, validate_canonical_document,
    MSG_MISSING_FIRST_H1, MSG_MULTIPLE_H1, MSG_IMAGE_MISSING_ALT,
)
from tests.test_pddl_actionability import _element, _manifest, _orchestrator
from tests.test_region_inspection import inspection as inspection


@pytest.mark.parametrize("levels, finding", [([2, 3], MSG_MISSING_FIRST_H1), ([1, 1], MSG_MULTIPLE_H1), ([0, 2], MSG_MISSING_FIRST_H1), ([1, 7], MSG_MISSING_FIRST_H1)])
def test_complete_plan_repairs_invalid_heading_sequence(tmp_path, levels, finding):
    elements = [_element(f"h{i}", "heading", text=f"Heading {i}", reading_order=i+1) for i in range(len(levels))]
    for element, level in zip(elements, levels):
        element.hierarchy_level = level
    observations, obligations = _derive_processing_needs(elements)
    assert obligations
    manifest = _manifest(elements, obligations)
    manifest.observations = observations
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status == "completed"
    payload = pddl.build_pddl_structured_payload(
        file_path=tmp_path / "headings.pdf", manifest=updated, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    canonical = build_canonical_document(payload)
    assert not validate_canonical_document(canonical)
    export_accessible_document(canonical, tmp_path / "result.txt", format_name="txt")
    assert (tmp_path / "result.txt").is_file()


def test_region_png_is_embedded_in_exported_html(inspection, tmp_path):
    manifest, _, _ = inspection
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status == "completed"
    assert Path(updated.elements[0].metadata["region_crop"]).is_file()
    payload = pddl.build_pddl_structured_payload(
        file_path=Path(manifest.source.path), manifest=updated, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    canonical = build_canonical_document(payload)
    html = document_to_html(canonical, profile="html")
    encoded = re.search(r'src="data:image/png;base64,([^" ]+)"', html).group(1)
    assert base64.b64decode(encoded, validate=True) == Path(updated.elements[0].metadata["region_crop"]).read_bytes()
    assert 'alt="A map"' in html


def test_accessibility_audit_accepts_existing_alternative_text():
    canonical = build_canonical_document({"pages": [{"blocks": [
        {"id": "picture", "type": "image", "alt_text": "A black square", "metadata": {}},
        {"id": "body", "type": "paragraph", "text": "Body content"},
    ]}]})
    assert 'alt="A black square"' in document_to_html(canonical, profile="html")
    warnings = audit_canonical_document(canonical)["WARNING"]
    assert not any(message == MSG_IMAGE_MISSING_ALT for message, _ in warnings)


@pytest.mark.parametrize("types", [("title", "title"), ("heading", "title"), ("title", "heading")])
def test_duplicate_top_level_titles_are_repaired(types, tmp_path):
    elements = [_element(f"h{i}", kind, text=f"Heading {i}", reading_order=i+1)
                for i, kind in enumerate(types)]
    for element in elements:
        element.hierarchy_level = 1
    observations, obligations = _derive_processing_needs(elements)
    assert obligations
    manifest = _manifest(elements, obligations)
    manifest.observations = observations
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status == "completed"
    assert not _derive_processing_needs(updated.elements)[1]
    payload = pddl.build_pddl_structured_payload(
        file_path=tmp_path / "headings.pdf", manifest=updated, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    assert not validate_canonical_document(build_canonical_document(payload))


@pytest.mark.parametrize("alt", ["", "   "])
def test_audit_still_warns_when_rendered_alternative_is_empty(alt):
    canonical = build_canonical_document({"pages": [{"blocks": [
        {"id": "picture", "type": "image", "alt_text": alt,
         "metadata": {"alt": "Unused legacy text"}},
        {"id": "body", "type": "paragraph", "text": "Body content"},
    ]}]})
    assert any(message == MSG_IMAGE_MISSING_ALT
               for message, _ in audit_canonical_document(canonical)["WARNING"])
