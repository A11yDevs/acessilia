"""``rescue-omitted``: put back the primary provider's text a page lost (#236).

``rescue-omitted-block`` is emitted for a page where the block-level fusion
dropped a primary (Docling) block (``dropped-docling-*`` in the page's fusion
stats). The method ports Dr.DocBench's ``rescue_omitted`` (tree_differ_v2.py of
the drbench-2026-snapshot tag): a primary text block that reads as legitimate
text is kept even when the fusion would discard it.

The manifest is not the fusion's output. It is the primary provider's
extraction, except for the pages the deterministic router took from the
secondary provider (``fusion.apply_page_routes``). So, per page:

- a page that kept the primary extraction already carries every block the
  fusion dropped, and the obligation is satisfied as it is;
- a page taken from the secondary provider lost every primary block the
  secondary did not extract. The secondary-extraction artifact keeps the
  primary elements it replaced (``replaced_primary_pages``); each legitimate
  text block that no element of the page pairs with, and whose text the page
  does not already carry, is inserted after the element paired with the
  primary block before it;
- a page the text fusion rewrote (``dual-provider-fusion``) no longer has the
  primary blocks anywhere, so the method fails and the obligation goes to
  human review.

The method restores the primary provider's own content and applies no
preference between the providers, so unlike ``skeleton-order`` it does not
require the calibrated docling + mineru pair.
"""

from __future__ import annotations

import re
from typing import Any

from docstruct.fusion.noise import is_junk, quality
from docstruct.fusion.similarity import PAGENUM_RE, is_duplicate, pair_block
from pydantic import ValidationError

from acessilia_core.execution.models import MethodResult
from acessilia_core.i18n import t
from acessilia_core.manifest.models import ManifestElement, ProcessingManifest
from acessilia_core.pipeline.elements import _element_bbox
from acessilia_core.pipeline.handlers.common import (
    _missing_obligation,
    _target_elements,
)
from acessilia_core.pipeline.handlers.messages import (
    MSG_RESCUE_FUSED_PAGES,
    MSG_RESCUE_PRIMARY_KEPT,
    MSG_RESCUE_REPLACED_UNKNOWN,
    MSG_RESCUE_RESTORED,
    MSG_RESCUE_ROUTED_COMPLETE,
)
from acessilia_core.pipeline.secondary import (
    _MIN_BLOCK_IOU,
    _MIN_BLOCK_TEXT_RATIO,
    _load_secondary_extraction,
)

#: Element types whose text the method rescues. Tables, formulas and pictures
#: are what the router took the secondary page for; page headers and footers
#: are decoration.
_RESCUABLE_TYPES = frozenset(
    {"title", "heading", "paragraph", "list_item", "caption", "footnote"}
)

#: A primary block inside one of these belongs to that structure, which the
#: secondary page carries in its own form.
_STRUCTURE_PARENTS = frozenset({"picture", "table", "group", "form"})

#: Least text a block needs for its presence in the page text to count.
_MIN_CONTAINED_TEXT = 8

#: Lowest share of word-like tokens of a legitimate block (``is_legitimate_text``).
_MIN_QUALITY = 0.35


def is_legitimate_text(text: str) -> bool:
    """Whether ``text`` reads as real text rather than OCR residue.

    Dr.DocBench's ``is_legitimate_text``: not junk, not a page number, at least
    three letters, mostly alphanumeric and mostly word-like tokens.
    """
    stripped = (text or "").strip()
    if not stripped or is_junk(stripped) or PAGENUM_RE.match(stripped):
        return False
    if sum(char.isalpha() for char in stripped) < 3:
        return False
    core = re.sub(r"\s+", "", stripped)
    if sum(char.isalnum() for char in core) / len(core) < 0.4:
        return False
    return quality(stripped) >= _MIN_QUALITY


def _handle_rescue_omitted_method(
    manifest: ProcessingManifest, obligation_id: str
) -> MethodResult:
    """Restore the primary text blocks missing from the obligation's pages."""
    elements = _target_elements(manifest, obligation_id)
    pages = sorted({e.page_number for e in elements if e.page_number is not None})
    if not pages:
        return _missing_obligation(obligation_id)

    fused = [
        page for page in pages
        if any(
            element.metadata.get("fusion_provider")
            for element in manifest.elements
            if element.page_number == page
        )
    ]
    if fused:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_RESCUE_FUSED_PAGES).format(pages=_pages(fused)),
        )

    secondary, problem = _load_secondary_extraction(manifest)
    if secondary is None:
        return MethodResult(success=False, validated=False, message=problem)

    kept: list[int] = []
    complete: list[int] = []
    unknown: list[int] = []
    restored: dict[int, int] = {}
    for page in pages:
        page_elements = _page_elements(manifest, page)
        if page in secondary.replaced_primary:
            count = _rescue_page(
                manifest, page, page_elements, secondary.replaced_primary[page]
            )
            if count:
                restored[page] = count
            else:
                complete.append(page)
        elif any(
            element.metadata.get("provider") == secondary.provider
            for element in page_elements
        ):
            unknown.append(page)
        else:
            kept.append(page)

    if restored:
        _renumber(manifest, set(restored))
    if unknown:
        return MethodResult(
            success=False,
            validated=False,
            message=t(MSG_RESCUE_REPLACED_UNKNOWN).format(
                pages=_pages(unknown), provider=secondary.provider or "?"
            ),
        )
    parts = []
    if restored:
        parts.append(
            t(MSG_RESCUE_RESTORED).format(
                count=sum(restored.values()), pages=_pages(restored)
            )
        )
    if complete:
        parts.append(t(MSG_RESCUE_ROUTED_COMPLETE).format(pages=_pages(complete)))
    if kept:
        parts.append(t(MSG_RESCUE_PRIMARY_KEPT).format(pages=_pages(kept)))
    return MethodResult(success=True, validated=True, message="; ".join(parts))


def _pages(pages: Any) -> str:
    return ", ".join(map(str, sorted(pages)))


def _page_elements(manifest: ProcessingManifest, page: int) -> list[ManifestElement]:
    return sorted(
        (element for element in manifest.elements if element.page_number == page),
        key=lambda element: element.reading_order,
    )


def _primary_elements(
    rows: list[dict[str, Any]], page: int
) -> list[ManifestElement]:
    """The replaced primary rows as manifest elements, in reading order.

    A row the manifest model rejects is skipped: the method can only insert an
    element the manifest accepts.
    """
    parsed = []
    for row in rows:
        try:
            element = ManifestElement.model_validate(
                {**row, "page_number": row.get("page_number") or page}
            )
        except ValidationError:
            continue
        parsed.append(element)
    return parsed


def _rescue_page(
    manifest: ProcessingManifest,
    page: int,
    current: list[ManifestElement],
    rows: list[dict[str, Any]],
) -> int:
    """Insert the omitted primary blocks of ``page``; returns how many."""
    primary = _primary_elements(rows, page)
    parent_types = {element.id: element.type for element in primary}
    boxes = [_element_bbox(element, manifest) for element in current]
    texts = [element.text for element in current]
    page_text = "\n".join(element.text or "" for element in current)
    used: set[int] = set()
    existing = {element.id for element in manifest.elements}
    provider = str((manifest.extractor.configuration or {}).get("toolbox_provider") or "")

    #: index in ``current`` after which a rescued block goes (-1: page start)
    inserts: dict[int, list[ManifestElement]] = {}
    anchor = -1
    for element in primary:
        box = _element_bbox(element, manifest)
        match = pair_block(
            box,
            element.text or "",
            boxes if box is not None else [],
            texts,
            used,
            min_iou=_MIN_BLOCK_IOU,
            min_text_ratio=_MIN_BLOCK_TEXT_RATIO,
        )
        if match is not None:
            used.add(match)
            anchor = match
            continue
        if not _omitted(element, page_text, parent_types):
            continue
        rescued = element.model_copy(deep=True)
        rescued.id = _unique_id(f"element-rescued-p{page}-{element.id}", existing)
        existing.add(rescued.id)
        rescued.parent_id = None
        rescued.parent_ref = None
        rescued.metadata = {
            **rescued.metadata,
            "provider": provider or rescued.metadata.get("provider"),
            "rescued_by": "rescue-omitted",
        }
        inserts.setdefault(anchor, []).append(rescued)

    if not inserts:
        return 0
    before = {current[0].id: inserts.pop(-1)} if -1 in inserts else {}
    after = {current[index].id: rescued for index, rescued in inserts.items()}
    ordered: list[ManifestElement] = []
    for element in sorted(manifest.elements, key=lambda item: item.reading_order):
        ordered.extend(before.get(element.id, []))
        ordered.append(element)
        ordered.extend(after.get(element.id, []))
    added = len(ordered) - len(manifest.elements)
    manifest.elements = ordered
    return added


def _omitted(
    element: ManifestElement, page_text: str, parent_types: dict[str, str]
) -> bool:
    """Whether an unpaired primary block is legitimate text the page lacks.

    The page lacks it unless its text, whitespace and case folded, is part of
    the page's text: the secondary provider may have merged it into a longer
    block, or split it across two.
    """
    if element.type not in _RESCUABLE_TYPES:
        return False
    if parent_types.get(element.parent_id or "") in _STRUCTURE_PARENTS:
        return False
    text = element.text or ""
    if not is_legitimate_text(text):
        return False
    return not is_duplicate(text, [page_text], min_len=_MIN_CONTAINED_TEXT)


def _unique_id(base: str, existing: set[str]) -> str:
    candidate, suffix = base, 2
    while candidate in existing:
        candidate, suffix = f"{base}-{suffix}", suffix + 1
    return candidate


def _renumber(manifest: ProcessingManifest, pages: set[int]) -> None:
    """Number the reading order 1..n again and refresh the touched pages."""
    for order, element in enumerate(manifest.elements, start=1):
        element.reading_order = order
    for page in manifest.pages:
        if page.page_number in pages:
            page.element_ids = [
                element.id
                for element in manifest.elements
                if element.page_number == page.page_number
            ]
    manifest.summary.element_count = len(manifest.elements)
    types: dict[str, int] = {}
    for element in manifest.elements:
        types[element.type] = types.get(element.type, 0) + 1
    manifest.summary.element_types = types


__all__ = ["is_legitimate_text"]
