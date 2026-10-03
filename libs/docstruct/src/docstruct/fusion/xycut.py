"""Recursive XY-cut reading order for fused pages.

Geometry-only column ordering: split the page at vertical gutters (columns,
read left to right), handle full-width blocks (titles, wide tables) as section
breaks, and read each region top to bottom. No model, OCR or LLM is involved.

Ported from the reading-order study on multi-column official gazettes that
motivated this option (best method there: Kendall tau 0.837, ~0.1 ms/page).
Boxes follow the ``DiffBlock`` contract: unit square, TOPLEFT origin
(``x0, y0, x1, y1`` with ``y0 < y1``).
"""
from __future__ import annotations

from collections import Counter
from typing import Sequence, TypeVar

Box = tuple[float, float, float, float]
T = TypeVar("T")

# Minimum gutter between columns: 4 pt on an A4 page (595 pt wide), the value
# calibrated in the gazette study, expressed as a fraction of the page width.
GUTTER = 4.0 / 595.0
# A column narrower than this fraction of the region width is merged into its
# neighbour (captions, drop caps and marginal numbers are not columns).
MIN_COLUMN_FRAC = 0.12
# A block at least this wide (fraction of the region width) is a section break.
WIDE_FRAC = 0.60
MAX_DEPTH = 60


def _normalise(box: Sequence[float]) -> Box:
    x0, y0, x1, y1 = (float(v) for v in box)
    return (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def _columns(indices: list[int], boxes: list[Box], gutter: float) -> list[list[int]]:
    """Group blocks into columns separated by vertical gutters; merge spurious narrow ones."""
    ordered = sorted(indices, key=lambda i: boxes[i][0])
    groups: list[list[int]] = [[ordered[0]]]
    right = boxes[ordered[0]][2]
    for i in ordered[1:]:
        if boxes[i][0] > right + gutter:
            groups.append([i])
        else:
            groups[-1].append(i)
        right = max(right, boxes[i][2])

    def width(group: list[int]) -> float:
        return max(boxes[i][2] for i in group) - min(boxes[i][0] for i in group)

    total = max(boxes[i][2] for i in indices) - min(boxes[i][0] for i in indices)
    while len(groups) > 1:
        k = min(range(len(groups)), key=lambda j: width(groups[j]))
        if width(groups[k]) >= MIN_COLUMN_FRAC * total:
            break
        if k == 0:
            j = 1
        elif k == len(groups) - 1:
            j = k - 1
        else:
            gap_left = min(boxes[i][0] for i in groups[k]) - max(boxes[i][2] for i in groups[k - 1])
            gap_right = min(boxes[i][0] for i in groups[k + 1]) - max(boxes[i][2] for i in groups[k])
            j = k - 1 if gap_left <= gap_right else k + 1
        a, b = sorted((k, j))
        groups[a] = groups[a] + groups[b]
        del groups[b]
    return groups


def _top_down(indices: list[int], boxes: list[Box]) -> list[int]:
    return sorted(indices, key=lambda i: (boxes[i][1], boxes[i][0]))


def _order(indices: list[int], boxes: list[Box], gutter: float, depth: int = 0) -> list[int]:
    if len(indices) <= 1 or depth > MAX_DEPTH:
        return _top_down(indices, boxes)

    groups = _columns(indices, boxes, gutter)
    if len(groups) > 1:
        out: list[int] = []
        for group in groups:
            out.extend(_order(group, boxes, gutter, depth + 1))
        return out

    # Single column at this level: full-width blocks split the region into
    # horizontal sections, each of which may hold its own columns.
    span = max(1e-9, max(boxes[i][2] for i in indices) - min(boxes[i][0] for i in indices))
    wide = sorted(
        (i for i in indices if boxes[i][2] - boxes[i][0] >= WIDE_FRAC * span),
        key=lambda i: boxes[i][1],
    )
    wide_set = set(wide)
    narrow = [i for i in indices if i not in wide_set]
    if wide and narrow:
        centres = [(boxes[i][1] + boxes[i][3]) / 2.0 for i in wide]
        sections: list[list[int]] = [[] for _ in range(len(wide) + 1)]
        for i in narrow:
            cy = (boxes[i][1] + boxes[i][3]) / 2.0
            sections[sum(1 for c in centres if c < cy)].append(i)
        out = []
        for k, section in enumerate(sections):
            out.extend(_order(section, boxes, gutter, depth + 1))
            if k < len(wide):
                out.append(wide[k])
        return out

    return _top_down(indices, boxes)


def xycut_order(boxes: Sequence[Sequence[float]], gutter: float = GUTTER) -> list[int]:
    """Return the indices of ``boxes`` in XY-cut reading order."""
    if not boxes:
        return []
    norm = [_normalise(b) for b in boxes]
    return _order(list(range(len(norm))), norm, gutter)


def count_columns(boxes: Sequence[Sequence[float]], gutter: float = GUTTER) -> int:
    """Number of top-level columns (vertical gutters that cut the whole page)."""
    if len(boxes) < 2:
        return 1
    norm = [_normalise(b) for b in boxes]
    return len(_columns(list(range(len(norm))), norm, gutter))


def column_balance(boxes: Sequence[Sequence[float]], gutter: float = GUTTER) -> float:
    """Narrowest / widest top-level column width (1.0 = equal columns, 0 = no columns).

    A main text column next to a narrow sidebar has a low balance; true multi-column
    body text is close to 1.
    """
    if len(boxes) < 2:
        return 0.0
    norm = [_normalise(b) for b in boxes]
    groups = _columns(list(range(len(norm))), norm, gutter)
    if len(groups) < 2:
        return 0.0
    widths = [max(norm[i][2] for i in g) - min(norm[i][0] for i in g) for g in groups]
    return min(widths) / max(widths) if max(widths) > 0 else 0.0


def _valid(box: Sequence[float] | None) -> bool:
    if box is None or len(box) != 4:
        return False
    try:
        x0, y0, x1, y1 = (float(v) for v in box)
    except (TypeError, ValueError):
        return False
    return x1 > x0 and y1 > y0


def reorder(
    items: Sequence[tuple[Sequence[float] | None, T]],
    *,
    mode: str = "multicol",
    min_columns: int = 2,
    min_balance: float = 0.0,
    stats: Counter | None = None,
) -> list[T]:
    """Reorder already-fused page items by XY-cut.

    ``items`` is the page in its current order as ``(box, payload)`` pairs.
    ``mode="multicol"`` only acts when the boxes form at least ``min_columns``
    top-level columns (single-column pages keep the incoming order);
    ``mode="always"`` acts on every page with two or more boxes. With ``min_balance > 0``
    the multicol gate also requires the narrowest column to be at least that fraction of
    the widest one (skips a main column next to a sidebar).

    Items without a usable box are not moved relative to the boxed item that
    precedes them, so nothing is added, dropped or rewritten.
    """
    stats = stats if stats is not None else Counter()
    payloads = [payload for _, payload in items]
    boxed = [k for k, (box, _) in enumerate(items) if _valid(box)]
    if len(boxed) < 2:
        stats["xycut-skipped:few-boxes"] += 1
        return payloads
    boxes = [_normalise(items[k][0]) for k in boxed]  # type: ignore[arg-type]
    if mode == "multicol":
        n_cols = count_columns(boxes)
        if n_cols < min_columns:
            stats["xycut-skipped:single-column"] += 1
            return payloads
        if min_balance > 0 and column_balance(boxes) < min_balance:
            stats["xycut-skipped:unbalanced-columns"] += 1
            return payloads
        stats[f"xycut-columns:{min(n_cols, 4)}{'+' if n_cols > 4 else ''}"] += 1
    elif mode != "always":
        raise ValueError(f"unknown xycut mode: {mode!r}")

    # Unboxed items travel with the boxed item before them (or stay in front).
    lead: list[int] = []
    trailing: dict[int, list[int]] = {k: [] for k in boxed}
    last: int | None = None
    boxed_set = set(boxed)
    for k in range(len(items)):
        if k in boxed_set:
            last = k
        elif last is None:
            lead.append(k)
        else:
            trailing[last].append(k)

    order = [boxed[i] for i in xycut_order(boxes)]
    result_idx = lead + [k for b in order for k in (b, *trailing[b])]
    moved = sum(1 for pos, k in enumerate(result_idx) if pos != k)
    stats["xycut-applied"] += 1
    stats["xycut-moved"] += moved
    return [payloads[k] for k in result_idx]
