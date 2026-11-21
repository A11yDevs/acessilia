"""Method handlers that inspect the source with the vision agent.

``pymupdf-region`` renders each target's region, and ``vision-page-inspection``
each target's page, through the core's render binding
(``acessilia_core.pipeline.toolbox``); the vision agent reads the image, and the
handler records what it found as evidence. Moved verbatim from the PDDL
orchestrator (#402, phase 3, step 6).

The agents it asks (the vision or the data agent) live in the core, in
``acessilia_core.agents`` (ADR-0016, step 2).
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from acessilia_sdk.runtime import run_sync

from acessilia_core.agents.output_schemas import PageInspectionOutput, VisionOutput
from acessilia_core.agents.vision_agent import VisionAgent
from acessilia_core.config import CoreConfig, ModelConfig, ToolboxConfig
from acessilia_core.execution.models import MethodResult
from acessilia_core.formula_tools import normalize_latex
from acessilia_core.manifest.builder import (
    is_unstructured_page_placeholder,
)
from acessilia_core.manifest.models import (
    Artifact,
    ManifestElement,
    ProcessingManifest,
)
from acessilia_core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
    write_atomic_artifact,
)
from acessilia_core.pipeline.toolbox import (
    _source_artifact_id,
    _toolbox_render,
)
from acessilia_core.ports import RegionCache, RunPorts, region_cache_for

if TYPE_CHECKING:
    from acessilia_sdk.toolbox.clients.pdf import ClipOrigin


def _resolve_region_page_number(element: ManifestElement) -> int | None:
    provenance = element.provenance[0] if element.provenance else None
    number = provenance.page_number if provenance else element.page_number
    if provenance and element.page_number is not None and number != element.page_number:
        raise ValueError("Region page identity is inconsistent")
    if number is not None and (type(number) is not int or number < 1):
        raise ValueError("Region page is missing or out of range")
    return number


def _validated_region_clip(
    element: ManifestElement,
) -> tuple[tuple[float, float, float, float] | None, ClipOrigin]:
    provenance = element.provenance[0] if element.provenance else None
    bbox = provenance.bbox if provenance else None
    if bbox is None:
        return None, "TOPLEFT"
    values = (bbox.left, bbox.top, bbox.right, bbox.bottom)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Region coordinates must be finite")
    # Unlike ordering, a crop certifies what the vision model describes,
    # so it requires an explicit origin instead of inferring one.
    if bbox.coord_origin not in {"TOPLEFT", "BOTTOMLEFT"}:
        raise ValueError("Region coordinate origin is unknown")
    return values, bbox.coord_origin


def _render_inspection_region(
    source: Path,
    element: ManifestElement,
    *,
    media_type: str | None = None,
    artifact_id: str | None = None,
    toolbox: ToolboxConfig,
) -> tuple[bytes, int, list[float]]:
    """Render only the requested, validated source region on the Toolbox.

    Crop metadata from the extractor is never trusted: the page identity and
    the box are checked here, and the Toolbox renders exactly that box and
    reports the region it applied. The page range is the document's, as the
    Toolbox reports it, like every other render: a page beyond it is refused
    there. An element without a page is accepted only in a one-page document.
    """
    number = _resolve_region_page_number(element)
    clip, origin = _validated_region_clip(element)
    page = _toolbox_render(
        source, number or 1, media_type=media_type, dpi=160, clip=clip,
        clip_origin=origin, artifact_id=artifact_id, toolbox=toolbox,
    )
    if number is None and page.page_count != 1:
        raise ValueError("Region page is missing or out of range")
    return page.image, number or 1, list(page.clip)


def _inspect_region(
    image: bytes,
    number: int,
    total_pages: int,
    mode: str,
    *,
    region_cache: RegionCache | None,
    toolbox: ToolboxConfig,
    models: ModelConfig,
) -> VisionOutput | None:
    async def inspect():
        agent = VisionAgent(
            mode=mode, region_cache=region_cache, toolbox=toolbox, models=models
        )
        return await agent.describe_region(
            image_bytes=image, classification="embedded_image", page_num=number,
            total_pages=total_pages, mode=mode, full_budget=True,
        )

    return run_sync(inspect())


def _save_region_artifact(
    content: bytes, scope: str, kind: str, suffix: str, media_type: str, *, data_dir: Path
) -> Artifact:
    """Write ``content`` atomically under the run's ``data_dir``, named by its digest."""
    return write_atomic_artifact(
        content,
        category="regions",
        scope=scope,
        kind=kind,
        suffix=suffix,
        media_type=media_type,
        data_dir=data_dir,
    )


@dataclass(frozen=True)
class _InspectedRegion:
    element: ManifestElement
    image: bytes
    page_number: int
    rectangle: list[float]
    output: VisionOutput
    text: str


@dataclass(frozen=True)
class _InspectedPage:
    element: ManifestElement
    page_number: int
    image: bytes
    output: PageInspectionOutput


def _verify_source_digest(manifest: ProcessingManifest, *, error_message: str) -> Path:
    source = Path(manifest.source.path)
    with source.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != manifest.source.sha256:
            raise ValueError(error_message)
    return source


def _inspection_artifact_scope(
    manifest: ProcessingManifest, obligation_id: str, element_id: str
) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                manifest.manifest_id,
                manifest.source.sha256,
                manifest.revision,
                obligation_id,
                element_id,
            ]
        ).encode()
    ).hexdigest()


def _apply_inspected_replacements(
    manifest: ProcessingManifest, replacements: dict[str, ManifestElement]
) -> None:
    manifest.elements = [
        replacements.get(item.id, item) for item in manifest.elements
    ]
    manifest.summary.element_types = dict(
        Counter(item.type for item in manifest.elements)
    )


def _inspect_region_target(
    manifest: ProcessingManifest,
    element: ManifestElement,
    *,
    source: Path,
    config: CoreConfig,
    ports: RunPorts,
) -> _InspectedRegion:
    if element.type != "unknown":
        raise ValueError("Region inspection requires an unknown target element")
    image, number, rectangle = _render_inspection_region(
        source,
        element,
        media_type=manifest.source.media_type,
        artifact_id=_source_artifact_id(manifest),
        toolbox=config.toolbox,
    )
    declared_pages = {
        page.page_number for page in manifest.pages if element.id in page.element_ids
    }
    if declared_pages and declared_pages != {number}:
        raise ValueError("Region page differs from the manifest page index")
    output = _inspect_region(
        image,
        number,
        max(len(manifest.pages), number),
        str(manifest.extractor.configuration.get("region_inspection_mode", "medio")),
        region_cache=region_cache_for(ports, config.vision),
        toolbox=config.toolbox,
        models=config.models,
    )
    if not isinstance(output, VisionOutput):
        raise ValueError(f"Region inspection failed for {element.id}")
    output = VisionOutput.model_validate(output.model_dump())
    text = (
        output.description
        if output.kind == "description"
        else normalize_latex(output.formula_latex or "")
    )
    if not text.strip():
        raise ValueError(f"Region inspection returned empty content for {element.id}")
    return _InspectedRegion(
        element=element,
        image=image,
        page_number=number,
        rectangle=rectangle,
        output=output,
        text=text,
    )


def _persist_region_inspection(
    manifest: ProcessingManifest,
    obligation_id: str,
    item: _InspectedRegion,
    *,
    data_dir: Path,
) -> tuple[ManifestElement, list[Artifact]]:
    scope = _inspection_artifact_scope(manifest, obligation_id, item.element.id)
    crop = _save_region_artifact(
        item.image, scope, "region-crop", "png", "image/png", data_dir=data_dir
    )
    evidence = {
        "source_sha256": manifest.source.sha256,
        "element_id": item.element.id,
        "page_number": item.page_number,
        "bbox": item.rectangle,
        "crop_sha256": crop.sha256,
        "result": item.output.model_dump(),
    }
    record = _save_region_artifact(
        json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode(),
        scope,
        "region-inspection",
        "json",
        "application/json",
        data_dir=data_dir,
    )
    replacement = item.element.model_copy(deep=True)
    replacement.metadata.update(
        original_type=item.element.type,
        vision_description_complete=True,
        vision_language=item.output.language,
        vision_confidence=item.output.confidence,
        vision_elements=list(item.output.mentioned_elements),
        vision_warnings=list(item.output.warnings),
        region_crop=crop.path,
        region_inspection=record.id,
    )
    # A successful inspection replaces the failed description (#680): the
    # failure keys would otherwise keep the element counted as undescribed.
    replacement.metadata.pop("vision_failure_reason", None)
    replacement.metadata.pop("vision_failure_detail", None)
    replacement.text = item.text
    replacement.type = "formula" if item.output.kind == "formula" else "picture"
    if replacement.type == "picture":
        replacement.metadata["src"] = (
            "data:image/png;base64," + base64.b64encode(item.image).decode("ascii")
        )
    replacement.raw_label = replacement.type
    replacement.page_number = item.page_number
    return replacement, [crop, record]


def _handle_pymupdf_region_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Inspect real source pixels and update targets only after every result validates."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    try:
        source = _verify_source_digest(
            manifest, error_message="Region source differs from the manifest"
        )
        inspected = [
            _inspect_region_target(
                manifest, element, source=source, config=config, ports=ports
            )
            for element in elements
        ]
        artifacts: list[Artifact] = []
        replacements: dict[str, ManifestElement] = {}
        for item in inspected:
            replacement, item_artifacts = _persist_region_inspection(
                manifest, obligation_id, item, data_dir=config.paths.data_dir
            )
            replacements[item.element.id] = replacement
            artifacts.extend(item_artifacts)
        _apply_inspected_replacements(manifest, replacements)
        return MethodResult(
            success=True,
            validated=True,
            message=f"Inspected {len(elements)} source region(s)",
            artifacts=artifacts,
        )
    except Exception as exc:
        return MethodResult(
            success=False,
            validated=False,
            message=f"Region inspection failed: {type(exc).__name__}: {exc}",
        )


def _render_source_page(
    source: Path,
    media_type: str,
    number: int,
    artifact_id: str | None = None,
    *,
    dpi: int,
    toolbox: ToolboxConfig,
) -> bytes:
    """The PNG of page ``number`` of a PDF, PNG or JPEG input, rendered by the Toolbox."""
    return _toolbox_render(
        source, number, media_type=media_type, dpi=dpi,
        artifact_id=artifact_id, toolbox=toolbox,
    ).image


def _inspect_page(
    image: bytes,
    number: int,
    total_pages: int,
    mode: str,
    *,
    region_cache: RegionCache | None,
    toolbox: ToolboxConfig,
    models: ModelConfig,
) -> PageInspectionOutput:
    return run_sync(
        VisionAgent(
            mode=mode, region_cache=region_cache, toolbox=toolbox, models=models
        ).inspect_page(
            image_bytes=image, page_num=number, total_pages=total_pages
        )
    )


def _inspect_unstructured_page_target(
    manifest: ProcessingManifest,
    element: ManifestElement,
    *,
    source: Path,
    total_pages: int,
    mode: str,
    config: CoreConfig,
    ports: RunPorts,
) -> _InspectedPage:
    number = element.page_number or 1
    image = _render_source_page(
        source,
        manifest.source.media_type,
        number,
        _source_artifact_id(manifest),
        dpi=config.vision.pdf_split_dpi,
        toolbox=config.toolbox,
    )
    output = _inspect_page(
        image,
        number,
        total_pages,
        mode,
        region_cache=region_cache_for(ports, config.vision),
        toolbox=config.toolbox,
        models=config.models,
    )
    if not isinstance(output, PageInspectionOutput):
        raise TypeError("Page inspection returned no structured output")
    return _InspectedPage(
        element=element, page_number=number, image=image, output=output
    )


def _persist_page_inspection(
    manifest: ProcessingManifest,
    obligation_id: str,
    item: _InspectedPage,
    *,
    data_dir: Path,
) -> tuple[ManifestElement, list[Artifact], bool]:
    scope = _inspection_artifact_scope(manifest, obligation_id, item.element.id)
    page_image = _save_region_artifact(
        item.image, scope, "page-render", "png", "image/png", data_dir=data_dir
    )
    record = _save_region_artifact(
        json.dumps(
            {
                "source_sha256": manifest.source.sha256,
                "element_id": item.element.id,
                "page_number": item.page_number,
                "page_image_sha256": page_image.sha256,
                "result": item.output.model_dump(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode(),
        scope,
        "page-inspection",
        "json",
        "application/json",
        data_dir=data_dir,
    )
    replacement = item.element.model_copy(deep=True)
    replacement.metadata.update(
        page_inspection=record.id,
        vision_language=item.output.language,
        vision_confidence=item.output.confidence,
        vision_warnings=list(item.output.warnings),
    )
    is_blank = item.output.kind == "blank"
    if is_blank:
        replacement.metadata["blank_page"] = True
    else:
        replacement.type = "picture"
        replacement.raw_label = "picture"
        replacement.text = item.output.description
        replacement.metadata.update(
            original_type=item.element.type,
            vision_description_complete=True,
            src="data:image/png;base64," + base64.b64encode(item.image).decode("ascii"),
        )
        # The page is now described; a previous failure is no longer true (#680).
        replacement.metadata.pop("vision_failure_reason", None)
        replacement.metadata.pop("vision_failure_detail", None)
    return replacement, [page_image, record], is_blank


def _handle_vision_page_inspection_method(
    manifest: ProcessingManifest, obligation_id: str, *, config: CoreConfig, ports: RunPorts
) -> MethodResult:
    """Look at a page the extractor left empty: describe it, or accept it as blank.

    The page is rendered by the Toolbox and judged by the vision model. A page
    with content replaces its placeholder with a ``picture`` that carries the
    page image and its accessible description; a blank page keeps the
    placeholder, marked ``blank_page`` so the canonical document skips it. The
    manifest changes only after every target page validates. Any failure (the
    Toolbox, the model, an invalid answer) fails the method, so a page is never
    dropped silently; the obligation is critical.
    """
    elements = [
        element
        for element in _target_elements(manifest, obligation_id)
        if is_unstructured_page_placeholder(element)
    ]
    if not elements:
        return _missing_obligation(obligation_id)
    try:
        source = _verify_source_digest(
            manifest, error_message="Page source differs from the manifest"
        )
        total_pages = max(len(manifest.pages), 1)
        mode = str(manifest.extractor.configuration.get("region_inspection_mode", "medio"))
        inspected = [
            _inspect_unstructured_page_target(
                manifest,
                element,
                source=source,
                total_pages=total_pages,
                mode=mode,
                config=config,
                ports=ports,
            )
            for element in elements
        ]
        artifacts: list[Artifact] = []
        replacements: dict[str, ManifestElement] = {}
        blank = 0
        for item in inspected:
            replacement, item_artifacts, is_blank = _persist_page_inspection(
                manifest, obligation_id, item, data_dir=config.paths.data_dir
            )
            replacements[item.element.id] = replacement
            artifacts.extend(item_artifacts)
            if is_blank:
                blank += 1
        _apply_inspected_replacements(manifest, replacements)
        return MethodResult(
            success=True,
            validated=True,
            message=(
                f"Inspected {len(inspected)} unstructured page(s): "
                f"{len(inspected) - blank} described, {blank} blank"
            ),
            artifacts=artifacts,
        )
    except Exception as exc:
        return MethodResult(
            success=False,
            validated=False,
            message=f"Page inspection failed: {type(exc).__name__}: {exc}",
        )
