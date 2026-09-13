"""Structurer que consome a capacidade document.layout.analyze da Toolbox.

Substitui o ToolboxStructurer genérico (que usava document.structure.extract)
por um structurer especializado em layout, retornando regiões classificadas
(text_clean, table, formula, embedded_image, code_block, etc.).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import fitz

from backend.tools.logger import logger
from backend.tools.region_extractor import Region, extract_regions
from backend.tools.structurer import BaseStructurer
from backend.tools.toolbox_layout_client import ToolboxLayoutClient

# Mapeamento dos tipos de layout retornados pela Toolbox para os tipos de Region.
LAYOUT_TO_REGION_TYPE: dict[str, str] = {
    "text_clean": "text",
    "text_scanned": "text",
    "heading": "heading",
    "title": "heading",
    "embedded_image": "image",
    "table": "table",
    "formula": "formula",
    "code_block": "code",
    "list_block": "list",
    "callout_box": "callout",
    "caption": "caption",
    "page_header": "page_header",
    "page_footer": "page_footer",
    "footnote": "footnote",
    "checkbox": "checkbox",
    "unknown": "unknown",
}


class ToolboxLayoutStructurer(BaseStructurer):
    """Structurer que analisa layout via Toolbox (document.layout.analyze).

    Classifica regiões visuais em categorias semânticas. Mantém cache em
    memória por documento (análogo a ToolboxStructurer).
    """

    def __init__(
        self,
        *,
        client: ToolboxLayoutClient | None = None,
    ) -> None:
        self._client = client or ToolboxLayoutClient()
        self._doc_cache: dict[str, dict[str, Any]] = {}

    @property
    def name(self) -> str:
        return "ToolboxLayout"

    async def _fetch_layout(self, file_path: Path) -> dict[str, Any]:
        """Busca a análise de layout na Toolbox, com cache em memória."""
        path_str = str(file_path.resolve())

        if path_str in self._doc_cache:
            entry = self._doc_cache[path_str]
            if time.time() - entry["time"] < 300:
                return entry["data"]
            del self._doc_cache[path_str]

        result = await self._client.analyze(file_path=file_path, language="pt-BR")

        self._doc_cache[path_str] = {"data": result, "time": time.time()}
        return result

    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        """Extrai regiões de layout de uma página via Toolbox.

        Fallback para PyMuPDF se a Toolbox estiver indisponível.
        """
        page_index = getattr(page, "number", 0)
        page_num = int(page_index or 0) + 1
        parent = page.parent

        try:
            if parent is None or not getattr(parent, "name", None):
                raise RuntimeError(
                    "Página sem documento pai para processamento Toolbox"
                )
            import asyncio

            result = asyncio.run(self._fetch_layout(Path(parent.name)))
            return self._layout_to_regions(result, page_num, page)
        except Exception as e:
            logger.warning(
                "ToolboxLayout falhou na pagina {} ({}), fallback PyMuPDF",
                page_num,
                e,
            )
            return extract_regions(page)

    def _layout_to_regions(
        self,
        result: dict[str, Any],
        page_num: int,
        fitz_page: fitz.Page,
    ) -> list[Region]:
        """Converte a resposta de document.layout.analyze em lista de Region."""
        regions: list[Region] = []
        page_w = fitz_page.rect.width
        page_h = fitz_page.rect.height

        document = result.get("document", {})
        pages = document.get("pages", [])

        if isinstance(pages, dict):
            pages = list(pages.values())

        # Encontra a página alvo
        target_page: dict[str, Any] | None = None
        for p in pages:
            if p.get("page_number") == page_num:
                target_page = p
                break

        if target_page is None:
            regions.append(
                Region(
                    bbox=(0, 0, page_w, page_h),
                    type="unknown",
                    text="",
                    image_bytes=None,
                    confidence=0.0,
                    page_num=page_num,
                    metadata={"toolbox_layout_empty": True, "source": "toolbox-layout"},
                )
            )
            return regions

        for raw_region in target_page.get("regions", []):
            region = self._raw_region_to_region(raw_region, page_num)
            if region:
                regions.append(region)

        if not regions:
            regions.append(
                Region(
                    bbox=(0, 0, page_w, page_h),
                    type="unknown",
                    text="",
                    image_bytes=None,
                    confidence=0.0,
                    page_num=page_num,
                    metadata={"toolbox_layout_empty": True, "source": "toolbox-layout"},
                )
            )

        regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
        return regions

    def _raw_region_to_region(
        self,
        raw: dict[str, Any],
        page_num: int,
    ) -> Region | None:
        """Converte uma região do JSON de layout em Region."""
        bbox_raw = raw.get("bbox", [])
        if not bbox_raw or len(bbox_raw) != 4:
            return None

        bbox = (float(bbox_raw[0]), float(bbox_raw[1]),
                float(bbox_raw[2]), float(bbox_raw[3]))

        layout_type = raw.get("type", "unknown")
        region_type = LAYOUT_TO_REGION_TYPE.get(layout_type, "unknown")
        text = raw.get("text", "") or ""
        confidence = float(raw.get("confidence", 0.8))

        return Region(
            bbox=bbox,
            type=region_type,
            text=text,
            image_bytes=None,
            confidence=confidence,
            page_num=page_num,
            metadata={
                "layout_type": layout_type,
                "label": raw.get("label", ""),
                "source": "toolbox-layout",
            },
        )


__all__ = ["ToolboxLayoutStructurer", "LAYOUT_TO_REGION_TYPE"]