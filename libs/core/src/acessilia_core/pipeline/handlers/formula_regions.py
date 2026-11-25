"""The document's formula region classification as a planned method (#640, M4).

Until 0.3.17 the orchestrator checked the extractor's formula labels before
planning. ``formula-region-classifier`` runs the same step as the method of
the document's ``classify-formula-regions`` obligation, so the plan chooses,
orders and accounts it (``docs/architecture/workflow-actions.md``):
``_classify_formula_regions`` asks the vision model whether each formula crop
without LaTeX holds mathematics, a drawing or nothing it can tell, with its
concurrency. The formulas' ``recognize-formulas`` waits for it (the two steps
share the formulas, in ``DOCUMENT_STEPS`` order), as do their own obligations.

The model call is the core's ``VisionAgent``, so the method is
``transitional`` in ``LOCAL_METHODS`` until that call becomes a Toolbox
capability (#804, #735); its ``pdf.render`` crop is an optional call (#848).
The breaker, the region cache and the progress reporter are the run's
(``RunPorts``); the mode is the one the run recorded in the manifest. Each
classified formula is saved into the execution checkpoint (#836).

**The step changes obligations.** A drawing it describes becomes a picture:
its formula obligations are replaced by a ``describe-image``. A region the
model cannot tell goes to human review: its ``verbalize-formula`` keeps only
``human-review`` and its ``normalize-formula`` is dropped. The executor skips
the changed steps and replans (M0).

**What the result means.** ``success`` and ``validated`` say that the step
ran for every formula of the obligation. A formula the model gave no answer
for stays ``unclassified`` with its reason and takes the formula path, whose
recognition fallback can still reclassify it. The method fails when the step
raises, and when none of its targets is in the manifest any more
(``MSG_MATH_NO_FORMULA``).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from acessilia_core.config import CoreConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.i18n.stage_messages import STAGE_ENRICHING_FORMULAS
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.formulas import _classify_formula_regions
from acessilia_core.pipeline.handlers.common import run_status, step_checkpoint
from acessilia_core.pipeline.handlers.messages import (
    MSG_FORMULA_REGIONS_CLASSIFIED,
    MSG_MATH_NO_FORMULA,
)
from acessilia_core.ports import RunPorts, region_cache_for
from acessilia_sdk.runtime import run_sync


async def _classify(
    manifest: ProcessingManifest,
    source: Path,
    config: CoreConfig,
    ports: RunPorts,
    targets: frozenset[str],
    obligation_id: str,
) -> None:
    """Classify the obligation's ``targets``: a second obligation never asks
    again about a formula an earlier one owns."""
    status = run_status(ports)
    if status is not None:
        await status(t(STAGE_ENRICHING_FORMULAS))
    await _classify_formula_regions(
        manifest,
        source,
        mode=str(manifest.extractor.configuration.get("region_inspection_mode", "medio")),
        vision=config.vision,
        toolbox=config.toolbox,
        models=config.models,
        region_cache=region_cache_for(ports, config.vision),
        breaker=run_breaker(ports, config.vision),
        targets=targets,
        # Each classified formula is saved into the execution checkpoint (#836).
        on_progress=step_checkpoint(ports, manifest, obligation_id),
    )


def _outcome(element: ManifestElement) -> str:
    """What the step left on a formula: ``picture`` (a drawing it described),
    the classification's status (``math``, ``unresolved``) or, for an
    ``unclassified`` one, the reason no answer came."""
    if element.type == "picture":
        return "picture"
    if element.type != "formula":
        return "not_formula"
    classification = element.metadata.get("formula_classification") or {}
    status = classification.get("status")
    if status in {"math", "unresolved"}:
        return str(status)
    return str(classification.get("reason") or "unclassified")


def _handle_formula_region_classifier_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Classify the document's formula regions; satisfied once the step ran for all of them."""
    obligation = next((item for item in manifest.obligations if item.id == obligation_id), None)
    targets = frozenset(obligation.target_ids) if obligation is not None else frozenset()
    formulas = [element for element in manifest.elements if element.id in targets]
    if not formulas:
        return MethodResult(success=False, validated=False, message=t(MSG_MATH_NO_FORMULA))
    run_sync(_classify(manifest, Path(manifest.source.path), config, ports, targets, obligation_id))
    outcomes = Counter(_outcome(element) for element in formulas)
    math, pictures, unresolved = (outcomes.pop(key, 0) for key in ("math", "picture", "unresolved"))
    return MethodResult(
        success=True,
        validated=True,
        message=n(*MSG_FORMULA_REGIONS_CLASSIFIED, len(formulas)).format(
            count=len(formulas),
            math=math,
            pictures=pictures,
            unresolved=unresolved,
            left=", ".join(f"{reason}: {count}" for reason, count in sorted(outcomes.items())) or "-",
        ),
    )


__all__ = ["_handle_formula_region_classifier_method"]
