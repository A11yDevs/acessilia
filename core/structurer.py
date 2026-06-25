from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import fitz

from config.settings import settings
from core.region_extractor import Region, crop_region_to_image, extract_regions
from core.utils.logger import logger

DOCLING_AVAILABLE = False
try:
    from docling.document_converter import DocumentConverter

    DOCLING_AVAILABLE = True
except ImportError:
    pass


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


class DoclingStructurer(BaseStructurer):
    def __init__(self) -> None:
        self._converter: Any = None
        self._doc_cache: dict[str, Any] = {}

    def _get_converter(self) -> Any:
        if self._converter is None:
            self._converter = DocumentConverter()
        return self._converter

    def _process_document(self, file_path: Path) -> Any:
        path_str = str(file_path.resolve())

        if path_str in self._doc_cache:
            cache_entry = self._doc_cache[path_str]
            if time.time() - cache_entry["time"] < 300:
                return cache_entry["doc"]
            del self._doc_cache[path_str]

        start = time.time()
        converter = self._get_converter()
        result = converter.convert(path_str)
        docling_doc = result.document
        elapsed = time.time() - start

        logger.info("Docling processou {} em {:.1f}s", file_path.name, elapsed)

        self._doc_cache[path_str] = {"doc": docling_doc, "time": time.time()}
        return docling_doc

    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        page_num = page.number + 1

        try:
            docling_doc = self._process_document(Path(page.parent.name))
            return self._docling_page_to_regions(docling_doc, page_num, page)
        except Exception as e:
            logger.warning(
                "Docling falhou na pagina {} ({}), fallback PyMuPDF",
                page_num,
                e,
            )
            return extract_regions(page)

    def _docling_page_to_regions(
        self,
        docling_doc: Any,
        page_num: int,
        fitz_page: fitz.Page,
    ) -> list[Region]:
        regions: list[Region] = []
        page_w = fitz_page.rect.width
        page_h = fitz_page.rect.height

        try:
            page_items = [
                item for item, level in docling_doc.iterate_items(page_no=page_num)
            ]
        except Exception:
            page_items = []

        for item in page_items:
            region = self._docling_item_to_region(item, page_num)
            if region:
                left, top, right, bottom = region.bbox
                if top > bottom:
                    top, bottom = page_h - top, page_h - bottom
                    region.bbox = (left, top, right, bottom)
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
                    metadata={"docling_empty": True},
                )
            )

        regions.sort(key=lambda r: (r.bbox[1], r.bbox[0]))
        return regions

    def _docling_item_to_region(self, item: Any, page_num: int) -> Region | None:
        bbox = self._docling_bbox(item)
        if bbox is None:
            return None

        item_type = self._docling_label(item)
        text = self._docling_text(item)

        return Region(
            bbox=bbox,
            type=item_type,
            text=text,
            image_bytes=None,
            confidence=0.8,
            page_num=page_num,
            metadata={
                "source": "docling",
                "docling_type": item_type,
                "docling_label": str(getattr(item, "label", "")),
            },
        )

    def _docling_bbox(self, item: Any) -> tuple[float, float, float, float] | None:
        prov = getattr(item, "prov", []) or []
        for p in prov:
            bbox = getattr(p, "bbox", None)
            if bbox:
                try:
                    return (float(bbox.l), float(bbox.t), float(bbox.r), float(bbox.b))
                except Exception:
                    try:
                        return (
                            float(bbox[0]),
                            float(bbox[1]),
                            float(bbox[2]),
                            float(bbox[3]),
                        )
                    except Exception:
                        pass

        obj = getattr(item, "bbox", None)
        if obj:
            try:
                return (float(obj.l), float(obj.t), float(obj.r), float(obj.b))
            except Exception:
                try:
                    return (float(obj[0]), float(obj[1]), float(obj[2]), float(obj[3]))
                except Exception:
                    pass
        return None

    def _docling_label(self, item: Any) -> str:
        label = str(getattr(item, "label", "")).lower()
        if (
            "figure" in label
            or "picture" in label
            or "image" in label
            or "photo" in label
        ):
            return "image"
        if "table" in label:
            return "table"
        if "formula" in label or "equation" in label or "math" in label:
            return "formula"
        if "heading" in label or "title" in label or "section" in label:
            return "heading"
        if "list" in label or "enumeration" in label:
            return "list"
        if "code" in label or "source" in label or "terminal" in label:
            return "code"
        if (
            "note" in label
            or "callout" in label
            or "sidebar" in label
            or "quote" in label
        ):
            return "callout"
        if "caption" in label or "legend" in label:
            return "caption"
        if "paragraph" in label or "text" in label or "body" in label:
            return "text"
        return "text"

    def _docling_text(self, item: Any) -> str:
        text = getattr(item, "text", "") or getattr(item, "caption", "") or ""
        if not text:
            for attr in ("markdown", "raw_text", "content"):
                val = getattr(item, attr, None)
                if val:
                    text = str(val)
                    break
        return str(text).strip()


def get_structurer() -> BaseStructurer:
    mode = settings.structurer.lower()

    if mode == "docling":
        if not DOCLING_AVAILABLE:
            logger.warning(
                "STRUCTURER=docling mas docling nao instalado. "
                "Execute: pip install docling. Usando PyMuPDF.",
            )
            return PyMuPDFStructurer()
        logger.info("Usando structurer: Docling (com fallback PyMuPDF)")
        return DoclingStructurer()

    logger.info("Usando structurer: PyMuPDF")
    return PyMuPDFStructurer()
