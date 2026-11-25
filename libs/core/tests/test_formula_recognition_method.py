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
from copy import deepcopy
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


#: Classified as mathematics already, so the region classification (M4) has
#: nothing to ask and these tests see the formula LaTeX step alone.
_CLASSIFIED = {"formula_classification": {"status": "math", "reason": None, "confidence": 0.9, "warnings": []}}


def _formula(element_id: str, text: str):
    return build_element(element_id, "formula", text=text, metadata=deepcopy(_CLASSIFIED))


def _formulas_manifest(*formulas: tuple[str, str], media_type: str = "application/pdf") -> ProcessingManifest:
    elements = [build_element("prose", "paragraph", text=_PROSE)]
    elements += [_formula(element_id, text) for element_id, text in formulas]
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
def test_two_document_steps_share_an_element_only_in_their_order(element_type) -> None:
    """The policy between the document steps (#845 review, M4): two steps
    share an element only when the first must run before the second, and
    ``DOCUMENT_STEPS`` lists them so. Today only a formula is shared: the
    region classification, then the formula LaTeX."""
    from acessilia_core.pipeline.document_obligations import (
        FORMULA_CLASSIFICATION,
        INLINE_MATH,
        PICTURE_DESCRIPTION,
        TABLE_ENRICHMENT,
    )

    element = build_element("x", element_type, text="")
    taking = [step for step in DOCUMENT_STEPS if step.applies(element)]

    # M4b: the inline math takes the prose (a paragraph the descriptions
    # may take first, in a mostly visual document) and a table whose marks
    # went stale after its enrichment.
    expected = {
        "formula": [FORMULA_CLASSIFICATION, FORMULA_RECOGNITION],
        "paragraph": [PICTURE_DESCRIPTION, INLINE_MATH],
        "table": [TABLE_ENRICHMENT, INLINE_MATH],
    }
    if element_type in expected:
        assert taking == expected[element_type]
    else:
        assert len(taking) <= 1


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
    manifest.elements.append(_formula("f-2", ""))
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


def test_a_formula_selected_for_its_label_is_not_recognized_again(monkeypatch) -> None:
    """#851 review, item 2: the selection and the execution share one policy.
    A formula with a recognition record is a target only for its equation
    label: the label is separated, and the recognizer is not called again
    nor the record overwritten."""
    calls = _recognizer(monkeypatch)
    manifest = _formulas_manifest(("f-1", "s ( t ) = t (2)"))
    record = {"method": "text-layer", "rejected": {"math.recognize": 0.1}}
    _by_id(manifest, "f-1").metadata["formula_recognition"] = dict(record)
    enrichment = reconcile_document_step(manifest, FORMULA_RECOGNITION)
    handler = build_method_registry().get("formula-recognizer")

    result = handler(manifest, enrichment.id, config=CONFIG, ports=RunPorts.none())

    assert enrichment.target_ids == ["f-1"]
    assert calls == []
    formula = _by_id(manifest, "f-1")
    assert formula.metadata["formula_recognition"] == record
    assert formula.metadata["equation_number"] == "2"
    assert result.message == n(*MSG_FORMULAS_RECOGNIZED, 1).format(
        count=1, recognized=0, methods="-", numbered=1, pictures=0, left="-"
    )


def test_the_step_announces_itself_once(monkeypatch) -> None:
    """#851 review, item 1: the method and the stage both sent
    ``STAGE_ENRICHING_FORMULAS``. The method announces the step; each formula
    then reports its own progress."""
    from acessilia_core.i18n.stage_messages import STAGE_ENRICHING_FORMULAS

    _recognizer(monkeypatch)
    ports = RunPorts.none()
    messages: list[str] = []
    ports.services.progress = messages.append

    _in_executor(_formulas_manifest(("f-1", "")), ports=ports)

    assert messages.count(t(STAGE_ENRICHING_FORMULAS)) == 1
    assert len(messages) == 2  # the step, then its one formula


@pytest.mark.parametrize(("page", "reason"), [(1, "crop_unavailable"), (0, "no_page")])
def test_a_formula_without_a_crop_says_why(monkeypatch, page, reason) -> None:
    """#851 review, item 3.4: a formula whose crop could not be made records
    the reason, as a picture does, instead of being reported unchanged."""
    calls = _recognizer(monkeypatch)
    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", lambda *_a, **_k: (None, page))

    updated, report = _in_executor(_formulas_manifest(("f-1", "")))

    assert calls == []
    assert _by_id(updated, "f-1").metadata["formula_recognition_failure"] == reason
    assert _step(report, "obligation-recognize-formulas").message == n(*MSG_FORMULAS_RECOGNIZED, 1).format(
        count=1, recognized=0, methods="-", numbered=0, pictures=0, left=f"{reason}: 1"
    )


def test_a_formula_left_without_latex_is_not_taken_as_readable(monkeypatch) -> None:
    """#851 review, item 3.1: the collective attempt succeeds, but a formula
    it could not read keeps no readable content, so its ``verbalize-formula``
    stays critical: the step's success never makes it accessible."""
    from acessilia_core.pipeline.obligations import _formula_has_readable_content

    _recognizer(monkeypatch, latex=None)

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, **_kwargs):
            return None

    monkeypatch.setattr(formula_stage, "VisionAgent", Vision)

    updated, report = _in_executor(_formulas_manifest(("f-1", "")))

    assert _step(report, "obligation-recognize-formulas").status == "succeeded"
    formula = _by_id(updated, "f-1")
    assert formula.text == "" and formula.metadata["formula_recognition_failure"] == "model_failed"
    assert not _formula_has_readable_content(_by_id(updated, "verbalize-f-1"), updated)


def test_each_obligation_probes_math_recognize_once(monkeypatch) -> None:
    """#851 review, item 3.3: the outage is paid once per obligation (one
    batch), not once per formula; a second obligation probes again."""
    from acessilia_core.toolbox.toolbox_math_tools import MathCapabilityUnavailable
    from acessilia_sdk.toolbox.errors import ToolboxError

    calls: list[str] = []

    def down(image, **_kwargs):
        calls.append(image.decode())
        raise MathCapabilityUnavailable("math.recognize", ToolboxError("down"))

    install_formula_recognizer(monkeypatch, down)
    monkeypatch.setattr(
        formula_stage, "_formula_recognition_crop", lambda _source, element, **_kwargs: (element.id.encode(), 1)
    )

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, **_kwargs):
            return None

    monkeypatch.setattr(formula_stage, "VisionAgent", Vision)
    manifest = _formulas_manifest(("f-1", ""), ("f-2", ""))
    first = reconcile_document_step(manifest, FORMULA_RECOGNITION)
    handler = build_method_registry().get("formula-recognizer")
    handler(manifest, first.id, config=CONFIG, ports=RunPorts.none())
    first.status = "satisfied"
    manifest.elements.append(_formula("f-3", ""))
    manifest.obligations.append(_verbalize("f-3"))
    manifest.summary.element_count = len(manifest.elements)
    second = reconcile_document_step(manifest, FORMULA_RECOGNITION, replan=True)

    handler(manifest, second.id, config=CONFIG, ports=RunPorts.none())

    assert len(calls) == 2 and calls[-1] == "f-3"


def test_an_outage_of_math_recognize_falls_back_to_the_vision_model(monkeypatch) -> None:
    """#846 acceptance: with ``math.recognize`` down, the vision fallback
    reads the formula, and the message says which method did."""
    from acessilia_core.toolbox.toolbox_math_tools import MathCapabilityUnavailable
    from acessilia_sdk.toolbox.errors import ToolboxError

    def down(_image, **_kwargs):
        raise MathCapabilityUnavailable("math.recognize", ToolboxError("down"))

    install_formula_recognizer(monkeypatch, down)
    monkeypatch.setattr(formula_stage, "_formula_recognition_crop", lambda *_a, **_k: (b"crop", 1))
    asked: list[str] = []

    class Vision:
        def __init__(self, mode, *, region_cache, toolbox, models):
            pass

        async def describe_region(self, **kwargs):
            asked.append(kwargs.get("classification", ""))
            return VisionOutput(
                kind="formula", description="", formula_latex=r"\frac{a}{b}", language="und", confidence=0.9
            )

    monkeypatch.setattr(formula_stage, "VisionAgent", Vision)

    updated, report = _in_executor(_formulas_manifest(("f-1", "")))

    assert len(asked) == 1
    formula = _by_id(updated, "f-1")
    assert formula.text == r"\frac{a}{b}"
    assert formula.metadata["formula_recognition"]["method"] == "vision"
    assert _step(report, "obligation-recognize-formulas").message == n(*MSG_FORMULAS_RECOGNIZED, 1).format(
        count=1, recognized=1, methods="vision: 1", numbered=0, pictures=0, left="-"
    )


def test_only_ordered_document_steps_share_pending_elements() -> None:
    """The policy, on the steps' real selections (#851 review, item 3.9; M4):
    an element is pending for two steps only for the region classification
    and the formula LaTeX, which run in that order."""
    from acessilia_core.pipeline.document_obligations import FORMULA_CLASSIFICATION

    manifest = build_manifest(
        [
            build_element("prose", "paragraph", text=_PROSE),
            build_element("p-1", "picture", text=""),
            build_element("f-1", "formula", text=""),
            build_element("f-2", "formula", text=r"x \qquad (1)"),
            build_element("t-1", "table", text="a b"),
        ],
        [],
    )

    pending = {step.kind: set(step.pending(manifest)) for step in DOCUMENT_STEPS}
    shared = {
        (a, b): pending[a] & pending[b]
        for i, a in enumerate(pending) for b in list(pending)[i + 1:]
        if pending[a] & pending[b]
    }

    assert shared == {(FORMULA_CLASSIFICATION.kind, FORMULA_RECOGNITION.kind): {"f-1"}}
    assert set().union(*pending.values()) == {"p-1", "f-1", "f-2", "t-1"}


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
