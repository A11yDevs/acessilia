"""CDM — Character Detection Matching F1 for LaTeX display formulas (0–100).

Token-based F1 over normalized LaTeX token sequences, following the CDM
principle: extract and match mathematical tokens between prediction and
ground truth.
"""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(
    r"\\[a-zA-Z]+|\\.|[a-zA-Z]|\d|[^\s\\a-zA-Z\d]"  # commands, symbols, chars
)

_SUBSUP = re.compile(r"[{}]")


def _normalize(latex: str) -> str:
    latex = latex.strip()
    latex = re.sub(r"\$\$", "", latex)
    latex = re.sub(r"\\left|\\right", "", latex)
    # Replace braces with spaces (token boundary) instead of deleting them.
    latex = _SUBSUP.sub(" ", latex)
    return latex


def _tokens(latex: str) -> list[str]:
    return _TOKEN_RE.findall(_normalize(latex))


def cdm_score(pred_latex: str, gt_latex: str) -> float | None:
    """CDM F1 between two LaTeX formulas, 0–100 (higher better).

    Returns None when both are empty (non-scorable).
    """
    pred_tokens = _tokens(pred_latex or "")
    gt_tokens = _tokens(gt_latex or "")
    if not pred_tokens and not gt_tokens:
        return None
    if not pred_tokens or not gt_tokens:
        return 0.0

    # Multiset (bag) matching of tokens.
    from collections import Counter

    pred_counter, gt_counter = Counter(pred_tokens), Counter(gt_tokens)
    matched = sum((pred_counter & gt_counter).values())

    precision = matched / len(pred_tokens)
    recall = matched / len(gt_tokens)
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall) * 100.0


__all__ = ["cdm_score", "_tokens"]
