"""Shared types, geometry helpers and materialization for manifest need detectors."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from docstruct.geometry import OrientedBox

from acessilia_core.manifest.models import ManifestElement, Obligation, Observation

PageSizes = dict[int, tuple[float | None, float | None]]

#: Longest id suffix spelled out from the target ids; past it the suffix is a
#: digest, since a document-level obligation targets every element of every
#: divergent page and its id goes into the manifest, the PDDL problem and plan.
MAX_ID_SUFFIX = 80

#: Methods of an adjudicate-page obligation. The deterministic router already
#: ran on the evidence (``route``), and re-running it as agreement-rule would
#: only repeat its answer, so the obligation goes straight to the VLM judge.
VLM_JUDGE_METHODS = ["vlm-pairwise-judge", "human-review"]


@dataclass(frozen=True)
class NeedCandidate:
    """A processing need emitted by a detector before deduplication and id assignment."""

    kind: str
    targets: list[ManifestElement]
    evidence: dict[str, Any]
    methods: list[str] | None = None
    emit_obligation: bool = True


def oriented_bbox(element: ManifestElement) -> OrientedBox | None:
    """First provenance bounding box as an ``OrientedBox``, if present."""
    if not element.provenance:
        return None
    bbox = element.provenance[0].bbox
    if bbox is None:
        return None
    return OrientedBox(bbox.left, bbox.top, bbox.right, bbox.bottom, bbox.coord_origin)


def normalized_element_bbox(
    element: ManifestElement,
    page_sizes: PageSizes | None,
) -> tuple[float, float, float, float] | None:
    """Element bounding box as top-down page fractions in ``[0, 1]``."""
    box = oriented_bbox(element)
    if box is None or element.page_number is None or page_sizes is None:
        return None
    size = page_sizes.get(element.page_number)
    if size is None:
        return None
    return box.page_fractions(*size)


def obligation_suffix(target_ids: list[str]) -> str:
    """Deterministic suffix for observation and obligation identifiers."""
    suffix = "-".join(item.removeprefix("element-") for item in target_ids)
    if len(suffix) <= MAX_ID_SUFFIX:
        return suffix
    digest = hashlib.sha256("\n".join(target_ids).encode("utf-8")).hexdigest()
    return f"{len(target_ids)}-targets-{digest[:12]}"


def materialize_needs(
    candidates: list[NeedCandidate],
    *,
    obligation_specs: Mapping[str, tuple[str, list[str]]],
    method_costs: Mapping[str, int],
    secondary_extraction_available: bool = False,
) -> tuple[list[Observation], list[Obligation]]:
    """Deduplicate detector candidates and build manifest observations and obligations."""
    observations: list[Observation] = []
    obligations: list[Obligation] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()

    for candidate in candidates:
        target_ids = list(dict.fromkeys(item.id for item in candidate.targets if item.id))
        if not target_ids:
            continue
        key = (candidate.kind, tuple(target_ids))
        if key in seen:
            continue
        seen.add(key)

        rationale, default_methods = obligation_specs[candidate.kind]
        methods = _admissible_methods(
            candidate.kind,
            candidate.methods or default_methods,
            secondary_extraction_available=secondary_extraction_available,
        )
        suffix = obligation_suffix(target_ids)
        observations.append(
            Observation(
                id=f"observation-{candidate.kind}-{suffix}",
                kind=f"{candidate.kind}-detected",
                severity="warning",
                message=rationale,
                target_ids=target_ids,
                evidence=candidate.evidence,
            )
        )
        if not candidate.emit_obligation:
            continue
        obligations.append(
            Obligation(
                id=f"obligation-{candidate.kind}-{suffix}",
                kind=candidate.kind,
                target_ids=target_ids,
                admissible_methods=methods,
                method_costs={method: method_costs.get(method, 50) for method in methods},
                rationale=rationale,
            )
        )

    return observations, obligations


def _admissible_methods(
    kind: str,
    methods: list[str],
    *,
    secondary_extraction_available: bool,
) -> list[str]:
    selected = list(methods)
    if kind == "refine-reading-order" and not secondary_extraction_available:
        return [method for method in selected if method != "skeleton-order"]
    return selected
