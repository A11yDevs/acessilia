"""Unavailable adapters and unsuccessful simulations must remain explicit."""

import pytest

from backend.core.planning.models import NominalPlan, PlanStep
from tests.pddl_support import (
    build_element as _element,
    build_manifest as _manifest,
    build_obligation as _obligation,
    build_orchestrator as _orchestrator,
)


@pytest.mark.parametrize("kind,method", [
    ("extract-line-numbers", "line-number-extractor"),
    ("chunk-verse", "verse-chunker"),
    ("join-tail-blocks", "tailjoin"),
    ("join-tail-blocks", "tailjoin-positioned"),
])
def test_text_adapter_runs_without_signature_errors(kind, method):
    manifest = _manifest(
        [_element("text", "paragraph", text="First line 5\nSecond line 10\nThird line 15")],
        [_obligation(kind, ["text"], [method, "human-review"])],
    )
    manifest.obligations[0].method_costs = {method: 1, "human-review": 100}
    orchestrator = _orchestrator()
    assert method not in orchestrator._unavailable_methods(manifest)
    plan, _ = orchestrator._build_plan(manifest)
    assert method in {step.method for step in plan.steps}
    _, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert all("TypeError" not in (step.message or "") for step in report.steps)


def test_failed_dry_run_reports_failure_and_preserves_manifest():
    manifest = _manifest(
        [_element("image", "picture")],
        [_obligation("describe-image", ["image"], ["vision-description"])],
    )
    original = manifest.model_dump()
    orchestrator = _orchestrator()
    plan, _ = orchestrator._build_plan(manifest)
    data = plan.model_dump()
    data.update(steps=[PlanStep(index=0, action="complete-job")], expected_total_cost=0)
    invalid_plan = NominalPlan.model_validate(data)
    returned, report = orchestrator.executor.execute(invalid_plan, manifest, dry_run=True)
    assert report.steps[0].status == "failed"
    assert report.failed_step_index == 0
    assert report.status == "failed"
    assert report.mode == "dry-run"
    assert returned.model_dump() == original == manifest.model_dump()


@pytest.mark.parametrize("crop", [True, "missing-crop.png", {"path": "missing.png"}])
def test_crop_metadata_cannot_certify_region_inspection(crop):
    manifest = _manifest(
        [_element("unknown", "unknown", metadata={"region_crop": crop})],
        [_obligation("review-structure", ["unknown"], ["pymupdf-region", "human-review"])],
    )
    manifest.obligations[0].method_costs = {"pymupdf-region": 1, "human-review": 100}
    orchestrator = _orchestrator()
    assert orchestrator._unavailable_methods(manifest) == []
    plan, _ = orchestrator._build_plan(manifest)
    assert "pymupdf-region" in {step.method for step in plan.steps}
    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)
    assert report.status == "replan-required"
    assert updated.obligations[0].status == "pending"
    assert updated.obligations[0].attempts[0].status == "failed"
    assert not updated.artifacts


def test_existing_crop_file_is_not_inspection_evidence(tmp_path):
    crop = tmp_path / "crop.png"
    crop.write_bytes(b"not even an image")
    manifest = _manifest(
        [_element("unknown", "unknown", metadata={"region_crop": str(crop)})],
        [_obligation("review-structure", ["unknown"], ["pymupdf-region", "human-review"])],
    )
    orchestrator = _orchestrator()
    assert orchestrator._unavailable_methods(manifest) == []
    assert not orchestrator.executor.registry.get("pymupdf-region")(manifest, "o-1").success
