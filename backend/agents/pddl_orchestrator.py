from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any, Callable, Coroutine

import fitz

from backend.agents.data_agent import DataAgent
from backend.core.agents.informational_structural import InformationalStructuralAgent
from backend.core.execution.executor import ExecutorAgent, MethodRegistry
from backend.core.execution.models import ExecutionReport, MethodResult
from backend.core.manifest.docling_extractor import DoclingManifestExtractor
from backend.core.manifest.pymupdf_extractor import PyMuPDFManifestExtractor
from backend.core.manifest.models import ManifestElement, ProcessingManifest
from backend.core.planning.domain_bundle import DomainBundle
from backend.core.planning.models import NominalPlan, PlanningComparison
from backend.core.planning.planner_agent import PlannerAgent

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
        self.executor = self._build_executor()

    @staticmethod
    def _build_executor() -> ExecutorAgent:
        registry = MethodRegistry()

        def _noop_handler(
            _manifest: ProcessingManifest, _obligation_id: str
        ) -> MethodResult:
            return MethodResult(success=True, validated=True, message="Handler padrão (sem operação real)")

        for method in (
            "docling",
            "hierarchy-llm",
            "canonical-builder",
            "accessibility-checker",
            "html-exporter",
            "local-summarizer",
            "vision",
            "human-review",
        ):
            registry.register(method, _noop_handler)

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
            await status_callback("Enriquecendo tabelas com OCR (fallback)...")
        await _enrich_table_structures(
            manifest,
            file_path.resolve(),
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

        image_bytes, page_number = await asyncio.to_thread(
            _extract_picture_bytes,
            source_file,
            element,
            fallback_page_number,
        )
        if not image_bytes:
            continue

        ocr_text = await data_agent.process_region(
            image_bytes=image_bytes,
            classification="table",
            page_num=page_number,
            fallback_text=element.text or "",
        )
        if not isinstance(ocr_text, str) or not ocr_text.strip():
            continue

        rows = _rows_from_visual_table_text(ocr_text)
        if not rows:
            continue

        table_ast = _table_ast_from_rows(rows)
        if table_ast is None:
            continue

        element.metadata["table_ast"] = table_ast
        element.metadata["table_linearization_hint"] = "ocr-visual-fallback"
        element.metadata["table_row_count"] = len(rows)
        element.metadata["table_column_count"] = max((len(row) for row in rows), default=0)
        element.metadata["table_has_header"] = bool(rows and len(rows[0]) >= 2)
        element.text = ""
        if element.page_number is None and page_number >= 1:
            element.page_number = page_number
        enriched += 1

    if enriched:
        logger.info(
            "Pipeline PDDL: {} tabela(s) enriquecida(s) com OCR/reconstrução",
            enriched,
        )


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
            _dedupe_callout_titles(blocks)
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
        _dedupe_callout_titles(blocks)
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
        block.update(
            {
                "type": "paragraph",
                "text": text or "Formula detectada.",
            }
        )
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
                if not isinstance(cell, dict):
                    continue
                text = str(cell.get("text", "")).strip()
                if not text:
                    continue
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
            if text:
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
            row_values = [value for value in row_values if value]
            if row_values:
                rows.append(row_values)
    return rows


# Compatibilidade retroativa com nomenclatura PMV.
PmvAccessibilityOrchestrator = PddlAccessibilityOrchestrator
build_pmv_structured_payload = build_pddl_structured_payload
