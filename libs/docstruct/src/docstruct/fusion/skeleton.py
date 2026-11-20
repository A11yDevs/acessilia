"""Reading-order reconstruction following a reference provider's block skeleton."""
from __future__ import annotations

from collections.abc import Mapping

#: Minimum share of elements that must pair with the skeleton to trust its order.
DEFAULT_MIN_SKELETON_MATCH = 0.5


def skeleton_reading_order(
    count: int,
    matched_positions: Mapping[int, int],
    *,
    min_match_ratio: float = DEFAULT_MIN_SKELETON_MATCH,
) -> list[int] | None:
    """Order ``0..count-1`` following the matched positions in a reference skeleton.

    ``matched_positions`` maps each paired source index (in ``0..count-1``) to
    its 0-based position in the reference sequence. Paired items take their
    skeleton order; unpaired items stay immediately after the last paired item
    that preceded them (or before the first paired item when none preceded
    them), preserving their relative order.

    Returns ``None`` when ``count < 2`` or when fewer than ``min_match_ratio``
    of the items are paired.
    """
    valid = {
        index: position
        for index, position in matched_positions.items()
        if 0 <= index < count
    }
    if count < 2 or len(valid) < min_match_ratio * count:
        return None
    ranked: list[tuple[float, int, int]] = []
    last = -1.0
    for index in range(count):
        if index in valid:
            last = float(valid[index])
            ranked.append((last, 0, index))
        else:
            ranked.append((last, 1, index))
    return [index for _, _, index in sorted(ranked)]


__all__ = [
    "DEFAULT_MIN_SKELETON_MATCH",
    "skeleton_reading_order",
]
