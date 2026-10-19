"""An obligation that no automatic method satisfies must not block the others.

Staging regression: with PDDL running live, `refine-reading-order` exhausted its
methods (XY-cut, skeleton, human review) and the executor stopped at that step,
so the independent heading repairs never ran. The executor now runs them, and a
job whose only open obligations are refinements finishes with a warning. A wrong
reading order is not a refinement: it still fails the job.
"""

from types import SimpleNamespace

import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.core.execution.models import MethodResult
from backend.core.manifest.builder import _derive_processing_needs
from backend.core.manifest.models import Obligation
from backend.tools.logger import logger
from tests.pddl_support import build_element, build_manifest, build_orchestrator


def _failing(_manifest, _obligation_id):
    return MethodResult(success=False, validated=False, message="falha controlada")


def _succeeding(_manifest, _obligation_id):
    return MethodResult(success=True, validated=True, message="ok")


def _open_obligation(obligation_id, kind, methods):
    """An obligation over the headings whose automatic methods all fail."""
    return Obligation(
        id=obligation_id,
        kind=kind,
        target_ids=[f"heading-{i}" for i in range(3)],
        admissible_methods=methods,
        method_costs={
            method: 100 if method == "human-review" else 1 for method in methods
        },
        rationale="Obrigação sem método automático que funcione",
    )


def _reading_order():
    return _open_obligation(
        "o-order", "refine-reading-order", ["xycut-order", "human-review"]
    )


def _text_refinement(methods=("norm-fix", "human-review")):
    return _open_obligation("o-refine", "normalize-text", list(methods))


def _describe_image(methods, costs):
    return Obligation(
        id="o-describe",
        kind="describe-image",
        target_ids=["image"],
        admissible_methods=methods,
        method_costs=costs,
        rationale="Descrever a imagem",
    )


def _headings_manifest(*open_obligations, extra_elements=()):
    """Three flat H1 headings, as the extractor reports them; the heading repairs
    are derived from them and `open_obligations` are planned first."""
    elements = [
        build_element(
            f"heading-{i}", "heading", text=f"Heading {i}", reading_order=i + 1
        )
        for i in range(3)
    ]
    _, repairs = _derive_processing_needs(elements)
    return build_manifest(
        [*elements, *extra_elements], [*open_obligations, *repairs]
    )


def _orchestrator(max_replans: int):
    orchestrator = build_orchestrator(max_replans=max_replans)
    orchestrator.executor.registry.register("xycut-order", _failing)
    orchestrator.executor.registry.register("norm-fix", _failing)
    return orchestrator


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


def _open_ids(payload):
    return [
        item["id"]
        for item in payload["canonical_metadata"]["pddl_unsatisfied_obligations"]
    ]


def _heading_levels(payload):
    return [
        block["level"]
        for page in payload["pages"]
        for block in page["blocks"]
        if block["type"] == "heading"
    ]


def test_failed_obligation_does_not_stop_independent_ones():
    manifest = _headings_manifest(_reading_order())
    orchestrator = _orchestrator(max_replans=0)
    plan, _ = orchestrator._build_plan(manifest)
    # The staging plan ran the reading order before the heading repairs.
    executed = [step.obligation_id for step in plan.steps if step.obligation_id]
    assert executed[0] == "o-order"

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
    manifest = _headings_manifest(_reading_order())
    orchestrator = _orchestrator(max_replans=0)
    plan, _ = orchestrator._build_plan(manifest)
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        orchestrator.executor.execute(plan, manifest, dry_run=False)
    finally:
        logger.remove(sink)

    assert any(
        "o-order" in message
        and "xycut-order" in message
        and "falha controlada" in message
        for message in messages
    )


@pytest.mark.asyncio
async def test_job_finishes_with_warning_when_only_refinements_remain(
    monkeypatch, tmp_path
):
    payload = await _run(
        _orchestrator(max_replans=2),
        _headings_manifest(_text_refinement()),
        monkeypatch,
        tmp_path,
    )

    assert payload["canonical_metadata"]["pddl_execution_status"] in {
        "failed", "replan-required",
    }
    assert any("o-refine" in warning for warning in payload["technical_warnings"])
    assert _open_ids(payload) == ["o-refine"]
    assert _heading_levels(payload) == [1, 2, 2]


@pytest.mark.asyncio
async def test_open_reading_order_still_fails_the_job(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="o-order"):
        await _run(
            _orchestrator(max_replans=2),
            _headings_manifest(_reading_order()),
            monkeypatch,
            tmp_path,
        )


@pytest.mark.asyncio
async def test_job_still_fails_when_a_critical_obligation_remains(
    monkeypatch, tmp_path
):
    manifest = _headings_manifest(
        _text_refinement(),
        _describe_image(["human-review"], {"human-review": 100}),
        extra_elements=[build_element("image", "picture", reading_order=10)],
    )

    with pytest.raises(RuntimeError, match="o-describe"):
        await _run(_orchestrator(max_replans=2), manifest, monkeypatch, tmp_path)


@pytest.mark.asyncio
async def test_replan_skips_exhausted_refinement_and_rescues_critical_one(
    monkeypatch, tmp_path
):
    # One execution exhausts the refinement (human review only) while the image
    # description still has an alternative: the replan must leave the exhausted
    # obligation out instead of being rejected by the planner, and the warning
    # and the structured metadata must agree on what was left open.
    manifest = _headings_manifest(
        _text_refinement(methods=["human-review"]),
        _describe_image(
            ["vision-description", "pymupdf-region"],
            {"vision-description": 1, "pymupdf-region": 2},
        ),
        extra_elements=[build_element("image", "picture", reading_order=10)],
    )
    orchestrator = _orchestrator(max_replans=1)
    orchestrator.executor.registry.register("vision-description", _failing)
    orchestrator.executor.registry.register("pymupdf-region", _succeeding)

    payload = await _run(orchestrator, manifest, monkeypatch, tmp_path)

    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert any("o-refine" in warning for warning in payload["technical_warnings"])
    assert not any(
        "o-describe" in warning for warning in payload["technical_warnings"]
    )
    assert _open_ids(payload) == ["o-refine"]
