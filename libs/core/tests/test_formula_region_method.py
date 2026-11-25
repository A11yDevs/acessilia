"""The document's formula region classification as a planned action (#640, M4).

Until 0.3.18 the orchestrator checked the extractor's formula labels before
planning. Now a ``classify-formula-regions`` obligation, added when the
document has formula regions to check, is satisfied by the
``formula-region-classifier`` method, which runs the same step. It shares the
formulas with the formula LaTeX (M3), which waits for it.
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
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.manifest.models import ProcessingManifest, validate_obligation_graph
from acessilia_core.pipeline import preflight
from acessilia_core.pipeline.document_obligations import (
    FORMULA_CLASSIFICATION,
    FORMULA_RECOGNITION,
    reconcile_document_step,
    reconcile_document_steps,
)
from acessilia_core.pipeline.enrichment import formulas as formula_stage
from acessilia_core.pipeline.handlers import formula_recognition as formula_method
from acessilia_core.pipeline.handlers.messages import (
    MSG_FORMULA_REGIONS_CLASSIFIED,
    MSG_MATH_NO_FORMULA,
)
from acessilia_core.pipeline.handlers.registry import bind_run, build_method_registry
from acessilia_core.planning.planner_agent import PlannerAgent
from acessilia_core.ports import RunPorts

CONFIG = core_config()
_PROSE = "A paragraph with enough words to make the document read as text, not as a picture."


def _verbalize(target: str):
    obligation = build_obligation("verbalize-formula", [target], ["mathml", "human-review"])
    obligation.id = f"verbalize-{target}"
    obligation.method_costs = {"mathml": 10, "human-review": 100}
    return obligation


def _manifest(*formulas: tuple[str, str], media_type: str = "application/pdf") -> ProcessingManifest:
    elements = [build_element("prose", "paragraph", text=_PROSE)]
    elements += [build_element(element_id, "formula", text=text) for element_id, text in formulas]
    manifest = build_manifest(elements, [_verbalize(element_id) for element_id, _ in formulas])
    manifest.source.media_type = media_type
    return manifest


def _by_id(manifest, item_id):
    return next(item for item in [*manifest.elements, *manifest.obligations] if item.id == item_id)


def _answers(monkeypatch, answers: dict[str, VisionOutput | None]) -> list[str]:
    """The vision model answers each region by its id; a missing one gets no answer."""
    calls: list[str] = []

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            element_id = image_bytes.decode()
            calls.append(element_id)
            return answers.get(element_id)

    monkeypatch.setattr(formula_stage, "VisionAgent", Vision)
    monkeypatch.setattr(
        formula_stage, "_formula_recognition_crop", lambda _source, element, **_kwargs: (element.id.encode(), 1)
    )
    return calls


def _math() -> VisionOutput:
    return VisionOutput(kind="formula", description="", formula_latex="x", language="und", confidence=0.9)


def _drawing() -> VisionOutput:
    return VisionOutput(kind="description", description="A ring of atoms.", language="en", confidence=0.9)


def _uncertain() -> VisionOutput:
    return VisionOutput(
        kind="description", description="Unclear marks.", language="en", confidence=0.4,
        classification_uncertain=True,
    )


def _in_executor(manifest):
    reconcile_document_steps(manifest)
    executor = build_orchestrator().executor
    executor.registry = bind_run(build_method_registry(), CONFIG, RunPorts.none())
    # The formula LaTeX is M3's; these tests look at the classification.
    executor.registry.register(
        "formula-recognizer", lambda *_a, **_k: MethodResult(success=True, validated=True)
    )
    _, plan = PlannerAgent().plan(manifest)
    return executor.execute(plan, manifest)


def _step(report, obligation_id):
    return next(step for step in report.steps if step.obligation_id == obligation_id)


# The obligation.


def test_the_obligation_covers_the_regions_to_check() -> None:
    manifest = _manifest(
        ("f-text", "x plus y"),                 # no LaTeX: checked
        ("f-latex", r"\frac{a}{b}"),            # LaTeX: not a candidate
        ("f-done", "a b"),                      # already classified
        ("f-vision", "E = mc2"),                # the vision model read it as a formula
    )
    _by_id(manifest, "f-done").metadata["formula_classification"] = {"status": "math"}
    _by_id(manifest, "f-vision").metadata["original_type"] = "picture"

    enrichment = reconcile_document_step(manifest, FORMULA_CLASSIFICATION)

    assert (enrichment.id, enrichment.kind) == ("obligation-classify-formula-regions", "classify-formula-regions")
    assert enrichment.target_ids == ["f-text"]
    assert enrichment.admissible_methods == ["formula-region-classifier", "human-review"]


def test_a_source_without_pages_to_render_gets_no_obligation() -> None:
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    manifest = _manifest(("f-text", "x plus y"), media_type=docx)

    assert reconcile_document_step(manifest, FORMULA_CLASSIFICATION) is None


def test_the_recognition_waits_for_the_classification() -> None:
    """The two steps share the formula: the recognition depends on the
    classification (``DOCUMENT_STEPS`` order), the verbalization on both,
    and the graph stays a DAG however often it is reconciled."""
    manifest = _manifest(("f-1", "x plus y"))

    reconcile_document_steps(manifest)
    once = manifest.model_dump()
    reconcile_document_steps(manifest, replan=True)

    assert manifest.model_dump() == once
    validate_obligation_graph(manifest)
    classify = _by_id(manifest, "obligation-classify-formula-regions")
    recognize = _by_id(manifest, "obligation-recognize-formulas")
    assert recognize.dependencies == [classify.id]
    assert classify.dependencies == []
    assert set(_by_id(manifest, "verbalize-f-1").dependencies) == {classify.id, recognize.id}
    _, plan = PlannerAgent().plan(manifest)
    order = [step.obligation_id for step in plan.steps if step.method]
    assert order.index(classify.id) < order.index(recognize.id) < order.index("verbalize-f-1")


# The method.


def test_the_method_classifies_each_region_and_reports_it(monkeypatch) -> None:
    calls = _answers(monkeypatch, {"f-math": _math(), "f-unsure": _uncertain()})
    manifest = _manifest(("f-math", "x plus y"), ("f-unsure", "a b"), ("f-none", "c d"))

    updated, report = _in_executor(manifest)

    assert sorted(calls) == ["f-math", "f-none", "f-unsure"]
    assert _step(report, "obligation-classify-formula-regions").message == n(
        *MSG_FORMULA_REGIONS_CLASSIFIED, 3
    ).format(count=3, math=1, pictures=0, unresolved=1, already=0, left="model_failed: 1")
    assert _by_id(updated, "f-math").metadata["formula_classification"]["status"] == "math"


def test_the_method_without_formulas_fails_instead_of_raising() -> None:
    manifest = _manifest(("f-1", "x plus y"))
    enrichment = reconcile_document_step(manifest, FORMULA_CLASSIFICATION)
    manifest.elements = [element for element in manifest.elements if element.id != "f-1"]
    handler = build_method_registry().get("formula-region-classifier")

    result = handler(manifest, enrichment.id, config=CONFIG, ports=RunPorts.none())

    assert (result.success, result.message) == (False, t(MSG_MATH_NO_FORMULA))


def test_a_drawing_is_described_as_a_picture_and_its_obligations_replaced(monkeypatch) -> None:
    """The step changes obligations (M0): the drawing becomes a described
    picture, its ``verbalize-formula`` is replaced by a ``describe-image``,
    and the executor skips the removed steps and asks for a replan."""
    _answers(monkeypatch, {"f-1": _drawing()})

    updated, report = _in_executor(_manifest(("f-1", "x plus y")))

    assert _step(report, "obligation-classify-formula-regions").message == n(
        *MSG_FORMULA_REGIONS_CLASSIFIED, 1
    ).format(count=1, math=0, pictures=1, unresolved=0, already=0, left="-")
    assert _step(report, "verbalize-f-1").status == "skipped"
    assert report.status == "replan-required"
    picture = _by_id(updated, "f-1")
    assert picture.type == "picture" and picture.metadata["vision_description_complete"]
    assert any(item.kind == "describe-image" and item.target_ids == ["f-1"] for item in updated.obligations)


def test_an_uncertain_region_goes_to_human_review(monkeypatch) -> None:
    """Its ``verbalize-formula`` keeps only ``human-review``: the planned
    method no longer applies, so the step is skipped and replanned (M0)."""
    _answers(monkeypatch, {"f-1": _uncertain()})

    updated, report = _in_executor(_manifest(("f-1", "x plus y")))

    assert _by_id(updated, "verbalize-f-1").admissible_methods == ["human-review"]
    assert _step(report, "verbalize-f-1").status == "skipped"
    assert report.status == "replan-required"


def test_a_run_replans_the_picture_a_region_became(monkeypatch, tmp_path) -> None:
    """End to end: the drawing's ``describe-image`` is planned on the
    replan and validated, nothing is verbalized, and the job completes."""
    _answers(monkeypatch, {"f-1": _drawing()})
    verbalized: list[str] = []

    async def nothing(*_args, **_kwargs):
        return None

    monkeypatch.setattr(preflight, "inspect_source_media", nothing)
    monkeypatch.setattr(formula_method, "_enrich_formula_latex", nothing)
    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.executor.registry.register(
        "mathml", lambda _m, obligation_id: verbalized.append(obligation_id) or MethodResult(success=True, validated=True)
    )
    manifest = _manifest(("f-1", "x plus y"))
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    payload = asyncio.run(orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True,
        config=CONFIG, model_calls=current_model_calls(), ports=RunPorts.none(),
    ))

    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert verbalized == []
    assert "A ring of atoms." in payload["text"]


def test_the_method_leaves_the_regions_as_the_step_before_planning_did(monkeypatch) -> None:
    """The differential test of the migration (ADR-0028): the same answers
    give the same elements, before planning as until 0.3.18, and inside the
    plan."""
    from acessilia_core.agents.provider_breaker import ProviderBreaker

    _answers(monkeypatch, {"f-math": _math(), "f-draw": _drawing(), "f-unsure": _uncertain()})

    def build():
        return _manifest(("f-math", "x plus y"), ("f-draw", "a b"), ("f-unsure", "c d"), ("f-latex", r"\sqrt{x}"))

    before = build()
    asyncio.run(formula_stage._classify_formula_regions(
        before, Path("doc.pdf"), mode="medio", vision=CONFIG.vision, toolbox=CONFIG.toolbox,
        models=CONFIG.models, region_cache=None, breaker=ProviderBreaker(CONFIG.vision.breaker_threshold),
    ))

    inside, _ = _in_executor(build())

    assert [element.model_dump() for element in inside.elements] == [
        element.model_dump() for element in before.elements
    ]


@pytest.mark.parametrize("step", [FORMULA_CLASSIFICATION, FORMULA_RECOGNITION])
def test_a_formula_the_vision_model_read_is_not_classified_again(step) -> None:
    """A picture read as a formula (M1) is not asked again whether it is
    mathematics; it still gets its LaTeX step."""
    manifest = _manifest(("f-1", "E = mc2"))
    _by_id(manifest, "f-1").metadata["original_type"] = "picture"

    obligation = reconcile_document_step(manifest, step)

    assert (obligation is None) == (step is FORMULA_CLASSIFICATION)


# The review of #862.


@pytest.mark.parametrize(
    ("element_type", "text"),
    [("paragraph", ""), ("unknown", ""), ("group", ""), ("heading", "Titulo")],
    ids=["paragraph-placeholder", "unknown-placeholder", "group-placeholder", "one-page-fallback"],
)
def test_a_placeholder_the_descriptions_read_as_a_formula_is_not_classified_again(
    monkeypatch, tmp_path, element_type, text
) -> None:
    """Item 1 (blocking): a placeholder visual of a mostly visual document,
    or the first element of a one-page one, that the descriptions (M1) read
    as a formula is not classified on the replan. Asked again, the model
    could read it as a drawing and drop the formula; here it would, so the
    test sees that call never happens, the formula is read and verbalized,
    and the delivered text keeps it."""
    from pddl_support import install_formula_recognizer

    from acessilia_core.pipeline.enrichment import pictures as picture_stage

    described: list[str] = []
    classified: list[str] = []
    verbalized: list[str] = []

    class PictureVision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            described.append(image_bytes.decode())
            return VisionOutput(kind="formula", description="", formula_latex="E = mc2", language="und", confidence=0.9)

    class RegionVision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, *, image_bytes, **_kwargs):
            classified.append(image_bytes.decode())
            return _drawing()  # the contradiction a second answer could bring

    monkeypatch.setattr(picture_stage, "VisionAgent", PictureVision)
    monkeypatch.setattr(
        picture_stage, "_extract_picture_bytes",
        lambda source, element, fallback, *rest, **_kwargs: (element.id.encode(), fallback or 1),
    )
    monkeypatch.setattr(formula_stage, "VisionAgent", RegionVision)
    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", lambda _s, element, **_k: (element.id.encode(), 1))
    install_formula_recognizer(monkeypatch, lambda _image, **_kwargs: [{"latex": "E = mc2"}])

    async def nothing(*_args, **_kwargs):
        return None

    def mathml(manifest, obligation_id):
        element = next(item for item in manifest.elements if item.id == "x")
        verbalized.append(f"{element.type}:{element.text}")
        return MethodResult(success=True, validated=True)

    monkeypatch.setattr(preflight, "inspect_source_media", nothing)
    orchestrator = build_orchestrator(max_replans=1)
    orchestrator.executor.registry.register("mathml", mathml)
    manifest = build_manifest([build_element("x", element_type, text=text)], [])
    orchestrator.information_structural = SimpleNamespace(process=lambda *a, **k: manifest)

    payload = asyncio.run(orchestrator.execute(
        tmp_path / "doc.pdf", tmp_path, structured_output=True,
        config=CONFIG, model_calls=current_model_calls(), ports=RunPorts.none(),
    ))

    assert described == ["x"]
    assert classified == []
    assert verbalized == ["formula:E = mc2"]
    assert payload["canonical_metadata"]["pddl_execution_status"] == "completed"
    assert "E = mc2" in payload["text"] and "A ring of atoms." not in payload["text"]


def test_a_classification_that_got_no_answer_is_tried_again() -> None:
    """Item 2: ``unclassified`` is an attempt, not a decision, so a step that
    runs again retries it, as the other composite steps retry a failed
    object; ``math`` and ``unresolved`` are decisions."""
    manifest = _manifest(("f-failed", "a b"), ("f-math", "c d"), ("f-unsure", "e f"))
    _by_id(manifest, "f-failed").metadata["formula_classification"] = {"status": "unclassified", "reason": "model_failed"}
    _by_id(manifest, "f-math").metadata["formula_classification"] = {"status": "math"}
    _by_id(manifest, "f-unsure").metadata["formula_classification"] = {"status": "unresolved"}

    assert formula_stage.formulas_to_classify(manifest) == ["f-failed"]


def test_a_region_without_a_crop_stays_unclassified_and_takes_the_formula_path(monkeypatch) -> None:
    """Item 2.3: without ``pdf.render`` (no crop) the classification records
    ``crop_unavailable``: no evidence against mathematics, so the formula's
    recognition still runs."""
    _answers(monkeypatch, {})
    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", lambda *_a, **_k: (None, 1))

    updated, report = _in_executor(_manifest(("f-1", "x plus y")))

    assert _by_id(updated, "f-1").metadata["formula_classification"] == {
        "status": "unclassified", "reason": "crop_unavailable", "confidence": None, "warnings": [],
    }
    assert _step(report, "obligation-classify-formula-regions").message == n(
        *MSG_FORMULA_REGIONS_CLASSIFIED, 1
    ).format(count=1, math=0, pictures=0, unresolved=0, already=0, left="crop_unavailable: 1")
    assert _step(report, "obligation-recognize-formulas").status == "succeeded"


def test_the_classification_announces_itself_apart_from_the_recognition(monkeypatch) -> None:
    """Item 4: the two steps send their own progress message."""
    from acessilia_core.i18n.stage_messages import (
        STAGE_CLASSIFYING_FORMULA_REGIONS,
        STAGE_ENRICHING_FORMULAS,
    )

    _answers(monkeypatch, {"f-1": _math()})
    ports = RunPorts.none()
    messages: list[str] = []
    ports.services.progress = messages.append
    reconcile_document_steps(manifest := _manifest(("f-1", "x plus y")))
    handler = build_method_registry().get("formula-region-classifier")

    handler(manifest, "obligation-classify-formula-regions", config=CONFIG, ports=ports)

    assert messages == [t(STAGE_CLASSIFYING_FORMULA_REGIONS)]
    assert t(STAGE_CLASSIFYING_FORMULA_REGIONS) != t(STAGE_ENRICHING_FORMULAS)


def test_a_resumed_attempt_counts_the_regions_decided_before_it(monkeypatch) -> None:
    """Item 4: the message counts this attempt's work; regions a crash left
    decided are counted apart."""
    calls = _answers(monkeypatch, {"f-2": _math()})
    manifest = _manifest(("f-1", "x plus y"), ("f-2", "a b"))
    enrichment = reconcile_document_step(manifest, FORMULA_CLASSIFICATION)
    _by_id(manifest, "f-1").metadata["formula_classification"] = {"status": "math"}
    handler = build_method_registry().get("formula-region-classifier")

    result = handler(manifest, enrichment.id, config=CONFIG, ports=RunPorts.none())

    assert calls == ["f-2"]
    assert result.message == n(*MSG_FORMULA_REGIONS_CLASSIFIED, 2).format(
        count=2, math=1, pictures=0, unresolved=0, already=1, left="-"
    )
