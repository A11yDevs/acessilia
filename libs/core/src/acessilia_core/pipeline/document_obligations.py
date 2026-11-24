"""Document-level obligations: one planned action over many elements (#640).

A step that works on the whole document (one provider breaker, one retry
pass, one progress counter) becomes one obligation that targets every element
it works on, instead of one per element: a per-element method would wait the
retry pass once per failing element, and the elements after the breaker
opened would lose the recovery (``docs/architecture/workflow-actions.md``).

Two steps are planned this way:
- the table enrichment (``enrich-tables``, method ``table-enrichment``, M2);
- the picture descriptions (``describe-images``, method
  ``picture-description``, M1).

Each one is a :class:`DocumentStep`, and :func:`reconcile_document_step`
creates its obligation when the manifest is enriched and reconciles it again
before each replan (#832):

- an element no obligation of the step covers, and that needs the step, joins
  the open one, or, when the existing ones are closed (satisfied or
  exhausted), a new one for the new elements only. Reopening a satisfied one
  would leave satisfied obligations after an open one; an exhausted one is
  not planned again, so an element joining it would never be worked on;
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
  obligations (``linearize-table``, ``describe-image``), it orders the page
  obligations (``refine-reading-order``, ``fuse-providers``,
  ``adjudicate-page``) of a page with such an element, whose targets are the
  page's elements. That is the order of the releases where the step ran
  before planning, at the cost of serializing those page obligations behind
  it. A future step that must run *before* it is not one this rule should
  order: it needs an exclusion here.

  Between the document's steps, the rule follows ``DOCUMENT_STEPS``: a
  step's obligation may depend on an earlier step's that shares an element,
  never on a later one's. Applied in both directions, the rule would make a
  cycle when the two steps share an element (a one-page mostly visual
  document whose first element, the one the descriptions take, is a table).

The step that removes an element must also remove or retarget that element's
own obligations and the page's ``element_ids``; the manifest refuses dangling
targets.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from acessilia_core.i18n import t
from acessilia_core.i18n.log_messages import (
    MSG_OBLIGATION_PICTURE_DESCRIPTION,
    MSG_OBLIGATION_TABLE_ENRICHMENT,
)
from acessilia_core.manifest.builder import DEFAULT_METHOD_COSTS
from acessilia_core.manifest.models import (
    ManifestElement,
    Obligation,
    ProcessingManifest,
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

#: In the order the enrichment before planning ran them until 0.3.13.
DOCUMENT_STEPS: tuple[DocumentStep, ...] = (PICTURE_DESCRIPTION, TABLE_ENRICHMENT)


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
    covered = {target for item in own for target in item.target_ids}
    new = [element_id for element_id in step.pending(manifest) if element_id not in covered]
    target = _cover(manifest, step, own, new, replan) if new else (own[0] if own else None)
    _reconcile_edges(manifest, step)
    manifest.summary.obligation_count = len(manifest.obligations)
    return target


def reconcile_document_steps(manifest: ProcessingManifest, *, replan: bool = False) -> None:
    """:func:`reconcile_document_step` for every step of ``DOCUMENT_STEPS``."""
    for step in DOCUMENT_STEPS:
        reconcile_document_step(manifest, step, replan=replan)


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
    """The first free suffix: removing an emptied obligation frees its id."""
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
    ones of ``DOCUMENT_STEPS`` (the module docstring).
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
        kept = [
            dependency for dependency in item.dependencies
            if dependency not in own or own[dependency] & targets
        ]
        needed = [
            obligation for obligation, elements in open_own.items()
            if elements & targets and obligation not in kept
        ]
        item.dependencies = kept + needed


__all__ = [
    "CLOSED_STATUSES",
    "DOCUMENT_STEPS",
    "PICTURE_DESCRIPTION",
    "TABLE_ENRICHMENT",
    "DocumentStep",
    "reconcile_document_step",
    "reconcile_document_steps",
]
