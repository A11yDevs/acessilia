"""Structural edits a deterministic handler applies to the manifest.

Splitting, joining and dropping elements has to keep the reading order, the
pages' ``element_ids``, the summary counts and every reference in sync. These
helpers do that bookkeeping so a handler only states which ids map to which
parts, and they live outside the text handlers to keep each module within the
size limit (decision D4).
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from docstruct.fusion.verse import split_box_rows

from backend.core.manifest.models import (
    BoundingBox,
    ManifestElement,
    ProcessingManifest,
    Provenance,
)


def replace_elements(
    manifest: ProcessingManifest,
    replacements: dict[str, list[ManifestElement]],
) -> None:
    """Rebuild the element list after a handler splits, joins or drops elements.

    ``replacements`` maps a source element id to its parts; an empty list drops
    the element. Reading order and the pages' ``element_ids`` are renumbered so
    the payload and the collection invariants see the new list, and the summary
    counts follow it.

    Page membership is rebuilt from the previous ``element_ids`` instead of from
    ``page_number``: the field is optional, and a valid manifest can own an
    element through the page list alone.
    """
    ordered = sorted(manifest.elements, key=lambda element: element.reading_order)
    rebuilt: list[ManifestElement] = []
    for element in ordered:
        if element.id in replacements:
            rebuilt.extend(replacements[element.id])
        else:
            rebuilt.append(element)
    for order, element in enumerate(rebuilt, start=1):
        element.reading_order = order
    manifest.elements = rebuilt
    existing = {element.id: element for element in rebuilt}
    for page in manifest.pages:
        members: list[str] = []
        for element_id in page.element_ids:
            if element_id in replacements:
                parts = replacements[element_id]
            elif element_id in existing:
                parts = [existing[element_id]]
            else:
                parts = []
            for part in parts:
                if part.id not in members:
                    members.append(part.id)
        page.element_ids = members
    manifest.summary.element_count = len(rebuilt)
    manifest.summary.element_types = dict(
        Counter(element.type for element in rebuilt)
    )


def remap_references(
    manifest: ProcessingManifest,
    mapping: dict[str, list[str]],
) -> None:
    """Point obligation, observation and parent references at the surviving ids.

    A split maps the source id to the source plus its parts; a join maps each
    dropped id to the element that now carries its text. References are kept in
    order and deduplicated, so an obligation never points at an element that is
    no longer in the manifest.

    When a join changes an element's parent, its ``parent_ref`` follows the new
    parent's ``source_ref``: the child now belongs to the surviving element,
    and keeping the removed parent's source reference would make the document
    fail the ``parent_ref``/``parent_id`` invariant. The previous value is kept
    in ``metadata["original_parent_ref"]`` for traceability.
    """
    def remapped(ids: list[str]) -> list[str]:
        out: list[str] = []
        for element_id in ids:
            for replacement in mapping.get(element_id, [element_id]):
                if replacement not in out:
                    out.append(replacement)
        return out

    for obligation in manifest.obligations:
        obligation.target_ids = remapped(obligation.target_ids)
    for observation in manifest.observations:
        observation.target_ids = remapped(observation.target_ids)
    by_id = {element.id: element for element in manifest.elements}
    for element in manifest.elements:
        replacements = mapping.get(element.parent_id or "")
        if not replacements:
            continue
        element.parent_id = replacements[0]
        parent = by_id.get(element.parent_id)
        if (
            element.parent_ref is not None
            and parent is not None
            and parent.source_ref is not None
            and parent.source_ref != element.parent_ref
        ):
            element.metadata["original_parent_ref"] = element.parent_ref
            element.parent_ref = parent.source_ref


def unique_element_id(base: str, known: set[str]) -> str:
    """``base``, or ``base-N`` when another element already owns it."""
    candidate = base
    suffix = 2
    while candidate in known:
        candidate = f"{base}-{suffix}"
        suffix += 1
    known.add(candidate)
    return candidate


def split_provenance(
    element: ManifestElement, parts: list[int]
) -> list[list[Provenance]]:
    """Provenance of each split part, with the source box divided by its lines.

    The first provenance entry carries the box; the others belong to the same
    source element and stay on the first part. Character offsets are dropped
    because each part now covers a different span.
    """
    if not element.provenance:
        return [[] for _ in parts]
    base = element.provenance[0]
    if base.bbox is None:
        boxes: list[Any] = [None] * len(parts)
    else:
        boxes = split_box_rows(
            (base.bbox.left, base.bbox.top, base.bbox.right, base.bbox.bottom),
            parts,
        )
    split: list[list[Provenance]] = []
    for box in boxes:
        update: dict[str, Any] = {"char_start": None, "char_end": None}
        if box is not None and base.bbox is not None:
            update["bbox"] = BoundingBox(
                left=box[0],
                top=box[1],
                right=box[2],
                bottom=box[3],
                coord_origin=base.bbox.coord_origin,
            )
        split.append([base.model_copy(deep=True, update=update)])
    extra = [entry.model_copy(deep=True) for entry in element.provenance[1:]]
    if split and extra:
        split[0].extend(extra)
    return split


def joined_provenance(
    elements: list[ManifestElement], joined_text: str
) -> list[Provenance]:
    """Provenance of the joined text, with character spans rebased.

    Every page and bounding box of every source entry is kept. The character
    ranges pointed into each element's own text, so they move to where that text
    now sits in ``joined_text`` instead of being silently dropped with the
    removed elements.
    """
    entries: list[Provenance] = []
    cursor = 0
    for element in elements:
        text = element.text or ""
        piece = text.strip()
        start = joined_text.find(piece, cursor)
        if start < 0:
            start = cursor
        # ``join_tail`` strips each part, so its own offsets start after the
        # whitespace this element carried and end before the trailing one.
        lead = len(text) - len(text.lstrip())
        lower = max(0, start - lead)
        upper = start + len(piece)
        for entry in element.provenance:
            copied = entry.model_copy(deep=True)
            if copied.char_start is not None:
                copied.char_start = min(max(lower + copied.char_start, 0), upper)
            if copied.char_end is not None:
                copied.char_end = min(max(lower + copied.char_end, 0), upper)
            if copied.char_start is not None and copied.char_end is not None:
                copied.char_end = max(copied.char_end, copied.char_start)
            entries.append(copied)
        cursor = upper + 1
    return entries
