"""A refinement that no automatic method satisfies must not sink the whole job.

Staging regression: with PDDL running live, `refine-reading-order` exhausted its
methods (XY-cut, skeleton, human review) and the executor stopped at that step,
so the independent heading repairs never ran and the job failed.
"""

from types import SimpleNamespace

import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.core.execution.models import MethodResult
from backend.core.manifest.builder import _derive_processing_needs
from backend.core.manifest.models import Obligation
from backend.tools.logger import logger
from tests.test_pddl_actionability import _element, _manifest, _orchestrator
from tests.test_pending_fixes import isolated_runtime as runtime_fixture

isolated_runtime = runtime_fixture


def _failing(_manifest, _obligation_id):
    return MethodResult(success=False, validated=False, message="falha controlada")


def _headings_and_order_manifest(
    extra: list[Obligation] | None = None, extra_elements=None
):
    """Three flat H1 headings, as the extractor reports them, plus a reading order
    obligation whose only automatic method fails."""
    elements = [
        _element(f"heading-{i}", "heading", text=f"Heading {i}", reading_order=i + 1)
        for i in range(3)
    ]
    _, obligations = _derive_processing_needs(elements)
    order = Obligation(
        id="o-order",
        kind="refine-reading-order",
        target_ids=[element.id for element in elements],
        admissible_methods=["xycut-order", "human-review"],
        method_costs={"xycut-order": 1, "human-review": 100},
        rationale="Ordem de leitura",
    )
    return _manifest(
        [*elements, *(extra_elements or [])], [order, *obligations, *(extra or [])]
    )


def _orchestrator_failing_order(max_replans: int):
    orchestrator = _orchestrator(max_replans=max_replans)
    orchestrator.executor.registry.register("xycut-order", _failing)
    return orchestrator


def test_failed_obligation_does_not_stop_independent_ones():
    manifest = _headings_and_order_manifest()
    orchestrator = _orchestrator_failing_order(max_replans=0)
    plan, _ = orchestrator._build_plan(manifest)

    updated, report = orchestrator.executor.execute(plan, manifest, dry_run=False)

    assert report.status == "replan-required"
    statuses = {item.id: item.status for item in updated.obligations}
    assert statuses.pop("o-order") == "pending"
    assert statuses and set(statuses.values()) == {"satisfied"}
    levels = [
        element.hierarchy_level
        for element in sorted(updated.elements, key=lambda item: item.reading_order)
    ]
    assert levels == [1, 2, 2]
    # The first failure is the one reported, not the complete-job that follows.
    failed = next(step for step in report.steps if step.status == "failed")
    assert report.failed_step_index == failed.index
    assert failed.obligation_id == "o-order"


def test_failed_step_cause_is_logged():
    manifest = _headings_and_order_manifest()
    orchestrator = _orchestrator_failing_order(max_replans=0)
    plan, _ = orchestrator._build_plan(manifest)
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        orchestrator.executor.execute(plan, manifest, dry_run=False)
    finally:
        logger.remove(sink)

    assert any(
        "o-order" in message and "xycut-order" in message and "falha controlada" in message
        for message in messages
    )


async def _run(orchestrator, manifest, monkeypatch, tmp_path):
    orchestrator.information_structural = SimpleNamespace(
        process=lambda *a, **k: manifest
    )

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(pddl, "inspect_source_media", noop)
    monkeypatch.setattr(pddl, "_enrich_picture_descriptions", noop)
    monkeypatch.setattr(pddl, "_enrich_table_structures", noop)
    return await orchestrator.executar(
        tmp_path / "doc.pdf", tmp_path, structured_output=True
    )


@pytest.mark.asyncio
async def test_job_finishes_with_warning_when_only_refinements_remain(
    monkeypatch, tmp_path
):
    manifest = _headings_and_order_manifest()
    orchestrator = _orchestrator_failing_order(max_replans=2)

    payload = await _run(orchestrator, manifest, monkeypatch, tmp_path)

    assert payload["canonical_metadata"]["pddl_execution_status"] in {
        "failed", "replan-required",
    }
    assert any("o-order" in warning for warning in payload["technical_warnings"])
    levels = [
        block["level"]
        for page in payload["pages"]
        for block in page["blocks"]
        if block["type"] == "heading"
    ]
    assert levels == [1, 2, 2]


@pytest.mark.asyncio
async def test_job_still_fails_when_a_critical_obligation_remains(
    monkeypatch, tmp_path
):
    describe = Obligation(
        id="o-describe",
        kind="describe-image",
        target_ids=["image"],
        admissible_methods=["human-review"],
        method_costs={"human-review": 100},
        rationale="Descrever a imagem",
    )
    manifest = _headings_and_order_manifest(
        [describe], [_element("image", "picture", reading_order=10)]
    )
    orchestrator = _orchestrator_failing_order(max_replans=2)

    with pytest.raises(RuntimeError, match="o-describe"):
        await _run(orchestrator, manifest, monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_replan_skips_exhausted_refinement_and_rescues_critical_one(
    monkeypatch, tmp_path
):
    # One execution exhausts the reading order (human review only) while the
    # image description still has an alternative: the replan must leave the
    # exhausted obligation out instead of being rejected by the planner.
    describe = Obligation(
        id="o-describe",
        kind="describe-image",
        target_ids=["image"],
        admissible_methods=["vision-description", "pymupdf-region"],
        method_costs={"vision-description": 1, "pymupdf-region": 2},
        rationale="Descrever a imagem",
    )
    manifest = _headings_and_order_manifest(
        [describe], [_element("image", "picture", reading_order=10)]
    )
    manifest.obligations[0].admissible_methods = ["human-review"]
    manifest.obligations[0].method_costs = {"human-review": 100}
    orchestrator = _orchestrator(max_replans=1)
    orchestrator.executor.registry.register("vision-description", _failing)
    orchestrator.executor.registry.register(
        "pymupdf-region",
        lambda _m, _o: MethodResult(success=True, validated=True, message="ok"),
    )

    payload = await _run(orchestrator, manifest, monkeypatch, tmp_path)

    assert any("o-order" in warning for warning in payload["technical_warnings"])
    assert not any("o-describe" in warning for warning in payload["technical_warnings"])
