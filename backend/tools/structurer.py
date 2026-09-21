from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import fitz

from backend.config.settings import settings
from backend.i18n import t
from backend.log_messages import (
    LOG_STRUCTURER_FALLBACK_PYMUPDF,
    LOG_STRUCTURER_PYMUPDF,
)
from backend.tools.region_extractor import Region, crop_region_to_image, extract_regions
from backend.tools.logger import logger

DOCLING_AVAILABLE = False


class BaseStructurer:
    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        raise NotImplementedError

    def crop_region(
        self, page: fitz.Page, bbox: tuple[float, float, float, float], dpi: int = 200
    ) -> bytes:
        return crop_region_to_image(page, bbox, dpi)

    @property
    def name(self) -> str:
        return self.__class__.__name__


class PyMuPDFStructurer(BaseStructurer):
    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        return extract_regions(page)

    @property
    def name(self) -> str:
        return "PyMuPDF"


class FusedStructurer(BaseStructurer):
    """FUSION_MODE=dual: fused text from two toolbox providers + local geometry.

    ``extract_fused`` returns markdown blocks without bbox/provenance, so
    geometry comes from the local PyMuPDF extraction while the fused text
    is attached to regions by reading order (sequential mapping within the
    page). Fallback to plain local regions if fusion fails.
    """

    def __init__(self) -> None:
        self._local = PyMuPDFStructurer()
        self._doc_cache: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "Fused"

    async def _fetch_fused(self, file_path: Path | str) -> dict[str, Any]:
        from backend.pipeline.fusion import extract_fused

        path = Path(file_path)
        path_str = str(path.resolve())
        if path_str in self._doc_cache:
            entry = self._doc_cache[path_str]
            if time.time() - entry["time"] < 300:
                return entry["data"]
            del self._doc_cache[path_str]

        result = await extract_fused(path)
        self._doc_cache[path_str] = {"data": result, "time": time.time()}
        return result

    def _fused_texts_for_page(self, result: dict[str, Any], page_index: int) -> list[str]:
        document = result.get("document", {})
        elements = document.get("elements", [])
        if not elements:
            return []
        # Single-page fused payloads do not carry page markers: treat all
        # elements as belonging to the requested page when only one page
        # exists in the extraction.
        pages = {el.get("page") for el in elements if el.get("page") is not None}
        if pages and pages != {None}:
            ordered = [
                el
                for el in elements
                if el.get("page") == page_index
            ]
        else:
            ordered = elements
        ordered.sort(key=lambda el: el.get("reading_order") or 0)
        return [str(el.get("text") or "") for el in ordered if (el.get("text") or "").strip()]

    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        page_index = getattr(page, "number", 0) or 0
        page_num = int(page_index) + 1
        parent = page.parent

        regions = self._local.extract_page_regions(page)
        try:
            if parent is None or not getattr(parent, "name", None):
                raise RuntimeError(
                    "Page without parent document for fusion processing"
                )
            import asyncio

            result = asyncio.run(self._fetch_fused(Path(parent.name)))
            texts = self._fused_texts_for_page(result, page_index)
            return self._attach_fused_text(regions, texts, page_num)
        except Exception as e:
            logger.warning(
                "Fusion failed on page {} ({}), falling back to local regions",
                page_num,
                e,
            )
            return regions

    def _attach_fused_text(
        self, regions: list[Region], texts: list[str], page_num: int
    ) -> list[Region]:
        """Distribute fused text over regions by reading order.

        The fused blocks carry no bbox, so we map them onto the local
        geometry: one text block per text-like region, in order; surplus
        texts are appended to the last region, surplus regions are kept
        with their local text.
        """
        text_regions = [r for r in regions if r.type in ("text", "unknown")]
        if not texts or not text_regions:
            return regions

        n = min(len(texts), len(text_regions))
        for i in range(n):
            text_regions[i].text = texts[i]
            text_regions[i].metadata["fused"] = True
        if len(texts) > n:
            text_regions[n - 1].text += "\n" + "\n".join(texts[n:])

        logger.info(
            "Fusion: {} fused text blocks mapped onto page {} regions",
            len(texts),
            page_num,
        )
        return regions


def get_structurer() -> BaseStructurer:
    # Fusion mode takes precedence: it wraps local geometry with fused text.
    if settings.fusion_mode == "dual":
        logger.info("Usando structurer: Fused (dual-provider fusion)")
        return FusedStructurer()

    mode = settings.structurer.lower()

    if mode == "toolbox":
        from backend.tools.toolbox_structurer import ToolboxStructurer

        logger.info("Usando structurer: Toolbox (remoto via Acessilia Toolbox)")
        return ToolboxStructurer()

    if mode in ("toolbox-layout", "toolbox_layout"):
        from backend.tools.toolbox_layout_structurer import ToolboxLayoutStructurer

        logger.info("Usando structurer: ToolboxLayout (layout remoto via Acessilia Toolbox)")
        return ToolboxLayoutStructurer()

    logger.info(t(LOG_STRUCTURER_PYMUPDF))
    return PyMuPDFStructurer()
