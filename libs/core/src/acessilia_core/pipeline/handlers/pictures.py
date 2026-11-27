"""The document's picture descriptions as a planned method (#640, M1).

Until 0.3.13 the orchestrator described the pictures before planning.
``picture-description`` runs the same step as the method of the document's
``describe-images`` obligation, so the plan chooses, orders and accounts it
(``docs/architecture/workflow-actions.md``): ``_enrich_picture_descriptions``
describes, with the ``VisionAgent``, the obligation's pictures not described
yet, with its concurrency and its single retry pass, then annotates the text
ownership again. What derives from the media inspection (the injected
full-page picture, the first annotation) stays before planning.

The model call is the core's ``VisionAgent``, so the method is
``transitional`` in ``LOCAL_METHODS`` until that call becomes a Toolbox
capability (#804, the target architecture of #735).

The breaker, the region cache and the progress reporter are the run's
(``RunPorts``), the ones the enrichment before planning uses, so a provider
outage and a progress message count for the whole document. The mode is the
one the run recorded in the manifest (``region_inspection_mode``).

**The step changes obligations.** A picture the model reads as a formula
becomes a formula: its ``describe-image`` is replaced by the formula's
obligations, and a placeholder visual the model describes becomes a picture
with a ``describe-image``. The executor skips the steps of the replaced
obligations and replans for the new ones (M0, #832).

**What the result means.** ``success`` and ``validated`` say that the
collective attempt ran for every picture. They do not say that every picture
is now described. That stays per picture: one left undescribed keeps its
reason (``vision_failure_reason``: ``model_failed``, ``admission_rejected``,
``crop_unavailable``, …), and its ``describe-image`` obligation validates it.
Failing the whole obligation for one picture would block the pictures that
are described. The message reports what happened to each picture. The method
fails when the step raises, when the local model-call runner rejected a
target (``failure_kind="admission_rejected"``, #828), and when none of its
targets is in the manifest any more (``MSG_VISION_NO_PICTURE``), as
``table-enrichment`` does.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from acessilia_core.config import CoreConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import n, t
from acessilia_core.i18n.stage_messages import STAGE_ENRICHING_IMAGE_DESCRIPTIONS
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.enrichment.common import run_breaker
from acessilia_core.pipeline.enrichment.pictures import (
    _enrich_picture_descriptions,
    is_describable,
)
from acessilia_core.pipeline.handlers.common import run_status, step_checkpoint
from acessilia_core.pipeline.handlers.messages import (
    MSG_PICTURES_DESCRIBED,
    MSG_VISION_NO_PICTURE,
)
from acessilia_core.ports import RunPorts, region_cache_for
from acessilia_sdk.runtime import run_sync


async def _describe_pictures(
    manifest: ProcessingManifest,
    source: Path,
    config: CoreConfig,
    ports: RunPorts,
    targets: frozenset[str],
    obligation_id: str,
) -> None:
    """Describe the obligation's ``targets``: a second obligation
    (``obligation-describe-images-2``, #832) never describes again a picture
    an earlier one owns."""
    status = run_status(ports)
    if status is not None:
        await status(t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS))
    await _enrich_picture_descriptions(
        manifest,
        source,
        mode=str(manifest.extractor.configuration.get("region_inspection_mode", "medio")),
        vision=config.vision,
        toolbox=config.toolbox,
        models=config.models,
        region_cache=region_cache_for(ports, config.vision),
        media_inspection=ports.services.media_inspection,
        status_callback=status,
        breaker=run_breaker(ports, config.vision),
        targets=targets,
        inject=False,
        # Each finished object is saved into the execution checkpoint (#836).
        on_progress=step_checkpoint(ports, manifest, obligation_id),
    )


def _outcome(element: ManifestElement) -> str:
    """What the step left on a picture it was asked to describe."""
    if element.metadata.get("vision_description_complete"):
        return "formula" if element.type == "formula" else "described"
    if not is_describable(element):
        # Another step's element now: not tried, and said so.
        return "not_describable"
    return str(element.metadata.get("vision_failure_reason") or "undescribed")


def _handle_picture_description_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Describe the document's pictures; satisfied once the step ran for all of them."""
    obligation = next((item for item in manifest.obligations if item.id == obligation_id), None)
    targets = frozenset(obligation.target_ids) if obligation is not None else frozenset()
    pictures = [element for element in manifest.elements if element.id in targets]
    if not pictures:
        return MethodResult(success=False, validated=False, message=t(MSG_VISION_NO_PICTURE))
    already = {
        element.id for element in pictures if element.metadata.get("vision_description_complete")
    }
    run_sync(_describe_pictures(manifest, Path(manifest.source.path), config, ports, targets, obligation_id))
    outcomes = Counter(_outcome(element) for element in pictures if element.id not in already)
    described = outcomes.pop("described", 0)
    formulas = outcomes.pop("formula", 0)
    rejected = outcomes.get("admission_rejected", 0)
    return MethodResult(
        # Admission pressure means the step could not ask the model for those
        # pictures: the method is deferred, not counted as tried, so the replan
        # retries it instead of escalating them to human review (#828).
        success=not rejected,
        validated=not rejected,
        failure_kind="admission_rejected" if rejected else None,
        message=n(*MSG_PICTURES_DESCRIBED, len(pictures)).format(
            count=len(pictures),
            described=described,
            formulas=formulas,
            already=len(already),
            left=", ".join(f"{reason}: {count}" for reason, count in sorted(outcomes.items())) or "-",
        ),
    )


__all__ = ["_handle_picture_description_method"]
