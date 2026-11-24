"""The document's formula LaTeX as a planned action (#640, M3, #846).

Until 0.3.14 the orchestrator read the formulas' LaTeX before planning. Now a
``recognize-formulas`` obligation, added when the document has formulas to
recognize or equation labels to separate, is satisfied by the
``formula-recognizer`` method, which runs the same step. These tests pin the
obligation, its place in the plan, the method, and its equivalence with the
step before planning.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from core_config_support import core_config
from pddl_support import (
    build_element,
    build_manifest,
    build_obligation,
    build_orchestrator,
    install_formula_recognizer,
)

from acessilia_core.agents.output_schemas import VisionOutput
from acessilia_core.i18n import n, t
from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.pipeline.document_obligations import (
    DOCUMENT_STEPS,
    FORMULA_RECOGNITION,
    reconcile_document_step,
    reconcile_document_steps,
)
from acessilia_core.pipeline.enrichment import formulas as formula_stage
from acessilia_core.pipeline.handlers.messages import (
    MSG_FORMULAS_RECOGNIZED,
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
    obligation.method_costs = {"mathml": 20, "human-review": 100}
    return obligation


def _formulas_manifest(*formulas: tuple[str, str], media_type: str = "application/pdf") -> ProcessingManifest:
    elements = [build_element("prose", "paragraph", text=_PROSE)]
    elements += [build_element(element_id, "formula", text=text) for element_id, text in formulas]
    manifest = build_manifest(elements, [_verbalize(element_id) for element_id, _ in formulas])
    manifest.source.media_type = media_type
    return manifest


def _by_id(manifest, item_id):
    return next(item for item in [*manifest.elements, *manifest.obligations] if item.id == item_id)


def _recognizer(monkeypatch, latex: str | None = r"\frac{a}{b}") -> list[bytes]:
    """``math.recognize`` answers every crop with ``latex`` (none with ``None``)."""
    calls: list[bytes] = []

    def answer(image, **_kwargs):
        calls.append(image)
        return [{"latex": latex}] if latex else []

    install_formula_recognizer(monkeypatch, answer)
    monkeypatch.setattr(
        formula_stage, "_formula_recognition_crop", lambda _source, element, **_kwargs: (element.id.encode(), 1)
    )
    return calls


def _in_executor(manifest, *, ports=None):
    reconcile_document_steps(manifest)
    executor = build_orchestrator().executor
    executor.registry = bind_run(build_method_registry(), CONFIG, ports or RunPorts.none())
    _, plan = PlannerAgent().plan(manifest)
    return executor.execute(plan, manifest)


def _step(report, obligation_id):
    return next(step for step in report.steps if step.obligation_id == obligation_id)


# The obligation.


def test_the_obligation_covers_the_formulas_the_step_has_work_on() -> None:
    manifest = _formulas_manifest(
        ("f-empty", ""),                          # no LaTeX: recognized
        ("f-text", "s ( t ) = t 3"),              # text layer: recognized
        ("f-latex", r"\frac{a}{b}"),              # LaTeX, nothing to do
        ("f-numbered", r"\frac{a}{b} \qquad (2)"),  # LaTeX with a label to separate
    )
    _by_id(manifest, "f-text").metadata["formula_recognition"] = {"method": "text-layer"}

    enrichment = reconcile_document_step(manifest, FORMULA_RECOGNITION)

    assert (enrichment.id, enrichment.kind) == ("obligation-recognize-formulas", "recognize-formulas")
    assert enrichment.target_ids == ["f-empty", "f-numbered"]
    assert enrichment.admissible_methods == ["formula-recognizer", "human-review"]
    assert _by_id(manifest, "verbalize-f-empty").dependencies == [enrichment.id]
    assert _by_id(manifest, "verbalize-f-latex").dependencies == []


def test_a_source_without_pages_to_render_only_separates_labels() -> None:
    """A DOCX formula is not recognized (no crop), as before planning; its
    equation label is still separated."""
    docx = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    manifest = _formulas_manifest(("f-empty", ""), ("f-numbered", r"x = 1 \qquad (4)"), media_type=docx)

    enrichment = reconcile_document_step(manifest, FORMULA_RECOGNITION)

    assert enrichment.target_ids == ["f-numbered"]


def test_a_manifest_whose_formulas_were_recognized_gets_no_obligation() -> None:
    """An enrichment checkpoint from 0.3.14 read its formulas before planning."""
    manifest = _formulas_manifest(("f-1", r"\frac{a}{b}"))

    assert reconcile_document_step(manifest, FORMULA_RECOGNITION) is None


def test_the_plan_recognizes_the_formulas_before_it_verbalizes_them() -> None:
    manifest = _formulas_manifest(("f-1", ""))
    reconcile_document_steps(manifest)

    _, plan = PlannerAgent().plan(manifest)

    order = [step.obligation_id for step in plan.steps if step.method]
    assert order.index("obligation-recognize-formulas") < order.index("verbalize-f-1")


@pytest.mark.parametrize("element_type", ["picture", "formula", "table", "heading", "paragraph"])
def test_no_two_document_steps_take_the_same_element(element_type) -> None:
    """The policy between the document steps (#845 review): none shares an
    element with another, so none depends on another."""
    element = build_element("x", element_type, text="")

    assert sum(step.applies(element) for step in DOCUMENT_STEPS) <= 1


# The method.


def test_the_method_recognizes_and_separates_and_reports_each_formula(monkeypatch) -> None:
    calls = _recognizer(monkeypatch)
    manifest = _formulas_manifest(("f-empty", ""), ("f-numbered", r"\frac{c}{d} \qquad (2)"))

    updated, report = _in_executor(manifest)

    assert calls == [b"f-empty"]
    step = _step(report, "obligation-recognize-formulas")
    assert step.status == "succeeded"
    assert step.message == n(*MSG_FORMULAS_RECOGNIZED, 2).format(
        count=2, recognized=1, methods="math.recognize: 1", numbered=1, pictures=0, left="-"
    )
    assert _by_id(updated, "f-empty").text == r"\frac{a}{b}"
    assert _by_id(updated, "f-numbered").metadata["equation_number"] == "2"


def test_the_method_without_formulas_fails_instead_of_raising() -> None:
    manifest = _formulas_manifest(("f-1", ""))
    enrichment = reconcile_document_step(manifest, FORMULA_RECOGNITION)
    manifest.elements = [element for element in manifest.elements if element.id != "f-1"]
    handler = build_method_registry().get("formula-recognizer")

    result = handler(manifest, enrichment.id, config=CONFIG, ports=RunPorts.none())

    assert (result.success, result.message) == (False, t(MSG_MATH_NO_FORMULA))


def test_a_second_obligation_reads_only_its_own_formulas(monkeypatch) -> None:
    calls = _recognizer(monkeypatch, latex=None)
    manifest = _formulas_manifest(("f-1", ""))
    first = reconcile_document_step(manifest, FORMULA_RECOGNITION)
    first.status = "satisfied"
    manifest.elements.append(build_element("f-2", "formula", text=""))
    manifest.obligations.append(_verbalize("f-2"))
    manifest.summary.element_count = len(manifest.elements)
    second = reconcile_document_step(manifest, FORMULA_RECOGNITION, replan=True)
    handler = build_method_registry().get("formula-recognizer")

    result = handler(manifest, second.id, config=CONFIG, ports=RunPorts.none())

    assert second.selected and second.target_ids == ["f-2"]
    assert calls == [b"f-2"]
    assert result.success


def test_a_formula_the_fallback_reads_as_a_picture_replaces_its_obligations(monkeypatch) -> None:
    """``math.recognize`` gives nothing and the vision fallback describes a
    drawing: the formula becomes a picture, its ``verbalize-formula`` is
    replaced by a ``describe-image``, and the executor replans (M0)."""
    _recognizer(monkeypatch, latex=None)

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, **_kwargs):
            return VisionOutput(kind="description", description="A ring of atoms.", language="en", confidence=0.9)

    monkeypatch.setattr(formula_stage, "VisionAgent", Vision)
    manifest = _formulas_manifest(("f-1", ""))

    updated, report = _in_executor(manifest)

    assert _step(report, "obligation-recognize-formulas").message == n(*MSG_FORMULAS_RECOGNIZED, 1).format(
        count=1, recognized=0, methods="-", numbered=0, pictures=1, left="-"
    )
    assert _step(report, "verbalize-f-1").status == "skipped"
    assert report.status == "replan-required"
    assert _by_id(updated, "f-1").type == "picture"


def test_the_method_leaves_the_formulas_as_the_step_before_planning_did(monkeypatch) -> None:
    """The differential test of the migration (ADR-0028): the same answers
    give the same elements before planning, as until 0.3.14, and as the
    method inside the plan."""
    _recognizer(monkeypatch)

    def build():
        return _formulas_manifest(
            ("f-empty", ""), ("f-numbered", r"\frac{c}{d} \qquad (2)"), ("f-latex", r"\sqrt{x}"),
        )

    before = build()
    asyncio.run(formula_stage._enrich_formula_latex(
        before, Path("doc.pdf"), mode="medio", document=CONFIG.document, vision=CONFIG.vision,
        toolbox=CONFIG.toolbox, models=CONFIG.models, region_cache=None,
    ))

    inside, _ = _in_executor(build())

    assert [element.model_dump() for element in inside.elements] == [
        element.model_dump() for element in before.elements
    ]
