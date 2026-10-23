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
from backend.core.execution.messages import EXE_COMPLETED_OBLIGATIONS_UNSATISFIED
from backend.core.execution.models import MethodResult
from backend.core.manifest.builder import _derive_processing_needs
from backend.core.manifest.models import Obligation
from backend.i18n import t
from backend.stage_messages import STAGE_PAGE_UNKNOWN, STAGE_PAGES
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
    assert any("normalize-text" in warning for warning in payload["technical_warnings"])
    assert _open_ids(payload) == ["o-refine"]
    assert _heading_levels(payload) == [1, 2, 2]


@pytest.mark.asyncio
async def test_an_omitted_block_with_no_rescue_method_does_not_fail_the_job(
    monkeypatch, tmp_path
):
    """`rescue-omitted` has no handler, so only human review was left to fail."""
    rescue = _open_obligation(
        "o-rescue", "rescue-omitted-block", ["rescue-omitted", "human-review"]
    )

    payload = await _run(
        _orchestrator(max_replans=2), _headings_manifest(rescue), monkeypatch, tmp_path
    )

    assert _open_ids(payload) == ["o-rescue"]
    # Delivered, not dropped silently: the omitted block is reported, and the
    # summary the result e-mail carries names it.
    assert any(
        "rescue-omitted-block" in warning for warning in payload["technical_warnings"]
    )
    assert "rescue-omitted-block" in (
        payload["canonical_metadata"]["pddl_unsatisfied_summary"]
    )


def test_the_job_error_groups_open_obligations_by_kind_and_page():
    """006.pdf's e-mail listed every obligation id with all its target elements."""
    order = _reading_order()
    # A second obligation of the same kind: its page merges into the group.
    second_order = _open_obligation(
        "o-order-2", "refine-reading-order", ["xycut-order", "human-review"]
    )
    second_order.target_ids = ["heading-1"]
    describe = _describe_image(["human-review"], {"human-review": 100})
    for obligation in (order, second_order, describe):
        obligation.status = "failed"
    manifest = _headings_manifest(
        order,
        second_order,
        describe,
        extra_elements=[build_element("image", "picture", reading_order=10)],
    )
    open_ids = {"o-order", "o-order-2", "o-describe"}
    for obligation in manifest.obligations:
        obligation.selected = obligation.id in open_ids
    elements = {element.id: element for element in manifest.elements}
    elements["heading-1"].page_number = 2
    elements["image"].page_number = None

    summary = pddl._unsatisfied_summary(manifest)

    expected = "; ".join([
        f"refine-reading-order ({t(STAGE_PAGES).format(pages='1, 2')})",
        f"describe-image ({t(STAGE_PAGE_UNKNOWN)})",
    ])
    assert summary == t(EXE_COMPLETED_OBLIGATIONS_UNSATISFIED).format(
        unsatisfied=expected
    )


@pytest.mark.asyncio
async def test_a_judge_verdict_for_the_secondary_provider_does_not_fail_the_job(
    monkeypatch, tmp_path
):
    """The page swap is not applied, so the verdict is a warning, not a failure."""
    orchestrator = _orchestrator(max_replans=2)
    orchestrator.executor.registry.register("vlm-pairwise-judge", _failing)
    adjudication = _open_obligation(
        "o-adjudicate", "adjudicate-page", ["vlm-pairwise-judge", "human-review"]
    )

    payload = await _run(
        orchestrator, _headings_manifest(adjudication), monkeypatch, tmp_path
    )

    assert _open_ids(payload) == ["o-adjudicate"]
    assert any("adjudicate-page" in warning for warning in payload["technical_warnings"])


@pytest.mark.asyncio
async def test_open_reading_order_still_fails_the_job(monkeypatch, tmp_path):
    with pytest.raises(RuntimeError, match="refine-reading-order"):
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

    with pytest.raises(RuntimeError, match="describe-image"):
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
    assert any("normalize-text" in warning for warning in payload["technical_warnings"])
    assert not any(
        "describe-image" in warning for warning in payload["technical_warnings"]
    )
    assert _open_ids(payload) == ["o-refine"]
