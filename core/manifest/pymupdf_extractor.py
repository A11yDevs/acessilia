from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Any

import fitz

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

                blocks = page.get_text("blocks")
                for block_idx, block in enumerate(blocks):
                    x0, y0, x1, y1, text, _, block_type = block
                    if block_type == 1 and not self.include_images:
                        continue

                    label = "picture" if block_type == 1 else "paragraph"
                    cleaned_text = text.strip() if isinstance(text, str) else ""
                    charspan = (0, len(cleaned_text)) if cleaned_text else None
                    bbox = SimpleNamespace(
                        l=float(x0),
                        t=float(y0),
                        r=float(x1),
                        b=float(y1),
                        coord_origin=SimpleNamespace(value="TOPLEFT"),
                    )
                    prov = SimpleNamespace(page_no=page_idx, bbox=bbox, charspan=charspan)
                    item = SimpleNamespace(
                        label=SimpleNamespace(value=label),
                        text=cleaned_text,
                        level=1,
                        prov=[prov],
                        self_ref=f"#/pages/{page_idx}/blocks/{block_idx}",
                        parent=SimpleNamespace(cref="#/body"),
                        content_layer=SimpleNamespace(value="body"),
                    )
                    items.append((item, 1))

        return _PseudoDocument(items=items, pages=pages)
