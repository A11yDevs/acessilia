"""Callouts split across several blocks.

Pure: zero external dependencies, standard library only.

A callout (a ``note`` or ``warning`` block) that spans several blocks shares
one ``metadata.callout_id`` across them; see ``docstruct.regions.grouping``.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Protocol

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


class CalloutPart(Protocol):
    """What :func:`callout_titles` reads of an element (read-only, so both
    ``docstruct.manifest.DocumentElement`` and the core's manifest element
    qualify)."""

    @property
    def text(self) -> str | None: ...

    @property
    def metadata(self) -> Mapping[str, Any]: ...


def callout_titles(elements: Iterable[CalloutPart]) -> dict[str, str]:
    """Each callout's title, read from its title element's text as it stands now.

    The Toolbox copies the title into ``metadata.callout_title`` when it groups
    the callout, before any repair; the text-repair methods then fix the
    title element's text only, so the copy keeps the broken accents
    ("observa¸ c˜ oes").

    Read per page: the Toolbox groups callouts page by page, so a callout's
    title and content never sit on different pages.
    """
    return {
        str(element.metadata["callout_id"]): (element.text or "").strip()
        for element in elements
        if element.metadata.get("callout_id")
        and str(element.metadata.get("callout_role", "")).lower() == "title"
        and (element.text or "").strip()
    }


__all__ = ["CALLOUT_BLOCK_TYPES", "CalloutPart", "callout_titles", "dedupe_callout_titles"]
