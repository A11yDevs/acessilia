from __future__ import annotations

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


def get_structurer() -> BaseStructurer:
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
