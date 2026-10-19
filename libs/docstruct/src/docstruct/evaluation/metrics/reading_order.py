"""Reading-order scoring: (1 - normalized sequence edit distance) × 100."""

from __future__ import annotations

from .text_ed import normalized_levenshtein


def reading_order_score(pred_blocks: list[str], gt_blocks: list[str]) -> float | None:
    """Compare block sequences in reading order.

    Args:
        pred_blocks: predicted block texts in the order they appear.
        gt_blocks: ground-truth block texts in reading order.

    Returns:
        Score 0–100 (higher better), or None when either side has no blocks
        (non-scorable).
    """
    if not pred_blocks and not gt_blocks:
        return None
    if not pred_blocks or not gt_blocks:
        return 0.0

    # Compare joined sequences — block-level edit distance approximated by
    # normalized Levenshtein over the joined, delimiter-separated sequence.
    pred_seq = "\n".join(b.strip() for b in pred_blocks)
    gt_seq = "\n".join(b.strip() for b in gt_blocks)
    dist = normalized_levenshtein(pred_seq, gt_seq)
    return (1.0 - dist) * 100.0


__all__ = ["reading_order_score"]
