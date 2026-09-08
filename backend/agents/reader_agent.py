"""ReaderAgent — structural reading and classification of page regions."""

from pathlib import Path

import fitz

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
    region_has_markers,
    region_needs_vision,
)
from backend.tools.region_extractor import Region
from backend.tools.logger import logger
from backend.tools.pdf_splitter import split_pdf

from backend.agents.types import RegionTask
from backend.tools.text_tools import apply_marker, content_fingerprint, overlaps_clean
from backend.tools.image_tools import crop_region_image, prepare_image_bytes, render_full_page
from backend.tools.structurer import get_structurer as get_structurer_instance


class ReaderAgent:
    """Analyzes document pages and generates typed tasks for the remaining agents."""

    def __init__(self):
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
        all_text_clean = True
        for r in regions:
            classification = classify_region(r)
            if classification != "text_clean" and classification != "ignore":
                all_text_clean = False
                break

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

            if classification == "text_clean" and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in clean_fps:
                    clean_fps.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=region.text,
                        region=region,
                        page_num=page_num,
                    ))
            elif region_has_markers(classification) and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in clean_fps:
                    clean_fps.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=apply_marker(region.text, classification, region),
                        region=region,
                        page_num=page_num,
                    ))

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
        """Generates mixed tasks: clean text sent directly plus regions that need a vision pass.

        Args:
            page_path: Path to the single-page file (per-page PDF or image).
            regions: Regions extracted from the page.
            page_num: 1-based page number within the document.
            total_pages: Total page count of the document.

        Returns:
            One RegionTask per region that produced usable output.
        """
        tasks: list[RegionTask] = []
        clean_bboxes: list[tuple[float, float, float, float]] = []
        content_fingerprints: set[int] = set()
        vision_count = 0

        for region in regions:
            classification = classify_region(region)

            if classification == "ignore":
                continue

            # Clean text goes straight to the EditorAgent
            if classification == "text_clean" and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=region.text,
                        region=region,
                        page_num=page_num,
                    ))
                    clean_bboxes.append(region.bbox)
                continue

            # Regions with markers that also carry clean text
            if region_has_markers(classification) and region.text.strip():
                fp = content_fingerprint(region.text)
                if fp not in content_fingerprints:
                    content_fingerprints.add(fp)
                    tasks.append(RegionTask(
                        agent_target="editor",
                        classification=classification,
                        text=apply_marker(region.text, classification, region),
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
                    if region.text.strip():
                        fp = content_fingerprint(region.text)
                        if fp not in content_fingerprints:
                            content_fingerprints.add(fp)
                            tasks.append(RegionTask(
                                agent_target="editor",
                                classification=classification,
                                text=region.text,
                                region=region,
                                page_num=page_num,
                            ))
                    continue

                vision_count += 1

                # Crop the region image to send to the vision agent
                image_bytes = crop_region_image(
                    self.structurer, page_path, region,
                )

                # Decide which agent will process the task
                if classification in ("table",):
                    target = "data"
                elif classification in ("formula",):
                    target = "data"
                elif classification in ("embedded_image",):
                    target = "vision"
                else:
                    target = "vision"

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
