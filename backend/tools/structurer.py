from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Any

import fitz

from backend.config.settings import settings
from backend.tools.code_tools import normalize_code_text
from backend.tools.region_extractor import Region, crop_region_to_image, extract_regions
from backend.tools.logger import logger

DOCLING_AVAILABLE = False
DocumentConverter: Any | None = None
try:
    from docling.document_converter import DocumentConverter

    DOCLING_AVAILABLE = True
except ImportError:
    pass


RAPIDOCR_MODEL_FILENAMES = {
    "PP-OCRv6_det_small.pth",
    "ch_ptocr_mobile_v2.0_cls_mobile.pth",
    "PP-OCRv6_rec_small.pth",
    "ppocrv6_dict.txt",
}


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
    def __init__(self, enable_ocr: bool = True) -> None:
        self._converter: Any = None
        self._doc_cache: dict[str, Any] = {}
        self.enable_ocr = enable_ocr

    def _get_converter(self) -> Any:
        if self._converter is None:
            if not DOCLING_AVAILABLE or DocumentConverter is None:
                raise RuntimeError("Docling não está disponível no ambiente atual.")
            from docling.datamodel.base_models import InputFormat
            from docling.datamodel.pipeline_options import (
                PdfPipelineOptions,
                RapidOcrOptions,
            )
            from docling.document_converter import PdfFormatOption

            _hydrate_rapidocr_models()
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = self.enable_ocr
            pipeline_options.ocr_options = RapidOcrOptions(backend="torch")
            self._converter = DocumentConverter(
                format_options={
                    InputFormat.PDF: PdfFormatOption(
                        pipeline_options=pipeline_options
                    ),
                }
            )
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
        _persist_rapidocr_models()
        elapsed = time.time() - start

        logger.info("Docling processou {} em {:.1f}s", file_path.name, elapsed)

        self._doc_cache[path_str] = {"doc": docling_doc, "time": time.time()}
        return docling_doc

    def extract_page_regions(self, page: fitz.Page) -> list[Region]:
        page_index = getattr(page, "number", 0)
        page_num = int(page_index or 0) + 1
        parent = page.parent

        try:
            if parent is None or not getattr(parent, "name", None):
                raise RuntimeError("Página sem documento pai para processamento Docling")
            docling_doc = self._process_document(Path(parent.name))
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
        if item_type == "code":
            text = normalize_code_text(text)

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
                "docling_label_kind": self._normalized_docling_label(item),
                "subtype": "callout" if item_type == "callout" else "",
            },
        )

    def _normalized_docling_label(self, item: Any) -> str:
        raw = str(getattr(item, "label", "")).strip().lower()
        raw = raw.removeprefix("docitemlabel.").removeprefix("grouplabel.")
        raw = raw.replace(" ", "_")
        return raw

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
            or "admonition" in label
            or "warning" in label
            or "caution" in label
            or "tip" in label
            or "important" in label
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


def _rapidocr_models_dir() -> Path | None:
    try:
        import rapidocr
    except ImportError:
        return None
    return Path(rapidocr.__file__).resolve().parent / "models"


def _hydrate_rapidocr_models() -> None:
    models_dir = _rapidocr_models_dir()
    cache_dir = settings.rapidocr_cache_dir
    if models_dir is None or not cache_dir.exists():
        return
    models_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in RAPIDOCR_MODEL_FILENAMES:
        source = cache_dir / name
        target = models_dir / name
        if not source.exists() or target.exists():
            continue
        shutil.copy2(source, target)
        copied += 1
    if copied:
        logger.info("RapidOCR: {} modelo(s) restaurado(s) do cache local", copied)


def _persist_rapidocr_models() -> None:
    models_dir = _rapidocr_models_dir()
    if models_dir is None or not models_dir.exists():
        return
    cache_dir = settings.rapidocr_cache_dir
    cache_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for name in RAPIDOCR_MODEL_FILENAMES:
        source = models_dir / name
        target = cache_dir / name
        if not source.exists():
            continue
        if target.exists() and target.stat().st_size == source.stat().st_size:
            continue
        shutil.copy2(source, target)
        copied += 1
    if copied:
        logger.info("RapidOCR: {} modelo(s) persistido(s) no cache local", copied)


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
