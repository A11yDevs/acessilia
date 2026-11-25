"""The document's prose inline math as a planned action (#640, M4b).

Until 0.3.19 the orchestrator marked the prose's inline math before
planning, and again in a pass after execution over the blocks the plan added
(#599). Now a ``mark-inline-math`` obligation, added when a PDF has prose to
mark, is satisfied by the ``inline-math-marker`` method. A block the plan adds
gets it on a replan, and the formula conversions wait for it.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from core_config_support import core_config, document_config
from pddl_support import build_element, build_manifest, build_obligation
from test_inline_math_marking import (
    DISPLAY_LINE,
    PARAGRAPH_LINE,
    RUN_TOOLBOX,
    _element,
    _manifest,
    _page,
)

from acessilia_core.i18n import n
from acessilia_core.manifest.models import validate_obligation_graph
from acessilia_core.pipeline.document_obligations import (
    INLINE_MATH,
    reconcile_document_step,
    reconcile_document_steps,
)
from acessilia_core.pipeline.handlers.messages import MSG_INLINE_MATH_MARKED
from acessilia_core.pipeline.handlers.registry import build_method_registry
from acessilia_core.pipeline.obligations import _document_work_found, _reopen
from acessilia_core.planning.planner_agent import PlannerAgent
from acessilia_core.ports import RunPorts

CONFIG = replace(core_config(), toolbox=RUN_TOOLBOX)
MARKED = r"inicial ´ e $s_0\in\mathbb{R}$, $h\neq0$"


@pytest.fixture
def spans(monkeypatch):
    calls = []

    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        calls.append(pages)
        return {1: _page(PARAGRAPH_LINE, DISPLAY_LINE)}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)
    return calls


def _by_id(manifest, item_id):
    return next(item for item in [*manifest.elements, *manifest.obligations] if item.id == item_id)


def _verbalize(target: str):
    obligation = build_obligation("verbalize-formula", [target], ["mathml", "human-review"])
    obligation.id = f"verbalize-{target}"
    obligation.method_costs = {"mathml": 10, "human-review": 100}
    return obligation


def _mark(manifest, obligation_id, *, config=CONFIG):
    return build_method_registry().get("inline-math-marker")(
        manifest, obligation_id, config=config, ports=RunPorts.none()
    )


# The obligation.


def test_the_obligation_covers_the_prose_to_mark() -> None:
    """A PDF's prose with boxes and text: the paragraph (``p1``) and the
    detached slash (``slash``). A formula is not prose."""
    manifest = _manifest()

    marking = reconcile_document_step(manifest, INLINE_MATH)

    assert (marking.id, marking.kind) == ("obligation-mark-inline-math", "mark-inline-math")
    assert marking.target_ids == ["p1", "slash"]
    assert marking.admissible_methods == ["inline-math-marker", "human-review"]


@pytest.mark.parametrize("case", ["docx", "no-boxes", "marked"])
def test_prose_with_nothing_to_mark_gets_no_obligation(case) -> None:
    manifest = build_manifest([build_element("p", "paragraph", text="s ( t ) = t 3")], [])
    if case == "docx":
        manifest = _manifest()
        manifest.source.media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    elif case == "marked":
        manifest = _manifest()
        for element in manifest.elements:
            element.metadata["inline_math_detection"] = {"marked": 0, "unmatched": 0}

    assert reconcile_document_step(manifest, INLINE_MATH) is None


def test_the_formula_conversions_wait_for_the_inline_math() -> None:
    """``verbalize-formula`` and ``normalize-formula`` depend on it although
    they share no element; another obligation does not. Reconciled twice,
    the graph is the same DAG, and the plan marks first."""
    manifest = _manifest()
    normalize = build_obligation("normalize-formula", ["f1"], ["latex-normalizer", "human-review"])
    normalize.id = "normalize-f1"
    normalize.method_costs = {"latex-normalizer": 10, "human-review": 100}
    review = build_obligation("review-structure", ["p1"], ["human-review"])
    review.id = "review-p1"
    manifest.obligations.extend([_verbalize("f1"), normalize, review])
    manifest.summary.obligation_count = len(manifest.obligations)

    reconcile_document_steps(manifest)
    once = manifest.model_dump()
    reconcile_document_steps(manifest, replan=True)

    assert manifest.model_dump() == once
    validate_obligation_graph(manifest)
    marking = "obligation-mark-inline-math"
    assert marking in _by_id(manifest, "verbalize-f1").dependencies
    assert marking in _by_id(manifest, "normalize-f1").dependencies
    assert _by_id(manifest, "review-p1").dependencies == [marking]  # it shares p1
    _, plan = PlannerAgent().plan(manifest)
    order = [step.obligation_id for step in plan.steps if step.method]
    assert order.index(marking) < order.index("verbalize-f1")


# The method.


def test_the_method_marks_its_prose_and_reports_it(spans) -> None:
    manifest = _manifest()
    marking = reconcile_document_step(manifest, INLINE_MATH)

    result = _mark(manifest, marking.id)

    assert _by_id(manifest, "p1").text == MARKED
    assert result.message == n(*MSG_INLINE_MATH_MARKED, 2).format(
        count=2, marked=2, elements=1, unmatched=0, detection="fonts"
    )
    assert spans == [[1]]


def test_with_the_detection_off_the_method_changes_nothing(spans) -> None:
    manifest = _manifest()
    marking = reconcile_document_step(manifest, INLINE_MATH)
    off = replace(CONFIG, document=document_config(inline_math_detection="off"))

    result = _mark(manifest, marking.id, config=off)

    assert spans == [] and _by_id(manifest, "p1").text == "inicial ´ e s 0 ∈ R , h = 0"
    assert result.success and result.message.endswith("detection: off")


@pytest.mark.parametrize("converted", [False, True])
def test_marks_after_a_conversion_invalidate_it(spans, converted) -> None:
    """The marks give variables the formula conversions read: when a
    conversion already ran (a replan for an added block), it is dropped so
    the canonical build redoes it; before any conversion ran (the first
    plan), nothing is dropped, so a conversion the extractor gave stays."""
    manifest = _manifest()
    formula = _by_id(manifest, "f1")
    formula.metadata.update({"mathml": "<math/>", "verbalization": "x igual a 1"})
    verbalize = _verbalize("f1")
    verbalize.status = "satisfied" if converted else "candidate"
    manifest.obligations.append(verbalize)
    manifest.summary.obligation_count = len(manifest.obligations)
    marking = reconcile_document_step(manifest, INLINE_MATH)

    _mark(manifest, marking.id)

    assert ("mathml" in formula.metadata) is not converted
    assert ("verbalization" in formula.metadata) is not converted


def test_a_table_whose_marks_went_stale_is_marked_again(monkeypatch) -> None:
    """``select-table-source`` adopted the secondary's cells after the table
    enrichment marked the primary's: the table is flagged, the inline math
    step marks it again, and the flag goes."""
    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        return {1: _page(PARAGRAPH_LINE)}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)
    table = _element("t1", "table", "", 210, 232)
    table.metadata["table_ast"] = {"body": [{"cells": [{"text": "inicial ´ e s 0 ∈ R , h = 0"}]}]}
    table.metadata["inline_math_stale"] = True
    manifest = build_manifest([table], [])
    manifest.pages[0].height = 792.0

    marking = reconcile_document_step(manifest, INLINE_MATH)
    _mark(manifest, marking.id)

    assert marking.target_ids == ["t1"]
    assert "inline_math_stale" not in table.metadata
    assert table.metadata["table_ast"]["body"][0]["cells"][0]["text"] == MARKED


# A run that completed with work for the document steps.


def test_a_completed_run_with_an_added_block_replans_for_it() -> None:
    """``rescue-omitted`` added a paragraph to a completed run: the
    reconciliation gives it the inline math, selected. Finding it does not
    reopen the job; the replan loop does, once the replan is allowed
    (``_reopen``)."""
    manifest = _manifest()
    first = reconcile_document_step(manifest, INLINE_MATH)
    first.status = "satisfied"
    for element in manifest.elements:
        element.metadata["inline_math_detection"] = {"marked": 0, "unmatched": 0}
    manifest.status = "completed"
    manifest.elements.append(_element("p2", "paragraph", "h = 0", 240, 260, reading_order=4))
    manifest.pages[0].element_ids.append("p2")
    manifest.summary.element_count = len(manifest.elements)

    assert _document_work_found(manifest)

    second = _by_id(manifest, "obligation-mark-inline-math-2")
    assert (second.target_ids, second.selected) == (["p2"], True)
    assert manifest.status == "completed"
    _reopen(manifest)
    assert manifest.status == "processing"


def test_a_completed_run_with_nothing_new_does_not_replan() -> None:
    """Every document step ran (its obligations satisfied), and its elements
    stay covered even those it found nothing in: nothing new, no replan."""
    manifest = _manifest()
    reconcile_document_steps(manifest)
    for item in manifest.obligations:
        item.status = "satisfied"
    manifest.status = "completed"

    assert not _document_work_found(manifest)
    assert manifest.status == "completed"


def test_an_obligation_left_open_does_not_fail_the_job() -> None:
    """The step is non-critical: a block left without its marks keeps the
    extractor's text, as with the detection off."""
    from acessilia_core.pipeline.obligations import NON_CRITICAL_OBLIGATION_KINDS

    assert INLINE_MATH.kind in NON_CRITICAL_OBLIGATION_KINDS


# What a run finds after its complete-job, with the discovery budget spent
# (#867 review): the job is not reopened, and what was found follows the
# delivery policy.

PROSE = " ".join(["A long sentence of plain prose, with nothing visual in it."] * 8)


def _finding_run(monkeypatch, tmp_path, added):
    """A run whose one step adds ``added`` (an element, with no obligation),
    with ``max_discovery_replans=0``. Returns the manifest the run built."""
    from pddl_support import build_orchestrator
    from test_changed_obligations import _obligation, _run

    from acessilia_core.execution.models import MethodResult as Result

    manifest = build_manifest([build_element("a", "paragraph", text=PROSE)], [_obligation("o-1", "review-structure", ["a"])])
    orchestrator = build_orchestrator()
    orchestrator.max_discovery_replans = 0
    seen = []

    def review(run_manifest, obligation_id):
        if all(element.id != added.id for element in run_manifest.elements):
            run_manifest.elements.append(added.model_copy(deep=True))
            run_manifest.pages[0].element_ids.append(added.id)
            run_manifest.summary.element_count = len(run_manifest.elements)
        seen.append(run_manifest)
        return Result(success=True, validated=True)

    orchestrator.executor.registry.register("human-review", review)
    _run(orchestrator, manifest, tmp_path, monkeypatch)
    return seen[-1]


def test_a_critical_step_found_with_the_budget_spent_fails_the_job(monkeypatch, tmp_path) -> None:
    """A table added without obligations gets ``enrich-tables`` from the
    reconciliation after the run completed: with no replan left, the job
    fails instead of shipping the table unread."""
    table = build_element("t-added", "table", text="a b", reading_order=2)

    with pytest.raises(RuntimeError, match="enrich-tables"):
        _finding_run(monkeypatch, tmp_path, table)


def test_a_refinement_found_with_the_budget_spent_is_delivered_as_completed(monkeypatch, tmp_path) -> None:
    """Only the non-critical inline math is found: the document is delivered
    (with a warning), and the job keeps the completed status."""
    evidence = build_element("p-added", "paragraph", text="com $h \\neq 0$ aqui", reading_order=2)

    manifest = _finding_run(monkeypatch, tmp_path, evidence)

    assert manifest.status == "completed"
    marking = _by_id(manifest, "obligation-mark-inline-math")
    assert marking.target_ids == ["p-added"] and marking.status != "satisfied"


# A table marked, then adopted again (#867 review).


def _stale_table(monkeypatch):
    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        return {1: _page(PARAGRAPH_LINE)}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)
    table = _element("t1", "table", "", 210, 232)
    table.metadata["table_ast"] = {"body": [{"cells": [{"text": "inicial ´ e s 0 ∈ R , h = 0"}]}]}
    table.metadata["inline_math_stale"] = True
    manifest = build_manifest([table], [])
    manifest.pages[0].height = 792.0
    reconcile_document_steps(manifest)
    # The table enrichment ran before: only the inline math is left.
    _by_id(manifest, "obligation-enrich-tables").status = "satisfied"
    return manifest, table, _by_id(manifest, "obligation-mark-inline-math")


def test_a_table_stale_again_after_its_marks_joins_a_new_obligation(monkeypatch) -> None:
    """The step marked the table (its obligation satisfied); a later adoption
    replaced the cells and flagged it again. The satisfied obligation no
    longer covers it: a new one, selected, marks the new cells. Reconciled
    again, nothing more is created."""
    manifest, table, first = _stale_table(monkeypatch)
    _mark(manifest, first.id)
    first.status = "satisfied"
    table.metadata.pop("inline_math_detection", None)
    table.metadata["table_ast"] = {"body": [{"cells": [{"text": "inicial ´ e s 0 ∈ R , h = 0"}]}]}
    table.metadata["inline_math_stale"] = True

    assert _document_work_found(manifest)
    second = _by_id(manifest, "obligation-mark-inline-math-2")
    assert (second.target_ids, second.selected) == (["t1"], True)
    once = manifest.model_dump()
    reconcile_document_steps(manifest, replan=True)
    assert manifest.model_dump() == once

    _mark(manifest, second.id)
    second.status = "satisfied"
    assert "inline_math_stale" not in table.metadata
    assert table.metadata["table_ast"]["body"][0]["cells"][0]["text"] == MARKED
    assert not _document_work_found(manifest)


def test_a_stale_table_an_exhausted_obligation_covers_is_not_reopened(monkeypatch) -> None:
    """A failed attempt keeps covering it: no obligation is created again and
    again for a table the step could not mark."""
    manifest, _, first = _stale_table(monkeypatch)
    first.status = "failed"

    assert not _document_work_found(manifest)
    assert [item.id for item in manifest.obligations if item.kind == INLINE_MATH.kind] == [first.id]


# Evidence the detection cannot read (#867 review: the cases of #599).


@pytest.mark.parametrize("converted", [False, True])
def test_a_block_without_boxes_that_carries_inline_math_is_weighed(spans, converted) -> None:
    """A block added without boxes (a rescued paragraph) that already carries
    ``$…$`` is variable evidence the conversions may not have seen: it joins
    the step, which marks nothing in it but drops a conversion made before
    it, as the pass after execution did."""
    manifest = _manifest()
    for element in manifest.elements:
        element.metadata["inline_math_detection"] = {"marked": 0, "unmatched": 0}
    formula = _by_id(manifest, "f1")
    formula.metadata.update({"mathml": "<math/>", "verbalization": "x igual a 1"})
    verbalize = _verbalize("f1")
    verbalize.status = "satisfied" if converted else "candidate"
    manifest.obligations.append(verbalize)
    added = build_element("p-added", "paragraph", text="com $h \\neq 0$", reading_order=4)
    manifest.elements.append(added)
    manifest.pages[0].element_ids.append("p-added")
    manifest.summary.element_count = len(manifest.elements)
    manifest.summary.obligation_count = len(manifest.obligations)

    marking = reconcile_document_step(manifest, INLINE_MATH, replan=True)
    _mark(manifest, marking.id)

    assert marking.target_ids == ["p-added"]
    assert spans == []  # nothing to read: the block has no boxes
    assert ("mathml" in formula.metadata) is not converted


def test_a_block_without_boxes_or_inline_math_is_not_a_target() -> None:
    manifest = build_manifest([build_element("p", "paragraph", text="no math here")], [])

    assert reconcile_document_step(manifest, INLINE_MATH) is None


# The step is non-critical (#867 review).


def test_an_exhausted_inline_math_does_not_block_the_formula_conversions() -> None:
    """The marker failed with no method left: the conversions that waited for
    it lose that edge and are planned without its variables, instead of
    being left out of the replan and failing the job."""
    from acessilia_core.pipeline.obligations import _replannable_obligation_ids

    manifest = _manifest()
    manifest.obligations.append(_verbalize("f1"))
    reconcile_document_steps(manifest)
    marking = _by_id(manifest, "obligation-mark-inline-math")
    marking.status, marking.selected = "failed", False
    verbalize = _by_id(manifest, "verbalize-f1")
    verbalize.selected = True

    reconcile_document_steps(manifest, replan=True)

    assert marking.id not in verbalize.dependencies
    assert "verbalize-f1" in _replannable_obligation_ids(manifest)
    validate_obligation_graph(manifest)


def test_a_critical_step_exhausted_still_blocks_its_dependents() -> None:
    """Only a non-critical step releases them: an exhausted table enrichment
    still holds the table's own obligations."""
    from acessilia_core.pipeline.document_obligations import TABLE_ENRICHMENT

    assert TABLE_ENRICHMENT.critical and not INLINE_MATH.critical


@pytest.mark.parametrize(
    ("media", "detection", "recorded", "expected"),
    [
        ("application/pdf", "fonts", None, "fonts"),
        ("application/pdf", "fonts", "unavailable", "unavailable"),
        ("application/pdf", "off", None, "off"),
        ("text/html", "fonts", None, "off"),
    ],
)
def test_the_detection_status_both_steps_report(media, detection, recorded, expected) -> None:
    from acessilia_core.pipeline.enrichment.inline_math import (
        inline_math_detection_status,
    )

    manifest = _manifest()
    manifest.source.media_type = media
    if recorded:
        manifest.extractor.configuration["inline_math_detection"] = recorded

    assert inline_math_detection_status(manifest, document_config(inline_math_detection=detection)) == expected
