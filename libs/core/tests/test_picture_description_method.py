"""The document's picture descriptions as a planned action (#640, M1).

Until 0.3.13 the orchestrator described the pictures before planning. Now a
``describe-images`` obligation, added when the document has pictures to
describe, is satisfied by the ``picture-description`` method, which runs the
same step. These tests pin the obligation, its place in the plan, the method,
and the obligations it changes while the plan runs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest
from core_config_support import core_config
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
)

from acessilia_core.agents.model_calls import current_model_calls
from acessilia_core.agents.output_schemas import VisionOutput
from acessilia_core.i18n import n, t
from acessilia_core.i18n.stage_messages import STAGE_ENRICHING_IMAGE_DESCRIPTIONS
from acessilia_core.manifest.models import ProcessingManifest, validate_obligation_graph
from acessilia_core.pipeline import orchestrator as pddl, preflight
from acessilia_core.pipeline.document_obligations import (
    PICTURE_DESCRIPTION,
    TABLE_ENRICHMENT,
    reconcile_document_step,
    reconcile_document_steps,
)
from acessilia_core.pipeline.enrichment import pictures as picture_stage
from acessilia_core.pipeline.handlers.messages import (
    MSG_PICTURES_DESCRIBED,
    MSG_VISION_NO_PICTURE,
)
from acessilia_core.pipeline.handlers.registry import bind_run, build_method_registry
from acessilia_core.planning.planner_agent import PlannerAgent
from acessilia_core.ports import RunPorts

CONFIG = core_config(vision={"retry_pass_delay_seconds": 0})
_PROSE = "A paragraph with enough words to make the document read as text, not as a picture."


def _describe_image(target: str) -> object:
    obligation = build_obligation("describe-image", [target], ["vision-description", "human-review"])
    obligation.id = f"describe-{target}"
    obligation.method_costs = {"vision-description": 20, "human-review": 100}
    return obligation


def _pictures_manifest(*pictures: str, described: tuple[str, ...] = ()) -> ProcessingManifest:
    elements = [build_element("prose", "paragraph", text=_PROSE)]
    for picture in pictures:
        metadata = {"vision_description_complete": True} if picture in described else {}
        elements.append(build_element(picture, "picture", text="A chart" if metadata else "", metadata=metadata))
    return build_manifest(elements, [_describe_image(picture) for picture in pictures])


def _by_id(manifest: ProcessingManifest, obligation_id: str):
    return next(item for item in manifest.obligations if item.id == obligation_id)


def _answers(monkeypatch, answers: dict[str, VisionOutput | None]) -> list[str]:
    """The vision model answers each picture by its id; a missing one gets no answer."""
    calls: list[str] = []

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            element_id = image_bytes.decode()
            calls.append(element_id)
            return answers.get(element_id)

    monkeypatch.setattr(picture_stage, "VisionAgent", Vision)
    monkeypatch.setattr(
        picture_stage, "_extract_picture_bytes",
        lambda source, element, fallback, *rest, **_kwargs: (element.id.encode(), fallback or 1),
    )
    return calls


def _description(text: str) -> VisionOutput:
    return VisionOutput(kind="description", description=text, language="en", confidence=0.9)


def _formula(latex: str) -> VisionOutput:
    return VisionOutput(kind="formula", description="", formula_latex=latex, language="und", confidence=0.9)


def _in_executor(manifest, *, config=CONFIG, ports=None):
    """Plan and execute ``manifest`` as a run does: the executor works on a copy."""
    reconcile_document_steps(manifest)
    executor = build_orchestrator().executor
    executor.registry = bind_run(build_method_registry(), config, ports or RunPorts.none())
    _, plan = PlannerAgent().plan(manifest)
    return executor.execute(plan, manifest)


def _step(report, obligation_id):
    return next(step for step in report.steps if step.obligation_id == obligation_id)


# The obligation.


def test_a_document_without_pictures_to_describe_gets_no_obligation() -> None:
    prose = build_manifest([build_element("prose", "paragraph", text=_PROSE)], [])
    described = _pictures_manifest("p-1", described=("p-1",))

    assert reconcile_document_step(prose, PICTURE_DESCRIPTION) is None
    assert reconcile_document_step(described, PICTURE_DESCRIPTION) is None


def test_the_obligation_covers_the_pictures_to_describe_and_precedes_their_obligations() -> None:
    manifest = _pictures_manifest("p-1", "p-2", "p-3", described=("p-2",))

    enrichment = reconcile_document_step(manifest, PICTURE_DESCRIPTION)

    assert enrichment.id == "obligation-describe-images"
    assert (enrichment.kind, enrichment.target_ids) == ("describe-images", ["p-1", "p-3"])
    assert enrichment.admissible_methods == ["picture-description", "human-review"]
    assert _by_id(manifest, "describe-p-1").dependencies == [enrichment.id]
    assert _by_id(manifest, "describe-p-2").dependencies == []
    assert manifest.summary.obligation_count == len(manifest.obligations)


def test_reconciling_twice_changes_nothing() -> None:
    manifest = _pictures_manifest("p-1")
    reconcile_document_steps(manifest)
    once = manifest.model_dump()

    reconcile_document_steps(manifest)

    assert manifest.model_dump() == once


def test_a_mostly_visual_one_page_document_has_its_first_element_described() -> None:
    """The rule of the stage before planning, kept: without pictures or
    placeholder visuals, a one-page mostly visual document has its first
    element described."""
    manifest = build_manifest([build_element("h", "heading", text="Titulo")], [])

    enrichment = reconcile_document_step(manifest, PICTURE_DESCRIPTION)

    assert enrichment.target_ids == ["h"]


def test_described_pictures_do_not_send_the_step_to_the_placeholders() -> None:
    """Before 0.3.14 a document whose pictures were all described moved on
    to its placeholder visuals; the candidates are now chosen first."""
    manifest = build_manifest(
        [build_element("p-1", "picture", text="A chart", metadata={"vision_description_complete": True})],
        [],
    )

    assert picture_stage._pictures_to_describe(manifest) == []


def test_the_plan_describes_the_pictures_before_it_validates_them() -> None:
    manifest = _pictures_manifest("p-1")
    reconcile_document_steps(manifest)

    _, plan = PlannerAgent().plan(manifest)

    order = [step.obligation_id for step in plan.steps if step.method]
    assert order.index("obligation-describe-images") < order.index("describe-p-1")


def _lone_table() -> ProcessingManifest:
    """A one-page mostly visual document whose only element is a table: the
    descriptions take it (the first element), and so does the table step."""
    linearize = build_obligation("linearize-table", ["t-1"], ["pandoc-table", "human-review"])
    linearize.id = "o-linearize"
    return build_manifest([build_element("t-1", "table", text="a b")], [linearize])


@pytest.mark.parametrize("table_first", [False, True], ids=["together", "tables-first"])
def test_two_document_steps_on_one_element_make_no_cycle(table_first) -> None:
    """#845 review, item 1: the rule applied in both directions made
    ``describe-images`` and ``enrich-tables`` depend on each other. The
    descriptions come first, as before planning until 0.3.13."""
    manifest = _lone_table()
    if table_first:
        reconcile_document_step(manifest, TABLE_ENRICHMENT)

    reconcile_document_steps(manifest)
    reconcile_document_steps(manifest, replan=True)

    validate_obligation_graph(manifest)
    by_kind = {item.kind: item for item in manifest.obligations}
    describe, enrich = by_kind[PICTURE_DESCRIPTION.kind], by_kind[TABLE_ENRICHMENT.kind]
    assert describe.target_ids == enrich.target_ids == ["t-1"]
    assert describe.dependencies == []
    assert describe.id in enrich.dependencies
    _, plan = PlannerAgent().plan(manifest)
    order = [step.obligation_id for step in plan.steps if step.method]
    assert order.index(describe.id) < order.index(enrich.id) < order.index("o-linearize")


def test_a_formula_is_never_a_picture_to_describe() -> None:
    """#845 review, item 2: the one-page fallback took a formula the step
    then dropped (``applies``), and recreated on the next reconciliation."""
    verbalize = build_obligation("verbalize-formula", ["f-1"], ["mathml", "human-review"])
    manifest = build_manifest([build_element("f-1", "formula", text="")], [verbalize])

    assert reconcile_document_step(manifest, PICTURE_DESCRIPTION) is None
    assert verbalize.dependencies == []


@pytest.mark.parametrize("elements", [
    [("h", "heading", "Titulo")],
    [("t-1", "table", "a b")],
    [("f-1", "formula", ""), ("h", "heading", "Titulo")],
    [("p-1", "picture", ""), ("prose", "paragraph", _PROSE)],
])
def test_the_step_applies_to_every_element_it_takes(elements) -> None:
    manifest = build_manifest([build_element(i, kind, text=text) for i, kind, text in elements], [])
    by_id = {element.id: element for element in manifest.elements}

    pending = PICTURE_DESCRIPTION.pending(manifest)

    assert pending and all(PICTURE_DESCRIPTION.applies(by_id[item]) for item in pending)


def test_the_two_document_steps_keep_to_their_own_elements() -> None:
    manifest = _pictures_manifest("p-1")
    manifest.elements.append(build_element("t-1", "table", text="a b"))
    manifest.summary.element_count = len(manifest.elements)

    reconcile_document_steps(manifest)

    by_kind = {item.kind: item for item in manifest.obligations}
    assert by_kind[PICTURE_DESCRIPTION.kind].target_ids == ["p-1"]
    assert by_kind[TABLE_ENRICHMENT.kind].target_ids == ["t-1"]
    assert by_kind[PICTURE_DESCRIPTION.kind].dependencies == []
    assert by_kind[TABLE_ENRICHMENT.kind].dependencies == []


def test_a_picture_found_during_the_run_gets_a_new_selected_obligation() -> None:
    manifest = _pictures_manifest("p-1")
    first = reconcile_document_step(manifest, PICTURE_DESCRIPTION)
    first.status = "satisfied"
    manifest.elements[1].metadata["vision_description_complete"] = True
    manifest.elements.append(build_element("p-2", "picture", text=""))
    manifest.obligations.append(_describe_image("p-2"))
    manifest.summary.element_count = len(manifest.elements)

    second = reconcile_document_step(manifest, PICTURE_DESCRIPTION, replan=True)

    assert (second.id, second.target_ids, second.selected) == ("obligation-describe-images-2", ["p-2"], True)
    assert _by_id(manifest, "describe-p-2").dependencies == [second.id]


# The method.


def test_the_method_describes_its_pictures_and_reports_each_one(monkeypatch) -> None:
    calls = _answers(monkeypatch, {"p-1": _description("A bar chart of sales.")})
    manifest = _pictures_manifest("p-1", "p-2")

    updated, report = _in_executor(manifest)

    assert sorted(calls) == ["p-1", "p-2", "p-2"]  # p-2 again in the retry pass
    step = _step(report, "obligation-describe-images")
    assert step.status == "succeeded"
    assert step.message == n(*MSG_PICTURES_DESCRIBED, 2).format(
        count=2, described=1, formulas=0, already=0, left="model_failed: 1"
    )
    by_id = {element.id: element for element in updated.elements}
    assert by_id["p-1"].text == "A bar chart of sales."
    assert by_id["p-2"].metadata["vision_failure_reason"] == "model_failed"


def test_the_method_without_pictures_fails_instead_of_raising() -> None:
    manifest = _pictures_manifest("p-1")
    enrichment = reconcile_document_step(manifest, PICTURE_DESCRIPTION)
    handler = build_method_registry().get("picture-description")
    manifest.elements = [element for element in manifest.elements if element.id != "p-1"]

    result = handler(manifest, enrichment.id, config=CONFIG, ports=RunPorts.none())

    assert (result.success, result.message) == (False, t(MSG_VISION_NO_PICTURE))


def test_a_second_obligation_describes_only_its_own_pictures(monkeypatch) -> None:
    """A picture an earlier obligation owns and left undescribed is not
    described again by a later one (#832): the step keeps to its targets."""
    calls = _answers(monkeypatch, {"p-2": _description("A map.")})
    manifest = _pictures_manifest("p-1")
    first = reconcile_document_step(manifest, PICTURE_DESCRIPTION)
    first.status = "satisfied"
    manifest.elements.append(build_element("p-2", "picture", text=""))
    manifest.obligations.append(_describe_image("p-2"))
    manifest.summary.element_count = len(manifest.elements)
    second = reconcile_document_step(manifest, PICTURE_DESCRIPTION, replan=True)
    handler = build_method_registry().get("picture-description")

    result = handler(manifest, second.id, config=CONFIG, ports=RunPorts.none())

    assert calls == ["p-2"]
    assert result.success


def test_the_method_reports_its_progress_through_the_run(monkeypatch) -> None:
    _answers(monkeypatch, {"p-1": _description("A chart.")})
    ports = RunPorts.none()
    messages: list[str] = []
    ports.services.progress = messages.append

    _in_executor(_pictures_manifest("p-1"), ports=ports)

    assert messages[0] == t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS)


def test_the_method_annotates_with_the_run_media_inspection(monkeypatch) -> None:
    """The second ownership annotation of the stage needs the media
    inspection, which the run keeps in its services."""
    _answers(monkeypatch, {"p-1": _description("A chart.")})
    seen: list = []
    monkeypatch.setattr(
        picture_stage, "_annotate_visual_text_ownership",
        lambda manifest, media_inspection=None: seen.append(media_inspection),
    )
    ports = RunPorts.none()
    ports.services.media_inspection = {"is_image": True}

    _in_executor(_pictures_manifest("p-1"), ports=ports)

    assert seen and all(item == {"is_image": True} for item in seen)


def test_the_method_leaves_the_pictures_as_the_step_before_planning_did(monkeypatch) -> None:
    """The differential test of the migration (ADR-0028): the same answers
    give the same elements, whether the step runs before planning, as until
    0.3.13, or as the method inside the plan."""
    answers = {
        "p-1": _description("A bar chart of sales."),
        "p-2": _formula(r"\frac{a}{b}"),
    }
    _answers(monkeypatch, answers)
    before = _pictures_manifest("p-1", "p-2", "p-3")
    asyncio.run(picture_stage._enrich_picture_descriptions(
        before, Path("doc.pdf"), mode="medio", vision=CONFIG.vision, toolbox=CONFIG.toolbox,
        models=CONFIG.models, region_cache=None,
    ))

    inside, _ = _in_executor(_pictures_manifest("p-1", "p-2", "p-3"))

    def elements(manifest):
        return [element.model_dump() for element in manifest.elements]

    assert elements(inside) == elements(before)


# The obligations the step changes while the plan runs.


def test_a_picture_read_as_a_formula_replaces_its_obligation(monkeypatch) -> None:
    """The model reads the picture as a formula: the element becomes a
    formula, its ``describe-image`` is replaced by the formula's obligation,
    and the executor skips the removed step and asks for a replan (M0)."""
    _answers(monkeypatch, {"p-1": _formula(r"\frac{a}{b}")})
    manifest = _pictures_manifest("p-1")

    updated, report = _in_executor(manifest)

    step = _step(report, "obligation-describe-images")
    assert step.message == n(*MSG_PICTURES_DESCRIBED, 1).format(
        count=1, described=0, formulas=1, already=0, left="-"
    )
    assert _step(report, "describe-p-1").status == "skipped"
    assert report.failed_step_index is None
    assert report.status == "replan-required"
    kinds = {item.kind for item in updated.obligations if "p-1" in item.target_ids}
    assert "verbalize-formula" in kinds and "describe-image" not in kinds


def _run(monkeypatch, manifest, tmp_path, *, register):
    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(preflight, "inspect_source_media", nothing)
    for name in ("_classify_formula_regions", "_mark_inline_math", "_enrich_formula_latex"):
        monkeypatch.setattr(pddl, name, nothing)
    orchestrator = build_orchestrator(max_replans=1)
    for method, handler in register.items():
        orchestrator.executor.registry.register(method, handler)
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)
    return asyncio.run(orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True,
        config=CONFIG, model_calls=current_model_calls(), ports=RunPorts.none(),
    ))


def test_a_run_plans_the_formula_a_picture_became(monkeypatch, tmp_path) -> None:
    """End to end: the replan after the descriptions plans the formula's
    obligation, so the job finishes with it satisfied."""
    from acessilia_core.execution.models import MethodResult

    _answers(monkeypatch, {"p-1": _formula(r"\frac{a}{b}"), "p-2": _description("A map.")})
    verbalized: list[str] = []

    def mathml(_manifest, obligation_id):
        verbalized.append(obligation_id)
        return MethodResult(success=True, validated=True)

    payload = _run(monkeypatch, _pictures_manifest("p-1", "p-2"), tmp_path, register={"mathml": mathml})

    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert len(verbalized) == 1


# Resume across the migration.


def _ctx(enriched_state):
    saved: dict = {}

    class Checkpoints:
        def load(self, phase):
            return enriched_state

        async def save(self, phase, build):
            saved[phase] = build()

    return SimpleNamespace(
        checkpoints=Checkpoints(), effective_mode="medio", config=CONFIG, ports=RunPorts.none(),
        source_path=Path("/tmp/doc.pdf"), status_callback=None,
    ), saved


def test_an_enrichment_checkpoint_from_before_the_migration_gets_no_obligation() -> None:
    """A 0.3.13 checkpoint has its pictures described already."""
    from acessilia_core.pipeline.checkpointing import manifest_payload

    checkpointed = _pictures_manifest("p-1", described=("p-1",))
    ctx, _ = _ctx({"manifest": manifest_payload(checkpointed)})

    resumed = asyncio.run(
        build_orchestrator()._load_or_enrich_manifest(ctx, _pictures_manifest("p-1"), None, {})
    )

    assert not any(item.kind == PICTURE_DESCRIPTION.kind for item in resumed.obligations)
    # Nor does the reconciliation before a replan (#845 review, item 3):
    # its pictures are described.
    reconcile_document_steps(resumed, replan=True)
    assert not any(item.kind == PICTURE_DESCRIPTION.kind for item in resumed.obligations)


def test_a_fresh_enrichment_adds_the_obligation_before_its_checkpoint(monkeypatch) -> None:
    async def no_enrichment(*_args, **_kwargs):
        return None

    orchestrator = build_orchestrator()
    monkeypatch.setattr(orchestrator, "_enrich_before_planning", no_enrichment)
    ctx, saved = _ctx(None)

    asyncio.run(orchestrator._load_or_enrich_manifest(ctx, _pictures_manifest("p-1"), None, {}))

    [state] = saved.values()
    assert any(item["kind"] == PICTURE_DESCRIPTION.kind for item in state["manifest"]["obligations"])


@pytest.mark.parametrize("media_inspection", [None, {"is_image": False}])
def test_the_media_inspection_reaches_the_run_services(monkeypatch, media_inspection) -> None:
    async def inspect(*_args, **_kwargs):
        return media_inspection, {}

    monkeypatch.setattr(pddl, "_inspect_media", inspect)
    ctx, _ = _ctx(None)

    asyncio.run(build_orchestrator()._load_or_inspect_media(ctx))

    assert ctx.ports.services.media_inspection == media_inspection
