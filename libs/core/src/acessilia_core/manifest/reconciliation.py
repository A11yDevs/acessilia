"""Element-level observation/obligation builders and reclassification reconciliation.

Extracted from ``acessilia_core.manifest.builder`` (#612) to keep the builder
under the module size limit and isolate element-type reclassification rules.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping

from acessilia_core.i18n import t
from acessilia_core.manifest.models import (
    ManifestElement,
    Obligation,
    Observation,
    ProcessingManifest,
)

ObligationSpec = tuple[str, str, list[str]]


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
    *,
    obsolete_kinds: set[str],
    current_kind: str,
    methods: list[str],
    method_costs: Mapping[str, int],
    rationale: str,
) -> list[Obligation]:
    removed_ids: set[str] = set()
    retained: list[Obligation] = []
    has_current = False
    for obligation in obligations:
        if obligation.target_ids == [element.id]:
            if obligation.kind == current_kind:
                has_current = True
            if obligation.kind in obsolete_kinds:
                removed_ids.add(obligation.id)
                continue
        retained.append(obligation)

    new_obligation = build_element_obligation(
        element,
        kind=current_kind,
        methods=methods,
        method_costs=method_costs,
        rationale=rationale,
    )
    if not has_current:
        retained.append(new_obligation)

    replacement_id = next(
        (
            obligation.id
            for obligation in retained
            if obligation.target_ids == [element.id]
            and obligation.kind == current_kind
        ),
        new_obligation.id,
    )
    _rewire_removed_dependencies(
        retained, removed_ids=removed_ids, replacement_id=replacement_id
    )
    return retained


def _reconcile_element_observations(
    observations: list[Observation],
    element: ManifestElement,
    *,
    obsolete_kinds: set[str],
    current_kind: str,
    rationale: str,
) -> list[Observation]:
    current_observation_kind = f"{element.type}-requires-processing"
    retained: list[Observation] = []
    has_current = False
    for observation in observations:
        if observation.target_ids == [element.id]:
            if observation.kind == current_observation_kind:
                has_current = True
            if observation.kind in obsolete_kinds:
                continue
        retained.append(observation)

    if not has_current:
        retained.append(
            build_element_observation(element, kind=current_kind, rationale=rationale)
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

    previous_spec = obligation_by_type.get(previous_type)
    current_kind, msgid, methods = current_spec
    rationale = t(msgid)
    bound_kinds = type_bound_v23_kinds.get(previous_type, frozenset())

    obsolete_obligation_kinds = set(bound_kinds)
    obsolete_observation_kinds = {f"{kind}-detected" for kind in bound_kinds}
    if previous_spec is not None:
        obsolete_obligation_kinds.add(previous_spec[0])
        obsolete_observation_kinds.add(f"{previous_type}-requires-processing")

    manifest.obligations = _reconcile_element_obligations(
        manifest.obligations,
        element,
        obsolete_kinds=obsolete_obligation_kinds,
        current_kind=current_kind,
        methods=methods,
        method_costs=method_costs,
        rationale=rationale,
    )
    manifest.observations = _reconcile_element_observations(
        manifest.observations,
        element,
        obsolete_kinds=obsolete_observation_kinds,
        current_kind=current_kind,
        rationale=rationale,
    )
    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)
    manifest.summary.element_types = dict(
        sorted(Counter(item.type for item in manifest.elements).items())
    )
