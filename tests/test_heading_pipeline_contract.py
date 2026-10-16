"""Heading repair and validation must agree on canonical section headings."""

import pytest

from backend.agents.pddl_orchestrator import build_pddl_structured_payload
from backend.core.manifest.builder import _derive_processing_needs
from backend.pipeline.canonical_builder import build_canonical_document
from docstruct.export.html import document_to_html
from docstruct.validation import (
    validate_canonical_document, MSG_HEADING_LEVELS_SKIPPED,
    MSG_MISSING_FIRST_H1, MSG_MULTIPLE_H1,
)
from tests.test_pddl_actionability import _element, _manifest, _orchestrator


@pytest.mark.parametrize("levels", [[1, 4, 5], [1, 3, 4], [1, 4, 5, 6]])
@pytest.mark.parametrize("reverse", [False, True])
def test_heading_repairs_do_not_leave_new_gaps(levels, reverse, tmp_path):
    elements = [_element(f"heading-{i}", "heading", text=f"Heading {i}", reading_order=i+1) for i in range(len(levels))]
    for element, level in zip(elements, levels):
        element.hierarchy_level = level
    if reverse:
        elements.reverse()
    observations, obligations = _derive_processing_needs(elements)
    manifest = _manifest(elements, obligations)
    manifest.observations = observations
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status == "completed"
    ordered = sorted(updated.elements, key=lambda element: element.reading_order)
    assert [element.hierarchy_level for element in ordered] == list(range(1, len(levels)+1))
    assert not _derive_processing_needs(updated.elements)[1]
    payload = build_pddl_structured_payload(
        file_path=tmp_path / "headings.pdf", manifest=updated, plan=plan,
        planner_backend="internal", execution_report=report, comparison=None,
    )
    assert not validate_canonical_document(build_canonical_document(payload))


def test_title_is_heading_predecessor_when_deriving_repairs():
    title = _element("title", "title", text="Title")
    heading = _element("heading", "heading", text="Section", reading_order=2)
    heading.hierarchy_level = 4
    _, obligations = _derive_processing_needs([title, heading])
    assert len(obligations) == 1
    assert obligations[0].target_ids == ["heading"]


@pytest.mark.parametrize("levels,finding", [
    ([1, 4], MSG_HEADING_LEVELS_SKIPPED),
    ([2, 3], MSG_MISSING_FIRST_H1), ([1, 1], MSG_MULTIPLE_H1),
])
def test_section_heading_levels_are_validated(levels, finding):
    canonical = build_canonical_document({"pages": [{"blocks": [
        {"id": f"h{i}", "type": "heading", "level": level, "text": f"Heading {i}"}
        for i, level in enumerate(levels)
    ]}]})
    findings = validate_canonical_document(canonical)
    assert any(message == finding for message, _ in findings)
    rendered = document_to_html(canonical, profile="html")
    assert all(f"<h{level}" in rendered for level in levels)


def test_legacy_explicit_heading_is_not_counted_twice():
    document = build_canonical_document("# Heading\n\nBody content.")
    section = document["sections"][0]
    section["blocks"].insert(0, {"id": "legacy-title", "type": "heading", "level": 1, "text": section["title"]})
    assert not validate_canonical_document(document)
