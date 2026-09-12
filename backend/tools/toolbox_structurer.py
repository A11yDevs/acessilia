from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import fitz

from backend.config.settings import settings
from backend.tools.region_extractor import Region, extract_regions
from backend.tools.structurer import BaseStructurer
from backend.tools.toolbox_client import ToolboxClient
from backend.tools.logger import logger


class ToolboxStructurer(BaseStructurer):
    """Structurer que consome a Acessilia Toolbox para extração remota.

    Implementa BaseStructurer.extract_page_regions(page) usando a resposta
    de document.structure.extract da Toolbox. Mantém cache em memória por
    documento (análogo a DoclingStructurer._doc_cache).
    """

    def __init__(
        self,
        *,
        client: ToolboxClient | None = None,
        enable_ocr: bool = True,
    ) -> None:
        self._client = client or ToolboxClient()
        self._doc_cache: dict[str, dict[str, Any]] = {}
        self.enable_ocr = enable_ocr

    @property
    def name(self) -> str:
        return "Toolbox"

    async def _fetch_document_structure(self, file_path: Path) -> dict[str, Any]:
        """Busca a estrutura do documento na Toolbox, com cache em memória."""
        path_str = str(file_path.resolve())

        if path_str in self._doc_cache:
            entry = self._doc_cache[path_str]
            if time.time() - entry["time"] < 300:
                return entry["data"]
            del self._doc_cache[path_str]

        result = await self._client.extract_structure(
            file_path=file_path,
            language="pt-BR",
        )

        self._doc_cache[path_str] = {"data": result, "time": time.time()}
        return result

    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        """Extrai regiões de uma página usando a Toolbox.

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

            result = asyncio.run(
                self._fetch_document_structure(Path(parent.name))
            )
            return self._toolbox_result_to_regions(result, page_num, page)
        except Exception as e:
            logger.warning(
                "Toolbox falhou na pagina {} ({}), fallback PyMuPDF",
                page_num,
                e,
            )
            return extract_regions(page)

    def _toolbox_result_to_regions(
        self,
        result: dict[str, Any],
        page_num: int,
        fitz_page: fitz.Page,
    ) -> list[Region]:
        """Converte a resposta da Toolbox em lista de Region."""
        regions: list[Region] = []
        page_w = fitz_page.rect.width
        page_h = fitz_page.rect.height

        document = result.get("document", {})
        elements = document.get("elements", [])

        page_elements = [el for el in elements if el.get("page_number") == page_num]

        for el in page_elements:
            region = self._element_to_region(el, page_num)
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
                    metadata={"toolbox_empty": True},
                )
            )

        regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
        return regions

    def _element_to_region(
        self, element: dict[str, Any], page_num: int
    ) -> Region | None:
        """Converte um elemento do JSON da Toolbox em Region."""
        bbox = self._parse_bbox(element)
        if bbox is None:
            return None

        element_type = element.get("type", "unknown")
        text = element.get("text", "") or ""
        confidence = element.get("confidence", 0.8)

        provenance = element.get("provenance", [])
        prov_page = page_num
        if provenance:
            prov_page = provenance[0].get("page_number", page_num)

        return Region(
            bbox=bbox,
            type=element_type,
            text=text,
            image_bytes=None,
            confidence=float(confidence),
            page_num=prov_page,
            metadata={
                "source": "toolbox",
                "toolbox_type": element_type,
                "toolbox_label": element.get("raw_label", ""),
            },
        )

    @staticmethod
    def _parse_bbox(element: dict[str, Any]) -> tuple[float, float, float, float] | None:
        """Extrai bbox do elemento no formato da Toolbox."""
        provenance = element.get("provenance", [])
        for prov in provenance:
            bbox_data = prov.get("bbox")
            if bbox_data:
                try:
                    return (
                        float(bbox_data.get("left", 0)),
                        float(bbox_data.get("top", 0)),
                        float(bbox_data.get("right", 0)),
                        float(bbox_data.get("bottom", 0)),
                    )
                except (TypeError, ValueError):
                    pass

        # Fallback: bbox direto no elemento
        bbox_data = element.get("bbox")
        if bbox_data and isinstance(bbox_data, dict):
            try:
                return (
                    float(bbox_data.get("left", 0)),
                    float(bbox_data.get("top", 0)),
                    float(bbox_data.get("right", 0)),
                    float(bbox_data.get("bottom", 0)),
                )
            except (TypeError, ValueError):
                pass

        return None