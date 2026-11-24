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
from acessilia_core.pipeline.handlers import formula_recognition as formula_method
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
    descriptions' one-page fallback took it before the review of #845."""
    linearize = build_obligation("linearize-table", ["t-1"], ["pandoc-table", "human-review"])
    linearize.id = "o-linearize"
    return build_manifest([build_element("t-1", "table", text="a b")], [linearize])


@pytest.mark.parametrize("table_first", [False, True], ids=["together", "tables-first"])
def test_a_table_is_left_to_the_table_step(table_first) -> None:
    """#845 review, items 2.1 and 2.2: the descriptions shared the table with
    ``enrich-tables`` and the two came to depend on each other, a cycle; the
    table could also be retyped as a picture. A table is not describable, so
    the steps never share an element. Reconciled twice, the graph is the
    same, a DAG, and the table is read before it is linearized."""
    manifest = _lone_table()
    if table_first:
        reconcile_document_step(manifest, TABLE_ENRICHMENT)

    reconcile_document_steps(manifest)
    once = manifest.model_dump()
    reconcile_document_steps(manifest, replan=True)

    assert manifest.model_dump() == once
    validate_obligation_graph(manifest)
    assert [item.kind for item in manifest.obligations] == ["linearize-table", TABLE_ENRICHMENT.kind]
    _, plan = PlannerAgent().plan(manifest)
    order = [step.obligation_id for step in plan.steps if step.method]
    assert order.index("obligation-enrich-tables") < order.index("o-linearize")


def test_the_edge_rule_never_makes_a_cycle_between_document_steps() -> None:
    """The guard behind the policy: even with obligations of both steps on
    one element (none of today's rules makes that), an earlier step's never
    depends on a later one's, in whichever order they are reconciled."""
    from acessilia_core.manifest.models import Obligation
    from acessilia_core.pipeline.document_obligations import _reconcile_edges

    manifest = build_manifest([build_element("x", "table", text="a b")], [])
    for kind, obligation_id in ((PICTURE_DESCRIPTION.kind, "d"), (TABLE_ENRICHMENT.kind, "e")):
        manifest.obligations.append(Obligation(
            id=obligation_id, kind=kind, target_ids=["x"],
            admissible_methods=["human-review"], method_costs={"human-review": 100},
            rationale="test",
        ))
    manifest.summary.obligation_count = len(manifest.obligations)

    for step in (TABLE_ENRICHMENT, PICTURE_DESCRIPTION, TABLE_ENRICHMENT):
        _reconcile_edges(manifest, step)

    by_id = {item.id: item for item in manifest.obligations}
    assert by_id["d"].dependencies == [] and by_id["e"].dependencies == ["d"]
    validate_obligation_graph(manifest)


def test_a_formula_is_never_a_picture_to_describe() -> None:
    """#845 review, item 2: the one-page fallback took a formula the step
    then dropped (``applies``), and recreated on the next reconciliation."""
    verbalize = build_obligation("verbalize-formula", ["f-1"], ["mathml", "human-review"])
    manifest = build_manifest([build_element("f-1", "formula", text="")], [verbalize])

    assert reconcile_document_step(manifest, PICTURE_DESCRIPTION) is None
    assert verbalize.dependencies == []


@pytest.mark.parametrize("elements", [
    [("h", "heading", "Titulo")],
    [("t-1", "table", "a b"), ("h", "heading", "Titulo")],
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


def _heading_only() -> ProcessingManifest:
    """A one-page mostly visual document: the fallback describes its heading."""
    return build_manifest([build_element("h", "heading", text="Titulo")], [])


@pytest.mark.parametrize("scenario", ["pictures-and-a-formula", "one-page-fallback"])
def test_the_method_leaves_the_pictures_as_the_step_before_planning_did(monkeypatch, scenario) -> None:
    """The differential test of the migration (ADR-0028): the same answers
    give the same elements, whether the step runs before planning, as until
    0.3.13, or as the method inside the plan.

    It compares the step, not the whole pipeline. The intended differences
    are listed in the 0.3.14 changelog: a formula or a table is never
    described, and a document whose pictures are all described does not move
    on to its placeholder visuals. A picture read as a formula gets the
    formula LaTeX step on the replan since 0.3.15 (M3,
    ``test_a_picture_read_as_a_formula_gets_the_formula_steps``)."""
    answers = {
        "p-1": _description("A bar chart of sales."),
        "p-2": _formula(r"\frac{a}{b}"),
        "h": _description("A road sign."),
    }
    _answers(monkeypatch, answers)
    build = {
        "pictures-and-a-formula": lambda: _pictures_manifest("p-1", "p-2", "p-3"),
        "one-page-fallback": _heading_only,
    }[scenario]
    before = build()
    asyncio.run(picture_stage._enrich_picture_descriptions(
        before, Path("doc.pdf"), mode="medio", vision=CONFIG.vision, toolbox=CONFIG.toolbox,
        models=CONFIG.models, region_cache=None,
    ))

    inside, _ = _in_executor(build())

    def elements(manifest):
        return [element.model_dump() for element in manifest.elements]

    assert elements(inside) == elements(before)


def test_the_method_tries_its_targets_even_when_the_candidates_changed(monkeypatch) -> None:
    """#845 review, item 2.3: the heading the one-page fallback took stops
    being a candidate once a picture appears; the method still describes it,
    because the plan's obligation decided its targets."""
    calls = _answers(monkeypatch, {"h": _description("A road sign."), "p-new": _description("x")})
    manifest = _heading_only()
    enrichment = reconcile_document_step(manifest, PICTURE_DESCRIPTION)
    manifest.elements.append(build_element("p-new", "picture", text=""))
    manifest.summary.element_count = len(manifest.elements)
    handler = build_method_registry().get("picture-description")

    result = handler(manifest, enrichment.id, config=CONFIG, ports=RunPorts.none())

    assert calls == ["h"]
    assert result.message == n(*MSG_PICTURES_DESCRIBED, 1).format(
        count=1, described=1, formulas=0, already=0, left="-"
    )


def test_a_target_another_step_now_reads_is_reported_not_described(monkeypatch) -> None:
    calls = _answers(monkeypatch, {})
    manifest = _pictures_manifest("p-1")
    enrichment = reconcile_document_step(manifest, PICTURE_DESCRIPTION)
    manifest.elements[1].type = "table"
    handler = build_method_registry().get("picture-description")

    result = handler(manifest, enrichment.id, config=CONFIG, ports=RunPorts.none())

    assert calls == []
    assert result.message == n(*MSG_PICTURES_DESCRIBED, 1).format(
        count=1, described=0, formulas=0, already=0, left="not_describable: 1"
    )


def test_the_method_does_not_inject_the_full_page_picture_again(monkeypatch) -> None:
    """#845 review, item 4.7: the injection is the bootstrap's; inside the
    plan the method only annotates and describes."""
    _answers(monkeypatch, {"h": _description("A photo.")})
    ports = RunPorts.none()
    ports.services.media_inspection = {"is_image": True, "requires_visual_inspection": True}

    updated, _ = _in_executor(_heading_only(), ports=ports)

    assert [element.id for element in updated.elements] == ["h"]


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


def _run(monkeypatch, manifest, tmp_path, *, register, recognize=False):
    """``recognize`` runs the real formula LaTeX step inside the plan."""
    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(preflight, "inspect_source_media", nothing)
    for name in ("_classify_formula_regions", "_mark_inline_math"):
        monkeypatch.setattr(pddl, name, nothing)
    if not recognize:
        monkeypatch.setattr(formula_method, "_enrich_formula_latex", nothing)
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


def test_a_picture_read_as_a_formula_gets_the_formula_steps(monkeypatch, tmp_path) -> None:
    """The gap of M1 closed (#846): picture, then formula, then the formula
    LaTeX step, then the verbalization. The replan gives the formula a
    ``recognize-formulas`` obligation its ``verbalize-formula`` waits for,
    so the verbalization sees the equation number separated, as the step
    before planning gave it until 0.3.14."""
    from acessilia_core.execution.models import MethodResult

    _answers(monkeypatch, {"p-1": _formula(r"E = mc^{2} \qquad (3)")})
    seen: list[tuple[str, str | None]] = []

    def mathml(manifest, obligation_id):
        formula = next(element for element in manifest.elements if element.id == "p-1")
        seen.append((formula.text, formula.metadata.get("equation_number")))
        return MethodResult(success=True, validated=True)

    payload = _run(
        monkeypatch, _pictures_manifest("p-1"), tmp_path, register={"mathml": mathml}, recognize=True
    )

    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert seen == [("E = mc^{2}", "3")]


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


def test_a_picture_a_0_3_13_run_left_undescribed_is_tried_again_on_a_replan() -> None:
    """The compatibility policy (#845 review, item 4.6): an enrichment
    checkpoint from 0.3.13 is resumed as it is, so its pictures the step
    left undescribed are not described before the first plan, as then. A
    replan's reconciliation gives them one obligation, selected, so the
    replan the run makes anyway tries them once more."""
    manifest = _pictures_manifest("p-1", "p-2", described=("p-1",))
    manifest.elements[2].metadata["vision_failure_reason"] = "model_failed"

    created = reconcile_document_step(manifest, PICTURE_DESCRIPTION, replan=True)

    assert (created.target_ids, created.selected) == (["p-2"], True)


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
