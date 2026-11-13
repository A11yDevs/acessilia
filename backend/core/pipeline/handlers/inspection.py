"""Method handlers that inspect the source with the vision agent.

``pymupdf-region`` renders each target's region, and ``vision-page-inspection``
each target's page, through the core's render binding
(``backend.core.pipeline.toolbox``); the vision agent reads the image, and the
handler records what it found as evidence. Moved verbatim from the PDDL
orchestrator (#402, phase 3, step 6).

Like every module of ``backend/core`` that asks an agent (the vision or the
data agent), this one imports ``backend.agents``. The dependency is transient:
step 2 of ADR-0016's roadmap gathers the agents into the core before its
boundary test (step 5) refuses imports of ``backend`` from outside the core.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING

from backend.agents.output_schemas import PageInspectionOutput, VisionOutput
from backend.agents.vision_agent import VisionAgent
from backend.core.execution.models import MethodResult
from backend.core.manifest.builder import (
    is_unstructured_page_placeholder,
)
from backend.core.manifest.models import (
    Artifact,
    ManifestElement,
    ProcessingManifest,
)
from backend.core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from backend.core.pipeline.toolbox import (
    _source_artifact_id,
    _toolbox_render,
)
from backend.tools.formula_tools import normalize_latex

if TYPE_CHECKING:
    from acessilia_sdk.toolbox.clients.pdf import ClipOrigin


def _render_inspection_region(
    source: Path,
    element: ManifestElement,
    *,
    media_type: str | None = None,
    artifact_id: str | None = None,
) -> tuple[bytes, int, list[float]]:
    """Render only the requested, validated source region on the Toolbox.

    Crop metadata from the extractor is never trusted: the page identity and
    the box are checked here, and the Toolbox renders exactly that box and
    reports the region it applied. The page range is the document's, as the
    Toolbox reports it, like every other render: a page beyond it is refused
    there. An element without a page is accepted only in a one-page document.
    """
    provenance = element.provenance[0] if element.provenance else None
    number = provenance.page_number if provenance else element.page_number
    if provenance and element.page_number is not None and number != element.page_number:
        raise ValueError("Region page identity is inconsistent")
    if number is not None and (type(number) is not int or number < 1):
        raise ValueError("Region page is missing or out of range")
    clip: tuple[float, float, float, float] | None = None
    origin: ClipOrigin = "TOPLEFT"
    bbox = provenance.bbox if provenance else None
    if bbox is not None:
        values = (bbox.left, bbox.top, bbox.right, bbox.bottom)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("Region coordinates must be finite")
        # Unlike ordering, a crop certifies what the vision model describes,
        # so it requires an explicit origin instead of inferring one.
        if bbox.coord_origin not in {"TOPLEFT", "BOTTOMLEFT"}:
            raise ValueError("Region coordinate origin is unknown")
        clip, origin = values, bbox.coord_origin
    page = _toolbox_render(
        source, number or 1, media_type=media_type, dpi=160, clip=clip,
        clip_origin=origin, artifact_id=artifact_id,
    )
    if number is None and page.page_count != 1:
        raise ValueError("Region page is missing or out of range")
    return page.image, number or 1, list(page.clip)


def _inspect_region(image: bytes, number: int, total_pages: int, mode: str) -> VisionOutput | None:
    async def inspect():
        return await VisionAgent(mode=mode).describe_region(
            image_bytes=image, classification="embedded_image", page_num=number,
            total_pages=total_pages, mode=mode, full_budget=True,
        )

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(inspect())
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(inspect())).result()


def _save_region_artifact(content: bytes, scope: str, kind: str, suffix: str, media_type: str) -> Artifact:
    from backend.config.settings import settings

    digest = hashlib.sha256(content).hexdigest()
    path = settings.data_dir / "artifacts" / "regions" / scope / f"{digest}.{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return Artifact(
        id=f"artifact-{kind}-{scope[:16]}-{digest[:16]}", kind=kind,
        path=str(path), media_type=media_type, sha256=digest,
    )


def _handle_pymupdf_region_method(manifest: ProcessingManifest, obligation_id: str) -> MethodResult:
    """Inspect real source pixels and update targets only after every result validates."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    try:
        source = Path(manifest.source.path)
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest.source.sha256:
                raise ValueError("Region source differs from the manifest")
        inspected = []
        for element in elements:
            if element.type != "unknown":
                raise ValueError("Region inspection requires an unknown target element")
            image, number, rectangle = _render_inspection_region(
                source,
                element,
                media_type=manifest.source.media_type,
                artifact_id=_source_artifact_id(manifest),
            )
            declared_pages = {
                page.page_number for page in manifest.pages if element.id in page.element_ids
            }
            if declared_pages and declared_pages != {number}:
                raise ValueError("Region page differs from the manifest page index")
            output = _inspect_region(
                image, number, max(len(manifest.pages), number),
                str(manifest.extractor.configuration.get("region_inspection_mode", "medio")),
            )
            if not isinstance(output, VisionOutput):
                raise ValueError(f"Region inspection failed for {element.id}")
            output = VisionOutput.model_validate(output.model_dump())
            text = output.description if output.kind == "description" else normalize_latex(output.formula_latex or "")
            if not text.strip():
                raise ValueError(f"Region inspection returned empty content for {element.id}")
            inspected.append((element, image, number, rectangle, output, text))

        artifacts = []
        replacements = {}
        for element, image, number, rectangle, output, text in inspected:
            scope = hashlib.sha256(json.dumps([
                manifest.manifest_id, manifest.source.sha256, manifest.revision, obligation_id, element.id,
            ]).encode()).hexdigest()
            crop = _save_region_artifact(image, scope, "region-crop", "png", "image/png")
            evidence = {
                "source_sha256": manifest.source.sha256, "element_id": element.id,
                "page_number": number, "bbox": rectangle, "crop_sha256": crop.sha256,
                "result": output.model_dump(),
            }
            record = _save_region_artifact(
                json.dumps(evidence, ensure_ascii=False, sort_keys=True).encode(),
                scope, "region-inspection", "json", "application/json",
            )
            replacement = element.model_copy(deep=True)
            replacement.metadata.update(
                original_type=element.type, vision_description_complete=True,
                vision_language=output.language, vision_confidence=output.confidence,
                vision_warnings=output.warnings, region_crop=crop.path,
                region_inspection=record.id,
            )
            replacement.text = text
            replacement.type = "formula" if output.kind == "formula" else "picture"
            if replacement.type == "picture":
                replacement.metadata["src"] = (
                    "data:image/png;base64," + base64.b64encode(image).decode("ascii")
                )
            replacement.raw_label = replacement.type
            replacement.page_number = number
            replacements[element.id] = replacement
            artifacts.extend([crop, record])
        manifest.elements = [replacements.get(element.id, element) for element in manifest.elements]
        manifest.summary.element_types = dict(Counter(element.type for element in manifest.elements))
        return MethodResult(
            success=True, validated=True,
            message=f"Inspected {len(elements)} source region(s)", artifacts=artifacts,
        )
    except Exception as exc:
        return MethodResult(
            success=False, validated=False,
            message=f"Region inspection failed: {type(exc).__name__}: {exc}",
        )


def _render_source_page(
    source: Path, media_type: str, number: int, artifact_id: str | None = None
) -> bytes:
    """The PNG of page ``number`` of a PDF, PNG or JPEG input, rendered by the Toolbox."""
    from backend.config.settings import settings

    return _toolbox_render(
        source, number, media_type=media_type, dpi=settings.pdf_split_dpi,
        artifact_id=artifact_id,
    ).image


def _inspect_page(image: bytes, number: int, total_pages: int, mode: str) -> PageInspectionOutput:
    from acessilia_sdk.runtime import run_sync

    return run_sync(
        VisionAgent(mode=mode).inspect_page(
            image_bytes=image, page_num=number, total_pages=total_pages
        )
    )


def _handle_vision_page_inspection_method(
    manifest: ProcessingManifest, obligation_id: str
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
        source = Path(manifest.source.path)
        with source.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != manifest.source.sha256:
                raise ValueError("Page source differs from the manifest")
        total_pages = max(len(manifest.pages), 1)
        mode = str(manifest.extractor.configuration.get("region_inspection_mode", "medio"))

        inspected = []
        for element in elements:
            number = element.page_number or 1
            image = _render_source_page(
                source, manifest.source.media_type, number, _source_artifact_id(manifest)
            )
            output = _inspect_page(image, number, total_pages, mode)
            if not isinstance(output, PageInspectionOutput):
                raise TypeError("Page inspection returned no structured output")
            inspected.append((element, number, image, output))

        artifacts: list[Artifact] = []
        replacements: dict[str, ManifestElement] = {}
        blank = 0
        for element, number, image, output in inspected:
            scope = hashlib.sha256(json.dumps([
                manifest.manifest_id, manifest.source.sha256, manifest.revision,
                obligation_id, element.id,
            ]).encode()).hexdigest()
            page_image = _save_region_artifact(image, scope, "page-render", "png", "image/png")
            record = _save_region_artifact(
                json.dumps(
                    {
                        "source_sha256": manifest.source.sha256,
                        "element_id": element.id,
                        "page_number": number,
                        "page_image_sha256": page_image.sha256,
                        "result": output.model_dump(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ).encode(),
                scope, "page-inspection", "json", "application/json",
            )
            artifacts.extend([page_image, record])
            replacement = element.model_copy(deep=True)
            replacement.metadata.update(
                page_inspection=record.id,
                vision_language=output.language,
                vision_confidence=output.confidence,
                vision_warnings=list(output.warnings),
            )
            if output.kind == "blank":
                replacement.metadata["blank_page"] = True
                blank += 1
            else:
                replacement.type = "picture"
                replacement.raw_label = "picture"
                replacement.text = output.description
                replacement.metadata.update(
                    original_type=element.type,
                    vision_description_complete=True,
                    src="data:image/png;base64," + base64.b64encode(image).decode("ascii"),
                )
            replacements[element.id] = replacement

        manifest.elements = [replacements.get(item.id, item) for item in manifest.elements]
        manifest.summary.element_types = dict(Counter(item.type for item in manifest.elements))
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
