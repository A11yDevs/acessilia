"""Similartidade e geometria do fusor (portados de tree_differ_v2.py).

Bboxes normalizados ao quadrado unitário (0..1). Funções puras.
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

Box = tuple[float, float, float, float]


def area(box: Optional[Box]) -> float:
    if not box:
        return 0.0
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def iou(a: Optional[Box], b: Optional[Box]) -> float:
    if a is None or b is None:
        return 0.0
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def contain_frac(inner: Optional[Box], outer: Optional[Box]) -> float:
    """Fração da área de ``inner`` contida em ``outer``."""
    if inner is None or outer is None or area(inner) == 0:
        return 0.0
    ix = max(0.0, min(inner[2], outer[2]) - max(inner[0], outer[0]))
    iy = max(0.0, min(inner[3], outer[3]) - max(inner[1], outer[1]))
    return ix * iy / area(inner)


def union_box(boxes) -> Optional[Box]:
    boxes = [b for b in boxes if b]
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def center(box: Optional[Box]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2, (box[1] + box[3]) / 2) if box else (0.5, 0.5)


def sim(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def swallows(d_text: str, other_texts: list[str], n: int = 30) -> bool:
    """True se ``d_text`` também contém material de >= 1 outro bloco (probes
    de n chars): o provider leu através de colunas / mesclou parágrafos
    vizinhos. Porta fiel de ``swallows()``."""
    hits = 0
    for t in other_texts:
        if len(t) < n:
            continue
        probes = {t[k:k + n] for k in range(0, len(t) - n, max(n, (len(t) - n) // 4 or 1))}
        if sum(p in d_text for p in probes) >= 2:
            hits += 1
            if hits >= 1:
                return True
    return False


# Página/número: token curto numérico/romano, com colchetes/traves/dots opcionais.
PAGENUM_RE = re.compile(
    r"^[\W_]*(?:page\s*)?(\d{1,4}|[ivxlcdm]{1,7})[\W_]*$", re.IGNORECASE
)
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
WORD_RE = re.compile(
    r"^[\W_]*(?:[A-Za-z\u00C0-\u024F]+(?:['\u2019\-][A-Za-z\u00C0-\u024F]+)*"
    r"|\d+(?:[.,:/]\d+)*)[\W_]*$"
)
