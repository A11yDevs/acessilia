from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timezone

from backend.core.manifest.models import ProcessingManifest
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import (
    ComparisonDetails,
    NominalPlan,
    PlannerOutcome,
    PlanningComparison,
)
from backend.core.planning.pddl_processor import CompiledProblem


def build_planning_comparison(
    *,
    manifest: ProcessingManifest,
    domain: DomainBundle,
    compiled: CompiledProblem,
    outcomes: dict[str, PlannerOutcome],
    plans: dict[str, NominalPlan],
    preferred_backend: str,
) -> PlanningComparison:
    """Compara planos sem confundir ordens causais igualmente válidas."""
    internal = plans.get("internal")
    fast_downward = plans.get("fast-downward")
    both_solved = internal is not None and fast_downward is not None

    if not both_solved:
        details = ComparisonDetails(
            verdict="inconclusive",
            both_solved=False,
            notes=[
                "A equivalência não pode ser determinada porque ao menos um "
                "backend não produziu plano válido."
            ],
        )
    else:
        assert internal is not None
        assert fast_downward is not None
        internal_signatures = [_step_signature(step) for step in internal.steps]
        fd_signatures = [_step_signature(step) for step in fast_downward.steps]
        internal_counter = Counter(internal_signatures)
        fd_counter = Counter(fd_signatures)
        same_cost = (
            internal.expected_total_cost
            == fast_downward.expected_total_cost
        )
        same_selected = (
            set(internal.selected_obligations)
            == set(fast_downward.selected_obligations)
        )
        same_executed = (
            _executed_obligations(internal)
            == _executed_obligations(fast_downward)
        )
        same_methods = (
            _method_selection(internal)
            == _method_selection(fast_downward)
        )
        same_multiset = internal_counter == fd_counter
        same_sequence = internal_signatures == fd_signatures
        semantic_equivalence = all(
            (
                same_cost,
                same_selected,
                same_executed,
                same_methods,
                same_multiset,
            )
        )
        verdict = (
            "identical"
            if semantic_equivalence and same_sequence
            else "equivalent"
            if semantic_equivalence
            else "different"
        )
        notes: list[str] = []
        if verdict == "equivalent":
            notes.append(
                "Os planos diferem apenas na ordem de ações independentes; "
                "ambos passaram pela validação causal."
            )
        elif verdict == "different" and same_cost:
            notes.append(
                "O custo total coincide, mas isso não basta para estabelecer "
                "equivalência semântica."
            )
        details = ComparisonDetails(
            verdict=verdict,
            both_solved=True,
            same_expected_total_cost=same_cost,
            cost_delta_fast_downward_minus_internal=(
                fast_downward.expected_total_cost
                - internal.expected_total_cost
            ),
            same_selected_obligations=same_selected,
            same_executed_obligations=same_executed,
            same_method_selection=same_methods,
            same_action_multiset=same_multiset,
            same_action_sequence=same_sequence,
            internal_only_steps=_counter_difference(
                internal_counter, fd_counter
            ),
            fast_downward_only_steps=_counter_difference(
                fd_counter, internal_counter
            ),
            notes=notes,
        )

    seed = (
        f"{manifest.manifest_id}:{manifest.revision}:{compiled.sha256}:"
        f"{domain.domain_sha256}"
    )
    return PlanningComparison(
        comparison_id=(
            "comparison-"
            + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        ),
        generated_at=datetime.now(timezone.utc),
        preferred_backend=preferred_backend,
        manifest_id=manifest.manifest_id,
        manifest_revision=manifest.revision,
        manifest_sha256=compiled.manifest_sha256,
        domain={
            "name": domain.name,
            "version": domain.version,
            "domain_sha256": domain.domain_sha256,
            "description_sha256": domain.description_sha256,
        },
        problem_name=compiled.projection.problem_name,
        problem_sha256=compiled.sha256,
        outcomes=outcomes,
        comparison=details,
    )


def _step_signature(step: object) -> tuple[str, str, str, str, int]:
    action = getattr(step, "action")
    return (
        action,
        getattr(step, "obligation_id") or "",
        getattr(step, "obligation_kind") or "",
        getattr(step, "method") or "",
        getattr(step, "expected_cost"),
    )


def _signature_text(signature: tuple[str, str, str, str, int]) -> str:
    action, obligation, kind, method, cost = signature
    parameters = ",".join(
        value for value in (obligation, kind, method) if value
    )
    return f"{action}({parameters})@{cost}"


def _counter_difference(
    left: Counter[tuple[str, str, str, str, int]],
    right: Counter[tuple[str, str, str, str, int]],
) -> list[str]:
    difference = left - right
    return [
        _signature_text(signature)
        for signature in sorted(difference)
        for _ in range(difference[signature])
    ]


def _executed_obligations(plan: NominalPlan) -> set[str]:
    return {
        step.obligation_id
        for step in plan.steps
        if step.action == "execute-obligation"
        and step.obligation_id is not None
    }


def _method_selection(plan: NominalPlan) -> dict[str, str]:
    return {
        step.obligation_id: step.method
        for step in plan.steps
        if step.action == "execute-obligation"
        and step.obligation_id is not None
        and step.method is not None
    }
