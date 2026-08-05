from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import fitz

from backend.pipeline.semantic_rules import classify_text_block
from core.manifest.docling_extractor import DoclingExtraction


class _PseudoDocument:
    def __init__(self, items: list[tuple[Any, int]], pages: dict[int, Any]) -> None:
        self._items = items
        self.pages = pages

    def iterate_items(self, **_: Any):
        return iter(self._items)

    def num_pages(self) -> int:
        return len(self.pages)


class PyMuPDFManifestExtractor:
    """Extrator estrutural simplificado para pipeline PDDL sem Docling."""

    def __init__(self, *, include_images: bool = True) -> None:
        self.include_images = include_images

    def extract(self, source_path: Path) -> DoclingExtraction:
        source_path = source_path.resolve()
        if not source_path.is_file():
            raise FileNotFoundError(f"Documento não encontrado: {source_path}")

        started_at = datetime.now(timezone.utc)
        started_clock = perf_counter()
        document = self._build_document(source_path)
        duration_ms = round((perf_counter() - started_clock) * 1000)
        completed_at = datetime.now(timezone.utc)

        return DoclingExtraction(
            document=document,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            version=f"pymupdf-{fitz.VersionBind}",
            configuration={
                "extractor": "pymupdf",
                "include_images": self.include_images,
            },
        )

    def _build_document(self, source_path: Path) -> _PseudoDocument:
        items: list[tuple[Any, int]] = []
        pages: dict[int, Any] = {}

        # Item raiz para preservar parentesco no manifesto.
        root = SimpleNamespace(
            label=None,
            name="body",
            self_ref="#/body",
            parent=None,
        )
        items.append((root, 0))

        with fitz.open(source_path) as doc:
            for page_idx, page in enumerate(doc, start=1):
                pages[page_idx] = SimpleNamespace(
                    size=SimpleNamespace(width=float(page.rect.width), height=float(page.rect.height))
                )

                semantic_blocks, median_font_size = self._extract_semantic_blocks(page)
                for block_idx, block in enumerate(semantic_blocks):
                    if block["kind"] == "image" and not self.include_images:
                        continue

                    label = block["label"]
                    cleaned_text = block["text"]
                    charspan = (0, len(cleaned_text)) if cleaned_text else None
                    bbox = SimpleNamespace(
                        l=float(block["bbox"][0]),
                        t=float(block["bbox"][1]),
                        r=float(block["bbox"][2]),
                        b=float(block["bbox"][3]),
                        coord_origin=SimpleNamespace(value="TOPLEFT"),
                    )
                    prov = SimpleNamespace(page_no=page_idx, bbox=bbox, charspan=charspan)
                    item = SimpleNamespace(
                        label=SimpleNamespace(value=label),
                        text=cleaned_text,
                        level=block["level"],
                        prov=[prov],
                        self_ref=f"#/pages/{page_idx}/blocks/{block_idx}",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                        avg_font_size=block.get("avg_font_size", median_font_size),
                        is_bold=block.get("is_bold", False),
                    )
                    items.append((item, 1))

        return _PseudoDocument(items=items, pages=pages)

    def _extract_semantic_blocks(self, page: fitz.Page) -> tuple[list[dict[str, Any]], float]:
        page_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        blocks = page_dict.get("blocks", [])

        font_sizes: list[float] = []
        raw_text_blocks: list[dict[str, Any]] = []
        for block in blocks:
            if block.get("type") != 0:
                continue
            spans = self._collect_spans(block)
            if not spans:
                continue
            span_sizes = [float(span.get("size", 0.0)) for span in spans if span.get("size")]
            if span_sizes:
                font_sizes.extend(span_sizes)

            text = self._join_block_text(spans)
            if not text.strip():
                continue

            is_bold = any("bold" in str(span.get("font", "")).lower() for span in spans)
            is_monospace = any(
                key in str(span.get("font", "")).lower()
                for span in spans
                for key in ("mono", "courier", "consolas", "menlo")
            )
            avg_font_size = sum(span_sizes) / len(span_sizes) if span_sizes else 0.0
            line_count = len(block.get("lines", []))

            raw_text_blocks.append(
                {
                    "bbox": tuple(block.get("bbox", (0, 0, 0, 0))),
                    "text": text.strip(),
                    "avg_font_size": avg_font_size,
                    "line_count": line_count,
                    "is_bold": is_bold,
                    "is_monospace": is_monospace,
                }
            )

        median_font_size = self._median(font_sizes) if font_sizes else 10.0

        semantic_blocks: list[dict[str, Any]] = []
        text_block_index = 0
        for block in blocks:
            block_type = block.get("type")
            if block_type == 1:
                semantic_blocks.append(
                    {
                        "kind": "image",
                        "label": "picture",
                        "level": 1,
                        "text": "",
                        "bbox": tuple(block.get("bbox", (0, 0, 0, 0))),
                    }
                )
                continue

            if block_type != 0 or text_block_index >= len(raw_text_blocks):
                continue

            raw = raw_text_blocks[text_block_index]
            text_block_index += 1
            label, level = classify_text_block(
                text=raw["text"],
                current_blocks=len(semantic_blocks),
                avg_font_size=float(raw["avg_font_size"]),
                median_font_size=float(median_font_size),
                line_count=int(raw["line_count"]),
                is_bold=bool(raw["is_bold"]),
                is_monospace=bool(raw["is_monospace"]),
            )
            semantic_blocks.append(
                {
                    "kind": "text",
                    "label": label,
                    "level": level,
                    "text": raw["text"],
                    "bbox": raw["bbox"],
                    "avg_font_size": raw["avg_font_size"],
                    "is_bold": raw["is_bold"],
                }
            )

        return semantic_blocks, median_font_size

    def _collect_spans(self, block: dict[str, Any]) -> list[dict[str, Any]]:
        spans: list[dict[str, Any]] = []
        for line in block.get("lines", []):
            spans.extend(line.get("spans", []))
        return spans

    def _join_block_text(self, spans: list[dict[str, Any]]) -> str:
        texts = [str(span.get("text", "")) for span in spans]
        return "".join(texts)

    def _median(self, values: list[float]) -> float:
        sorted_values = sorted(values)
        mid = len(sorted_values) // 2
        if len(sorted_values) % 2 == 1:
            return sorted_values[mid]
        return (sorted_values[mid - 1] + sorted_values[mid]) / 2
