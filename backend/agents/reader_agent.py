"""ReaderAgent — structural reading and classification of page regions."""

from pathlib import Path

import fitz

from agno.workflow.step import Step, StepInput, StepOutput

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import (
    LOG_READER_CLEAN_TEXT_REGIONS,
    LOG_READER_FULL_PAGE_FALLBACK,
    LOG_READER_IMAGE_READING,
    LOG_READER_PDF_REGIONS_EXTRACTED,
    LOG_READER_REGION_TASK,
    LOG_READER_TASKS_SUMMARY,
)
from backend.tools.region_classifier import (
    classify_region,
    formula_already_extracted,
    region_has_markers,
    region_needs_vision,
)
from backend.tools.region_extractor import Region
from backend.tools.logger import logger
from backend.tools.pdf_splitter import split_pdf

from backend.agents.types import RegionTask
from backend.tools.formula_tools import (
    ensure_math_delimiters,
    try_extract_formula_locally,
)
from backend.tools.text_tools import apply_marker, content_fingerprint, overlaps_clean
from backend.tools.image_tools import crop_region_image, prepare_image_bytes, render_full_page
from backend.tools.structurer import get_structurer as get_structurer_instance


class ReaderAgent:
    """Analyzes document pages and generates typed tasks for the remaining agents."""

    def __init__(self):
        self.__name__ = self.__class__.__name__
        self.structurer = get_structurer_instance()

    def split_file(self, file_path: Path, tmpdir: Path) -> list[Path]:
        """Splits a PDF into individual pages; returns [file_path] unchanged for image inputs."""
        is_pdf = file_path.suffix.lower() == ".pdf"
        if is_pdf:
            return split_pdf(file_path, tmpdir, settings.max_pages)
        return [file_path]

    def analyse_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
        is_pdf: bool,
    ) -> list[RegionTask]:
        """Analyzes a page and returns a list of RegionTasks.

        Args:
            page_path: Path to the single-page file (per-page PDF or image).
            page_num: 1-based page number within the document.
            total_pages: Total page count of the document.
            is_pdf: Whether the page file is a PDF (True) or a raster image (False).

        Returns:
            One RegionTask per detected region on the page.
        """

        if not is_pdf:
            return self._analyse_image_page(page_path, page_num, total_pages)

        return self._analyse_pdf_page(page_path, page_num, total_pages)

    # ── PDF ──

    def _analyse_pdf_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
    ) -> list[RegionTask]:
        doc = fitz.open(page_path)
        try:
            page = doc[0]
            regions = self.structurer.extract_page_regions(page)
        finally:
            doc.close()

        if not regions:
            return []

        logger.info(
            t(LOG_READER_PDF_REGIONS_EXTRACTED).format(
                page_num=page_num,
                count=len(regions),
                structurer=self.structurer.name,
            )
        )

        # Check whether every region is clean text (no vision pass needed)
        all_text_clean = all(
            classify_region(r) in ("text_clean", "ignore") for r in regions
        )

        if all_text_clean:
            return self._extract_clean_text_tasks(regions, page_num)

        return self._extract_mixed_tasks(page_path, regions, page_num, total_pages)

    def _extract_clean_text_tasks(
        self,
        regions: list[Region],
        page_num: int,
    ) -> list[RegionTask]:
        """Generates tasks for purely textual regions that need no vision pass."""
        tasks: list[RegionTask] = []
        clean_fps: set[int] = set()

        for region in regions:
            classification = classify_region(region)
            if (classification == "text_clean" or region_has_markers(classification)) and region.text.strip():
                task = _build_text_task(region, classification, page_num)
                if task:
                    fp = content_fingerprint(region.text)
                    if fp not in clean_fps:
                        clean_fps.add(fp)
                        tasks.append(task)

        if tasks:
            logger.info(
                t(LOG_READER_CLEAN_TEXT_REGIONS).format(
                    page_num=page_num,
                    count=len(tasks),
                )
            )

        return tasks

    def _extract_mixed_tasks(
        self,
        page_path: Path,
        regions: list[Region],
        page_num: int,
        total_pages: int,
    ) -> list[RegionTask]:
        """Generates mixed tasks: clean text sent directly plus regions that need a vision pass."""
        tasks: list[RegionTask] = []
        clean_bboxes: list[tuple[float, float, float, float]] = []
        content_fingerprints: set[int] = set()
        vision_count = 0

        for region in regions:
            classification = classify_region(region)

            if classification == "ignore":
                continue

            # Clean text or regions with markers that also carry clean text
            if (classification == "text_clean" or region_has_markers(classification)) and region.text.strip():
                task = _build_text_task(region, classification, page_num)
                if task:
                    fp = content_fingerprint(region.text)
                    if fp not in content_fingerprints:
                        content_fingerprints.add(fp)
                        tasks.append(task)
                        clean_bboxes.append(region.bbox)
                continue

            # Formula with LaTeX already extracted by Docling (CodeFormula) → editor directly
            if classification == "formula" and formula_already_extracted(region):
                latex = ensure_math_delimiters(region.text)
                fp = content_fingerprint(latex)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    logger.info(
                        "[pag {}] Formula ja enriquecida pelo Docling (sem LLM)",
                        page_num,
                    )
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=latex,
                        region=region,
                        page_num=page_num,
                    ))
                    clean_bboxes.append(region.bbox)
                continue

            # Regions that need a vision pass
            if region_needs_vision(classification):
                if classification in ("unknown", "text_scanned") and overlaps_clean(
                    region.bbox, clean_bboxes
                ):
                    task = _build_text_task(region, classification, page_num)
                    if task:
                        fp = content_fingerprint(region.text)
                        if fp not in content_fingerprints:
                            content_fingerprints.add(fp)
                            tasks.append(task)
                    continue

                vision_count += 1
                image_bytes = crop_region_image(
                    self.structurer, page_path, region,
                )

                # Local cascade: image that is actually a formula → OCR + CodeFormula
                if (
                    classification == "embedded_image"
                    and settings.formula_image_cascade
                ):
                    latex = try_extract_formula_locally(image_bytes)
                    if latex:
                        latex = ensure_math_delimiters(latex)
                        vision_count -= 1
                        fp = content_fingerprint(latex)
                        if fp in content_fingerprints:
                            continue
                        content_fingerprints.add(fp)
                        logger.info(
                            "[pag {}] Imagem identificada como formula pela "
                            "cascata local (sem LLM)",
                            page_num,
                        )
                        tasks.append(RegionTask(
                            agent_target="editor",
                            classification="formula",
                            text=latex,
                            region=region,
                            page_num=page_num,
                        ))
                        continue

                target = "data" if classification in ("table", "formula") else "vision"

                logger.info(
                    t(LOG_READER_REGION_TASK).format(
                        page_num=page_num,
                        idx=len(tasks) + 1,
                        type=classification,
                        bbox=region.bbox,
                        target=target,
                    )
                )

                tasks.append(RegionTask(
                    agent_target=target,
                    classification=classification,
                    text=region.text,
                    image_bytes=image_bytes,
                    region=region,
                    page_num=page_num,
                ))

        if not tasks:
            # Fallback: send the whole page to the VisionAgent
            logger.warning(
                t(LOG_READER_FULL_PAGE_FALLBACK).format(page_num=page_num)
            )
            image_bytes = render_full_page(page_path)
            tasks.append(RegionTask(
                agent_target="vision",
                classification="full_page_fallback",
                image_bytes=image_bytes,
                page_num=page_num,
            ))

        logger.info(
            t(LOG_READER_TASKS_SUMMARY).format(
                page_num=page_num,
                count=len(tasks),
                text_count=len(tasks) - vision_count,
                vision_count=vision_count,
            )
        )

        return tasks

    # ── Image ──

    def _analyse_image_page(
        self,
        page_path: Path,
        page_num: int,
        total_pages: int,
    ) -> list[RegionTask]:
        """For image files, generate a single vision task for the whole page."""
        logger.debug(
            t(LOG_READER_IMAGE_READING).format(page_num=page_num, path=page_path)
        )
        with open(page_path, "rb") as file_handle:
            raw_bytes = file_handle.read()

        jpg_bytes = prepare_image_bytes(raw_bytes)

        return [RegionTask(
            agent_target="vision",
            classification="full_page_image",
            image_bytes=jpg_bytes,
            page_num=page_num,
        )]

    def execute_step(self, step_input: StepInput) -> StepOutput:
        """Executes reader step for an Agno workflow."""
        raw = step_input.input if step_input.input is not None else step_input.previous_step_content
        page_path, page_num, total_pages, is_pdf = self._parse_step_input(raw)

        if not page_path:
            return StepOutput(
                content=None,
                success=False,
                error="ReaderAgent requires 'page_path' or 'file_path' in input",
            )

        try:
            tasks = self.analyse_page(
                page_path=page_path,
                page_num=page_num,
                total_pages=total_pages,
                is_pdf=is_pdf if is_pdf is not None else (page_path.suffix.lower() == ".pdf"),
            )
            return StepOutput(
                content={
                    "tasks": tasks,
                    "page_path": str(page_path),
                    "page_num": page_num,
                    "total_pages": total_pages,
                    "is_pdf": is_pdf if is_pdf is not None else (page_path.suffix.lower() == ".pdf"),
                    "total_tasks": len(tasks),
                },
                success=True,
            )
        except Exception as exc:
            logger.error(f"ReaderAgent step execution failed for {page_path}: {exc}")
            return StepOutput(content=None, success=False, error=str(exc))

    @staticmethod
    def _parse_step_input(raw: object) -> tuple[Path | None, int, int, bool | None]:
        if isinstance(raw, dict):
            path_val = raw.get("page_path") or raw.get("file_path")
            return (
                Path(path_val) if path_val else None,
                raw.get("page_num") or 1,
                raw.get("total_pages") or 1,
                raw.get("is_pdf"),
            )
        if isinstance(raw, (str, Path)):
            return Path(raw), 1, 1, None
        if hasattr(raw, "page_path"):
            path_val = raw.page_path
            return (
                Path(path_val) if path_val else None,
                getattr(raw, "page_num", 1) or 1,
                getattr(raw, "total_pages", 1) or 1,
                getattr(raw, "is_pdf", None),
            )
        return None, 1, 1, None

    def __call__(self, step_input: StepInput) -> StepOutput:
        """Allows ReaderAgent instance to be passed directly as an Agno workflow step."""
        return self.execute_step(step_input)

    def as_step(
        self,
        name: str = "ReaderAgent",
        description: str = "Structural page reading and region classification",
    ) -> Step:
        """Wraps ReaderAgent as an explicit Agno Step instance."""
        return Step(name=name, description=description, executor=self.execute_step)


def _build_text_task(region: Region, classification: str, page_num: int) -> RegionTask | None:
    if not region.text.strip():
        return None
    text = (
        apply_marker(region.text, classification, region)
        if region_has_markers(classification)
        else region.text
    )
    return RegionTask(
        agent_target="editor",
        classification=classification,
        text=text,
        region=region,
        page_num=page_num,
    )


def reader_step(step_input: StepInput) -> StepOutput:
    """Module-level step function for ReaderAgent in Agno workflows."""
    return ReaderAgent().execute_step(step_input)


