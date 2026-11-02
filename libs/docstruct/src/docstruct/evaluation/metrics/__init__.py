"""Document-parsing metrics, dataset-agnostic and dependency-free.

- ``text_ed`` — normalized Levenshtein distance over text (0–1, lower better)
- ``reading_order_score`` — (1 - normalized edit distance) × 100 (higher better)
- ``teds_score`` — tree-edit-distance similarity for HTML tables (0–100)
- ``cdm_score`` — token F1 for LaTeX display formulas (0–100)
- ``overall_score`` — page aggregate: mean of available components on 0–100,
  non-scorable pages excluded

These are local approximations for tracking deltas, not the official
evaluators of any benchmark.
"""

from docstruct.evaluation.metrics.cdm import cdm_score
from docstruct.evaluation.metrics.overall import PageScores, overall_score
from docstruct.evaluation.metrics.reading_order import reading_order_score
from docstruct.evaluation.metrics.teds import teds_score
from docstruct.evaluation.metrics.text_ed import levenshtein, normalized_levenshtein, text_ed

__all__ = [
    "PageScores",
    "cdm_score",
    "levenshtein",
    "normalized_levenshtein",
    "overall_score",
    "reading_order_score",
    "teds_score",
    "text_ed",
]
