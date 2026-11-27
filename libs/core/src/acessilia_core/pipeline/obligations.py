"""Which processing obligations stay open, and which of them block delivery.

Moved verbatim from the PDDL orchestrator (#402, phase 3, step 6). The
orchestrator's final check, its replanning and the payload read them.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING, Any

from acessilia_core.execution.messages import EXE_COMPLETED_OBLIGATIONS_UNSATISFIED
from acessilia_core.i18n import t
from acessilia_core.i18n.stage_messages import STAGE_PAGE_UNKNOWN
from acessilia_core.manifest.models import (
    ManifestElement,
    Obligation,
    ProcessingManifest,
)
from acessilia_core.pipeline.document_obligations import (
    CLOSED_STATUSES,
    DOCUMENT_STEPS,
    TABLE_ENRICHMENT,
    reconcile_document_step,
    reconcile_document_steps,
)
from acessilia_core.pipeline.page_labels import _pages_label
from docstruct.text.latex import bare_latex as normalize_latex

if TYPE_CHECKING:
    pass


#: The document's table enrichment as one planned action (#640, M2): its
#: kind, method and first id, kept here for the callers that name them. The
#: rules live in ``document_obligations``, shared with the picture
#: descriptions (M1).
TABLE_ENRICHMENT_KIND = TABLE_ENRICHMENT.kind
TABLE_ENRICHMENT_METHOD = TABLE_ENRICHMENT.method
TABLE_ENRICHMENT_OBLIGATION_ID = TABLE_ENRICHMENT.obligation_id


def add_table_enrichment_obligation(
    manifest: ProcessingManifest, *, replan: bool = False
) -> Obligation | None:
    """Cover every table of the document with an ``enrich-tables`` obligation,
    and reconcile the existing ones (``document_obligations``)."""
    return reconcile_document_step(manifest, TABLE_ENRICHMENT, replan=replan)


def _formula_elements_for_obligation(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return [
        el for el in manifest.elements if el.id in targets and el.type == "formula"
    ]


#: Obligation kinds that only refine content the extraction already delivered.
#: Leaving one open (every automatic method failed and it was escalated to
#: human review) does not lose content, so the job finishes with a warning
#: instead of failing. Heading levels are also normalized by the canonical
#: builder, which keeps the exported document valid without the repair.
#: `refine-reading-order` is deliberately absent: a wrong reading order is what
#: a screen reader user hits first, so an open one still fails the job.
NON_CRITICAL_OBLIGATION_KINDS = frozenset(
    {
        # The adjudication verdict is recorded but cannot be applied (a page
        # swap would reopen the manifest mid-plan), and the extracted content
        # is complete either way, so a verdict for the secondary provider must
        # not fail the job.
        "adjudicate-page",
        "repair-heading-hierarchy",
        "join-tail-blocks",
        "normalize-text",
        "repair-legacy-unicode",
        "chunk-verse",
        "extract-line-numbers",
        # The vision model is the only automatic method, and a degenerate
        # answer repeats on every try: in 006.pdf two images out of 40 failed
        # a 42-page document. The picture is exported with the generic alt
        # text and the result e-mail names its page. Unless no picture at all
        # was described: see _blocks_delivery.
        "describe-image",
        # The prose's inline math (#640, M4b): a block left without its
        # marks keeps its text as the extractor gave it, as when the
        # detection is off, so it degrades the reading, not the content.
        "mark-inline-math",
    }
)


def _formula_has_readable_content(
    obligation: Obligation, manifest: ProcessingManifest
) -> bool:
    """Whether every target formula still carries something readable.

    A formula the Toolbox could not verbalize or normalize is exported as its
    LaTeX: the canonical builder and the renderers fall back to it when
    ``math.verbalize`` is unavailable or rejects the input, so the document
    keeps the content. That is a degradation, not a lost document. A formula
    with neither LaTeX, a normalized LaTeX, MathML nor a verbalization has
    nothing to deliver, so its obligation stays critical.
    """
    targets = _formula_elements_for_obligation(manifest, obligation.id)
    return bool(targets) and all(
        bool(normalize_latex(element.text or ""))
        or bool(str(element.metadata.get("latex_normalized") or "").strip())
        or bool(str(element.metadata.get("mathml") or "").strip())
        or bool(str(element.metadata.get("verbalization") or "").strip())
        for element in targets
    )


def _blocks_delivery(obligation: Obligation, manifest: ProcessingManifest) -> bool:
    """Whether an open obligation fails the job instead of leaving a warning.

    ``describe-image`` is non-critical while some picture was described: a few
    degenerate answers are sampling (2 of 40 in 006.pdf). With none described,
    the model is unreachable or misconfigured (``describe_region`` turns a
    timeout or an auth error into ``None``), and every picture would silently
    get the generic alt text, so the job fails. A document with a single
    picture its one description failed on fails too. A picture that was never
    sent to the model, because its source has no page to render and the
    extraction embedded no image (a DOCX or HTML picture), says nothing about
    the model: it is left for human review with the generic alt text instead
    of failing the document.

    ``verbalize-formula`` and ``normalize-formula`` are non-critical while the
    target formulas keep their LaTeX: without MathML or spoken text the exported
    document still shows the formula source, and the result e-mail names the
    page. With no readable content at all there is nothing to deliver, so the
    obligation fails the job.
    """
    if obligation.kind == "describe-image":
        if _has_no_image_to_describe(obligation, manifest):
            return False
        return not any(
            other.kind == "describe-image" and other.status == "satisfied"
            for other in manifest.obligations
        )
    if obligation.kind in {"verbalize-formula", "normalize-formula"}:
        return not _formula_has_readable_content(obligation, manifest)
    return obligation.kind not in NON_CRITICAL_OBLIGATION_KINDS


def _has_no_image_to_describe(
    obligation: Obligation, manifest: ProcessingManifest
) -> bool:
    """Whether every target of a ``describe-image`` had no image to send to the model."""
    targets = [
        element for element in manifest.elements if element.id in obligation.target_ids
    ]
    return bool(targets) and all(
        element.metadata.get("vision_failure_reason") == "image_unavailable"
        for element in targets
    )


def _is_open_obligation(obligation: Obligation) -> bool:
    """Whether a job goal stays unsatisfied, independently of the plan.

    Failed obligations also stay open for checkpoints whose older executor
    cleared their goal flag when leaving them out of a later plan.
    """
    return obligation.status != "satisfied" and (
        obligation.selected or obligation.status == "failed"
    )


def _unsatisfied_selected_obligations(manifest: ProcessingManifest) -> list:
    return [
        obligation for obligation in manifest.obligations
        if _is_open_obligation(obligation)
    ]


def planning_signature(manifest: ProcessingManifest) -> str:
    """A digest of what a replan would plan from (#832): each replannable
    obligation's kind, targets, dependencies, status and the methods already
    tried. Two states with the same digest give the replan the same problem,
    so a replan from the second makes no progress; the same ids with other
    targets or dependencies are a different problem. Nothing volatile (no
    timestamp, no message) enters it."""
    by_id = {item.id: item for item in manifest.obligations}
    state = [
        [
            item.id, item.kind, sorted(item.target_ids), sorted(item.dependencies), item.status,
            sorted({attempt.method for attempt in item.attempts if attempt.status != "succeeded"}),
        ]
        for item in (by_id[obligation_id] for obligation_id in sorted(_replannable_obligation_ids(manifest)))
    ]
    return hashlib.sha256(json.dumps(state, separators=(",", ":")).encode()).hexdigest()


def _replannable_obligation_ids(manifest: ProcessingManifest) -> list[str]:
    """Open selected obligations that a new plan can still satisfy.

    Exhausted obligations, and those depending on one, are excluded: the planner
    rejects an obligation without an untried admissible method.
    """
    by_id = {obligation.id: obligation for obligation in manifest.obligations}

    def blocked(obligation_id: str, seen: set[str]) -> bool:
        if obligation_id in seen:
            return False
        seen.add(obligation_id)
        obligation = by_id[obligation_id]
        if obligation.status == "failed":
            return True
        return any(blocked(dependency, seen) for dependency in obligation.dependencies)

    return [
        obligation.id for obligation in manifest.obligations
        if obligation.selected
        and obligation.status != "satisfied"
        and not blocked(obligation.id, set())
    ]


def _discovered_roots(manifest: ProcessingManifest) -> list[str]:
    """The replannable obligations no failure touches (#842): never tried,
    and with no open, tried obligation among their dependencies, directly or
    not.

    A discovery replan serves only these whenever the failure budget is
    spent, in the round that failed and in every later one (with
    ``max_replans=0``, every discovery replan), so the failed work and what
    waits for it are not retried. They are not only the obligations a run
    found: preexisting work never tried is served too, since it does not
    spend the failure budget. What they leave out stays a job goal.

    Precondition: the references are valid and the graph is a DAG; the
    replan loop validates them before (``validate_obligation_graph``). Each
    obligation is visited once.
    """
    by_id = {obligation.id: obligation for obligation in manifest.obligations}
    touched: dict[str, bool] = {}

    def is_touched(obligation_id: str) -> bool:
        if obligation_id not in touched:
            obligation = by_id[obligation_id]
            touched[obligation_id] = (obligation.status != "satisfied" and bool(obligation.attempts)) or any(
                is_touched(dependency) for dependency in obligation.dependencies
            )
        return touched[obligation_id]

    return [
        obligation_id for obligation_id in _replannable_obligation_ids(manifest)
        if not is_touched(obligation_id)
    ]


def replan_roots(manifest: ProcessingManifest, *, failure_budget_spent: bool) -> list[str]:
    """Choose the next plan's roots and record why other goals wait (#883)."""
    eligible = _replannable_obligation_ids(manifest)
    roots = _discovered_roots(manifest) if failure_budget_spent else eligible
    eligible_ids = set(eligible)
    selected = set(roots)
    for obligation in manifest.obligations:
        if not _is_open_obligation(obligation) or obligation.id in selected:
            obligation.deferred_reason = None
        elif failure_budget_spent and obligation.id in eligible_ids:
            obligation.deferred_reason = "failure-budget-exhausted"
        else:
            obligation.deferred_reason = "outside-plan"
    return roots


def _unsatisfied_summary(manifest: ProcessingManifest) -> str:
    """The open obligations grouped by kind with their pages.

    "refine-reading-order (pages 1, 7, 11); describe-image (page 18)" instead of
    one id per obligation, each listing every target element.
    """
    pages: dict[str, set[int]] = {}
    unknown: set[str] = set()
    for obligation in _unsatisfied_selected_obligations(manifest):
        numbers = {
            page for page in _obligation_pages(manifest, obligation.id) if page
        }
        pages.setdefault(obligation.kind, set()).update(numbers)
        if not numbers:
            unknown.add(obligation.kind)
    groups = []
    for kind, numbers in pages.items():
        labels = [_pages_label(numbers)] if numbers else []
        if kind in unknown:
            labels.append(t(STAGE_PAGE_UNKNOWN))
        groups.append(f"{kind} ({', '.join(labels)})")
    return t(EXE_COMPLETED_OBLIGATIONS_UNSATISFIED).format(unsatisfied="; ".join(groups))


def _obligation_pages(manifest: ProcessingManifest, obligation_id: str) -> list[int | None]:
    obligation = next(
        (item for item in manifest.obligations if item.id == obligation_id), None
    )
    if obligation is None:
        return []
    page_by_element = {element.id: element.page_number for element in manifest.elements}
    return [page_by_element.get(target) for target in obligation.target_ids]


def _unsatisfied_obligations(manifest: ProcessingManifest) -> list[dict[str, Any]]:
    """Selected obligations the execution left unsatisfied.

    `pddl_execution_status` alone does not say which obligations were exhausted
    or escalated, so each one is reported with its last attempt. An obligation
    whose last attempt is `human-review` is a pending escalation.
    """
    unsatisfied: list[dict[str, Any]] = []
    for obligation in manifest.obligations:
        if not _is_open_obligation(obligation):
            continue
        last = obligation.attempts[-1] if obligation.attempts else None
        unsatisfied.append(
            {
                "id": obligation.id,
                "kind": obligation.kind,
                "status": obligation.status,
                **({"deferred_reason": obligation.deferred_reason} if obligation.deferred_reason else {}),
                "target_ids": list(obligation.target_ids),
                "last_method": last.method if last else None,
                "last_message": last.message if last else None,
                "escalated": bool(last and last.method == "human-review"),
                "recovery": (
                    "human-review" if last and last.method == "human-review"
                    and obligation.kind in NON_CRITICAL_OBLIGATION_KINDS else "retry"
                ),
            }
        )
    return unsatisfied


def _document_work_found(manifest: ProcessingManifest) -> bool:
    """Whether a run left work for the document steps that no plan has (#640, M4b).

    A step can add elements without adding obligations: ``rescue-omitted``
    restores a paragraph, ``select-table-source`` adopts a table's cells. The
    reconciliation gives them the document step they need (the inline math,
    a picture's description), so a run that completed still replans for
    them, as a discovery; this replaced the pass after execution of #599.

    Its one effect is that reconciliation, which the replan loop runs anyway;
    it does not reopen the job. The loop does that (``_reopen``) once the
    replan is allowed; with the budget spent, the job keeps its status and
    ``_check_unsatisfied`` judges what was found.
    """
    reconcile_document_steps(manifest, replan=True)
    kinds = {step.kind for step in DOCUMENT_STEPS}
    return any(
        item.kind in kinds and item.selected and item.status not in CLOSED_STATUSES and not item.attempts
        for item in manifest.obligations
    )


def _reopen(manifest: ProcessingManifest) -> None:
    """Reopen a job the run's ``complete-job`` closed while work was left
    (M4b): the planner refuses a completed manifest, and the replan's own
    ``complete-job`` closes it again."""
    if manifest.status == "completed":
        manifest.status = "processing"
