"""Callouts split across several blocks.

Pure: zero external dependencies, standard library only.

A callout (a ``note`` or ``warning`` block) that spans several blocks shares
one ``metadata.callout_id`` across them; see ``docstruct.regions.grouping``.
"""
from __future__ import annotations

from typing import Any

CALLOUT_BLOCK_TYPES = frozenset({"note", "warning"})


def dedupe_callout_titles(blocks: list[dict[str, Any]]) -> None:
    """Keep each callout's title on its first block only, in place.

    Later ``note``/``warning`` blocks with the same ``callout_id`` lose their
    ``title``, so a reader hears it once. Blocks without a callout id, and
    blocks of other types, are left alone.
    """
    seen_callout_ids: set[str] = set()
    for block in blocks:
        metadata = block.get("metadata") or {}
        callout_id = str(metadata.get("callout_id") or "").strip()
        if not callout_id:
            continue
        if block.get("type") not in CALLOUT_BLOCK_TYPES:
            continue
        if callout_id in seen_callout_ids:
            block.pop("title", None)
            continue
        seen_callout_ids.add(callout_id)


__all__ = ["CALLOUT_BLOCK_TYPES", "dedupe_callout_titles"]
