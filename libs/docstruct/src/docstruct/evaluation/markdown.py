"""Score one predicted markdown page against its ground truth.

Both sides use the benchmark markdown that ``docstruct.export.markdown``
emits: blocks separated by blank lines, tables as HTML ``<table>`` and display
formulas as ``$$...$$``. Port of ``scripts/drbench/eval_run.py``.
"""
from __future__ import annotations

import re
from collections.abc import Callable

from docstruct.evaluation.metrics import (
    PageScores,
    cdm_score,
    reading_order_score,
    teds_score,
    text_ed,
)
from docstruct.export.markdown import bare_latex

TABLE_RE = re.compile(r"<table.*?</table>", re.DOTALL | re.IGNORECASE)
DISPLAY_FORMULA_RE = re.compile(r"\$\$(.+?)\$\$", re.DOTALL)


def score_markdown_page(item_id: str, pred_md: str, gt_md: str) -> PageScores:
    """Text, reading order, TEDS and CDM of one page.

    Tables and formulas are paired by order of appearance; a component is
    non-scorable (``None``) when either side has none of that element.
    """
    return PageScores(
        item_id=item_id,
        text_ed=text_ed(pred_md, gt_md),
        reading_order=reading_order_score(_blocks(pred_md), _blocks(gt_md)),
        teds=_pairwise_mean(_tables(pred_md), _tables(gt_md), teds_score),
        cdm=_pairwise_mean(_formulas(pred_md), _formulas(gt_md), cdm_score),
    )


def _blocks(md: str) -> list[str]:
    return [b for b in md.split("\n\n") if b.strip()]


def _tables(md: str) -> list[str]:
    return [m.group(0) for m in TABLE_RE.finditer(md)]


def _formulas(md: str) -> list[str]:
    return [bare_latex(m.group(1)) for m in DISPLAY_FORMULA_RE.finditer(md)]


def _pairwise_mean(
    preds: list[str], gts: list[str], metric: Callable[[str, str], float | None]
) -> float | None:
    if not preds or not gts:
        return None
    valid = [v for v in (metric(p, g) for p, g in zip(preds, gts)) if v is not None]
    return sum(valid) / len(valid) if valid else None


__all__ = ["score_markdown_page"]
