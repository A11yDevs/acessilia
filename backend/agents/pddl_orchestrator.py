from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import math
import os
import re
import tempfile
from collections import Counter
from collections.abc import Callable, Coroutine, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docstruct.fusion.tailjoin import is_page_number as _is_page_number
from docstruct.tables.ast import effective_section_width, linearize_table_for_text
from docstruct.text.norm_fix import norm_fix

from backend.services.blocking import run_blocking
from backend.agents.data_agent import DataAgent
from backend.agents.output_schemas import DataOutput, PageInspectionOutput, VisionOutput
from backend.agents.vision_agent import VisionAgent
from backend.core.agents.fusion_agent import FusionAgent
from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import ExecutorAgent, MethodRegistry
from backend.core.execution.models import ExecutionReport, MethodResult
from backend.core.execution.messages import EXE_COMPLETED_OBLIGATIONS_UNSATISFIED
from backend.core.manifest.builder import (
    SECONDARY_EXTRACTION_KIND,
    _derive_processing_needs,
    is_unstructured_page_placeholder,
    reconcile_reclassified_element_processing_needs,
)
from backend.core.manifest.models import (
    Artifact,
    ManifestElement,
    Obligation,
    PageDescriptor,
    ProcessingManifest,
    is_bottom_left,
)
from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanningComparison
from backend.core.planning import toolbox_gate
from backend.core.planning.planner_agent import PlannerAgent
from backend.i18n import t
from backend.log_messages import (
    LOG_MEDIA_INSPECT_FAILED,
    LOG_PDDL_ELEMENT_CROP_FAILED,
    LOG_PDDL_EMPTY_VISION_DESCRIPTION,
    LOG_PDDL_IMAGES_ENRICHED,
    LOG_PDDL_PREFERRED_PLAN_MISSING,
    LOG_PDDL_TABLES_ENRICHED,
)
from backend.stage_messages import (
    STAGE_ANALYZING_STRUCTURAL,
    STAGE_STRUCTURAL_EXTRACTION_FAILED,
    STAGE_ENRICHING_IMAGE_DESCRIPTIONS,
    STAGE_ENRICHING_TABLES_OCR,
    STAGE_GENERATING_PDDL_PLAN,
    STAGE_VALIDATING_PLAN_DRY_RUN,
    STAGE_EXECUTING_PLAN,
)
from backend.tools.code_tools import normalize_code_text
from backend.tools.formula_tools import (
    latex_to_mathml,
    normalize_latex,
    verbalize_latex_fallback,
)
from backend.tools.logger import logger
from backend.tools.media_inspect import inspect_source_media
from backend.tools.toolbox_client import ToolboxError


def _formula_elements_for_obligation(
    manifest: ProcessingManifest, obligation_id: str
) -> list[ManifestElement]:
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return []
    targets = set(obligation.target_ids)
    return [
        el for el in manifest.elements if el.id in targets and el.type == "formula"
    ]


def _handle_mathml_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Converte o LaTeX das fórmulas alvo em MathML (metadata.mathml)."""
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )
    converted = 0
    for element in elements:
        mathml = latex_to_mathml(element.text or "")
        if mathml:
            element.metadata["mathml"] = mathml
            converted += 1
    if converted == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=f"MathML gerado para {converted} fórmula(s)",
        )
    return MethodResult(
        success=False,
        validated=False,
        message=f"MathML gerado para {converted}/{len(elements)} fórmula(s)",
    )


def _handle_latex_verbalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Gera verbalização pt-BR determinística das fórmulas (metadata.verbalization)."""
    elements = _formula_elements_for_obligation(manifest, obligation_id)
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )
    verbalized = 0
    for element in elements:
        latex = normalize_latex(element.text or "")
        spoken = verbalize_latex_fallback(latex) if latex else ""
        if spoken:
            element.metadata["verbalization"] = spoken
            verbalized += 1
    if verbalized == len(elements):
        return MethodResult(
            success=True,
            validated=True,
            message=f"Verbalização gerada para {verbalized} fórmula(s)",
        )
    return MethodResult(
        success=False,
        validated=False,
        message=f"Verbalização gerada para {verbalized}/{len(elements)} fórmula(s)",
    )


def _run_extract_fused(
    source_path: Path, *, artifact_id: str | None = None
) -> dict:
    """Executa ``extract_fused`` respeitando o contexto de event loop.

    Detecta a presença de um event loop **antes** de criar a coroutine,
    evitando criar um objeto coroutine que ficaria sem ``await`` (e
    produziria ``RuntimeWarning: coroutine ... was never awaited``).

    Nota de arquitetura: quando chamado a partir de um thread com event
    loop ativo (Agno Workflow, API), ``.result()`` ainda bloqueia o loop
    chamador até a fusão terminar. O contrato dos handlers permanece
    síncrono; quem invoca o executor a partir de código async deve rodar
    o executor inteiro via ``await run_blocking(...)`` para não
    bloquear o event loop principal.
    """
    import concurrent.futures

    from backend.pipeline.fusion import extract_fused

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Contexto síncrono (executor determinístico, CLI, testes):
        # não existe event loop ativo neste thread.
        return asyncio.run(extract_fused(source_path, artifact_id=artifact_id))

    # Já existe um event loop neste thread; como o handler é síncrono,
    # a coroutine é executada em um thread dedicado com seu próprio loop.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            lambda: asyncio.run(
                extract_fused(source_path, artifact_id=artifact_id)
            )
        ).result()


def _run_extract_single_provider(source_path: Path) -> dict[str, Any]:
    """Extract through the configured Toolbox provider for the PDDL fallback."""
    import concurrent.futures

    from acessilia_sdk.toolbox.clients import ToolboxStructureClient
    from backend.tools.toolbox_client import make_toolbox_client

    async def extract() -> dict[str, Any]:
        client = make_toolbox_client(ToolboxStructureClient)
        try:
            return await client.extract_structure(
                file_path=source_path,
                language="pt-BR",
                use_remote_cache=False,
            )
        finally:
            await client.close()

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(extract())

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(extract())).result()


def _fusion_agent() -> FusionAgent:
    """Fusion agent used to reach the deterministic fusion primitives.

    The `docstruct` functions take classified blocks, counters and tuning
    parameters; `FusionAgent.process_*` is the in-repo entry point that supplies
    them, so handlers call that instead of a primitive whose signature they would
    otherwise have to guess.
    """
    return FusionAgent()


def _element_bbox(
    element: ManifestElement,
    manifest: ProcessingManifest,
) -> tuple[float, float, float, float] | None:
    """Element bounding box normalized to the unit page expected by docstruct."""
    for item in element.provenance:
        box = getattr(item, "bbox", None)
        if box is None:
            continue
        page = next(
            (
                page
                for page in manifest.pages
                if page.page_number == item.page_number
            ),
            None,
        )
        if page is None or not page.width or not page.height:
            return None
        top, bottom = box.top, box.bottom
        if is_bottom_left(box.coord_origin, top, bottom):
            top, bottom = page.height - top, page.height - bottom
        return (
            box.left / page.width,
            top / page.height,
            box.right / page.width,
            bottom / page.height,
        )
    return None


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


def _handle_vision_description_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require every picture target to already carry a description.

    The description itself is produced before planning (`_enrich_picture_descriptions`
    tries the vision model and falls back to a deterministic description), so this
    method validates that the work the planner is asking for actually happened
    instead of pretending to perform it. A picture that is still undescribed is a
    real failure and keeps the next admissible method available.
    """
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "picture"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma imagem encontrada para a obrigação",
        )

    undescribed = [
        el for el in elements
        if not (
            bool((el.text or "").strip())
            if el.metadata.get("vision_description_complete")
            else _has_meaningful_text(el)
        )
    ]
    if undescribed:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Imagem sem descrição textual: "
                + ", ".join(el.id for el in undescribed)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Descrição validada para {len(elements)} imagem(ns)",
    )


def _handle_pandoc_table_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Require the table targets to carry a structured AST."""
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "table"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma tabela encontrada para a obrigação",
        )

    missing = []
    for element in elements:
        try:
            usable = _table_element_has_structured_content(element)
            table_ast = element.metadata.get("table_ast")
            if usable:
                usable = any(
                    value.strip() for row in _rows_from_table_ast(table_ast) for value in row
                )
                linearize_table_for_text({"table_ast": table_ast})
        except (TypeError, ValueError, AttributeError):
            usable = False
        if not usable:
            missing.append(element)
    if missing:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Tabela sem estrutura tabular: "
                + ", ".join(el.id for el in missing)
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Estrutura tabular validada para {len(elements)} tabela(s)",
    )


def _handle_pandoc_code_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize code targets in place and record the normalized language."""
    elements = [
        el for el in _target_elements(manifest, obligation_id) if el.type == "code"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de código encontrado para a obrigação",
        )

    normalized = 0
    for element in elements:
        text = normalize_code_text(element.text or "")
        if not text:
            continue
        element.text = text
        element.metadata["code_normalized"] = True
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"Código normalizado em {normalized}/{len(elements)} bloco(s)"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Código normalizado em {normalized} bloco(s)",
    )


def _handle_latex_normalizer_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Normalize the LaTeX of every formula target in place."""
    elements = [
        el
        for el in _target_elements(manifest, obligation_id)
        if el.type == "formula"
    ]
    if not elements:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma fórmula encontrada para a obrigação",
        )

    normalized = 0
    for element in elements:
        cleaned = normalize_latex(element.text or "")
        if not cleaned:
            continue
        element.metadata["latex_normalized"] = cleaned
        normalized += 1

    if normalized != len(elements):
        return MethodResult(
            success=False,
            validated=False,
            message=(
                f"LaTeX normalizado em {normalized}/{len(elements)} fórmula(s)"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"LaTeX normalizado em {normalized} fórmula(s)",
    )


def _handle_norm_fix_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Apply the deterministic text cleanups (ligatures, hyphenation, NBSP)."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fixed = 0
    for element in elements:
        current = element.text or ""
        if not current:
            continue
        cleaned = norm_fix(current)
        if cleaned != current:
            element.text = cleaned
            element.metadata["norm_fixed"] = True
        fixed += 1

    if not fixed:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum texto elegível para normalização",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Normalização determinística aplicada em {fixed} elemento(s)",
    )


def _render_inspection_region(
    source: Path,
    element: ManifestElement,
    *,
    page_count: int,
    artifact_id: str | None = None,
) -> tuple[bytes, int, list[float]]:
    """Render only the requested, validated source region on the Toolbox.

    Crop metadata from the extractor is never trusted: the page identity and
    the box are checked here, and the Toolbox renders exactly that box and
    reports the region it applied.
    """
    provenance = element.provenance[0] if element.provenance else None
    number = provenance.page_number if provenance else element.page_number
    if provenance and element.page_number is not None and number != element.page_number:
        raise ValueError("Region page identity is inconsistent")
    if number is None and page_count == 1:
        number = 1
    if type(number) is not int or not 1 <= number <= page_count:
        raise ValueError("Region page is missing or out of range")
    clip: tuple[float, float, float, float] | None = None
    origin = "TOPLEFT"
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
        source, number, dpi=160, clip=clip, clip_origin=origin, artifact_id=artifact_id
    )
    return page.image, number, list(page.clip)

def _inspect_region(image: bytes, number: int, total_pages: int, mode: str) -> VisionOutput | None:
    async def inspect():
        return await VisionAgent(mode=mode).describe_region(
            image_bytes=image, classification="embedded_image", page_num=number,
            total_pages=total_pages, mode=mode,
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
                page_count=max(len(manifest.pages), 1),
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


def _source_artifact_id(manifest: ProcessingManifest) -> str | None:
    """The Toolbox artifact of the source document, when the extractor stored one."""
    value = (manifest.extractor.configuration or {}).get("artifact_id")
    return value if isinstance(value, str) and value else None


def _toolbox_render(
    source: Path,
    page_number: int,
    *,
    dpi: int,
    max_side: int | None = None,
    clip: tuple[float, float, float, float] | None = None,
    clip_origin: str = "TOPLEFT",
    artifact_id: str | None = None,
):
    """Render a page (or a region of it) on the Toolbox with ``pdf.render@2``.

    There is no local rendering (docs/adr/0003): the Toolbox converts, clips,
    bounds and refuses oversized renders, and reports what it applied. With
    ``artifact_id`` the source already stored by the extractor is referenced
    instead of uploaded; the file is sent only if the Toolbox no longer has it.
    """
    from acessilia_sdk.toolbox.clients import ToolboxPdfClient

    from backend.tools.toolbox_client import make_toolbox_client, run_sync

    async def render():
        client = make_toolbox_client(
            ToolboxPdfClient, resend_file_on_missing_artifact=artifact_id is not None
        )
        try:
            return await client.render(
                file_path=source,
                artifact_id=artifact_id,
                page_number=page_number,
                dpi=dpi,
                max_side=max_side,
                clip=clip,
                clip_origin=clip_origin,
            )
        finally:
            await client.close()

    return run_sync(render())


def _render_source_page(
    source: Path, media_type: str, number: int, artifact_id: str | None = None
) -> bytes:
    """The PNG of page ``number`` of a PDF or raster input, rendered by the Toolbox."""
    from backend.config.settings import settings

    return _toolbox_render(
        source, number, dpi=settings.pdf_split_dpi, artifact_id=artifact_id
    ).image

def _inspect_page(image: bytes, number: int, total_pages: int, mode: str) -> PageInspectionOutput:
    from backend.tools.toolbox_client import run_sync

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


def _handle_repetition_guard_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Remove repeated token loops from the obligation's current page text."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fusion_agent = _fusion_agent()
    cut_total = 0
    for element in elements:
        result = fusion_agent.process_guard_repetition(element.text or "")
        cut = int(result["tokens_cut"])
        if not cut:
            continue
        element.text = result["text"]
        element.metadata["repetition_guard"] = {"tokens_cut": cut}
        cut_total += cut

    if not cut_total:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhuma repetição degenerada encontrada nos alvos",
        )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Guarda de repetição removeu {cut_total} token(s)",
    )


def _element_blocks(
    elements: list[ManifestElement],
    manifest: ProcessingManifest,
) -> list[dict[str, Any]]:
    """Manifest elements as the fusion stack's block dicts.

    The deterministic primitives in `docstruct` operate on classified blocks, not
    on bare strings, so the elements are adapted once here instead of each handler
    guessing at a signature.
    """
    blocks: list[dict[str, Any]] = []
    for element in elements:
        bbox = _element_bbox(element, manifest)
        blocks.append(
            {
                "md": element.text or "",
                "text": element.text or "",
                "kind": _block_kind(element),
                "type": element.type,
                "role": _element_role(element),
                "box": list(bbox) if bbox else None,
            }
        )
    return blocks


def _element_role(element: ManifestElement) -> str | None:
    """Fusion block role for an element.

    The manifest builder records page furniture in `element.type`
    (`page_header`/`page_footer`) and does not populate `metadata["role"]`, so the
    role is derived from the type when the metadata does not carry one.
    """
    role = (element.metadata or {}).get("role")
    if role:
        return role
    return {"page_header": "header", "page_footer": "footer"}.get(element.type)


def _block_kind(element: ManifestElement) -> str:
    """Fusion block kind for an element type (`DiffBlock.kind` vocabulary)."""
    if element.type == "heading":
        return "heading"
    if element.type == "table":
        return "table"
    if element.type == "formula":
        return "formula"
    return "text"


def _handle_extract_line_numbers_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pull marginal verse line numbers out of the target blocks.

    Uses `FusionAgent.process_extract_line_numbers`, which is the supported entry
    point: `docstruct.fusion.line_numbers.extract_line_numbers` needs a block list
    plus a stats counter and a provenance tag, so calling it with a plain string
    raised `TypeError` on every step.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    result = _fusion_agent().process_extract_line_numbers(
        _element_blocks(elements, manifest)
    )
    extracted = int(result.get("stats", {}).get("line-numbers-agent-count", 0))
    if not extracted:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum número de linha marginal encontrado",
        )
    for element in elements:
        element.metadata["line_numbers_extracted"] = extracted
    return MethodResult(
        success=True,
        validated=True,
        message=f"{extracted} número(s) de linha extraído(s)",
    )


def _handle_chunk_verse_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Split verse/record blocks into chunks the evaluator can re-group.

    `docstruct.fusion.verse.chunk_verse` takes already-split lines plus a character
    budget, so the handler goes through `FusionAgent.process_chunk_verse`, which
    detects the verse lines itself.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    result = _fusion_agent().process_chunk_verse(_element_blocks(elements, manifest))
    # `verse_blocks` reports `verse-{tag}-{whole,kept,split,chunks}`; only the
    # blocks it actually split are evidence that the method did anything.
    chunks = result.get("stats", {}).get("verse-agent-split", 0)
    if not chunks:
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de verso elegível para fragmentação",
        )
    for element in elements:
        element.metadata["verse_chunks"] = chunks
    return MethodResult(
        success=True,
        validated=True,
        message=f"Verso fragmentado em {chunks} pedaço(s)",
    )


def _tailjoin_position(manifest: ProcessingManifest) -> str | None:
    """Vertical position ("top"/"bot") of the page number in the manifest.

    `join_tail` only applies the position-conditioned `tj3` rule when it knows
    where the page number sits, which is the distinction between `tailjoin` and
    `tailjoin-positioned`.
    """
    for element in manifest.elements:
        role = _element_role(element)
        if role in {"header", "footer", "page_number"} and _is_page_number(
            element.text or ""
        ):
            bbox = _element_bbox(element, manifest)
            if bbox is None:
                continue
            return "top" if (bbox[1] + bbox[3]) / 2 < 0.5 else "bot"
    return None


def _handle_tailjoin_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Join the trailing short blocks (header/footer/page number).

    `docstruct.fusion.tailjoin.join_tail` requires the tail mode, a maximum short
    block length and the number of blocks to consider, so it cannot be called with
    the text alone. `FusionAgent.process_join_tail` supplies those defaults.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    texts = [(element.text or "") for element in elements]
    merged = _fusion_agent().process_join_tail(
        texts, position=_tailjoin_position(manifest)
    )
    if len(merged) >= len(texts):
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum bloco de cauda elegível para união",
        )
    for element in elements:
        element.metadata["tailjoined"] = True
    return MethodResult(
        success=True,
        validated=True,
        message=(
            f"Blocos de cauda unidos: {len(texts)} -> {len(merged)} bloco(s)"
        ),
    )


# --- Methods that choose between the two providers of FUSION_MODE=dual -------
#
# table-smart-fusion, skeleton-order and agreement-rule port Dr.DocBench rules
# (scripts/drbench/experiments/differ/tree_differ_v2.py and
# docstruct.fusion.adjudication.decide_v1). They read the secondary provider's
# extraction that the structure extractor keeps as a manifest artifact. The
# rules were calibrated on the docling + mineru pair, so any other pair fails
# explicitly instead of applying a preference nobody measured.

_CALIBRATED_PAIR = ("docling", "mineru")
#: Accepted Dr.DocBench table preference (TEDS): MinerU's table, unless Docling's
#: has spans or is the only one.
_TABLE_PREFERENCE = "mineru"
#: Minimum intersection over union to pair two blocks by position.
_MIN_BLOCK_IOU = 0.3
#: Minimum text similarity to pair two blocks that could not be paired by position.
_MIN_BLOCK_TEXT_RATIO = 0.8
#: Share of a page's elements that must be paired to follow the skeleton order.
_MIN_SKELETON_MATCH = 0.5

_Box = tuple[float, float, float, float]


@dataclass(frozen=True)
class _SecondaryExtraction:
    provider: str
    #: page number -> raw elements of the secondary provider, in reading order.
    pages: dict[int, list[dict[str, Any]]]
    sizes: dict[int, tuple[float, float]]

    def bbox(self, element: dict[str, Any]) -> _Box | None:
        """Normalized box of a raw Toolbox element (same frame as _element_bbox)."""
        for item in element.get("provenance") or []:
            if not isinstance(item, dict) or not item.get("bbox"):
                continue
            box = item["bbox"]
            page = _page_number(item.get("page_number", element.get("page_number")))
            width, height = self.sizes.get(page, (0.0, 0.0)) if page else (0.0, 0.0)
            if not width or not height:
                return None
            try:
                left, right = float(box["left"]), float(box["right"])
                top, bottom = float(box["top"]), float(box["bottom"])
            except (KeyError, TypeError, ValueError):
                return None
            if is_bottom_left(box.get("coord_origin"), top, bottom):
                top, bottom = height - top, height - bottom
            return _ordered_box(
                left / width, top / height, right / width, bottom / height
            )
        return None


def _page_number(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _load_secondary_extraction(
    manifest: ProcessingManifest,
) -> tuple[_SecondaryExtraction | None, str]:
    """The secondary provider's extraction, if recorded and unchanged.

    When it cannot be used, the second item says why (missing, replaced or
    unreadable), so the method result can tell those cases apart.
    """
    import json

    artifact = next(
        (a for a in manifest.artifacts if a.kind == SECONDARY_EXTRACTION_KIND), None
    )
    if artifact is None:
        return None, "Extração do provider secundário ausente do manifesto"
    try:
        raw = Path(artifact.path).read_bytes()
    except OSError:
        return None, f"Extração do provider secundário indisponível: {artifact.path}"
    if artifact.sha256 and hashlib.sha256(raw).hexdigest() != artifact.sha256:
        logger.warning(
            "Extração secundária {} não confere com o sha256 registrado",
            artifact.path,
        )
        return None, (
            "Extração do provider secundário alterada: sha256 diverge do "
            f"registrado no manifesto ({artifact.path})"
        )
    unreadable = f"Extração do provider secundário ilegível: {artifact.path}"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, unreadable
    payload = data.get("document") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return None, unreadable
    document = payload.get("document", payload)
    sizes: dict[int, tuple[float, float]] = {}
    for page in document.get("pages") or []:
        try:
            sizes[int(page["page_number"])] = (
                float(page.get("width") or 0),
                float(page.get("height") or 0),
            )
        except (KeyError, TypeError, ValueError):
            continue
    pages: dict[int, list[dict[str, Any]]] = {}
    for element in sorted(
        (e for e in document.get("elements") or [] if isinstance(e, dict)),
        key=lambda e: e.get("reading_order") or 0,
    ):
        page = _page_number(element.get("page_number"))
        if page is not None:
            pages.setdefault(page, []).append(element)
    return _SecondaryExtraction(str(data.get("provider") or ""), pages, sizes), ""


def _provider_pair_problem(
    manifest: ProcessingManifest, secondary: _SecondaryExtraction
) -> str | None:
    primary = str((manifest.extractor.configuration or {}).get("toolbox_provider") or "")
    if (primary, secondary.provider) == _CALIBRATED_PAIR:
        return None
    return (
        f"Regra calibrada para {'+'.join(_CALIBRATED_PAIR)}; "
        f"par atual: {primary or '?'}+{secondary.provider or '?'}"
    )


def _secondary_or_failure(
    manifest: ProcessingManifest,
) -> tuple[_SecondaryExtraction | None, MethodResult | None]:
    secondary, problem = _load_secondary_extraction(manifest)
    if secondary is None:
        return None, MethodResult(success=False, validated=False, message=problem)
    problem = _provider_pair_problem(manifest, secondary)
    if problem:
        return None, MethodResult(success=False, validated=False, message=problem)
    return secondary, None


def _ordered_box(left: float, top: float, right: float, bottom: float) -> _Box:
    return (min(left, right), min(top, bottom), max(left, right), max(top, bottom))


def _iou(a: _Box, b: _Box) -> float:
    width = min(a[2], b[2]) - max(a[0], b[0])
    height = min(a[3], b[3]) - max(a[1], b[1])
    if width <= 0 or height <= 0:
        return 0.0
    inter = width * height
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def _pair_block(
    element: ManifestElement,
    manifest: ProcessingManifest,
    candidates: list[dict[str, Any]],
    secondary: _SecondaryExtraction,
    used: set[int],
) -> int | None:
    """Index in ``candidates`` of the block that matches ``element``.

    Greedy: each element takes its best free candidate in the current reading
    order, while Dr.DocBench uses a global (Hungarian) assignment. The two can
    differ only when blocks compete for the same candidate, which is rare above
    the IoU / text thresholds and does not move the skeleton's 0.5 page gate.
    """
    import difflib

    box = _element_bbox(element, manifest)
    if box is not None:
        box = _ordered_box(*box)
        scored = [
            (_iou(box, other), index)
            for index, candidate in enumerate(candidates)
            if index not in used and (other := secondary.bbox(candidate)) is not None
        ]
        best = max(scored, default=(0.0, None))
        if best[0] >= _MIN_BLOCK_IOU:
            return best[1]
    text = " ".join((element.text or "").split())
    if not text:
        return None
    scored_text = [
        (
            difflib.SequenceMatcher(
                None,
                text,
                " ".join(str(candidate["text"]).split()),
                autojunk=False,
            ).ratio(),
            index,
        )
        for index, candidate in enumerate(candidates)
        if index not in used and candidate.get("text")
    ]
    best_text = max(scored_text, default=(0.0, None))
    return best_text[1] if best_text[0] >= _MIN_BLOCK_TEXT_RATIO else None


def _handle_table_smart_fusion_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pick each table's source between the two providers (Dr.DocBench rule).

    Docling's table is kept when it has spans (MinerU flattens them) or when it
    is the only one; otherwise MinerU's table is adopted. Tables are paired by
    position or text; a page with a single table on each side pairs them only
    when there is no position to compare. The choice and its reason are recorded
    in ``table_source`` / ``table_source_reason``.
    """
    from docstruct.tables.ast import analyze_table_complexity

    tables = [
        element
        for element in _target_elements(manifest, obligation_id)
        if element.type == "table"
    ]
    if not tables:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name, secondary_name = _CALIBRATED_PAIR
    primary_tables_by_page = Counter(
        element.page_number
        for element in manifest.elements
        if element.type == "table"
    )
    reasons: Counter = Counter()
    for element in tables:
        primary_ast = (element.metadata or {}).get("table_ast")
        candidates = [
            block
            for block in secondary.pages.get(element.page_number or 0, [])
            if block.get("type") == "table"
        ]
        match = _pair_block(element, manifest, candidates, secondary, set())
        if (
            match is None
            and len(candidates) == 1
            and primary_tables_by_page[element.page_number] == 1
            and (
                _element_bbox(element, manifest) is None
                or secondary.bbox(candidates[0]) is None
            )
        ):
            # One table on each side and no position to compare them by: the
            # same table. With both positions known and no overlap, they are not.
            match = 0
        chosen = candidates[match] if match is not None else None
        chosen_meta = (chosen or {}).get("metadata") or {}

        if primary_ast and analyze_table_complexity(primary_ast).has_spans:
            source, reason = primary_name, "primary-has-spans"
        elif not candidates:
            source, reason = primary_name, "no-secondary-table"
        elif chosen is None:
            source, reason = primary_name, "no-secondary-match"
        elif not (chosen.get("text") or chosen_meta.get("table_ast")):
            source, reason = primary_name, "secondary-table-empty"
        else:
            source, reason = _TABLE_PREFERENCE, f"preference-{_TABLE_PREFERENCE}"

        if source == secondary_name and chosen is not None:
            # Docling's table_* keys (AST, row/column counts, header) describe
            # the table being replaced; the output prefers table_ast over the
            # text, so a stale AST would hide the adopted MinerU text.
            for key in [k for k in element.metadata if k.startswith("table_")]:
                del element.metadata[key]
            if chosen.get("text"):
                element.text = chosen["text"]
            for key, value in chosen_meta.items():
                if key.startswith("table_"):
                    element.metadata[key] = value
        element.metadata["table_source"] = source
        element.metadata["table_source_reason"] = reason
        reasons[reason] += 1

    return MethodResult(
        success=True,
        validated=True,
        message="Fonte de tabela escolhida: "
        + ", ".join(f"{reason}={count}" for reason, count in sorted(reasons.items())),
    )


def _handle_skeleton_order_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Follow the secondary provider's reading order (MinerU skeleton).

    Page elements are paired with the secondary blocks by position (falling
    back to text); paired elements take the skeleton order and unpaired ones
    stay right after the element that preceded them. A page with fewer than
    half its elements paired is left alone.
    """
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    by_page: dict[int, list[ManifestElement]] = {}
    for element in elements:
        if element.page_number is not None:
            by_page.setdefault(element.page_number, []).append(element)

    reordered: set[int] = set()
    confirmed: set[int] = set()
    for page_number, page_elements in by_page.items():
        current = sorted(page_elements, key=lambda element: element.reading_order)
        skeleton = secondary.pages.get(page_number, [])
        used: set[int] = set()
        keys: dict[int, int] = {}
        for index, element in enumerate(current):
            match = _pair_block(element, manifest, skeleton, secondary, used)
            if match is not None:
                used.add(match)
                keys[index] = match
        if len(current) < 2 or len(keys) < _MIN_SKELETON_MATCH * len(current):
            continue
        ranked: list[tuple[float, int, int]] = []
        last = -1.0
        for index in range(len(current)):
            if index in keys:
                last = float(keys[index])
                ranked.append((last, 0, index))
            else:
                ranked.append((last, 1, index))
        order = [index for _, _, index in sorted(ranked)]
        if _apply_page_order(current, order):
            reordered.add(page_number)
        else:
            confirmed.add(page_number)

    if not reordered and not confirmed:
        return MethodResult(
            success=False,
            validated=False,
            message="Esqueleto do provider secundário não casou com a página",
        )
    _refresh_page_element_ids(manifest, reordered)
    parts = []
    if reordered:
        parts.append("aplicada nas páginas " + ", ".join(map(str, sorted(reordered))))
    if confirmed:
        parts.append("confirmada nas páginas " + ", ".join(map(str, sorted(confirmed))))
    return MethodResult(
        success=True,
        validated=True,
        message="Ordem do esqueleto " + "; ".join(parts),
    )


def _page_markdown(items: Iterable[tuple[str, str | None]]) -> str:
    """Page text with the markers the page router looks for."""
    parts = []
    for kind, text in items:
        text = (text or "").strip()
        if kind == "table":
            parts.append(f"<table>{text}</table>")
        elif kind == "formula":
            parts.append(f"$${text}$$")
        elif text:
            parts.append(text)
    return "\n\n".join(parts)


def _handle_agreement_rule_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Deterministic page router between the providers (``decide_v1``).

    When the router keeps the primary (Docling) page the obligation is
    satisfied without changing the text. When it picks the secondary page the
    decision is recorded but not applied: replacing a whole page would reopen
    the manifest mid-plan, and Dr.DocBench measured this router below the
    block-level fusion the core already runs. The method then fails, so the
    obligation goes to ``human-review`` with the route in ``page_route``.
    """
    from docstruct.fusion.adjudication import decide_v1

    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name = _CALIBRATED_PAIR[0]
    routes: dict[int, tuple[str, str]] = {}
    for page_number in sorted({e.page_number for e in elements if e.page_number}):
        primary_md = _page_markdown(
            (element.type, element.text)
            for element in sorted(manifest.elements, key=lambda e: e.reading_order)
            if element.page_number == page_number
        )
        secondary_md = _page_markdown(
            (str(block.get("type") or ""), block.get("text"))
            for block in secondary.pages.get(page_number, [])
        )
        routes[page_number] = decide_v1(primary_md, secondary_md)

    for element in elements:
        if element.page_number in routes:
            choice, reason = routes[element.page_number]
            element.metadata["page_route"] = {"choice": choice, "reason": reason}

    rerouted = {page: route for page, route in routes.items() if route[0] != primary_name}
    if not routes:
        return MethodResult(
            success=False,
            validated=False,
            message="Obrigação sem página identificada para o roteador",
        )
    if rerouted:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Roteador por página escolhe o provider secundário ("
                + ", ".join(f"p{page}: {reason}" for page, (_, reason) in sorted(rerouted.items()))
                + "); a troca de página não é aplicada automaticamente"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message="Roteador por página mantém o provider primário nas páginas "
        + ", ".join(map(str, sorted(routes))),
    )


#: Longest side of the page image sent to the judge. Two candidates plus the
#: image must fit one 8192-token slot of the production VLM server.
_JUDGE_PAGE_MAX_SIDE = 1600


def _render_page_png(
    source_path: Path, page_number: int, artifact_id: str | None = None
) -> bytes:
    """Page ``page_number`` (1-based) of a PDF or image as PNG, rendered by the Toolbox.

    At most 144 dpi, with the longest side bounded by ``_JUDGE_PAGE_MAX_SIDE``.
    """
    return _toolbox_render(
        source_path,
        page_number,
        dpi=144,
        max_side=_JUDGE_PAGE_MAX_SIDE,
        artifact_id=artifact_id,
    ).image

def _judge_page(image: bytes, candidate_a: str, candidate_b: str) -> dict[str, Any]:
    """Call document.adjudicate.page through the Toolbox (sync wrapper)."""
    import tempfile

    from acessilia_sdk.toolbox.clients import ToolboxAdjudicateClient
    from backend.tools.toolbox_client import make_toolbox_client, run_sync

    async def call(path: Path) -> dict[str, Any]:
        client = make_toolbox_client(ToolboxAdjudicateClient)
        try:
            result = await client.judge_page(candidate_a, candidate_b, file_path=path)
        finally:
            await client.close()
        logger.info(
            "Toolbox: page adjudication finished (pB={})",
            result.get("document", {}).get("pB", "?"),
        )
        return result

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "page.png"
        path.write_bytes(image)
        return run_sync(call(path))


#: Characters per candidate the Toolbox's judge reads (``judge_max_chars`` of
#: ``qwen3-vl-8b`` in its ``providers-config.yaml``); beyond it the candidate is
#: cut on the Toolbox side, so the verdict does not cover the whole page.
_JUDGE_MAX_CHARS = 6000


def _judge_probability(document: dict[str, Any]) -> float | None:
    """``pB`` of a judge answer, or ``None`` when absent or outside [0, 1]."""
    try:
        p_b = float(document["pB"])
    except (KeyError, TypeError, ValueError):
        return None
    return p_b if 0.0 <= p_b <= 1.0 else None


def _handle_vlm_pairwise_judge_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Pairwise VLM judge between the two providers' pages.

    The Toolbox (``document.adjudicate.page``) returns the position-debiased
    probability that the secondary page is the more faithful transcription.
    Only pages where the two transcriptions diverge are judged
    (``should_judge``); the others keep the primary page without a call. Of
    docstruct's two-threshold rule (``decide_pair``) only the ``p_new >
    DEFAULT_NEW_THR`` branch applies: there is no previous judge to consult
    here. As with ``agreement-rule``, a kept primary page satisfies the
    obligation, and a preferred secondary page is recorded in
    ``page_judgement`` but not swapped in: the method fails and the obligation
    goes to ``human-review``. An answer without a valid ``pB`` fails the method
    instead of counting as a kept primary.
    """
    from docstruct.fusion.judge import DEFAULT_NEW_THR, should_judge

    from backend.tools.toolbox_client import (
        ToolboxAuthenticationError,
        ToolboxContractViolation,
        ToolboxError,
    )

    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)
    secondary, failure = _secondary_or_failure(manifest)
    if failure is not None:
        return failure

    primary_name = _CALIBRATED_PAIR[0]
    source_path = Path(manifest.source.path)
    judgements: dict[int, dict[str, Any]] = {}
    for page_number in sorted({e.page_number for e in elements if e.page_number}):
        primary_md = _page_markdown(
            (element.type, element.text)
            for element in sorted(manifest.elements, key=lambda e: e.reading_order)
            if element.page_number == page_number
        )
        secondary_md = _page_markdown(
            (str(block.get("type") or ""), block.get("text"))
            for block in secondary.pages.get(page_number, [])
        )
        if not primary_md.strip() or not secondary_md.strip():
            logger.info(
                "vlm-pairwise-judge: página {} sem as duas transcrições; ignorada", page_number
            )
            continue
        if not should_judge(primary_md, secondary_md):
            judgements[page_number] = {"choice": primary_name, "pB": None, "reason": "agree"}
            continue

        try:
            image = _render_page_png(
                source_path, page_number, _source_artifact_id(manifest)
            )
        except Exception as exc:  # noqa: BLE001 - rendering a broken source
            return MethodResult(
                success=False,
                validated=False,
                message=f"Página {page_number} não pôde ser renderizada: {exc}",
            )
        truncated = max(len(primary_md), len(secondary_md)) > _JUDGE_MAX_CHARS
        if truncated:
            logger.warning(
                "vlm-pairwise-judge: página {} passa de {} caracteres; "
                "o juiz lê a transcrição truncada",
                page_number,
                _JUDGE_MAX_CHARS,
            )
        logger.info("vlm-pairwise-judge: julgando a página {}", page_number)
        try:
            result = _judge_page(image, primary_md, secondary_md)
        except (ToolboxAuthenticationError, ToolboxContractViolation) as exc:
            return MethodResult(
                success=False,
                validated=False,
                message=f"Juiz VLM recusou a chamada: {type(exc).__name__}: {exc}",
            )
        except ToolboxError as exc:
            return MethodResult(
                success=False,
                validated=False,
                message=f"Juiz VLM indisponível: {type(exc).__name__}: {exc}",
            )
        document = result.get("document") or {}
        p_b = _judge_probability(document)
        if p_b is None:
            return MethodResult(
                success=False,
                validated=False,
                message=(
                    f"Juiz VLM não devolveu pB válido para a página {page_number}: "
                    f"{document.get('pB')!r}"
                ),
            )
        judgements[page_number] = {
            "choice": secondary.provider if p_b > DEFAULT_NEW_THR else primary_name,
            "pB": p_b,
            "pB_ab": document.get("pB_ab"),
            "pA_ba": document.get("pA_ba"),
            "model": document.get("model"),
            "truncated": truncated,
        }

    if not judgements:
        return MethodResult(
            success=False,
            validated=False,
            message="Sem páginas com as duas transcrições para o juiz VLM",
        )
    for element in elements:
        if element.page_number in judgements:
            element.metadata["page_judgement"] = judgements[element.page_number]

    preferred = {
        page: judgement
        for page, judgement in judgements.items()
        if judgement["choice"] != primary_name
    }
    if preferred:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Juiz VLM prefere o provider secundário ("
                + ", ".join(f"p{page}: pB={j['pB']:.2f}" for page, j in sorted(preferred.items()))
                + "); a troca de página não é aplicada automaticamente"
            ),
        )
    return MethodResult(
        success=True,
        validated=True,
        message="Juiz VLM mantém o provider primário nas páginas "
        + ", ".join(
            f"{page} (pB={j['pB']:.2f})" if j["pB"] is not None else f"{page} (concordam)"
            for page, j in sorted(judgements.items())
        ),
    )


def _apply_page_order(current: list[ManifestElement], order: list[int]) -> bool:
    """Reassign the reading-order slots of ``current`` following ``order``.

    ``order[i]`` is the index in ``current`` of the element that goes to the
    i-th slot. Returns whether anything moved.
    """
    if order == list(range(len(current))):
        return False
    slots = sorted(element.reading_order for element in current)
    for slot, index in zip(slots, order):
        current[index].reading_order = slot
    return True


def _refresh_page_element_ids(
    manifest: ProcessingManifest, page_numbers: set[int]
) -> None:
    manifest.elements.sort(key=lambda element: element.reading_order)
    for page in manifest.pages:
        if page.page_number in page_numbers:
            page.element_ids = [
                element.id
                for element in manifest.elements
                if element.page_number == page.page_number
            ]


def _handle_xycut_order_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Apply XY-cut reading order to the evidenced page elements."""
    elements = _target_elements(manifest, obligation_id)
    if not elements:
        return _missing_obligation(obligation_id)

    fusion_agent = _fusion_agent()
    reordered_pages: set[int] = set()
    by_page: dict[int, list[ManifestElement]] = {}
    for element in elements:
        if element.page_number is not None:
            by_page.setdefault(element.page_number, []).append(element)

    for page_number, page_elements in by_page.items():
        positioned = [
            element for element in page_elements
            if _element_bbox(element, manifest) is not None
        ]
        if len(positioned) < 2:
            continue
        current = sorted(positioned, key=lambda element: element.reading_order)
        boxes = [_element_bbox(element, manifest) for element in current]
        order = fusion_agent.process_refine_reading_order(
            [list(box) for box in boxes if box is not None]
        )
        if _apply_page_order(current, order):
            reordered_pages.add(page_number)

    if not reordered_pages:
        return MethodResult(
            success=False,
            validated=False,
            message="XY-cut não identificou uma mudança de ordem de leitura",
        )

    _refresh_page_element_ids(manifest, reordered_pages)
    return MethodResult(
        success=True,
        validated=True,
        message=(
            "Ordem de leitura XY-cut aplicada nas páginas "
            + ", ".join(map(str, sorted(reordered_pages)))
        ),
    )


def _handle_human_review_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Record the obligation as escalated to a human reviewer.

    `human-review` is the terminal method every obligation lists as its last
    admissible option. It is not an automated method that can succeed on its own,
    so resolving it must be an explicit decision: an obligation reaching this
    handler is escalated and stays visible in the execution report, instead of
    being marked satisfied by a handler that did nothing.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    return MethodResult(
        success=False,
        validated=False,
        message=(
            "Escalonado para revisão humana: nenhum método automático satisfez "
            f"{obligation.kind} ({obligation_id})"
        ),
    )


def _handle_deterministic_heading_repair_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Repair the full sequence, since fixing one heading can expose a later gap."""
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)

    targets = _target_elements(manifest, obligation_id)
    if not targets or any(element.type not in {"title", "heading"} for element in targets):
        return MethodResult(
            success=False,
            validated=False,
            message="Nenhum título encontrado para a obrigação",
        )
    previous = 0
    repaired = 0
    for element in sorted(manifest.elements, key=lambda item: item.reading_order):
        if element.type not in {"title", "heading"}:
            continue
        level = 1 if not previous else max(2, min(element.hierarchy_level, previous + 1, 6))
        if previous and element.type == "title":
            element.metadata["original_type"] = "title"
            element.type = "heading"
        if level != element.hierarchy_level:
            element.metadata["original_heading_level"] = element.hierarchy_level
            element.hierarchy_level = level
            element.metadata["heading_repaired"] = True
            repaired += 1
        previous = level
    manifest.summary.element_types = dict(Counter(element.type for element in manifest.elements))
    return MethodResult(
        success=True,
        validated=True,
        message=f"Hierarquia de títulos verificada; {repaired} título(s) reparado(s)",
    )


DETERMINISTIC_METHOD_HANDLERS: dict[
    str, Callable[[ProcessingManifest, str], MethodResult]
] = {
    #: Method name -> handler for every method whose work is already done before
    #: planning (or can be done without a model call). A method the manifest can
    #: require but that is absent from here is reported to the planner as
    #: unavailable, so the plan never contains a step that can only fail.
    "vision-description": _handle_vision_description_method,
    "pandoc-table": _handle_pandoc_table_method,
    "pandoc-code": _handle_pandoc_code_method,
    "pymupdf-region": _handle_pymupdf_region_method,
    "vision-page-inspection": _handle_vision_page_inspection_method,
    "latex-normalizer": _handle_latex_normalizer_method,
    "norm-fix": _handle_norm_fix_method,
    "rep-guard": _handle_repetition_guard_method,
    "line-number-extractor": _handle_extract_line_numbers_method,
    "verse-chunker": _handle_chunk_verse_method,
    "tailjoin": _handle_tailjoin_method,
    "tailjoin-positioned": _handle_tailjoin_method,
    "xycut-order": _handle_xycut_order_method,
    "skeleton-order": _handle_skeleton_order_method,
    "table-smart-fusion": _handle_table_smart_fusion_method,
    "agreement-rule": _handle_agreement_rule_method,
    "deterministic-heading-repair": _handle_deterministic_heading_repair_method,
}


def _handle_dual_provider_fusion_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Funde dois providers (docling+mineru) para a obrigação alvo.

    Reutiliza ``backend.pipeline.fusion.extract_fused`` (Fase 4) para
    produzir o payload fundido, persiste o JSON em ``data_dir/artifacts/
    fusion/`` e o retorna em ``MethodResult.artifacts`` — deixando o
    ``ExecutorAgent`` responsável por incorporá-lo ao manifesto e registrar
    a proveniência na tentativa.

    Em modo single (FUSION_MODE=single) o método não é admissível e não
    deve ser selecionado pelo compilador.

    Custo: a fusão reextrai o documento inteiro nos dois providers, sem
    reutilizar a evidência que o ``ToolboxManifestExtractor`` já coletou em
    ``FUSION_MODE=dual``. Cada passo ``fuse-providers`` paga, portanto, uma
    extração dual completa (cache remoto da Toolbox à parte). Em regra o
    documento não é reenviado: os dois providers leem o ``artifact_id`` que o
    extrator registrou em ``manifest.extractor.configuration``. Se a Toolbox
    não tiver mais esse artefato (expirado/removido), ``extract_fused`` faz o
    upload do arquivo como fallback.
    """
    obligation = next(
        (o for o in manifest.obligations if o.id == obligation_id), None
    )
    if obligation is None:
        return MethodResult(
            success=False,
            validated=False,
            message=f"Obrigação não encontrada: {obligation_id}",
        )
    source_path = Path(manifest.source.path)
    # Reuse the document the structure extractor already stored in the Toolbox.
    artifact_id = (manifest.extractor.configuration or {}).get("artifact_id")
    try:
        payload = _run_extract_fused(source_path, artifact_id=artifact_id)
    except Exception as exc:  # noqa: BLE001
        return MethodResult(
            success=False,
            validated=False,
            message=f"Fusão dual-provider falhou: {type(exc).__name__}: {exc}",
        )
    if payload.get("status") != "succeeded":
        return MethodResult(
            success=False,
            validated=False,
            message="Fusão dual-provider não concluiu com sucesso",
        )

    # A ação planejada é dual-provider: se apenas um provider participou,
    # a semântica planejada não foi executada → falha para permitir replanning
    # para um método single-provider.
    provider = str(payload.get("provider") or "")
    if "+" not in provider:
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Fusão dual-provider executou com um único provider "
                f"({provider or 'desconhecido'}); replanning necessário"
            ),
        )

    try:
        elements = _fused_text_elements(manifest, obligation.target_ids, payload)
    except (TypeError, ValueError) as exc:
        return MethodResult(success=False, validated=False, message=str(exc))

    artifact = _persist_fusion_payload(
        manifest,
        payload,
        obligation_id,
        kind="fusion-payload",
    )

    manifest.elements = elements
    page_ids = {element.page_number or 1 for element in elements}
    existing_pages = {page.page_number: page for page in manifest.pages}
    manifest.pages = [
        PageDescriptor(
            page_number=number,
            width=existing_pages[number].width if number in existing_pages else None,
            height=existing_pages[number].height if number in existing_pages else None,
            element_ids=[element.id for element in elements if (element.page_number or 1) == number],
        )
        for number in sorted(page_ids)
    ]
    manifest.summary.page_count = len(manifest.pages)
    manifest.summary.element_count = len(elements)
    manifest.summary.element_types = dict(Counter(element.type for element in elements))
    return MethodResult(
        success=True,
        validated=True,
        message="Fusão dual-provider concluída com sucesso",
        artifacts=[artifact],
    )


def _fused_text_elements(
    manifest: ProcessingManifest, target_ids: list[str], payload: dict[str, Any]
) -> list[ManifestElement]:
    # The fusion adapter currently emits text-only blocks. It cannot safely
    # replace a structured document or a subset with a whole-document result.
    if any(element.type != "paragraph" for element in manifest.elements) or set(target_ids) != {
        element.id for element in manifest.elements
    }:
        raise ValueError("Text fusion requires all paragraphs of a text-only manifest")
    raw_elements = payload.get("document", {}).get("elements")
    if not isinstance(raw_elements, list) or not raw_elements:
        raise ValueError("Fusion returned no usable document elements")
    originals = sorted(manifest.elements, key=lambda element: element.reading_order)
    by_page: dict[int, list[dict[str, Any]]] = {}
    for raw in raw_elements:
        if not isinstance(raw, dict) or raw.get("type") != "paragraph":
            raise ValueError("Fusion returned unsupported structured content")
        text = raw.get("text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("Fusion returned an empty text block")
        page = raw.get("page_number", raw.get("page"))
        if page is None:
            if len(manifest.pages) > 1:
                raise ValueError("Fusion omitted page identity for a multipage document")
            page = manifest.pages[0].page_number if manifest.pages else 1
        if type(page) is not int or page < 1:
            raise ValueError("Fusion returned an invalid page number")
        by_page.setdefault(page, []).append(raw)
    original_pages = {element.page_number or 1 for element in originals}
    if not original_pages.issubset(by_page):
        raise ValueError("Fusion omitted a source page")

    result = []
    for number, rows in sorted(by_page.items()):
        old = [element for element in originals if (element.page_number or 1) == number]
        # Keep every existing ID and reference; ambiguous mappings fail closed.
        if len(rows) < len(old):
            raise ValueError("Fusion cannot safely map fewer blocks to existing element references")
        for index, raw in enumerate(rows):
            if index < len(old):
                element = old[index].model_copy(deep=True)
                element.text = raw["text"]
                element.page_number = number
            else:
                identifier = hashlib.sha256(json.dumps([
                    manifest.manifest_id, number, index, raw["text"],
                ]).encode()).hexdigest()[:24]
                element = ManifestElement(
                    id=f"element-fusion-{identifier}", type="paragraph", raw_label="paragraph",
                    reading_order=len(result) + 1, hierarchy_level=0,
                    page_number=number, text=raw["text"],
                )
            element.metadata["fusion_provider"] = payload["provider"]
            element.reading_order = len(result) + 1
            result.append(element)
    return result


def _handle_single_provider_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Run the configured provider as a real fallback after dual fusion fails."""
    obligation = next(
        (item for item in manifest.obligations if item.id == obligation_id), None
    )
    if obligation is None:
        return _missing_obligation(obligation_id)
    if obligation.kind != "fuse-providers":
        return MethodResult(
            success=False,
            validated=False,
            message="single-provider só é válido para fuse-providers",
        )

    source_path = Path(manifest.source.path)
    if not source_path.is_file():
        return MethodResult(
            success=False,
            validated=False,
            message=f"Documento-fonte indisponível: {source_path}",
        )
    try:
        payload = _run_extract_single_provider(source_path)
    except Exception as exc:  # noqa: BLE001
        return MethodResult(
            success=False,
            validated=False,
            message=(
                "Extração single-provider falhou: "
                f"{type(exc).__name__}: {exc}"
            ),
        )

    provider = str(payload.get("provider") or "")
    if payload.get("status") != "succeeded" or not provider or "+" in provider:
        return MethodResult(
            success=False,
            validated=False,
            message="A Toolbox não confirmou uma extração de provider único",
        )

    artifact = _persist_fusion_payload(
        manifest,
        payload,
        obligation_id,
        kind="single-provider-payload",
    )
    return MethodResult(
        success=True,
        validated=True,
        message=f"Fallback single-provider concluído ({provider})",
        artifacts=[artifact],
    )


def _persist_fusion_payload(
    manifest: ProcessingManifest,
    payload: dict[str, Any],
    obligation_id: str,
    *,
    kind: str,
) -> Artifact:
    """Write the payload atomically, addressed by its manifest scope and content."""
    from backend.config.settings import settings

    content = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    scope = hashlib.sha256(json.dumps([
        manifest.manifest_id, manifest.source.document_id, manifest.source.sha256,
        manifest.revision, obligation_id,
    ]).encode()).hexdigest()
    output_path = settings.data_dir / "artifacts" / "fusion" / scope / f"{digest}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output_path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(content)
        os.replace(temporary, output_path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return Artifact(
        id=f"artifact-{kind.removesuffix('-payload')}-{scope[:16]}-{digest[:16]}",
        kind=kind,
        path=str(output_path),
        media_type="application/json",
        sha256=digest,
    )


class StructuralExtractionError(RuntimeError):
    """The Toolbox could not extract the document structure (job-level failure)."""


class PddlAccessibilityOrchestrator:
    """Drives the PDDL pipeline: informational-extraction -> planner -> executor.

    Args:
        planner_backend (str): Which planner backend to prefer for nominal-plan generation; defaults to "internal".
        preferred_plan (str): Which plan source to prefer when multiple are available; defaults to "internal".
        execute_dry_run (bool): When True the produced plan is only validated in dry-run instead of executed for real; defaults to True.
        fast_downward (Path | None): Optional filesystem path to a fast-downward binary used when planner_backend is fast-downward; defaults to None.
        fast_downward_alias (str | None): Optional shell alias to invoke fast_downward through instead of the raw path; defaults to None.
        fast_downward_search (str): Fast-downward search heuristic string passed when the backend is active; defaults to "astar(blind())".
        enable_ocr (bool): Whether the docling extraction backend should run its OCR pass; defaults to True.
        extractor_backend (str): Which manifest-extraction backend to use.
            Supported values:
            - "toolbox" — ToolboxManifestExtractor (remote via Acessilia Toolbox)
            - "toolbox-layout" / "toolbox_layout" — mapped to "toolbox" (same REST API)
            Defaults to "toolbox".
    """

    def __init__(
        self,
        *,
        planner_backend: str = "internal",
        preferred_plan: str = "internal",
        execute_dry_run: bool = True,
        fast_downward: Path | None = None,
        fast_downward_alias: str | None = None,
        fast_downward_search: str = "astar(blind())",
        enable_ocr: bool = True,
        extractor_backend: str = "toolbox",
        max_replans: int = 2,
    ) -> None:
        self.planner_backend = planner_backend
        self.preferred_plan = preferred_plan
        self.execute_dry_run = execute_dry_run
        self.max_replans = max(0, max_replans)
        self.fast_downward = fast_downward
        self.fast_downward_alias = fast_downward_alias
        self.fast_downward_search = fast_downward_search
        self.extractor_backend = extractor_backend.strip().lower()

        if self.extractor_backend in ("toolbox", "toolbox-layout", "toolbox_layout"):
            logger.info(
                "PDDL extractor_backend={}: usando ToolboxManifestExtractor",
                self.extractor_backend,
            )
            extractor = ToolboxManifestExtractor(enable_ocr=enable_ocr)
        else:
            raise ValueError(
                f"Extractor local '{self.extractor_backend}' desativado. "
                f"Use extractor_backend='toolbox' para o pipeline PDDL+Toolbox."
            )

        self.information_structural = InformationalStructuralAgent(
            extractor
        )
        self.planner = PlannerAgent()
        self.executor = self._build_executor()

    @staticmethod
    def _build_executor() -> ExecutorAgent:
        registry = MethodRegistry()

        # Model-backed or cross-cutting methods already wired by the pipeline.
        registry.register("mathml", _handle_mathml_method)
        registry.register("latex-verbalizer", _handle_latex_verbalizer_method)
        registry.register(
            "dual-provider-fusion", _handle_dual_provider_fusion_method
        )
        registry.register("single-provider", _handle_single_provider_method)
        registry.register("vlm-pairwise-judge", _handle_vlm_pairwise_judge_method)
        for method, handler in DETERMINISTIC_METHOD_HANDLERS.items():
            registry.register(method, handler)

        # `human-review` has its own semantics: it is the terminal escalation the
        # pipeline performs when no automated method can satisfy an obligation.
        registry.register("human-review", _handle_human_review_method)

        return ExecutorAgent(registry, domain=DomainBundle.load())

    async def executar(
        self,
        file_path: Path,
        tmpdir: Path,
        status_callback: Callable[[str], Coroutine] | None = None,
        mode: str | None = None,
        structured_output: bool = False,
        custom_prompt: str | None = None,
        thinking_mode: bool = False,
    ) -> str | dict[str, Any]:
        effective_mode = mode or "medio"

        if custom_prompt or thinking_mode:
            raise ValueError("Custom instructions and thinking mode are unavailable for this pipeline")

        if status_callback:
            await status_callback(t(STAGE_ANALYZING_STRUCTURAL))
        try:
            manifest = await run_blocking(
                self.information_structural.process,
                file_path.resolve(),
                language="pt-BR",
            )
        except ToolboxError as exc:
            # The SDK already retried and failed over; there is no local
            # extractor to fall back on (docs/adr/0003), so the job fails here.
            # The message reaches the end user, so it names the capability and
            # the kind of failure only; the full cause, which carries internal
            # Toolbox endpoints, goes to the log and stays chained.
            logger.error("Structural extraction failed on the Toolbox: {}", exc)
            raise StructuralExtractionError(
                t(STAGE_STRUCTURAL_EXTRACTION_FAILED).format(
                    capability="document.structure.extract", error=type(exc).__name__
                )
            ) from exc
        manifest.extractor.configuration["region_inspection_mode"] = effective_mode

        source_path = file_path.resolve()
        media_inspection = await _inspect_media_or_degrade(manifest, source_path)

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_IMAGE_DESCRIPTIONS))
        await _enrich_picture_descriptions(
            manifest,
            source_path,
            mode=effective_mode,
            media_inspection=media_inspection,
        )

        if status_callback:
            await status_callback(t(STAGE_ENRICHING_TABLES_OCR))
        await _enrich_table_structures(
            manifest,
            file_path.resolve(),
        )

        if status_callback:
            await status_callback(t(STAGE_GENERATING_PDDL_PLAN))
        # One catalogue snapshot per document, so the first plan and every replan
        # see the same Toolbox.
        availability = await toolbox_gate.decide(manifest)
        _log_availability(availability)
        gated = availability.unavailable_methods
        plan, comparison = await run_blocking(
            self._build_plan, manifest, extra_unavailable=gated
        )

        execution_report: ExecutionReport | None = None
        if status_callback:
            await status_callback(
                t(STAGE_VALIDATING_PLAN_DRY_RUN)
                if self.execute_dry_run
                else t(STAGE_EXECUTING_PLAN)
            )
        # `execute_dry_run` selects the *mode* of execution; it used to also gate
        # whether the executor ran at all, so setting it to false produced a plan
        # that was never executed and a report of None. Real execution is now the
        # other branch instead of silence.
        manifest, execution_report = await run_blocking(
            self.executor.execute,
            plan,
            manifest,
            dry_run=self.execute_dry_run,
        )

        # A `replan-required` report means the executor recorded `(tried ?o ?m)`
        # for a method that failed and left the obligation pending. Without this
        # loop the status was terminal in production: the pipeline returned a plan
        # it already knew was wrong, and `complete-job` never ran, so no document
        # was produced.
        replans = 0
        while (
            execution_report.replan_required
            and replans < self.max_replans
            and not self.execute_dry_run
        ):
            # Steps after a failure still run, so one execution can leave an
            # obligation exhausted (no method left) next to another that has an
            # alternative. The planner rejects exhausted obligations, so they are
            # left out of the replan; an exhausted critical one fails the job.
            exhausted = [
                obligation for obligation in manifest.obligations
                if obligation.status == "failed"
            ]
            if any(
                obligation.kind not in NON_CRITICAL_OBLIGATION_KINDS
                for obligation in exhausted
            ):
                break
            roots = _replannable_obligation_ids(manifest)
            if not roots:
                break
            replans += 1
            logger.info(
                "PDDL: replanejando ({}/{}) após {}",
                replans,
                self.max_replans,
                execution_report.status,
            )
            plan, comparison = await run_blocking(
                self._build_plan,
                manifest,
                extra_unavailable=gated,
                selected_roots=roots,
            )
            manifest, execution_report = await run_blocking(
                self.executor.execute,
                plan,
                manifest,
                dry_run=False,
            )

        if execution_report.status not in {"completed", "dry-run-completed"}:
            unsatisfied = _unsatisfied_selected_obligations(manifest)
            critical = [
                obligation for obligation in unsatisfied
                if obligation.kind not in NON_CRITICAL_OBLIGATION_KINDS
            ]
            if not unsatisfied or critical:
                raise RuntimeError(_unsatisfied_execution_message(manifest))
            # Only refinements are left open; the extracted content is still
            # complete, so the document is delivered with a technical warning.
            logger.warning(
                "PDDL: concluindo com obrigações não críticas pendentes: {}",
                ", ".join(obligation.id for obligation in unsatisfied),
            )

        payload = build_pddl_structured_payload(
            file_path=file_path,
            manifest=manifest,
            plan=plan,
            planner_backend=self.planner_backend,
            execution_report=execution_report,
            comparison=comparison,
            toolbox_availability=availability.to_metadata(),
        )

        if structured_output:
            return payload
        return payload["text"]

    def _build_plan(
        self,
        manifest: ProcessingManifest,
        *,
        extra_unavailable: Iterable[str] = (),
        selected_roots: Iterable[str] | None = None,
    ) -> tuple[NominalPlan, PlanningComparison | None]:
        # Tell the compiler which methods the executor can actually run. Without
        # this the planner happily emits steps for methods that have no handler,
        # and the failure only surfaces at execution time -- after the model-backed
        # work has already been paid for. ``extra_unavailable`` adds the methods
        # the Toolbox availability gate rules out for this document.
        unavailable = sorted(
            set(self._unavailable_methods(manifest)) | set(extra_unavailable)
        )
        if self.planner_backend == "both":
            _, plans, comparison = self.planner.compare(
                manifest,
                selected_roots=selected_roots,
                unavailable_methods=unavailable,
                fast_downward=self.fast_downward,
                fast_downward_alias=self.fast_downward_alias,
                fast_downward_search=self.fast_downward_search,
                preferred_backend=self.preferred_plan,
            )
            if self.preferred_plan not in plans:
                raise RuntimeError(
                    t(LOG_PDDL_PREFERRED_PLAN_MISSING).format(
                        backend=self.preferred_plan
                    )
                )
            return plans[self.preferred_plan], comparison

        _, plan = self.planner.plan(
            manifest,
            selected_roots=selected_roots,
            unavailable_methods=unavailable,
            backend=self.planner_backend,
            fast_downward=self.fast_downward,
            fast_downward_alias=self.fast_downward_alias,
            fast_downward_search=self.fast_downward_search,
        )
        return plan, None

    def _unavailable_methods(self, manifest: ProcessingManifest) -> list[str]:
        """Methods this manifest can ask for that no registered handler implements.

        The set is restricted to the methods the manifest actually declares: the
        compiler rejects unknown names on purpose, so passing every method that
        exists anywhere would be reported as a typo instead of a capability gap.
        """
        registered = set(self.executor.registry.names())
        requested = {
            method
            for obligation in manifest.obligations
            for method in obligation.admissible_methods
        }
        return sorted(requested - registered)


async def _enrich_picture_descriptions(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
    media_inspection: dict[str, Any] | None = None,
) -> None:
    _inject_full_page_picture(manifest, media_inspection)

    pictures = [
        element
        for element in manifest.elements
        if element.type == "picture"
        and not element.metadata.get("vision_description_complete")
    ]
    if not pictures and _is_mostly_visual_manifest(manifest):
        pictures = [
            element
            for element in manifest.elements
            if _is_placeholder_visual_element(element)
            and not element.metadata.get("vision_description_complete")
        ]

    if (
        not pictures
        and _is_mostly_visual_manifest(manifest)
        and len(manifest.pages) == 1
        and manifest.elements
    ):
        pictures = [element for element in manifest.elements
                    if not element.metadata.get("vision_description_complete")
                    and not is_unstructured_page_placeholder(element)][:1]

    if not pictures:
        return

    vision = VisionAgent(mode=mode)
    total_pages = len(manifest.pages)
    enriched = 0

    for element in pictures:
        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        image_bytes, page_number = await run_blocking(
            _extract_picture_bytes,
            source_file,
            element,
            fallback_page_number,
            _source_artifact_id(manifest),
        )
        if not image_bytes:
            continue

        vision_output = await vision.describe_region(
            image_bytes=image_bytes,
            classification="embedded_image",
            page_num=page_number,
            total_pages=total_pages,
            mode=mode,
        )
        if isinstance(vision_output, VisionOutput):
            element.metadata["vision_description_complete"] = True
            element.metadata["vision_language"] = vision_output.language
            element.metadata["vision_confidence"] = vision_output.confidence
            element.metadata["vision_elements"] = list(vision_output.mentioned_elements)
            if vision_output.warnings:
                element.metadata["vision_warnings"] = list(vision_output.warnings)

            if vision_output.kind == "formula":
                element.text = vision_output.formula_latex or ""
                if element.type != "formula":
                    previous_type = element.type
                    element.metadata["original_type"] = element.type
                    element.type = "formula"
                    element.raw_label = "formula"
                    reconcile_reclassified_element_processing_needs(
                        manifest,
                        element,
                        previous_type=previous_type,
                    )
            else:
                element.text = vision_output.description
                if element.type != "picture":
                    previous_type = element.type
                    element.metadata["original_type"] = element.type
                    element.type = "picture"
                    element.raw_label = "picture"
                    reconcile_reclassified_element_processing_needs(
                        manifest,
                        element,
                        previous_type=previous_type,
                    )
            if element.page_number is None and page_number >= 1:
                element.page_number = page_number
            # A model that answers with an empty description used to be counted as
            # an enrichment, producing an element that still had no text and an
            # obligation that could not be satisfied. Report it so the operator
            # sees the model refused instead of a silent gap.
            if _has_meaningful_text(element):
                enriched += 1
            else:
                logger.warning(
                    t(LOG_PDDL_EMPTY_VISION_DESCRIPTION).format(
                        element_id=element.id
                    )
                )

    if enriched:
        logger.info(t(LOG_PDDL_IMAGES_ENRICHED).format(count=enriched))


async def _inspect_media_or_degrade(
    manifest: ProcessingManifest,
    source_path: Path,
) -> dict[str, Any] | None:
    """Runs ``media.inspect`` and degrades visibly when it fails.

    The inspection only feeds the standalone-image heuristic, so no failure of
    the step fails the job: any ``Exception`` (a ``ToolboxError``, but also an
    SDK bug or a client configuration error) makes the run continue without
    the signal, logs a warning and records the cause. Cancellation is not
    caught, since ``asyncio.CancelledError`` derives from ``BaseException``.

    The outcome goes to ``manifest.extractor.configuration``:
    ``media_inspection`` is ``toolbox``, ``disabled`` (by
    ``TOOLBOX_MEDIA_INSPECT_ENABLED``), ``source_missing`` or ``failed``, plus
    ``media_inspection_error`` on failure.
    """
    from backend.config.settings import settings

    configuration = manifest.extractor.configuration
    try:
        media_inspection = await inspect_source_media(source_path)
    except Exception as exc:  # noqa: BLE001 - the step degrades, never fails the job
        cause = f"{type(exc).__name__}: {exc}"
        logger.warning(
            t(LOG_MEDIA_INSPECT_FAILED).format(
                filename=source_path.name, error=cause
            )
        )
        configuration["media_inspection"] = "failed"
        configuration["media_inspection_error"] = cause
        return None
    if media_inspection is not None:
        status = "toolbox"
    elif not settings.toolbox_media_inspect_enabled:
        status = "disabled"
    else:
        status = "source_missing"
    configuration["media_inspection"] = status
    return media_inspection


def _inject_full_page_picture(
    manifest: ProcessingManifest,
    media_inspection: dict[str, Any] | None,
) -> None:
    """Injeta um elemento `picture` sintético de página inteira.

    Quando a entrada é uma imagem raster isolada (``media_inspect`` classifica
    como imagem e sinaliza ``requires_visual_inspection=true``) e o extrator
    estrutural não produziu nenhum bloco visual (picture/formula), o orquestrador
    não teria alvo para audiodescrição. Este fallback cria um elemento `picture`
    que cobre a página inteira para que o VisionAgent descreva a imagem.

    O sinal é consumido apenas como heurística de enriquecimento: não altera o
    problema PDDL (predicados ``media_inspected``/``media_profile_classified``
    pertencem ao domínio da Toolbox).
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


async def _enrich_table_structures(
    manifest: ProcessingManifest,
    source_file: Path,
) -> None:
    table_elements = [
        element
        for element in manifest.elements
        if element.type == "table" and not _table_element_has_structured_content(element)
    ]
    if not table_elements:
        return

    data_agent = DataAgent()
    enriched = 0
    for element in table_elements:
        if _backfill_table_from_existing_text(element):
            enriched += 1
            continue

        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        image_bytes, page_number = await run_blocking(
            _extract_picture_bytes,
            source_file,
            element,
            fallback_page_number,
            _source_artifact_id(manifest),
        )
        if not image_bytes:
            continue

        table_output = await data_agent.process_region(
            image_bytes=image_bytes,
            classification="table",
            page_num=page_number,
            fallback_text=element.text or "",
        )
        if not isinstance(table_output, DataOutput) or table_output.kind != "table":
            continue

        rows = table_output.table_rows()
        table_ast = table_output.table_ast()

        element.metadata["table_ast"] = table_ast
        element.metadata["table_linearization_hint"] = "data-agent-structured"
        element.metadata["table_row_count"] = len(rows)
        element.metadata["table_column_count"] = _table_ast_column_count(table_ast)
        element.metadata["table_has_header"] = any(
            cell.header or cell.scope != "none"
            for row in table_output.rows
            for cell in row.cells
        )
        element.metadata["data_language"] = table_output.language
        element.metadata["data_confidence"] = table_output.confidence
        if table_output.warnings:
            element.metadata["data_warnings"] = list(table_output.warnings)
        element.text = ""
        if element.page_number is None and page_number >= 1:
            element.page_number = page_number
        enriched += 1

    if enriched:
        logger.info(t(LOG_PDDL_TABLES_ENRICHED).format(count=enriched))


def _table_element_has_structured_content(element: ManifestElement) -> bool:
    metadata = element.metadata or {}
    table_ast = metadata.get("table_ast")
    if not isinstance(table_ast, dict):
        return False

    rows = _rows_from_table_ast(table_ast)
    if not rows:
        return False

    width = max((len(row) for row in rows), default=0)
    if len(rows) >= 2 and width >= 2:
        return True

    return not _rows_look_like_placeholder(rows)


def _table_ast_column_count(table_ast: dict[str, Any]) -> int:
    """Return the widest logical section, including cell spans."""
    widths: list[int] = []
    for section_name in ("header", "body", "footer"):
        section = table_ast.get(section_name)
        if isinstance(section, list):
            widths.append(effective_section_width(section))
    return max(widths, default=0)


def _backfill_table_from_existing_text(element: ManifestElement) -> bool:
    text = (element.text or "").strip()
    if not text:
        return False

    rows = _rows_from_visual_table_text(text)
    if not rows:
        return False

    table_ast = _table_ast_from_rows(rows)
    if table_ast is None:
        return False

    element.metadata["table_ast"] = table_ast
    element.metadata["table_linearization_hint"] = "text-heuristic"
    element.metadata["table_row_count"] = len(rows)
    element.metadata["table_column_count"] = max((len(row) for row in rows), default=0)
    element.metadata["table_has_header"] = bool(rows and len(rows[0]) >= 2)
    element.text = ""
    return True


def _rows_from_visual_table_text(raw_text: str) -> list[list[str]]:
    text = raw_text.strip()
    if not text:
        return []

    rows = _rows_from_pipe_table(text)
    if rows:
        return rows

    rows = _rows_from_delimited_lines(text, delimiter="\t")
    if rows:
        return rows

    semicolon_rows = _rows_from_delimited_lines(text, delimiter=";")
    comma_rows = _rows_from_delimited_lines(text, delimiter=",")
    if _score_rows(semicolon_rows) >= _score_rows(comma_rows):
        return semicolon_rows
    return comma_rows


def _rows_from_pipe_table(text: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if "|" not in line:
            continue
        if _looks_like_markdown_separator(line):
            continue
        cleaned = line.strip().strip("|")
        cells = [cell.strip() for cell in cleaned.split("|")]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if _score_rows(rows) >= 4:
        return rows
    return []


def _rows_from_delimited_lines(text: str, *, delimiter: str) -> list[list[str]]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    rows: list[list[str]] = []
    for line in lines:
        if delimiter not in line:
            continue
        if "|" in line and delimiter != "|":
            continue
        cells = [cell.strip() for cell in line.split(delimiter)]
        cells = [cell for cell in cells if cell]
        if len(cells) >= 2:
            rows.append(cells)
    if _score_rows(rows) >= 4:
        return rows
    return []


def _looks_like_markdown_separator(line: str) -> bool:
    cleaned = line.strip().strip("|").replace(" ", "")
    if not cleaned:
        return False
    parts = cleaned.split("|")
    if not parts:
        return False
    return all(re.fullmatch(r":?-{2,}:?", part or "") for part in parts)


def _score_rows(rows: list[list[str]]) -> int:
    if not rows:
        return 0
    row_count = len(rows)
    width = max((len(row) for row in rows), default=0)
    return row_count * width


def _rows_look_like_placeholder(rows: list[list[str]]) -> bool:
    if len(rows) != 1 or len(rows[0]) != 1:
        return False
    return rows[0][0].strip().lower() == "tabela detectada"


def _extract_picture_bytes(
    source_file: Path,
    element: ManifestElement,
    fallback_page_number: int | None,
    artifact_id: str | None = None,
) -> tuple[bytes | None, int]:
    provenance = element.provenance[0] if element.provenance else None
    page_number = provenance.page_number if provenance is not None else (fallback_page_number or 0)
    if page_number < 1:
        return None, 0

    clip, origin = _picture_clip(provenance)
    try:
        page = _toolbox_render(
            source_file, page_number, dpi=160, clip=clip, clip_origin=origin,
            artifact_id=artifact_id,
        )
        left, top, right, bottom = page.clip
        if clip is not None and (right - left < 4 or bottom - top < 4):
            # A sliver of a box is not a picture: describe the page instead.
            page = _toolbox_render(source_file, page_number, dpi=160, artifact_id=artifact_id)
        return page.image, page_number
    except Exception:
        if clip is not None:
            try:
                # A box outside the page is refused by the Toolbox; like a
                # sliver, fall back to the whole page.
                page = _toolbox_render(
                    source_file, page_number, dpi=160, artifact_id=artifact_id
                )
                return page.image, page_number
            except Exception:
                pass
        logger.exception(
            t(LOG_PDDL_ELEMENT_CROP_FAILED).format(element_id=element.id)
        )
        return None, page_number


def _picture_clip(provenance: Any) -> tuple[tuple[float, float, float, float] | None, str]:
    """The box of a picture to render, and its origin; no box means the whole page.

    Pictures tolerate an inferred origin (``is_bottom_left``), unlike region
    inspection, which certifies its crop and requires an explicit one.
    """
    bbox = getattr(provenance, "bbox", None)
    if bbox is None:
        return None, "TOPLEFT"
    left, top, right, bottom = (
        float(bbox.left), float(bbox.top), float(bbox.right), float(bbox.bottom)
    )
    if not all(math.isfinite(value) for value in (left, top, right, bottom)):
        return None, "TOPLEFT"
    origin = (
        "BOTTOMLEFT"
        if is_bottom_left(getattr(bbox, "coord_origin", None), top, bottom)
        else "TOPLEFT"
    )
    return (left, top, right, bottom), origin

def _is_mostly_visual_manifest(manifest: ProcessingManifest) -> bool:
    for element in manifest.elements:
        if element.type in {"heading", "title", "paragraph", "list_item", "table", "code", "formula"}:
            text = (element.text or "").strip()
            if text and not _is_placeholder_text(text) and not _is_ocr_noise(text):
                return False
    return True


def _is_ocr_noise(text: str) -> bool:
    """Retorna True se o texto parece ser ruído de OCR (muito curto, sem
    estrutura de linguagem natural), não devendo ser considerado como
    conteúdo textual significativo para efeitos de detecção de manifesto
    majoritariamente visual."""
    normalized = text.strip()
    if not normalized:
        return True
    # Texto muito curto (≤4 caracteres) é quase sempre OCR noise
    if len(normalized) <= 4:
        return True
    # Texto sem espaços e com ≤8 caracteres também é suspeito
    if " " not in normalized and len(normalized) <= 8:
        return True
    return False


def _is_placeholder_visual_element(element: ManifestElement) -> bool:
    if is_unstructured_page_placeholder(element):
        # Inspected by the planned vision-page-inspection method instead.
        return False
    if element.type not in {"group", "unknown", "paragraph"}:
        return False
    text = (element.text or "").strip()
    raw_label = (element.raw_label or "").strip().lower()
    return (not text) or _is_placeholder_text(text) or _is_ocr_noise(text) or raw_label in {"body", "unspecified", "group"}


def _is_placeholder_text(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {"body", "_root_", "root", "unspecified", "group"}


def _has_meaningful_text(element: ManifestElement) -> bool:
    """Retorna True se o elemento contém texto significativo (não é OCR noise
    nem placeholder). Usado para filtrar elementos do tipo 'picture' que já
    vieram com descrição textual válida do extrator."""
    text = (element.text or "").strip()
    if not text:
        return False
    if _is_placeholder_text(text):
        return False
    if _is_ocr_noise(text):
        return False
    return True


#: Obligation kinds that only refine content the extraction already delivered.
#: Leaving one open (every automatic method failed and it was escalated to
#: human review) does not lose content, so the job finishes with a warning
#: instead of failing. Heading levels are also normalized by the canonical
#: builder, which keeps the exported document valid without the repair.
#: `refine-reading-order` is deliberately absent: a wrong reading order is what
#: a screen reader user hits first, so an open one still fails the job.
NON_CRITICAL_OBLIGATION_KINDS = frozenset(
    {
        "repair-heading-hierarchy",
        "join-tail-blocks",
        "normalize-text",
        "chunk-verse",
        "extract-line-numbers",
    }
)


def _is_open_obligation(obligation: Obligation) -> bool:
    """Whether the job selected the obligation and left it unsatisfied.

    An exhausted obligation is left out of later replans, which clears its
    `selected` flag; its `failed` status keeps it open.
    """
    return obligation.status != "satisfied" and (
        obligation.selected or obligation.status == "failed"
    )


def _unsatisfied_selected_obligations(manifest: ProcessingManifest) -> list:
    return [
        obligation for obligation in manifest.obligations
        if _is_open_obligation(obligation)
    ]


def _replannable_obligation_ids(manifest: ProcessingManifest) -> list[str]:
    """Open selected obligations that a new plan can still satisfy.

    Exhausted obligations, and those depending on one, are excluded: the planner
    rejects an obligation without an untried admissible method.
    """
    by_id = {obligation.id: obligation for obligation in manifest.obligations}

    def blocked(obligation_id: str, seen: set[str]) -> bool:
        if obligation_id in seen:
            return False
        seen.add(obligation_id)
        obligation = by_id[obligation_id]
        if obligation.status == "failed":
            return True
        return any(blocked(dependency, seen) for dependency in obligation.dependencies)

    return [
        obligation.id for obligation in manifest.obligations
        if obligation.selected
        and obligation.status != "satisfied"
        and not blocked(obligation.id, set())
    ]


def _unsatisfied_execution_message(manifest: ProcessingManifest) -> str:
    return t(EXE_COMPLETED_OBLIGATIONS_UNSATISFIED).format(
        unsatisfied=", ".join(
            obligation.id
            for obligation in _unsatisfied_selected_obligations(manifest)
        )
    )


def _log_availability(availability: toolbox_gate.AvailabilityDecision) -> None:
    if not availability.blocked:
        return
    blocked = "; ".join(
        f"{method}: {', '.join(reasons)}"
        for method, reasons in availability.blocked.items()
    )
    if availability.enforced:
        logger.warning(
            "Gate da Toolbox (catálogo {}): métodos fora do plano — {}",
            availability.catalog_revision or "indisponível",
            blocked,
        )
    else:
        logger.warning(
            "Gate da Toolbox em observação (catálogo {}): removeria — {}",
            availability.catalog_revision or "indisponível",
            blocked,
        )


def build_pddl_structured_payload(
    *,
    file_path: Path,
    manifest: ProcessingManifest,
    plan: NominalPlan,
    planner_backend: str,
    execution_report: ExecutionReport | None,
    comparison: PlanningComparison | None,
    toolbox_availability: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pages_payload = _manifest_pages_to_payload(manifest)
    text_output = _render_text_from_pages(pages_payload)
    configuration = manifest.extractor.configuration
    media_inspection_status = configuration.get("media_inspection")

    technical_warnings: list[str] = []
    if execution_report is None:
        technical_warnings.append(
            "Executor nao foi executado; somente manifesto e plano foram gerados."
        )
    elif execution_report.status in {
        "failed", "replan-required",
    } or _unsatisfied_selected_obligations(manifest):
        # A replan that leaves an exhausted refinement out can still report
        # `completed`; the open obligation must reach the document anyway.
        technical_warnings.append(_unsatisfied_execution_message(manifest))

    if comparison is not None:
        technical_warnings.append(
            f"Comparacao de planners: {comparison.comparison.verdict}."
        )

    return {
        "text": text_output,
        "pages": pages_payload,
        "page_count": len(pages_payload),
        "mode": f"pddl-{planner_backend}",
        "source_path": str(file_path),
        "canonical_metadata": {
            "pipeline_engine": "pddl",
            "pddl_validation_only": True,
            "accessibility_verified": False,
            "pddl_manifest_id": manifest.manifest_id,
            "pddl_manifest_revision": manifest.revision,
            "pddl_plan_id": plan.plan_id,
            "pddl_planner": plan.planner,
            "pddl_expected_total_cost": plan.expected_total_cost,
            "pddl_execution_id": execution_report.execution_id
            if execution_report
            else None,
            "pddl_execution_status": execution_report.status
            if execution_report
            else None,
            "pddl_comparison_verdict": comparison.comparison.verdict
            if comparison
            else None,
            "pddl_unsatisfied_obligations": _unsatisfied_obligations(manifest),
            "pddl_toolbox_availability": toolbox_availability,
            "pddl_media_inspection": {
                "status": media_inspection_status,
                "error": configuration.get("media_inspection_error"),
            }
            if media_inspection_status is not None
            else None,
        },
        "technical_warnings": technical_warnings,
        # A step degraded by a Toolbox failure must not be replayed from the
        # cache once the Toolbox is back.
        "cacheable": media_inspection_status != "failed",
    }


def _unsatisfied_obligations(manifest: ProcessingManifest) -> list[dict[str, Any]]:
    """Selected obligations the execution left unsatisfied.

    `pddl_execution_status` alone does not say which obligations were exhausted
    or escalated, so each one is reported with its last attempt. An obligation
    whose last attempt is `human-review` is a pending escalation.
    """
    unsatisfied: list[dict[str, Any]] = []
    for obligation in manifest.obligations:
        if not _is_open_obligation(obligation):
            continue
        last = obligation.attempts[-1] if obligation.attempts else None
        unsatisfied.append(
            {
                "id": obligation.id,
                "kind": obligation.kind,
                "status": obligation.status,
                "target_ids": list(obligation.target_ids),
                "last_method": last.method if last else None,
                "last_message": last.message if last else None,
                "escalated": bool(last and last.method == "human-review"),
            }
        )
    return unsatisfied


def _is_left_out_of_payload(element: ManifestElement) -> bool:
    """A page accepted as blank, or a placeholder not yet inspected, adds nothing.

    An inspected page with content is a ``picture``, no longer a placeholder.
    A placeholder still present means the inspection did not run (dry-run), so
    the page contributes no block rather than its raw label.
    """
    return bool(element.metadata.get("blank_page")) or is_unstructured_page_placeholder(element)


def _manifest_pages_to_payload(manifest: ProcessingManifest) -> list[dict[str, Any]]:
    elements_by_id = {element.id: element for element in manifest.elements}
    pages: list[dict[str, Any]] = []

    if manifest.pages:
        sorted_pages = sorted(manifest.pages, key=lambda page: page.page_number)
        for page in sorted_pages:
            block_elements = [
                elements_by_id[element_id]
                for element_id in page.element_ids
                if element_id in elements_by_id
            ]
            if not block_elements:
                # Some extractors can fill in pages without element_ids; in that
                # case we fall back to page_number so no content is lost.
                block_elements = [
                    element
                    for element in manifest.elements
                    if (element.page_number or 1) == page.page_number
                ]
            block_elements = [
                item for item in block_elements if not _is_left_out_of_payload(item)
            ]
            block_elements.sort(key=lambda item: item.reading_order)
            blocks = [_element_to_block(item) for item in block_elements]
            _dedupe_callout_titles(blocks)
            pages.append(
                {
                    "page_number": page.page_number,
                    "text": _render_text_from_blocks(blocks),
                    "blocks": blocks,
                }
            )
        return pages

    grouped: dict[int, list[ManifestElement]] = {}
    for element in manifest.elements:
        if _is_left_out_of_payload(element):
            continue
        page_number = element.page_number or 1
        grouped.setdefault(page_number, []).append(element)

    for page_number in sorted(grouped):
        page_elements = sorted(
            grouped[page_number],
            key=lambda item: item.reading_order,
        )
        blocks = [_element_to_block(item) for item in page_elements]
        _dedupe_callout_titles(blocks)
        pages.append(
            {
                "page_number": page_number,
                "text": _render_text_from_blocks(blocks),
                "blocks": blocks,
            }
        )

    return pages


def _element_to_block(element: ManifestElement) -> dict[str, Any]:
    provenance = element.provenance[0] if element.provenance else None
    metadata: dict[str, Any] = {
        "raw_label": element.raw_label,
        "source_ref": element.source_ref,
        "parent_id": element.parent_id,
        "confidence": element.confidence,
        "manifest_element_id": element.id,
    }
    if element.metadata:
        metadata.update(element.metadata)
    metadata = _normalize_metadata_links(metadata)

    source_location: dict[str, Any] = {}
    if provenance is not None:
        source_location["page_number"] = provenance.page_number
        if provenance.bbox is not None:
            source_location["bbox"] = {
                "left": provenance.bbox.left,
                "top": provenance.bbox.top,
                "right": provenance.bbox.right,
                "bottom": provenance.bbox.bottom,
            }

    text = element.text or ""
    callout_id = metadata.get("callout_id")
    callout_role = str(metadata.get("callout_role", "")).lower()
    callout_type = str(metadata.get("callout_type", "note")).lower()
    callout_title = str(metadata.get("callout_title", "")).strip()
    callout_block_type = "warning" if callout_type in {"warning", "aviso", "importante", "caution"} else "note"
    block: dict[str, Any] = {
        "id": element.id,
        "source_location": source_location,
        "metadata": metadata,
    }

    if callout_id and callout_role != "title":
        block.update(
            {
                "type": callout_block_type,
                "title": callout_title,
                "text": text,
            }
        )
        return block

    if element.type in {"title", "heading"}:
        block.update(
            {
                "type": "heading",
                "level": 1 if element.type == "title" else max(1, element.hierarchy_level),
                "text": text or element.raw_label,
            }
        )
    elif element.type == "list_item":
        block.update(
            {
                "type": "list",
                "ordered": False,
                "items": [text] if text else [],
            }
        )
    elif element.type == "table":
        table_ast = _table_ast_from_metadata(metadata)
        rows = _rows_from_table_ast(table_ast) if table_ast else None
        if not rows:
            rows = [[text]] if text else [["Tabela detectada"]]
            if table_ast is None:
                table_ast = _table_ast_from_rows(rows)
        block.update(
            {
                "type": "table",
                "rows": rows,
                "table_ast": table_ast,
            }
        )
    elif element.type == "picture":
        block.update(
            {
                "type": "image",
                "alt_text": text or "Imagem detectada sem descricao textual.",
            }
        )
    elif element.type == "code":
        block.update({"type": "code", "text": normalize_code_text(text)})
    elif element.type == "formula":
        if text:
            block.update({"type": "math", "text": text})
        else:
            block.update({"type": "paragraph", "text": "Formula detectada."})
    else:
        block.update({"type": "paragraph", "text": text or element.raw_label})

    return block


def _dedupe_callout_titles(blocks: list[dict[str, Any]]) -> None:
    seen_callout_ids: set[str] = set()
    for block in blocks:
        metadata = block.get("metadata") or {}
        callout_id = str(metadata.get("callout_id") or "").strip()
        if not callout_id:
            continue
        if block.get("type") not in {"note", "warning"}:
            continue
        if callout_id in seen_callout_ids:
            block.pop("title", None)
            continue
        seen_callout_ids.add(callout_id)


def _normalize_metadata_links(metadata: dict[str, Any]) -> dict[str, Any]:
    def normalize_value(value: Any) -> Any:
        if isinstance(value, str) and value.startswith("#/"):
            return value[1:]
        if isinstance(value, list):
            return [normalize_value(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize_value(item) for key, item in value.items()}
        return value

    return {key: normalize_value(value) for key, value in metadata.items()}


def _render_text_from_blocks(blocks: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for block in blocks:
        block_type = block.get("type")
        if block_type == "heading":
            level = int(block.get("level", 1))
            prefix = "#" * max(1, min(level, 6))
            lines.append(f"{prefix} {block.get('text', '').strip()}")
        elif block_type == "list":
            for item in block.get("items", []):
                lines.append(f"- {str(item).strip()}")
        elif block_type == "table":
            rows = block.get("rows")
            if not rows and isinstance(block.get("table_ast"), dict):
                rows = _rows_from_table_ast(block["table_ast"])
            for row in rows or []:
                if isinstance(row, list):
                    lines.append(" | ".join(str(cell).strip() for cell in row))
        elif block_type == "image":
            lines.append(block.get("alt_text", "Imagem"))
        else:
            text = block.get("text", "")
            if isinstance(text, str) and text.strip():
                lines.append(text.strip())
    return "\n".join(lines).strip()


def _render_text_from_pages(pages: list[dict[str, Any]]) -> str:
    chunks: list[str] = []
    for page in pages:
        page_number = page.get("page_number", "?")
        text = str(page.get("text", "")).strip()
        if text:
            chunks.append(f"=== Pagina {page_number} ===\n{text}")
    return "\n\n".join(chunks)


def _table_ast_from_metadata(metadata: dict[str, Any]) -> dict[str, Any] | None:
    raw = metadata.get("table_ast")
    if not isinstance(raw, dict):
        return None

    table_ast: dict[str, Any] = {}
    caption = raw.get("caption")
    if isinstance(caption, str) and caption.strip():
        table_ast["caption"] = caption.strip()

    for section_name in ("header", "body", "footer"):
        section = raw.get(section_name)
        if not isinstance(section, list):
            continue
        normalized_rows: list[dict[str, Any]] = []
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            normalized_cells: list[dict[str, Any]] = []
            for cell in cells:
                if not isinstance(cell, dict) or "text" not in cell:
                    continue
                text = str(cell.get("text", "")).strip()
                normalized_cell: dict[str, Any] = {"text": text}
                if isinstance(cell.get("header"), bool):
                    normalized_cell["header"] = cell["header"]
                scope = cell.get("scope")
                if isinstance(scope, str) and scope in {
                    "none",
                    "row",
                    "col",
                    "rowgroup",
                    "colgroup",
                }:
                    normalized_cell["scope"] = scope
                for span_key in ("rowspan", "colspan"):
                    span = cell.get(span_key)
                    if isinstance(span, int) and span >= 1:
                        normalized_cell[span_key] = span
                normalized_cells.append(normalized_cell)
            if normalized_cells:
                normalized_rows.append({"cells": normalized_cells})
        if normalized_rows:
            table_ast[section_name] = normalized_rows

    metadata_obj = raw.get("metadata")
    if isinstance(metadata_obj, dict):
        table_ast["metadata"] = metadata_obj

    return table_ast if table_ast.get("body") else None


def _table_ast_from_rows(rows: list[list[str]]) -> dict[str, Any]:
    body: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, list):
            continue
        cells = []
        for cell in row:
            text = str(cell).strip()
            cells.append({"text": text})
        if cells:
            body.append({"cells": cells})
    return {"body": body}


def _rows_from_table_ast(table_ast: dict[str, Any]) -> list[list[str]]:
    rows: list[list[str]] = []
    for section_name in ("header", "body", "footer"):
        section = table_ast.get(section_name)
        if not isinstance(section, list):
            continue
        for row in section:
            if not isinstance(row, dict):
                continue
            cells = row.get("cells")
            if not isinstance(cells, list):
                continue
            row_values = [
                str(cell.get("text", "")).strip()
                for cell in cells
                if isinstance(cell, dict)
            ]
            if row_values:
                rows.append(row_values)
    return rows


# Backward compatibility with the PMV naming.
PmvAccessibilityOrchestrator = PddlAccessibilityOrchestrator
build_pmv_structured_payload = build_pddl_structured_payload
