"""Element-level observation/obligation builders and reclassification reconciliation.

Extracted from ``acessilia_core.manifest.builder`` (#612) to keep the builder
under the module size limit and isolate element-type reclassification rules.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass

from acessilia_core.i18n import t
from acessilia_core.manifest.models import (
    ManifestElement,
    Obligation,
    Observation,
    ProcessingManifest,
)

ObligationSpec = tuple[str, str, list[str]]


@dataclass(frozen=True)
class _ReconcilePlan:
    current_kind: str
    methods: list[str]
    method_costs: Mapping[str, int]
    rationale: str
    obsolete_obligation_kinds: frozenset[str]
    obsolete_observation_kinds: frozenset[str]


def build_element_observation(
    element: ManifestElement,
    *,
    kind: str,
    rationale: str,
) -> Observation:
    suffix = element.id.removeprefix("element-")
    return Observation(
        id=f"observation-{kind}-{suffix}",
        kind=f"{element.type}-requires-processing",
        severity="warning" if element.type != "code" else "info",
        message=rationale,
        target_ids=[element.id],
        evidence={
            "raw_label": element.raw_label,
            "page_number": element.page_number,
        },
    )


def build_element_obligation(
    element: ManifestElement,
    *,
    kind: str,
    methods: list[str],
    method_costs: Mapping[str, int],
    rationale: str,
) -> Obligation:
    suffix = element.id.removeprefix("element-")
    return Obligation(
        id=f"obligation-{kind}-{suffix}",
        kind=kind,
        target_ids=[element.id],
        admissible_methods=list(methods),
        method_costs={method: method_costs.get(method, 50) for method in methods},
        rationale=rationale,
    )


def _build_reconcile_plan(
    *,
    previous_type: str,
    current_spec: ObligationSpec,
    previous_spec: ObligationSpec | None,
    type_bound_v23_kinds: Mapping[str, frozenset[str]],
    method_costs: Mapping[str, int],
) -> _ReconcilePlan:
    current_kind, msgid, methods = current_spec
    bound_kinds = type_bound_v23_kinds.get(previous_type, frozenset())
    obsolete_obligations = set(bound_kinds)
    obsolete_observations = {f"{kind}-detected" for kind in bound_kinds}
    if previous_spec is not None:
        obsolete_obligations.add(previous_spec[0])
        obsolete_observations.add(f"{previous_type}-requires-processing")
    return _ReconcilePlan(
        current_kind=current_kind,
        methods=methods,
        method_costs=method_costs,
        rationale=t(msgid),
        obsolete_obligation_kinds=frozenset(obsolete_obligations),
        obsolete_observation_kinds=frozenset(obsolete_observations),
    )


def _rewire_removed_dependencies(
    obligations: list[Obligation],
    *,
    removed_ids: set[str],
    replacement_id: str,
) -> None:
    for obligation in obligations:
        obligation.dependencies = [
            replacement_id if dependency in removed_ids else dependency
            for dependency in obligation.dependencies
        ]


def _reconcile_element_obligations(
    obligations: list[Obligation],
    element: ManifestElement,
    plan: _ReconcilePlan,
) -> list[Obligation]:
    removed_ids: set[str] = set()
    retained: list[Obligation] = []
    has_current = False
    for obligation in obligations:
        if obligation.target_ids == [element.id]:
            if obligation.kind == plan.current_kind:
                has_current = True
            if obligation.kind in plan.obsolete_obligation_kinds:
                removed_ids.add(obligation.id)
                continue
        retained.append(obligation)

    suffix = element.id.removeprefix("element-")
    default_id = f"obligation-{plan.current_kind}-{suffix}"
    if not has_current:
        retained.append(
            build_element_obligation(
                element,
                kind=plan.current_kind,
                methods=plan.methods,
                method_costs=plan.method_costs,
                rationale=plan.rationale,
            )
        )

    replacement_id = next(
        (
            obligation.id
            for obligation in retained
            if obligation.target_ids == [element.id]
            and obligation.kind == plan.current_kind
        ),
        default_id,
    )
    _rewire_removed_dependencies(
        retained, removed_ids=removed_ids, replacement_id=replacement_id
    )
    return retained


def _reconcile_element_observations(
    observations: list[Observation],
    element: ManifestElement,
    plan: _ReconcilePlan,
) -> list[Observation]:
    current_observation_kind = f"{element.type}-requires-processing"
    retained: list[Observation] = []
    has_current = False
    for observation in observations:
        if observation.target_ids == [element.id]:
            if observation.kind == current_observation_kind:
                has_current = True
            if observation.kind in plan.obsolete_observation_kinds:
                continue
        retained.append(observation)

    if not has_current:
        retained.append(
            build_element_observation(
                element, kind=plan.current_kind, rationale=plan.rationale
            )
        )
    return retained


def reconcile_reclassified_element(
    manifest: ProcessingManifest,
    element: ManifestElement,
    *,
    previous_type: str,
    obligation_by_type: Mapping[str, ObligationSpec],
    type_bound_v23_kinds: Mapping[str, frozenset[str]],
    method_costs: Mapping[str, int],
) -> None:
    """Reconcile derived observations/obligations after an element changes type."""
    if previous_type == element.type:
        return

    current_spec = obligation_by_type.get(element.type)
    if current_spec is None:
        return

    plan = _build_reconcile_plan(
        previous_type=previous_type,
        current_spec=current_spec,
        previous_spec=obligation_by_type.get(previous_type),
        type_bound_v23_kinds=type_bound_v23_kinds,
        method_costs=method_costs,
    )
    manifest.obligations = _reconcile_element_obligations(
        manifest.obligations, element, plan
    )
    manifest.observations = _reconcile_element_observations(
        manifest.observations, element, plan
    )
    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)
    manifest.summary.element_types = dict(
        sorted(Counter(item.type for item in manifest.elements).items())
    )
