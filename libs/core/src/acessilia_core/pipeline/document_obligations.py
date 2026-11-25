"""Document-level obligations: one planned action over many elements (#640).

A step that works on the whole document (one provider breaker, one retry
pass, one progress counter) becomes one obligation that targets every element
it works on, instead of one per element: a per-element method would wait the
retry pass once per failing element, and the elements after the breaker
opened would lose the recovery (``docs/architecture/workflow-actions.md``).

Five steps are planned this way, in ``DOCUMENT_STEPS`` order:
- the formula region classification (``classify-formula-regions``, method
  ``formula-region-classifier``, M4a);
- the picture descriptions (``describe-images``, method
  ``picture-description``, M1);
- the formula LaTeX (``recognize-formulas``, method ``formula-recognizer``,
  M3);
- the table enrichment (``enrich-tables``, method ``table-enrichment``, M2);
- the prose's inline math (``mark-inline-math``, method
  ``inline-math-marker``, M4b), last: a table it marks again went stale
  after its enrichment, and the formula conversions wait for it whatever
  their targets (``waiting_kinds``).

Each one is a :class:`DocumentStep`, and :func:`reconcile_document_step`
creates its obligation when the manifest is enriched and reconciles it again
before each replan (#832):

- an element no obligation of the step covers, and that needs the step, joins
  the open one, or, when the existing ones are closed (satisfied or
  exhausted), a new one for the new elements only. Reopening a satisfied one
  would leave satisfied obligations after an open one; an exhausted one is
  not planned again, so an element joining it would never be worked on. A
  satisfied obligation does not cover an element whose result the run
  invalidated since (``DocumentStep.renewed``: M4b's stale tables), which
  joins a new one the same way;
- an obligation drops the elements the step no longer applies to (removed
  from the document, or of another type now), and one left without elements
  is removed, with the dependencies on it (``target_ids`` cannot be empty);
- every open obligation whose targets include one of the step's elements
  depends on the step's open obligation for that element, and only on those:
  an edge to an obligation of the step, open or closed, that no longer
  shares an element with it (the step lost the element, or the obligation
  was retargeted) is dropped. Only this rule makes edges to the step's
  obligations, so the edges it drops are its own; an edge to a closed one
  stays while the element that justified it does. Otherwise an edge to an
  exhausted one would block its dependents from being replanned at all.

  It is a rule on targets, not a list of kinds: besides the element's own
  obligations (``linearize-table``, ``describe-image``, ``verbalize-formula``
  and ``normalize-formula``), it orders the page
  obligations (``refine-reading-order``, ``fuse-providers``,
  ``adjudicate-page``) of a page with such an element, whose targets are the
  page's elements. That is the order of the releases where the step ran
  before planning, at the cost of serializing those page obligations behind
  it. A future step that must run *before* it is not one this rule should
  order: it needs an exclusion here.

  Between the document's steps, the policy is explicit (#845 review): two
  steps share elements only when the first must run before the second, and
  ``DOCUMENT_STEPS`` lists them in that order. The rule follows it: a step's
  obligation may depend on an earlier step's that shares an element, never
  on a later one's, so it can never make a cycle between them. Today the
  formula region classification and the formula LaTeX share the formulas
  (M4: the recognition waits for the classification); the inline math
  (M4b) shares a paragraph with the descriptions (in a mostly visual
  document) and a stale table with the table enrichment, after both. The
  descriptions never take a table or a formula (``is_describable``), and the
  table step only tables, so no other pair shares one.

  So the order between the steps is not a dependency: the planner breaks
  the tie (their costs are equal), and ``DOCUMENT_STEPS`` is the order of the
  reconciliation, not of the plan. The steps share the run's vision
  breaker, so under a partial provider outage the step the plan runs first
  spends the breaker's budget first; that is an operational effect, not a
  data dependency, and no edge forces the order before planning (#853).

The step that removes an element must also remove or retarget that element's
own obligations and the page's ``element_ids``; the manifest refuses dangling
targets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    MSG_OBLIGATION_FORMULA_CLASSIFICATION,
    MSG_OBLIGATION_FORMULA_RECOGNITION,
    MSG_OBLIGATION_INLINE_MATH,
    MSG_OBLIGATION_PICTURE_DESCRIPTION,
    MSG_OBLIGATION_TABLE_ENRICHMENT,
)
from acessilia_core.manifest.builder import DEFAULT_METHOD_COSTS
from acessilia_core.manifest.models import (
    ManifestElement,
    Obligation,
    ProcessingManifest,
)
from acessilia_core.pipeline.enrichment.formulas import (
    formulas_to_classify,
    formulas_to_recognize,
)
from acessilia_core.pipeline.enrichment.inline_math import (
    inline_math_pending,
    inline_math_renewed,
)
from acessilia_core.pipeline.enrichment.pictures import (
    description_candidates,
    is_describable,
)

#: Statuses after which an obligation is not planned again: satisfied, or
#: exhausted (every automatic method failed).
CLOSED_STATUSES = frozenset({"satisfied", "failed"})


@dataclass(frozen=True)
class DocumentStep:
    """A document-wide step planned as one obligation over its elements."""

    #: The obligation's kind and its method; ``human-review`` is the only alternative.
    kind: str
    method: str
    #: The first obligation's id; later ones get ``-2``, ``-3``, …
    obligation_id: str
    #: The msgid of the obligation's rationale.
    rationale: str
    #: Whether the step still applies to an element it covers. One it no
    #: longer applies to is dropped from the step's obligations.
    applies: Callable[[ManifestElement], bool]
    #: The elements that need the step, in document order: the ones an
    #: uncovered element joins the step with.
    pending: Callable[[ProcessingManifest], list[str]]
    #: Obligation kinds that wait for the step's open obligations whatever
    #: their targets: the step's result is evidence they read across the
    #: document, not on their own elements (M4b: the formula conversions read
    #: the variables the prose's inline math marks). A minimal, declared
    #: dependency; declaring predecessors between steps in general is #865.
    waiting_kinds: frozenset[str] = frozenset()
    #: The pending elements whose earlier result the run invalidated: a
    #: satisfied obligation of the step no longer covers them, so they join
    #: a new one (M4b: a table whose inline math marks went stale after the
    #: step marked it). An open or exhausted obligation still covers them,
    #: so a degraded attempt is not reopened forever.
    renewed: Callable[[ProcessingManifest], set[str]] = lambda _manifest: set()
    #: Whether the step's result is needed to deliver: with ``False``, an
    #: exhausted obligation of the step is a degradation, and the obligations
    #: that waited for it are planned without it (M4b: a formula conversion
    #: reads fewer variables, as with the detection off).
    critical: bool = True


def _pictures_pending(manifest: ProcessingManifest) -> list[str]:
    return [
        element.id
        for element in description_candidates(manifest)
        if not element.metadata.get("vision_description_complete")
    ]


#: The document's table enrichment (M2): every table, so its
#: ``linearize-table`` and ``select-table-source`` wait for the reading.
TABLE_ENRICHMENT = DocumentStep(
    kind="enrich-tables",
    method="table-enrichment",
    obligation_id="obligation-enrich-tables",
    rationale=MSG_OBLIGATION_TABLE_ENRICHMENT,
    applies=lambda element: element.type == "table",
    pending=lambda manifest: [
        element.id for element in manifest.elements if element.type == "table"
    ],
)

#: The document's picture descriptions (M1): the elements the vision model
#: describes and that are not described yet, so a manifest whose pictures are
#: all described (an enrichment checkpoint from before 0.3.14) gets none. A
#: picture the model reads as a formula becomes a formula, which the step no
#: longer applies to; the element's ``describe-image`` is then replaced by the
#: formula's obligations, which the replan plans. ``applies`` and the
#: candidates share ``is_describable``, so the step never takes an element it
#: would then drop.
PICTURE_DESCRIPTION = DocumentStep(
    kind="describe-images",
    method="picture-description",
    obligation_id="obligation-describe-images",
    rationale=MSG_OBLIGATION_PICTURE_DESCRIPTION,
    applies=is_describable,
    pending=_pictures_pending,
)

#: The document's formula LaTeX (M3, #846): the formulas with an equation
#: label to separate or, in a source that can be rendered, without LaTeX and
#: not recognized yet. A formula the descriptions find while the plan runs
#: gets one on the replan, so its ``verbalize-formula`` and
#: ``normalize-formula`` wait for its recognition, as before planning until
#: 0.3.14. A formula the recognition reads as a picture becomes one, which the
#: step no longer applies to.
FORMULA_RECOGNITION = DocumentStep(
    kind="recognize-formulas",
    method="formula-recognizer",
    obligation_id="obligation-recognize-formulas",
    rationale=MSG_OBLIGATION_FORMULA_RECOGNITION,
    applies=lambda element: element.type == "formula",
    pending=formulas_to_recognize,
)

#: The document's formula region classification (M4a): the formulas without
#: LaTeX in a source that can be rendered, not decided yet, and not turned
#: into a formula by the descriptions (``formulas_needing_classification``). It shares the formulas with the
#: formula LaTeX, which comes after it in ``DOCUMENT_STEPS``, so their
#: recognition waits for it, as before planning until 0.3.18. A drawing it
#: describes becomes a picture, which it no longer applies to.
FORMULA_CLASSIFICATION = DocumentStep(
    kind="classify-formula-regions",
    method="formula-region-classifier",
    obligation_id="obligation-classify-formula-regions",
    rationale=MSG_OBLIGATION_FORMULA_CLASSIFICATION,
    applies=lambda element: element.type == "formula",
    pending=formulas_to_classify,
)

#: The document's prose inline math (M4b): in a PDF, the prose elements no
#: detection has marked yet and the tables whose marks went stale. A block
#: the plan adds gets it on the replan, which replaced the pass after
#: execution of #599. The formula conversions wait for it whatever their
#: targets (``waiting_kinds``): they mark implicit products with the
#: variables the prose's inline math gives, as before planning until 0.3.19.
INLINE_MATH = DocumentStep(
    kind="mark-inline-math",
    method="inline-math-marker",
    obligation_id="obligation-mark-inline-math",
    rationale=MSG_OBLIGATION_INLINE_MATH,
    applies=lambda element: element.type in {"paragraph", "list_item", "caption", "footnote", "table"},
    pending=inline_math_pending,
    waiting_kinds=frozenset({"verbalize-formula", "normalize-formula"}),
    renewed=inline_math_renewed,
    critical=False,
)

#: The formula region classification, the descriptions (which can find
#: formulas), the formula LaTeX, the tables, then the prose's inline math.
#: Two steps share elements only when the first must run before the second:
#: the classification, then the formula LaTeX, on a formula; the
#: descriptions, then the inline math, on a paragraph of a mostly visual
#: document; the table enrichment, then the inline math, on a table whose
#: marks went stale. This order makes those dependencies, and never the
#: reverse.
DOCUMENT_STEPS: tuple[DocumentStep, ...] = (
    FORMULA_CLASSIFICATION,
    PICTURE_DESCRIPTION,
    FORMULA_RECOGNITION,
    TABLE_ENRICHMENT,
    INLINE_MATH,
)


def reconcile_document_step(
    manifest: ProcessingManifest, step: DocumentStep, *, replan: bool = False
) -> Obligation | None:
    """Create or reconcile ``step``'s obligations (the module docstring).

    ``replan`` says the call is before a replan, whose roots are the selected
    obligations: a new obligation is then selected. Before the first plan the
    plan selects it.

    Idempotent. Returns the obligation of the newest elements, or the first
    one when nothing changed; ``None`` when the step has none.
    """
    _drop_lost(manifest, step)
    own = [item for item in manifest.obligations if item.kind == step.kind]
    renewed = step.renewed(manifest)
    covered = {
        target for item in own for target in item.target_ids
        if target not in renewed or item.status != "satisfied"
    }
    new = [element_id for element_id in step.pending(manifest) if element_id not in covered]
    target = _cover(manifest, step, own, new, replan) if new else (own[0] if own else None)
    if not step.critical:
        _release_exhausted(manifest, step)
    _reconcile_edges(manifest, step)
    manifest.summary.obligation_count = len(manifest.obligations)
    return target


def reconcile_document_steps(manifest: ProcessingManifest, *, replan: bool = False) -> None:
    """:func:`reconcile_document_step` for every step of ``DOCUMENT_STEPS``.

    The edges are reconciled once more after every step's obligations exist:
    a step's pass links the obligations that exist then, so when two steps
    share an element (M4), the later step's obligation, created in its own
    pass, would otherwise wait for the next reconciliation to depend on the
    earlier one, and the first plan could run them in either order."""
    for step in DOCUMENT_STEPS:
        reconcile_document_step(manifest, step, replan=replan)
    for step in DOCUMENT_STEPS:
        _reconcile_edges(manifest, step)


def _drop_lost(manifest: ProcessingManifest, step: DocumentStep) -> None:
    """Every obligation of ``step`` keeps only the elements it still applies to; empty ones go."""
    by_id = {element.id: element for element in manifest.elements}
    emptied: set[str] = set()
    for item in manifest.obligations:
        if item.kind == step.kind:
            item.target_ids = [
                target for target in item.target_ids
                if target in by_id and step.applies(by_id[target])
            ]
            if not item.target_ids:
                emptied.add(item.id)
    if not emptied:
        return
    manifest.obligations = [item for item in manifest.obligations if item.id not in emptied]
    for item in manifest.obligations:
        item.dependencies = [
            dependency for dependency in item.dependencies if dependency not in emptied
        ]


def _cover(
    manifest: ProcessingManifest,
    step: DocumentStep,
    own: list[Obligation],
    new: list[str],
    replan: bool,
) -> Obligation:
    """The obligation the ``new`` elements join: the open one, or a new one."""
    open_one = next((item for item in own if item.status not in CLOSED_STATUSES), None)
    if open_one is not None:
        open_one.target_ids.extend(new)
        return open_one
    index = _next_index(step, own)
    methods = [step.method, "human-review"]
    created = Obligation(
        id=_obligation_id(step, index),
        kind=step.kind,
        selected=replan or index > 0,
        target_ids=list(new),
        admissible_methods=methods,
        method_costs={method: DEFAULT_METHOD_COSTS.get(method, 50) for method in methods},
        rationale=t(step.rationale),
    )
    manifest.obligations.append(created)
    return created


def _next_index(step: DocumentStep, own: list[Obligation]) -> int:
    """The next suffix: from the number of the step's obligations, skipping
    the ids in use. An id freed by a removal comes back only when no later
    one is left (every obligation of the step removed); within one
    execution the executor compares a step with the plan's own obligation,
    so a reused id never runs a stale step (#832)."""
    ids = {item.id for item in own}
    index = len(own)
    while _obligation_id(step, index) in ids:
        index += 1
    return index


def _obligation_id(step: DocumentStep, index: int) -> str:
    if index == 0:
        return step.obligation_id
    return f"{step.obligation_id}-{index + 1}"


def _reconcile_edges(manifest: ProcessingManifest, step: DocumentStep) -> None:
    """Each open obligation depends on the step's open obligations for its
    elements, and on no edge to the step whose element it no longer shares.

    An edge to an obligation of the step that no longer shares an element
    with the dependent is dropped, whether that obligation is open or closed:
    a closed one is history only while the element that justified it stays,
    and an edge to a ``failed`` one would block the dependent from being
    replanned at all. A closed dependent is not planned again, so it is left
    as it is, and so are the obligations of this step and of the earlier
    ones of ``DOCUMENT_STEPS`` (the module docstring). An edge to an
    exhausted obligation of a non-critical step goes even while the element
    stays (``_release_exhausted``, run before this rule, which never adds
    one back: it links open obligations only).
    """
    order = [item.kind for item in DOCUMENT_STEPS]
    skipped = set(order[: order.index(step.kind) + 1]) if step.kind in order else {step.kind}
    own = {item.id: set(item.target_ids) for item in manifest.obligations if item.kind == step.kind}
    open_own = {
        item.id: set(item.target_ids)
        for item in manifest.obligations
        if item.kind == step.kind and item.status not in CLOSED_STATUSES
    }
    for item in manifest.obligations:
        if item.kind in skipped or item.status in CLOSED_STATUSES:
            continue
        targets = set(item.target_ids)
        waits = item.kind in step.waiting_kinds
        kept = [
            dependency for dependency in item.dependencies
            if dependency not in own or waits or own[dependency] & targets
        ]
        needed = [
            obligation for obligation, elements in open_own.items()
            if (waits or elements & targets) and obligation not in kept
        ]
        item.dependencies = kept + needed


def _release_exhausted(manifest: ProcessingManifest, step: DocumentStep) -> None:
    """Drop the open obligations' edges to an exhausted obligation of a step
    the delivery does not need (``critical=False``). The replan leaves out an
    obligation that depends on an exhausted one
    (``_replannable_obligation_ids``), so a critical formula conversion would
    otherwise fail the job for a missing refinement."""
    exhausted = {
        item.id for item in manifest.obligations
        if item.kind == step.kind and item.status == "failed"
    }
    if not exhausted:
        return
    for item in manifest.obligations:
        if item.status not in CLOSED_STATUSES:
            item.dependencies = [
                dependency for dependency in item.dependencies if dependency not in exhausted
            ]


__all__ = [
    "CLOSED_STATUSES",
    "DOCUMENT_STEPS",
    "FORMULA_CLASSIFICATION",
    "FORMULA_RECOGNITION",
    "INLINE_MATH",
    "PICTURE_DESCRIPTION",
    "TABLE_ENRICHMENT",
    "DocumentStep",
    "reconcile_document_step",
    "reconcile_document_steps",
]
