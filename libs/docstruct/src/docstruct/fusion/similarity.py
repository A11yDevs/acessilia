"""Similartidade e geometria do fusor (portados de tree_differ_v2.py).

Bboxes normalizados ao quadrado unitário (0..1). Funções puras.
"""
from __future__ import annotations

import difflib
import re
from typing import Any, Optional, Sequence

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


def ordered_box(left: float, top: float, right: float, bottom: float) -> Box:
    """The box with its edges in order: ``left <= right`` and ``top <= bottom``."""
    return (min(left, right), min(top, bottom), max(left, right), max(top, bottom))


def pair_block(
    box: Optional[Box],
    text: str,
    candidate_boxes: Sequence[Optional[Box]],
    candidate_texts: Sequence[Any],
    used: set[int],
    *,
    min_iou: float,
    min_text_ratio: float,
) -> Optional[int]:
    """Index of the candidate block that matches a block with ``box`` and ``text``.

    The free candidate (not in ``used``) with the largest IoU wins when it
    reaches ``min_iou``; otherwise the free candidate whose text, whitespace
    folded, is most similar (``sim``) wins when it reaches ``min_text_ratio``.
    Ties go to the later candidate. ``candidate_boxes`` may be shorter than
    ``candidate_texts`` (empty when ``box`` is ``None``); a ``None`` entry
    has no box.

    Greedy: each block takes its best free candidate in the caller's order,
    while Dr.DocBench uses a global (Hungarian) assignment. The two can differ
    only when blocks compete for the same candidate, which is rare above the
    thresholds.
    """
    if box is not None:
        box = ordered_box(*box)
        scored = [
            (iou(box, other), index)
            for index, other in enumerate(candidate_boxes)
            if index not in used and other is not None
        ]
        best = max(scored, default=(0.0, None))
        if best[0] >= min_iou:
            return best[1]
    text = " ".join(text.split())
    if not text:
        return None
    scored_text = [
        (sim(text, " ".join(str(candidate).split())), index)
        for index, candidate in enumerate(candidate_texts)
        if index not in used and candidate
    ]
    best_text = max(scored_text, default=(0.0, None))
    return best_text[1] if best_text[0] >= min_text_ratio else None


def _comparison_text(text: str) -> str:
    # A word broken at a line end is OCR formatting; punctuation inside a
    # number/expression is content. Keep decimal points, signs and operators.
    text = re.sub(r"(?<=[^\W\d_])-[ \t]*\r?\n[ \t]*(?=[^\W\d_])", "", text)
    return re.sub(r"\s+", "", text.casefold().replace("\u00ad", ""))


def swallows(d_text: str, other_texts: list[str], n: int = 25) -> bool:
    """True se ``d_text`` também contém material de >= 1 outro bloco.
    Normaliza espaços e hifenização de fim de linha sem apagar pontuação
    que distingue números e expressões. O texto emitido não é modificado."""
    nd = _comparison_text(d_text)
    if len(nd) < n:
        return False
    for t in other_texts:
        nt = _comparison_text(t)
        if len(nt) < n:
            continue
        if nt in nd:
            return True
        step = max(n, (len(nt) - n) // 4 or 1)
        probes = {nt[k:k + n] for k in range(0, len(nt) - n + 1, step)}
        threshold = 2 if len(probes) >= 2 else 1
        if sum(p in nd for p in probes) >= threshold:
            return True
    return False


def is_duplicate(text: str, other_texts: list[str], min_len: int = 20) -> bool:
    """True when the full normalized text is contained in another emitted block.

    Preserve numeric punctuation; partial matching probes cannot establish
    that all content, including a changed value, is already represented.
    """
    normalized = _comparison_text(text)
    return len(normalized) >= min_len and any(
        normalized in _comparison_text(other) for other in other_texts
    )


# Página/número: token curto numérico/romano, com colchetes/traves/dots opcionais.
PAGENUM_RE = re.compile(
    r"^[\W_]*(?:page\s*)?(\d{1,4}|[ivxlcdm]{1,7})[\W_]*$", re.IGNORECASE
)
CJK_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]")
WORD_RE = re.compile(
    r"^[\W_]*(?:[A-Za-z\u00C0-\u024F]+(?:['\u2019\-][A-Za-z\u00C0-\u024F]+)*"
    r"|\d+(?:[.,:/]\d+)*)[\W_]*$"
)
