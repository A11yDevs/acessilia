"""Conversão entre o modelo canônico e os tipos internos do fusor."""
from __future__ import annotations

import re
from typing import Optional

from docstruct.fusion.similarity import PAGENUM_RE
from docstruct.fusion.types import DiffBlock
from docstruct.types import BBox, CanonicalBlock

TABLE_RE = re.compile(r"<table", re.IGNORECASE)
FORMULA_RE = re.compile(r"\$\$")


def normalize_bbox(
    bbox: BBox | None,
    page_size: tuple[float, float] | None = None,
    coord_origin: str = "",
) -> Optional[BBox]:
    """Normaliza um bbox para o quadrado unitário (0..1).

    ``coord_origin`` começando com "BOTTOM" (convenção PyMuPDF/Docling)
    faz o flip vertical antes da normalização.
    """
    if not bbox or not page_size or not all(page_size):
        return None
    w, h = float(page_size[0]), float(page_size[1])
    if w <= 0 or h <= 0:
        return None
    l, t, r, b = (float(v) for v in bbox)
    if coord_origin.upper().startswith("BOTTOM"):
        t, b = h - t, h - b
    y0, y1 = sorted((t / h, b / h))
    x0, x1 = sorted((l / w, r / w))
    return (max(0.0, x0), max(0.0, y0), min(1.0, x1), min(1.0, y1))


def classify_kind(type_: str, md: str) -> str:
    """Classifica o bloco: table / formula / heading / text (porta de load_blocks)."""
    t = (type_ or "unknown").lower()
    if t == "table" or TABLE_RE.search(md):
        return "table"
    if t == "formula" or FORMULA_RE.search(md):
        return "formula"
    if t in ("heading", "title", "section_header"):
        return "heading"
    return "text"


def block_to_diff(b: CanonicalBlock) -> DiffBlock:
    """CanonicalBlock → DiffBlock (bbox normalizado se houver page_size no metadata)."""
    md = (b.metadata.get("markdown") or b.text or "").strip()
    kind = classify_kind(b.type, md)
    box = None
    if b.bbox is not None:
        page_size = b.metadata.get("page_size")
        origin = b.metadata.get("coord_origin") or ""
        already_unit = all(0.0 <= v <= 1.0 for v in b.bbox)
        if isinstance(page_size, (tuple, list)) and len(page_size) == 2 and not already_unit:
            # bbox em coordenadas de página → normaliza (com flip se BOTTOM*)
            box = normalize_bbox(
                b.bbox, (float(page_size[0]), float(page_size[1])), origin
            )
        elif already_unit:
            # bbox já normalizado: aplica apenas o flip vertical se BOTTOM*
            box = normalize_bbox(b.bbox, (1.0, 1.0), origin)
        else:
            box = None
    text = b.text or md
    if kind == "table" or kind == "formula" or PAGENUM_RE.match(md):
        pass  # kind já decidido
    return DiffBlock(md=md, kind=kind, box=box, text=text, type=(b.type or "unknown").lower())
