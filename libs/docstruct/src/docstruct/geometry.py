"""Geometria de bbox e fingerprints de conteúdo.

Migrado de: backend/tools/text_tools.py (content_fingerprint, overlaps_clean)
e backend/tools/region_extractor.py (_merge_bboxes).

Funções puras sobre tuplas (x0, y0, x1, y1). Nenhuma depende de PyMuPDF.
"""
from __future__ import annotations

from docstruct.types import BBox


def content_fingerprint(text: str) -> int:
    """Fingerprint estável de texto: lowercase + colapso de whitespace."""
    return hash(" ".join(text.lower().split()))


def overlaps_clean(
    bbox: BBox,
    clean_bboxes: list[BBox],
    threshold: float = 0.3,
) -> bool:
    """True se ``bbox`` intersecta algum bbox limpo acima do ``threshold``
    (fração da área do bbox coberta pela interseção)."""
    x0, y0, x1, y1 = bbox
    area = max((x1 - x0) * (y1 - y0), 1)
    for cb in clean_bboxes:
        ox0, oy0 = max(x0, cb[0]), max(y0, cb[1])
        ox1, oy1 = min(x1, cb[2]), min(y1, cb[3])
        if ox0 < ox1 and oy0 < oy1:
            if ((ox1 - ox0) * (oy1 - oy0)) / area >= threshold:
                return True
    return False


def merge_bboxes(bboxes: list[BBox], vertical_gap: float = 5.0) -> list[BBox]:
    """Agrupa bboxes verticalmente próximos em faixas (bands).

    Ordena por (y0, x0) e funde bboxes cujo y0 não ultrapassa o y1 da faixa
    atual + ``vertical_gap``. Comportamento idêntico ao ``_merge_bboxes``
    original do region_extractor (gap padrão de 5px).
    """
    if not bboxes:
        return []
    sorted_b = sorted(bboxes, key=lambda b: (b[1], b[0]))
    merged: list[list[float]] = [list(sorted_b[0])]
    for b in sorted_b[1:]:
        if b[1] <= merged[-1][3] + vertical_gap:
            merged[-1][2] = max(merged[-1][2], b[2])
            merged[-1][3] = max(merged[-1][3], b[3])
        else:
            merged.append(list(b))
    return [tuple(b) for b in merged]


def union(a: BBox, b: BBox) -> BBox:
    """Menor bbox que contém ambos."""
    return (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))


def intersection_area(a: BBox, b: BBox) -> float:
    """Área de interseção entre dois bboxes (0 se não intersectam)."""
    ox0, oy0 = max(a[0], b[0]), max(a[1], b[1])
    ox1, oy1 = min(a[2], b[2]), min(a[3], b[3])
    if ox0 >= ox1 or oy0 >= oy1:
        return 0.0
    return (ox1 - ox0) * (oy1 - oy0)
