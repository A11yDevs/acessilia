"""Normalized Levenshtein edit distance for text scoring."""

from __future__ import annotations

MISSING = 1.0  # score when either side is empty and the other is not


def levenshtein(a: str, b: str) -> int:
    """Classic O(len(a)*len(b)) Levenshtein distance with two rows."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i]
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr.append(min(
                prev[j] + 1,        # deletion
                curr[j - 1] + 1,    # insertion
                prev[j - 1] + cost, # substitution
            ))
        prev = curr
    return prev[-1]


def normalized_levenshtein(a: str, b: str) -> float:
    """Levenshtein distance normalized to [0, 1]; 0 = identical."""
    if not a and not b:
        return 0.0
    if not a or not b:
        return 1.0
    max_len = max(len(a), len(b))
    return levenshtein(a, b) / max_len


def text_ed(pred: str, gt: str) -> float:
    """Text Edit Distance score: normalized Levenshtein, 0 (best)–1 (worst).

    Empty GT with non-empty prediction scores as full miss (1.0).
    """
    return normalized_levenshtein(pred.strip(), gt.strip())


__all__ = ["levenshtein", "normalized_levenshtein", "text_ed", "MISSING"]
