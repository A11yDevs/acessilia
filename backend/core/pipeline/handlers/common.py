"""Helpers every deterministic method handler shares.

A handler takes the manifest and an obligation id and returns a
``MethodResult``. Moved verbatim from the PDDL orchestrator (#402, phase 3,
step 6).
"""

from __future__ import annotations

from backend.core.agents.fusion_agent import FusionAgent
from backend.core.execution.models import MethodResult
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)


def _fusion_agent() -> FusionAgent:
    """Fusion agent used to reach the deterministic fusion primitives.

    The `docstruct` functions take classified blocks, counters and tuning
    parameters; `FusionAgent.process_*` is the in-repo entry point that supplies
    them, so handlers call that instead of a primitive whose signature they would
    otherwise have to guess.
    """
    return FusionAgent()


def _target_elements(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    """Elements an obligation points at, in reading order."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return sorted(
        (el for el in manifest.elements if el.id in targets),
        key=lambda el: el.reading_order,
    )


def _missing_obligation(obligation_id: str) -> MethodResult:
    return MethodResult(
        success=False,
        validated=False,
        message=f"Obrigação não encontrada: {obligation_id}",
    )
