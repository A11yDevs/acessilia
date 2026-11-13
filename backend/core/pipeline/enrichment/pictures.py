"""The picture enrichment stage: describe each picture with the vision model.

Runs before planning. It chooses the pictures to describe, asks the vision
model with bounded concurrency, folds each description into the manifest or
records why a picture was left undescribed, and retries the failures a second
try may fix.

Moved from the PDDL orchestrator (#402, phase 3, step 6): the code verbatim,
with the docstring of ``_inject_full_page_picture`` translated from Portuguese.

Like every module of ``backend/core`` that asks an agent (the vision or the
data agent), this one imports ``backend.agents``. The dependency is transient:
step 2 of ADR-0016's roadmap gathers the agents into the core before its
boundary test (step 5) refuses imports of ``backend`` from outside the core.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any, Literal

from docstruct.placeholders import (
    has_meaningful_text,
    is_mostly_visual,
    is_placeholder_visual,
)

from backend.agents.output_schemas import VisionOutput
from backend.agents.provider_breaker import ProviderBreaker
from backend.agents.vision_agent import VisionAgent
from backend.core.manifest.builder import (
    _derive_processing_needs,
    is_unstructured_page_placeholder,
    reconcile_reclassified_element_processing_needs,
)
from backend.core.manifest.models import (
    ManifestElement,
    ProcessingManifest,
)
from backend.core.pipeline.enrichment.common import (
    _RETRIED_VISION_FAILURES,
    _extract_picture_bytes,
    _retry_failed,
)
from backend.core.pipeline.obligations import (
    _pages_label,
)
from backend.core.pipeline.toolbox import (
    _source_artifact_id,
)
from backend.i18n import t
from backend.log_messages import (
    LOG_PDDL_EMPTY_VISION_DESCRIPTION,
    LOG_PDDL_IMAGES_ENRICHED,
    LOG_VISION_ELEMENT_DESCRIPTION,
)
from backend.services.blocking import run_blocking
from backend.stage_messages import (
    STAGE_DESCRIBING_IMAGE,
)
from backend.tools.logger import logger

#: Why a picture was left undescribed, recorded in metadata["vision_failure_reason"]
#: for the operator: the crop could not be rendered, the source has no page to
#: render and the extraction embedded no image in the picture (a DOCX or HTML
#: picture, so the model was never asked), the vision call failed (its error
#: goes to metadata["vision_failure_detail"]), or the answer had no text.
VisionFailureReason = Literal[
    "crop_unavailable", "image_unavailable", "model_failed", "empty_description"
]


def _record_vision_failure(
    element: ManifestElement, reason: VisionFailureReason, detail: str | None = None
) -> None:
    """Mark ``element`` as undescribed and say why, so a later pass describes it again."""
    element.metadata.pop("vision_description_complete", None)
    element.metadata["vision_failure_reason"] = reason
    if detail:
        element.metadata["vision_failure_detail"] = detail
    else:
        element.metadata.pop("vision_failure_detail", None)


async def _enrich_picture_descriptions(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    media_inspection: dict[str, Any] | None = None,
    status_callback: Callable[[str], Coroutine[Any, Any, None]] | None = None,
    breaker: ProviderBreaker | None = None,
) -> None:
    from backend.config.settings import settings

    _inject_full_page_picture(manifest, media_inspection)

    pictures = _pictures_to_describe(manifest)
    if not pictures:
        return

    vision = VisionAgent(mode=mode)
    breaker = breaker or ProviderBreaker(settings.vision_breaker_threshold)
    total_pages = len(manifest.pages)

    # Descriptions are independent, so they run concurrently, bounded by
    # VISION_CONCURRENCY to stay inside what the model provider accepts (a
    # rate-limited hosted API, or a local Ollama that queues beyond its own
    # parallelism). The progress callback is serialized separately: two
    # admitted tasks would otherwise interleave the state writes behind it
    # (the API's status persistence, the Telegram progress message), and even
    # serialized the emission order may vary with completion, so nothing here
    # promises FIFO delivery.
    slots = asyncio.Semaphore(max(1, settings.vision_concurrency))
    progress_lock = asyncio.Lock()

    async def describe_one(position: int, element: ManifestElement) -> bool:
        """Describe one picture and fold the answer into it; True when enriched."""
        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        async with slots:
            if status_callback:
                async with progress_lock:
                    await status_callback(
                        t(STAGE_DESCRIBING_IMAGE).format(
                            current=position,
                            total=len(pictures),
                            pages=_pages_label([fallback_page_number], len(manifest.pages)),
                        )
                    )
            if breaker.open:
                _record_vision_failure(element, "model_failed", breaker.skip_detail())
                return False
            image_bytes, page_number = await run_blocking(
                _extract_picture_bytes,
                source_file,
                element,
                fallback_page_number,
                _source_artifact_id(manifest),
                manifest.source.media_type,
            )
            if not image_bytes:
                _record_vision_failure(
                    element,
                    "crop_unavailable" if page_number >= 1 else "image_unavailable",
                )
                return False

            errors: list[str] = []
            vision_output = await vision.describe_region(
                image_bytes=image_bytes,
                # A whole presentation slide gets the page prompt and budget.
                classification=(
                    "full_page_image" if element.metadata.get("slide_visual") else "embedded_image"
                ),
                page_num=page_number,
                total_pages=total_pages,
                mode=mode,
                errors=errors,
            )
            breaker.record(isinstance(vision_output, VisionOutput))

        if not isinstance(vision_output, VisionOutput):
            _record_vision_failure(element, "model_failed", errors[-1] if errors else None)
            return False
        return _fold_picture_description(manifest, element, vision_output, page_number)

    # The fold above touches only its own element and runs without awaits, so
    # concurrent folds cannot interleave. The TaskGroup cancels the sibling
    # descriptions when one of them fails and re-raises as an ExceptionGroup,
    # matching the sequential stage this replaced — the first failure aborted
    # the stage — without leaving tasks mutating the manifest after it failed.
    async with asyncio.TaskGroup() as group:
        tasks = [
            group.create_task(describe_one(position, element))
            for position, element in enumerate(pictures, start=1)
        ]
    enriched = sum(task.result() for task in tasks)
    enriched += await _retry_failed(
        [
            (position, element)
            for position, element in enumerate(pictures, start=1)
            if element.metadata.get("vision_failure_reason") in _RETRIED_VISION_FAILURES
        ],
        describe_one,
        kind="pictures",
        breaker=breaker,
    )

    if enriched:
        logger.info(t(LOG_PDDL_IMAGES_ENRICHED).format(count=enriched))


def _pictures_to_describe(manifest: ProcessingManifest) -> list[ManifestElement]:
    """The elements the vision step describes, none already described.

    The pictures; without any, in a mostly visual document, the elements that
    stand in for visual content (``is_placeholder_visual``); and without
    those either, in a one-page mostly visual document, its first element
    that is not an unstructured-page placeholder (a page inspection reads
    that one).
    """
    pictures = [
        element
        for element in manifest.elements
        if element.type == "picture"
        and not element.metadata.get("vision_description_complete")
    ]
    if not pictures and is_mostly_visual(manifest.elements):
        pictures = [
            element
            for element in manifest.elements
            if is_placeholder_visual(element)
            and not element.metadata.get("vision_description_complete")
        ]

    if (
        not pictures
        and is_mostly_visual(manifest.elements)
        and len(manifest.pages) == 1
        and manifest.elements
    ):
        pictures = [element for element in manifest.elements
                    if not element.metadata.get("vision_description_complete")
                    and not is_unstructured_page_placeholder(element)][:1]
    return pictures


def _fold_picture_description(
    manifest: ProcessingManifest,
    element: ManifestElement,
    vision_output: VisionOutput,
    page_number: int,
) -> bool:
    """Fold the vision model's answer into ``element``; True when it is now described.

    A formula answer makes the element a formula; a description makes it a
    picture. The element is marked described when the model answered, or
    when its extractor text is still meaningful; otherwise its text is
    cleared and it is recorded as an empty description.
    """
    logger.debug(
        t(LOG_VISION_ELEMENT_DESCRIPTION).format(
            element_id=element.id,
            page_num=page_number,
            chars=len(vision_output.description),
            description=vision_output.description,
        )
    )
    element.metadata["vision_language"] = vision_output.language
    element.metadata["vision_confidence"] = vision_output.confidence
    element.metadata["vision_elements"] = list(vision_output.mentioned_elements)
    if vision_output.warnings:
        element.metadata["vision_warnings"] = list(vision_output.warnings)

    if vision_output.kind == "formula":
        element.text = vision_output.formula_latex or ""
        answered = bool(element.text.strip())
        _retype_element(manifest, element, "formula")
    else:
        # An empty answer keeps text the extractor already had; whether
        # that text is worth keeping is decided below.
        answered = bool(vision_output.description.strip())
        if answered:
            element.text = vision_output.description
        _retype_element(manifest, element, "picture")
    if element.page_number is None and page_number >= 1:
        element.page_number = page_number
    # The model's own text stands however short ("Logo" is a description);
    # text left over from the extractor after an empty answer must still be
    # meaningful. Otherwise the picture is reported as undescribed, so the
    # operator sees the model refused instead of a silent gap, and stays
    # eligible for a later pass.
    if answered or has_meaningful_text(element):
        element.metadata["vision_description_complete"] = True
        element.metadata.pop("vision_failure_reason", None)
        element.metadata.pop("vision_failure_detail", None)
        return True
    # What is left is an extractor placeholder ("body") or OCR noise, which
    # must not become the alt text.
    element.text = ""
    _record_vision_failure(element, "empty_description")
    logger.warning(
        t(LOG_PDDL_EMPTY_VISION_DESCRIPTION).format(
            element_id=element.id
        )
    )
    return False


def _retype_element(
    manifest: ProcessingManifest, element: ManifestElement, new_type: Literal["formula", "picture"]
) -> None:
    """Make ``element`` a ``new_type``, keeping its ``original_type``, and update its needs.

    Nothing changes when it already is one.
    """
    if element.type == new_type:
        return
    previous_type = element.type
    element.metadata["original_type"] = element.type
    element.type = new_type
    element.raw_label = new_type
    reconcile_reclassified_element_processing_needs(
        manifest,
        element,
        previous_type=previous_type,
    )


def _inject_full_page_picture(
    manifest: ProcessingManifest,
    media_inspection: dict[str, Any] | None,
) -> None:
    """Inject a synthetic full-page `picture` element.

    When the input is a standalone raster image (``media_inspect`` classifies it
    as an image and flags ``requires_visual_inspection=true``) and the
    structural extractor produced no visual block (picture/formula), the
    stage would have nothing to describe. This fallback creates a
    `picture` element covering the whole page so the VisionAgent describes the
    image.

    The signal is used only as an enrichment heuristic: it does not change the
    PDDL problem (the ``media_inspected``/``media_profile_classified``
    predicates belong to the Toolbox domain).
    """
    if not isinstance(media_inspection, dict):
        return
    if not media_inspection.get("is_image"):
        return
    if not media_inspection.get("requires_visual_inspection"):
        return

    has_visual_element = any(
        element.type in {"picture", "formula"} for element in manifest.elements
    )
    if has_visual_element or any(
        is_unstructured_page_placeholder(element) for element in manifest.elements
    ):
        # An empty page is already planned for visual inspection.
        return

    max_reading_order = max(
        (element.reading_order for element in manifest.elements), default=0
    )
    page_number = (
        manifest.pages[0].page_number if manifest.pages else 1
    )

    element = ManifestElement(
        id=f"element-injected-picture-{len(manifest.elements) + 1:06d}",
        type="picture",
        raw_label="picture",
        reading_order=max_reading_order + 1,
        hierarchy_level=1,
        text=None,
        page_number=page_number,
        metadata={
            "injected_picture": True,
            "media_inspection": media_inspection,
        },
    )
    manifest.elements.append(element)

    if manifest.pages:
        manifest.pages[0].element_ids.append(element.id)

    observations, obligations = _derive_processing_needs([element])
    manifest.observations.extend(observations)
    manifest.obligations.extend(obligations)

    manifest.summary.element_count = len(manifest.elements)
    manifest.summary.observation_count = len(manifest.observations)
    manifest.summary.obligation_count = len(manifest.obligations)
    manifest.summary.element_types = dict(
        sorted(Counter(item.type for item in manifest.elements).items())
    )
