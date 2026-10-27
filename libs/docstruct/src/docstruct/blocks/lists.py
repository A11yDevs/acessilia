"""List blocks.

Pure: zero external dependencies, standard library only.

A ``list`` block holds its ``items`` as text; an ordered one may carry
``start``, the number of its first item, when the source list was split
by a formula or a paragraph between its items.
"""
from __future__ import annotations

from typing import Any


def list_start(block: dict[str, Any]) -> int:
    """The number of an ordered list block's first item: ``start``, else 1."""
    start = block.get("start")
    return start if isinstance(start, int) and not isinstance(start, bool) and start > 0 else 1


__all__ = ["list_start"]
