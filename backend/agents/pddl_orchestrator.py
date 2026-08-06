from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Callable, Coroutine

import fitz

from core.agents.informational_structural import InformationalStructuralAgent
from core.execution.executor import ExecutorAgent, MethodRegistry
from core.execution.models import ExecutionReport
from core.manifest.docling_extractor import DoclingManifestExtractor
from core.manifest.pymupdf_extractor import PyMuPDFManifestExtractor
from core.manifest.models import ManifestElement, ProcessingManifest
from core.planning.models import NominalPlan, PlanningComparison
from core.planning.planner_agent import PlannerAgent

from backend.agents.vision_agent import VisionAgent
from backend.tools.code_tools import normalize_code_text
from backend.tools.logger import logger


class PddlAccessibilityOrchestrator:
    """Orquestra o pipeline PDDL: IE -> Planner -> Executor."""

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
        extractor_backend: str = "docling",
    ) -> None:
        self.planner_backend = planner_backend
        self.preferred_plan = preferred_plan
        self.execute_dry_run = execute_dry_run
        self.fast_downward = fast_downward
        self.fast_downward_alias = fast_downward_alias
        self.fast_downward_search = fast_downward_search
        self.extractor_backend = extractor_backend.strip().lower()

        if self.extractor_backend == "pymupdf":
            extractor = PyMuPDFManifestExtractor(include_images=True)
        elif self.extractor_backend == "docling":
            extractor = DoclingManifestExtractor(enable_ocr=enable_ocr)
        else:
            raise ValueError(
                "extractor_backend inválido; use 'docling' ou 'pymupdf'"
            )

        self.information_structural = InformationalStructuralAgent(
            extractor
        )
        self.planner = PlannerAgent()
        self.executor = ExecutorAgent(
            MethodRegistry(),
            domain=self.planner.domain,
        )

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
        del tmpdir

        effective_mode = mode or "medio"

        if custom_prompt or thinking_mode:
            logger.warning(
                "Pipeline PDDL ignora custom_prompt/thinking_mode; "
                "apenas fluxo deterministico de manifesto/planejamento/execucao"
            )

        if status_callback:
            await status_callback("Analisando documento com agente estrutural...")
        manifest = await asyncio.to_thread(
            self.information_structural.process,
            file_path.resolve(),
            language="pt-BR",
        )

        if status_callback:
            await status_callback("Enriquecendo descrições de imagens...")
        await _enrich_picture_descriptions(
            manifest,
            file_path.resolve(),
            mode=effective_mode,
        )

        if status_callback:
            await status_callback("Gerando plano nominal com PDDL...")
        plan, comparison = await asyncio.to_thread(self._build_plan, manifest)

        execution_report: ExecutionReport | None = None
        if self.execute_dry_run:
            if status_callback:
                await status_callback("Validando plano em dry-run...")
            _, execution_report = await asyncio.to_thread(
                self.executor.execute,
                plan,
                manifest,
                dry_run=True,
            )

        payload = build_pddl_structured_payload(
            file_path=file_path,
            manifest=manifest,
            plan=plan,
            planner_backend=self.planner_backend,
            execution_report=execution_report,
            comparison=comparison,
        )

        if structured_output:
            return payload
        return payload["text"]

    def _build_plan(
        self,
        manifest: ProcessingManifest,
    ) -> tuple[NominalPlan, PlanningComparison | None]:
        if self.planner_backend == "both":
            _, plans, comparison = self.planner.compare(
                manifest,
                fast_downward=self.fast_downward,
                fast_downward_alias=self.fast_downward_alias,
                fast_downward_search=self.fast_downward_search,
                preferred_backend=self.preferred_plan,
            )
            if self.preferred_plan not in plans:
                raise RuntimeError(
                    "Backend preferido nao gerou plano valido no modo both: "
                    f"{self.preferred_plan}"
                )
            return plans[self.preferred_plan], comparison

        _, plan = self.planner.plan(
            manifest,
            backend=self.planner_backend,
            fast_downward=self.fast_downward,
            fast_downward_alias=self.fast_downward_alias,
            fast_downward_search=self.fast_downward_search,
        )
        return plan, None


async def _enrich_picture_descriptions(
    manifest: ProcessingManifest,
    source_file: Path,
    *,
    mode: str,
) -> None:
    pictures = [
        element
        for element in manifest.elements
        if element.type == "picture" and not (element.text or "").strip()
    ]
    if not pictures and _is_mostly_visual_manifest(manifest):
        pictures = [
            element
            for element in manifest.elements
            if _is_placeholder_visual_element(element)
        ]

    if (
        not pictures
        and _is_mostly_visual_manifest(manifest)
        and len(manifest.pages) == 1
        and manifest.elements
    ):
        pictures = [manifest.elements[0]]

    if not pictures:
        return

    vision = VisionAgent(mode=mode)
    total_pages = len(manifest.pages)
    enriched = 0

    for element in pictures:
        fallback_page_number = element.page_number
        if fallback_page_number is None and len(manifest.pages) == 1:
            fallback_page_number = manifest.pages[0].page_number

        image_bytes, page_number = await asyncio.to_thread(
            _extract_picture_bytes,
            source_file,
            element,
            fallback_page_number,
        )
        if not image_bytes:
            continue

        description = await vision.describe_region(
            image_bytes=image_bytes,
            classification="embedded_image",
            page_num=page_number,
            total_pages=total_pages,
            mode=mode,
        )
        if description and description.strip():
            element.text = description.strip()
            if element.type != "picture":
                element.metadata["original_type"] = element.type
                element.type = "picture"
                element.raw_label = "picture"
            if element.page_number is None and page_number >= 1:
                element.page_number = page_number
            enriched += 1

    if enriched:
        logger.info(
            "Pipeline PDDL: {} imagem(ns) enriquecida(s) com descrição visual",
            enriched,
        )


def _extract_picture_bytes(
    source_file: Path,
    element: ManifestElement,
    fallback_page_number: int | None,
) -> tuple[bytes | None, int]:
    provenance = element.provenance[0] if element.provenance else None
    page_number = provenance.page_number if provenance is not None else (fallback_page_number or 0)
    if page_number < 1:
        return None, 0

    doc = fitz.open(source_file)
    try:
        page = doc.load_page(page_number - 1)
        rect = _clip_rect_from_provenance(page, provenance)
        pixmap = page.get_pixmap(clip=rect, dpi=160, alpha=False)
        return pixmap.tobytes("png"), page_number
    except Exception:
        logger.exception(
            "Falha ao extrair recorte de imagem para elemento {}",
            element.id,
        )
        return None, page_number
    finally:
        doc.close()


def _clip_rect_from_provenance(page: fitz.Page, provenance: Any) -> fitz.Rect:
    bbox = getattr(provenance, "bbox", None)
    if bbox is None:
        return page.rect

    left = float(bbox.left)
    right = float(bbox.right)
    top = float(bbox.top)
    bottom = float(bbox.bottom)

    if getattr(bbox, "coord_origin", "UNKNOWN") == "BOTTOMLEFT":
        page_height = float(page.rect.height)
        top_from_top = page_height - top
        bottom_from_top = page_height - bottom
        y0 = min(top_from_top, bottom_from_top)
        y1 = max(top_from_top, bottom_from_top)
    else:
        y0 = min(top, bottom)
        y1 = max(top, bottom)

    x0 = min(left, right)
    x1 = max(left, right)

    rect = fitz.Rect(x0, y0, x1, y1) & page.rect
    if rect.width < 4 or rect.height < 4:
        return page.rect
    return rect


def _is_mostly_visual_manifest(manifest: ProcessingManifest) -> bool:
    for element in manifest.elements:
        if element.type in {"heading", "title", "paragraph", "list_item", "table", "code", "formula"}:
            text = (element.text or "").strip()
            if text and not _is_placeholder_text(text):
                return False
    return True


def _is_placeholder_visual_element(element: ManifestElement) -> bool:
    if element.type not in {"group", "unknown", "paragraph"}:
        return False
    text = (element.text or "").strip()
    raw_label = (element.raw_label or "").strip().lower()
    return (not text) or _is_placeholder_text(text) or raw_label in {"body", "unspecified", "group"}


def _is_placeholder_text(text: str) -> bool:
    normalized = text.strip().lower()
    return normalized in {"body", "_root_", "root", "unspecified", "group"}


def build_pddl_structured_payload(
    *,
    file_path: Path,
    manifest: ProcessingManifest,
    plan: NominalPlan,
    planner_backend: str,
    execution_report: ExecutionReport | None,
    comparison: PlanningComparison | None,
) -> dict[str, Any]:
    pages_payload = _manifest_pages_to_payload(manifest)
    text_output = _render_text_from_pages(pages_payload)

    technical_warnings: list[str] = []
    if execution_report is None:
        technical_warnings.append(
            "Executor nao foi executado; somente manifesto e plano foram gerados."
        )

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
        },
        "technical_warnings": technical_warnings,
    }


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
                # Alguns extratores podem preencher pages sem element_ids; nesse
                # caso, fazemos fallback por page_number para não perder conteúdo.
                block_elements = [
                    element
                    for element in manifest.elements
                    if (element.page_number or 1) == page.page_number
                ]
            block_elements.sort(key=lambda item: item.reading_order)
            blocks = [_element_to_block(item) for item in block_elements]
            pages.append(
                {
                    "page_number": page.page_number,
                    "text": _render_text_from_blocks(blocks),
                    "blocks": blocks,
                    "cached": False,
                }
            )
        return pages

    grouped: dict[int, list[ManifestElement]] = {}
    for element in manifest.elements:
        page_number = element.page_number or 1
        grouped.setdefault(page_number, []).append(element)

    for page_number in sorted(grouped):
        page_elements = sorted(
            grouped[page_number],
            key=lambda item: item.reading_order,
        )
        blocks = [_element_to_block(item) for item in page_elements]
        pages.append(
            {
                "page_number": page_number,
                "text": _render_text_from_blocks(blocks),
                "blocks": blocks,
                "cached": False,
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
    block: dict[str, Any] = {
        "id": element.id,
        "source_location": source_location,
        "metadata": metadata,
    }

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
        block.update(
            {
                "type": "table",
                "rows": [[text]] if text else [["Tabela detectada"]],
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
        block.update(
            {
                "type": "paragraph",
                "text": text or "Formula detectada.",
            }
        )
    else:
        block.update({"type": "paragraph", "text": text or element.raw_label})

    return block


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
            for row in block.get("rows", []):
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


# Compatibilidade retroativa com nomenclatura PMV.
PmvAccessibilityOrchestrator = PddlAccessibilityOrchestrator
build_pmv_structured_payload = build_pddl_structured_payload
