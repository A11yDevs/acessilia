"""acessilia-metrics — reusable document-parsing evaluation metrics.

Implements the Dr.DocBench EvalAI scoring contract as a domain-agnostic
Python package for benchmarking models and agents:

- ``text_ed`` — normalized Levenshtein distance over text (0–1, lower better)
- ``reading_order`` — (1 - normalized edit distance) × 100 (higher better)
- ``teds`` — tree-edit-distance similarity for HTML tables (0–100)
- ``cdm`` — CDM F1 for LaTeX display formulas (0–100)
- ``overall`` — page aggregate: mean of available components × 100,
  non-scorable pages excluded
"""

from .text_ed import normalized_levenshtein, text_ed
from .reading_order import reading_order_score
from .teds import teds_score
from .cdm import cdm_score
from .overall import overall_score, PageScores

__version__ = "0.1.0"

__all__ = [
    "text_ed",
    "normalized_levenshtein",
    "reading_order_score",
    "teds_score",
    "cdm_score",
    "overall_score",
    "PageScores",
]
