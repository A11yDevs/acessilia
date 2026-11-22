"""Pure multi-provider payload fusion and deterministic page routing.

Operates on Toolbox extraction payloads (``{"document": {"elements": [...], "pages": [...]}}``)
with no I/O, network calls, or logging. Callers that want operational logs inspect
the returned ``fusion_stats`` or :class:`PageRouteResult` fields.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Set as AbstractSet
from dataclasses import dataclass, field
from typing import Any

from docstruct.fusion.adjudication import decide_v1
from docstruct.fusion.convert import block_to_diff
from docstruct.fusion.differ import merge_blocks
from docstruct.fusion.judge import DEFAULT_MAX_RATIO
from docstruct.fusion.page_select import page_norm, ratio
from docstruct.fusion.repetition import guard_page, token_norm
from docstruct.fusion.types import DiffBlock
from docstruct.policy import FusionPolicy
from docstruct.types import CanonicalBlock

_rapidfuzz_fuzz: Any
try:  # optional accelerator; the library itself has no dependencies
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except ImportError:
    _rapidfuzz_fuzz = None

#: DiffBlock kinds whose text decides whether two providers transcribed a page alike.
TEXT_KINDS: frozenset[str] = frozenset({"text", "heading", "title"})

#: Structural element types tracked independently of running text.
STRUCTURAL_TYPES: frozenset[str] = frozenset({"picture", "table", "formula"})


@dataclass(frozen=True)
class PageRouteResult:
    """Outcome of applying deterministic page routes between two provider payloads.

    ``payload`` is the primary payload unchanged (same object) when no page was
    routed; otherwise a new payload dict whose routed pages hold the adopted
    secondary elements. ``replaced`` maps each routed 1-based page number to the
    primary elements it replaced. ``routed_pages`` and ``missing_pages`` let
    callers log routing decisions without coupling docstruct to a logger.
    ``page_evidence`` is an annotated copy of the caller's evidence; the caller's
    list is never mutated.
    """

    payload: dict[str, Any]
    replaced: dict[int, list[dict[str, Any]]]
    routed_pages: tuple[int, ...]
    missing_pages: tuple[Any, ...]
    #: Copy of the caller's routing evidence with ``stats["applied"]`` set on
    #: routed entries. The input list is never mutated (#633).
    page_evidence: list[dict[str, Any]] = field(default_factory=list)


def page_similarity(a: str, b: str) -> float:
    """Character similarity in ``[0, 1]`` of two page transcriptions.

    Matches :func:`docstruct.fusion.judge.should_judge`'s character LCS metric
    over :func:`docstruct.fusion.page_select.page_norm`: uses
    ``rapidfuzz.fuzz.ratio`` when installed and falls back to the pure-Python
    :func:`docstruct.fusion.page_select.ratio`.
    """
    norm_a, norm_b = page_norm(a), page_norm(b)
    if not norm_a and not norm_b:
        return 1.0
    if not norm_a or not norm_b:
        return 0.0
    if _rapidfuzz_fuzz is not None:
        return _rapidfuzz_fuzz.ratio(norm_a, norm_b) / 100.0
    return ratio(norm_a, norm_b)


def _extract_element_bbox(element: dict[str, Any]) -> list[float] | None:
    raw = element.get("bbox")
    if not raw:
        provenance = element.get("provenance") or []
        if provenance:
            raw = provenance[0].get("bbox")
    if isinstance(raw, dict):
        raw = [raw.get(key) for key in ("left", "top", "right", "bottom")]
    if raw and all(isinstance(coord, (int, float)) for coord in raw):
        return [float(coord) for coord in raw]
    return None


def element_to_canonical_block(
    element: dict[str, Any], page_index: int
) -> dict[str, Any]:
    """Convert a processing-manifest element dict into a canonical block dict."""
    element_type = str(element.get("type", "")).lower() or "paragraph"
    text = (element.get("text") or "").strip()
    block: dict[str, Any] = {
        "type": element_type,
        "text": text,
        "metadata": {
            "reading_order": element.get("reading_order") or 0,
            "page_size": element.get("page_size"),
            "coord_origin": element.get("coord_origin") or "",
        },
    }
    bbox = _extract_element_bbox(element)
    if bbox is not None:
        block["bbox"] = bbox
        block["page_index"] = page_index
    return block


def group_payload_by_page(payload: dict[str, Any]) -> dict[int, list[dict[str, Any]]]:
    """Group payload elements by 0-based page index (defaulting to page ``0``)."""
    document = payload.get("document", payload)
    grouped: dict[int, list[dict[str, Any]]] = {}
    for element in document.get("elements") or []:
        text = (element.get("text") or "").strip()
        if not text and element.get("type") not in STRUCTURAL_TYPES:
            continue
        page_number = element.get("page_number")
        page = max(0, int(page_number) - 1) if page_number is not None else int(element.get("page") or 0)
        grouped.setdefault(page, []).append(element_to_canonical_block(element, page))
    return grouped


def structure_signature(
    blocks: list[dict[str, Any]],
    *,
    kinds: AbstractSet[str] = STRUCTURAL_TYPES,
) -> list[tuple[str, int]]:
    """Count structural elements by kind without comparing provider-specific boxes."""
    counts = Counter(block["type"] for block in blocks if block["type"] in kinds)
    return sorted(counts.items())


def page_content_signature(
    blocks: list[DiffBlock],
    *,
    kinds: AbstractSet[str] | None = None,
) -> list[tuple[str, str]]:
    """Sorted ``(kind, normalized_token)`` multiset for diff blocks on a page."""
    return sorted(
        (block.kind, token)
        for block in blocks
        if kinds is None or block.kind in kinds
        for token in token_norm(block.text).split()
    )


def _canonical_to_diff(block: dict[str, Any]) -> DiffBlock:
    bbox = block.get("bbox")
    metadata = block.get("metadata", {})
    canonical = CanonicalBlock(
        id=str(metadata.get("reading_order", 0)),
        type=block["type"],
        text=block["text"],
        bbox=tuple(bbox) if bbox else None,
        page_index=block.get("page_index"),
        metadata=metadata,
    )
    return block_to_diff(canonical)


def _guard_merged_blocks(
    merged_blocks: list[str], primary_text: str, secondary_text: str
) -> tuple[list[str], int]:
    guarded_blocks: list[str] = []
    tokens_cut = 0
    for block_text in merged_blocks:
        guarded, cut, _ = guard_page(block_text, primary_text, secondary_text)
        guarded_blocks.append(guarded)
        tokens_cut += cut
    return guarded_blocks, tokens_cut


def _structure_content(blocks: list[dict[str, Any]]) -> Counter[tuple[str, str]]:
    return Counter(
        (block["type"], " ".join((block.get("text") or "").split()))
        for block in blocks
        if block["type"] in STRUCTURAL_TYPES
    )


def _resolve_page_route(
    primary_blocks: list[dict[str, Any]],
    secondary_blocks: list[dict[str, Any]],
    primary_text: str,
    secondary_text: str,
    *,
    secondary_adds_structure: bool,
    text_similarity: float,
) -> tuple[str, str]:
    route, route_reason = decide_v1(primary_text, secondary_text)
    if not (secondary_adds_structure and route_reason == "default_docling"):
        return route, route_reason
    primary_content = _structure_content(primary_blocks)
    secondary_content = _structure_content(secondary_blocks)
    if not (primary_content - secondary_content) and text_similarity >= DEFAULT_MAX_RATIO:
        return "mineru", "secondary_structure_superset"
    return "docling", "structure_ambiguous"


def _build_page_evidence(
    primary_page: list[dict[str, Any]],
    secondary_page: list[dict[str, Any]],
    d_blocks: list[DiffBlock],
    m_blocks: list[DiffBlock],
    primary_text: str,
    secondary_text: str,
    page_stats: Counter[str],
    repetition_tokens_cut: int,
    *,
    primary_provider: str,
    secondary_provider: str,
) -> dict[str, Any]:
    similarity = page_similarity(primary_text, secondary_text)
    text_similarity = page_similarity(
        "\n\n".join(block.text for block in d_blocks if block.kind in TEXT_KINDS),
        "\n\n".join(block.text for block in m_blocks if block.kind in TEXT_KINDS),
    )
    structure_d = structure_signature(primary_page)
    structure_m = structure_signature(secondary_page)
    primary_counts = Counter(dict(structure_d))
    secondary_counts = Counter(dict(structure_m))
    # Only a structure the secondary found and the primary did not is worth
    # acting on: the primary's page is kept by default.
    secondary_adds_structure = bool(secondary_counts - primary_counts)

    route, route_reason = _resolve_page_route(
        primary_page,
        secondary_page,
        primary_text,
        secondary_text,
        secondary_adds_structure=secondary_adds_structure,
        text_similarity=text_similarity,
    )
    table_divergence = (
        page_content_signature(d_blocks, kinds={"table"})
        != page_content_signature(m_blocks, kinds={"table"})
        or structure_signature(primary_page, kinds={"table"})
        != structure_signature(secondary_page, kinds={"table"})
    )

    evidence_stats: dict[str, Any] = dict(page_stats)
    evidence_stats.update(
        {
            "provider_count": 2,
            "similarity": round(similarity, 4),
            "text_similarity": round(text_similarity, 4),
            "structure_divergence": structure_d != structure_m,
            "structure_counts": {
                primary_provider: dict(primary_counts),
                secondary_provider: dict(secondary_counts),
            },
            "provider_divergence": (
                similarity < DEFAULT_MAX_RATIO or secondary_adds_structure
            ),
            "text_divergence": text_similarity < DEFAULT_MAX_RATIO,
            "route": route,
            "route_reason": route_reason,
            "table_divergence": table_divergence,
        }
    )
    if repetition_tokens_cut:
        evidence_stats["repetition_tokens_cut"] = repetition_tokens_cut
    return evidence_stats


def _fuse_page(
    page_key: int,
    primary_page: list[dict[str, Any]],
    secondary_page: list[dict[str, Any]],
    *,
    primary_provider: str,
    secondary_provider: str,
    policy: FusionPolicy,
) -> tuple[list[tuple[int, str]], Counter[str], dict[str, Any]]:
    d_blocks = [_canonical_to_diff(block) for block in primary_page if block["text"]]
    m_blocks = [_canonical_to_diff(block) for block in secondary_page if block["text"]]
    m_pics = [
        diff.box
        for block in secondary_page
        if block["type"] == "picture" and "bbox" in block
        if (diff := _canonical_to_diff(block)).box is not None
    ]
    page_stats: Counter[str] = Counter()
    merged, page_stats = merge_blocks(
        d_blocks, m_blocks, policy, min_len=0, m_pics=m_pics, stats=page_stats
    )
    primary_text = "\n\n".join(block.md for block in d_blocks)
    secondary_text = "\n\n".join(block.md for block in m_blocks)
    guarded, repetition_tokens_cut = _guard_merged_blocks(
        merged, primary_text, secondary_text
    )
    evidence_stats = _build_page_evidence(
        primary_page,
        secondary_page,
        d_blocks,
        m_blocks,
        primary_text,
        secondary_text,
        page_stats,
        repetition_tokens_cut,
        primary_provider=primary_provider,
        secondary_provider=secondary_provider,
    )
    if repetition_tokens_cut:
        page_stats["repetition_tokens_cut"] += repetition_tokens_cut
    page_entry = {"page_number": page_key + 1, "stats": evidence_stats}
    return [(page_key, block) for block in guarded], page_stats, page_entry


def fuse_extraction_payloads(
    primary_res: dict[str, Any],
    secondary_res: dict[str, Any],
    *,
    primary_provider: str,
    secondary_provider: str,
    policy: FusionPolicy | None = None,
) -> dict[str, Any]:
    """Fuse two already-extracted payloads and return merged blocks plus evidence."""
    active_policy = policy or FusionPolicy()
    stats: Counter[str] = Counter()
    merged_page_blocks: list[tuple[int, str]] = []
    page_evidence: list[dict[str, Any]] = []

    pages_primary = group_payload_by_page(primary_res)
    pages_secondary = group_payload_by_page(secondary_res)
    for page_key in sorted(set(pages_primary) | set(pages_secondary)):
        page_blocks, page_stats, page_entry = _fuse_page(
            page_key,
            pages_primary.get(page_key, []),
            pages_secondary.get(page_key, []),
            primary_provider=primary_provider,
            secondary_provider=secondary_provider,
            policy=active_policy,
        )
        stats.update(page_stats)
        page_evidence.append(page_entry)
        merged_page_blocks.extend(page_blocks)

    return {
        "status": "succeeded",
        "provider": f"{primary_provider}+{secondary_provider}",
        "document": {
            "elements": [
                {
                    "type": "paragraph",
                    "text": markdown,
                    "reading_order": order,
                    "page": page_key,
                    "page_number": page_key + 1,
                }
                for order, (page_key, markdown) in enumerate(merged_page_blocks, start=1)
            ]
        },
        "fusion_stats": dict(stats),
        "fusion_evidence": {"pages": page_evidence},
    }


def _element_page_number(element: dict[str, Any]) -> int | None:
    page_number = element.get("page_number")
    if isinstance(page_number, int):
        return page_number
    zero_based = element.get("page")
    return zero_based + 1 if isinstance(zero_based, int) else None


def _has_id(element: dict[str, Any]) -> bool:
    """Whether the element carries a truthy id (``adopt_elements`` coerces it)."""
    return bool(element.get("id"))


def _has_usable_id(element: dict[str, Any]) -> bool:
    """Whether the element carries the non-empty string id the manifest requires."""
    element_id = element.get("id")
    return isinstance(element_id, str) and bool(element_id)


def _elements_by_page(elements: list[Any]) -> dict[int, list[dict[str, Any]]]:
    ordered = sorted(
        (item for item in elements if isinstance(item, dict)),
        key=lambda item: item.get("reading_order") or 0,
    )
    by_page: dict[int, list[dict[str, Any]]] = {}
    for element in ordered:
        page_number = _element_page_number(element)
        if page_number is not None:
            by_page.setdefault(page_number, []).append(element)
    return by_page


def _routed_page_sizes(
    pages: list[Any], routed: AbstractSet[int]
) -> dict[int, tuple[float, float]]:
    sizes: dict[int, tuple[float, float]] = {}
    for page in pages:
        if not isinstance(page, dict):
            continue
        number = page.get("page_number")
        width, height = page.get("width"), page.get("height")
        if (
            isinstance(number, int)
            and number in routed
            and isinstance(width, (int, float))
            and isinstance(height, (int, float))
            and width > 0
            and height > 0
        ):
            sizes[number] = (float(width), float(height))
    return sizes


def page_scales(
    primary_pages: list[Any],
    secondary_pages: list[Any],
    routed: AbstractSet[int],
) -> dict[int, tuple[float, float]]:
    """Scale factors ``(sx, sy)`` mapping routed secondary boxes into primary page frames."""
    primary_sizes = _routed_page_sizes(primary_pages, routed)
    secondary_sizes = _routed_page_sizes(secondary_pages, routed)
    return {
        number: (primary_sizes[number][0] / sec_w, primary_sizes[number][1] / sec_h)
        for number, (sec_w, sec_h) in secondary_sizes.items()
        if number in primary_sizes and primary_sizes[number] != (sec_w, sec_h)
    }


def scaled_box(box: Any, scale: tuple[float, float]) -> Any:
    """Scale a bounding box (dict or 4-element sequence) by ``(sx, sy)``."""
    scale_x, scale_y = scale
    if isinstance(box, dict):
        scaled = dict(box)
        for key in ("left", "right"):
            value = box.get(key)
            if isinstance(value, (int, float)):
                scaled[key] = value * scale_x
        for key in ("top", "bottom"):
            value = box.get(key)
            if isinstance(value, (int, float)):
                scaled[key] = value * scale_y
        return scaled
    if (
        isinstance(box, (list, tuple))
        and len(box) == 4
        and all(isinstance(value, (int, float)) for value in box)
    ):
        left, top, right, bottom = box
        return [left * scale_x, top * scale_y, right * scale_x, bottom * scale_y]
    return box


def _scale_provenance_list(
    provenance: list[Any], scale: tuple[float, float]
) -> list[Any]:
    return [
        {**entry, "bbox": scaled_box(entry["bbox"], scale)}
        if isinstance(entry, dict) and entry.get("bbox") is not None
        else entry
        for entry in provenance
    ]


def adopt_elements(
    pages: dict[int, list[dict[str, Any]]],
    provider: str,
    scales: dict[int, tuple[float, float]],
) -> dict[int, list[dict[str, Any]]]:
    """Copy routed secondary elements with prefixed IDs, remapped parents, and scaled boxes."""
    id_map = {
        element["id"]: f"{provider}-{element['id']}"
        for page_elements in pages.values()
        for element in page_elements
        if _has_id(element)
    }
    adopted: dict[int, list[dict[str, Any]]] = {}
    for page_number, page_elements in pages.items():
        scale = scales.get(page_number)
        page_copies: list[dict[str, Any]] = []
        for position, element in enumerate(page_elements, start=1):
            copied = dict(element)
            copied["id"] = (
                id_map[element["id"]]
                if _has_id(element)
                else f"{provider}-p{page_number}-{position}"
            )
            copied["parent_id"] = id_map.get(element.get("parent_id"))
            copied["metadata"] = {**(element.get("metadata") or {}), "provider": provider}
            if scale is not None:
                if "bbox" in copied:
                    copied["bbox"] = scaled_box(copied["bbox"], scale)
                provenance = copied.get("provenance")
                if isinstance(provenance, list):
                    copied["provenance"] = _scale_provenance_list(provenance, scale)
            page_copies.append(copied)
        adopted[page_number] = page_copies
    return adopted


def _select_routed_and_missing(
    page_evidence: list[dict[str, Any]],
    secondary_by_page: dict[int, list[dict[str, Any]]],
) -> tuple[set[int], tuple[Any, ...]]:
    preferred: set[int] = set()
    for entry in page_evidence:
        number = entry.get("page_number")
        if isinstance(number, float) and number.is_integer():
            number = int(number)
        if isinstance(number, int) and (entry.get("stats") or {}).get("route") == "mineru":
            preferred.add(number)
    routed = {
        number for number in preferred if secondary_by_page.get(number)
    }
    missing = tuple(sorted(preferred - routed, key=str))
    return routed, missing


def _merge_routed_elements(
    primary_by_page: dict[int, list[dict[str, Any]]],
    unpaged: list[dict[str, Any]],
    adopted: dict[int, list[dict[str, Any]]],
    routed: AbstractSet[int],
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    replaced: dict[int, list[dict[str, Any]]] = {}
    merged: list[dict[str, Any]] = []
    for page_number in sorted(set(primary_by_page) | set(routed)):
        if page_number in routed:
            replaced[page_number] = primary_by_page.get(page_number, [])
            merged.extend(adopted[page_number])
        else:
            merged.extend(dict(item) for item in primary_by_page[page_number])
    merged.extend(dict(item) for item in unpaged)
    for reading_order, item in enumerate(merged, start=1):
        item["reading_order"] = reading_order
    return merged, replaced


def _normalize_missing_ids(elements: list[dict[str, Any]]) -> None:
    """Give the elements without a usable id a deterministic one, in place.

    ``ProcessingManifest`` requires every element to carry a non-empty string
    ``id``; page membership is rebuilt from those ids by
    ``_rebuild_routed_pages``. Leaving a primary element id-less (or with an
    empty or non-string id) drops it from ``page.element_ids`` and makes the
    payload fail manifest validation later (#664). The generated id is
    page-scoped, so it stays stable when elements before that page change, and
    a numeric suffix keeps it unique when the provider already used the same
    shape. ``parent_id`` references to a replaced non-string id follow the new
    id.
    """
    used = {str(element.get("id")) for element in elements if _has_id(element)}
    replacements: dict[Any, str] = {}
    positions: Counter[int | None] = Counter()
    for element in elements:
        page_number = _element_page_number(element)
        positions[page_number] += 1
        if _has_usable_id(element):
            continue
        previous_id = element.get("id")
        scope = f"p{page_number}" if page_number is not None else "unpaged"
        candidate = f"element-{scope}-{positions[page_number]}"
        suffix = 2
        while candidate in used:
            candidate = f"element-{scope}-{positions[page_number]}-{suffix}"
            suffix += 1
        element["id"] = candidate
        used.add(candidate)
        if previous_id:
            # The input is already invalid when the id repeats; the last
            # occurrence wins so a child still points at some regenerated id.
            try:
                replacements[previous_id] = candidate
            except TypeError:  # an unhashable id cannot be referenced either
                pass
    for element in elements:
        try:
            replacement = replacements.get(element.get("parent_id"))
        except TypeError:
            continue
        if replacement is not None:
            element["parent_id"] = replacement


def _page_element_ids(elements: list[dict[str, Any]]) -> dict[int, list[Any]]:
    """The usable ids of the elements on each page, in elements order."""
    ids_by_page: dict[int, list[Any]] = {}
    for element in elements:
        page_number = _element_page_number(element)
        if page_number is not None and _has_usable_id(element):
            ids_by_page.setdefault(page_number, []).append(element["id"])
    return ids_by_page


def _rebuild_routed_pages(
    primary_doc: dict[str, Any],
    secondary_doc: dict[str, Any],
    elements: list[dict[str, Any]],
    routed: AbstractSet[int],
) -> list[dict[str, Any]]:
    page_descriptors = {
        descriptor["page_number"]: dict(descriptor)
        for descriptor in primary_doc.get("pages") or []
        if isinstance(descriptor, dict) and isinstance(descriptor.get("page_number"), int)
    }
    for descriptor in secondary_doc.get("pages") or []:
        if isinstance(descriptor, dict) and descriptor.get("page_number") in routed:
            page_descriptors.setdefault(descriptor["page_number"], dict(descriptor))

    ids_by_page = _page_element_ids(elements)
    for number, descriptor in page_descriptors.items():
        descriptor["element_ids"] = ids_by_page.get(number, [])
    return [page_descriptors[number] for number in sorted(page_descriptors)]


def normalize_element_ids(document: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of ``document`` with usable element ids and consistent pages.

    This is the normalization :func:`route_pages` applies to the payload it
    returns, exposed for callers that build a manifest from an extraction the
    routing never touches (#679). Every element without a usable ``id``
    (missing, empty or not a string) receives the deterministic page-scoped id,
    and each page's ``element_ids`` is rebuilt from the final elements.

    The input is never mutated: the returned document has copied elements and
    page descriptors when normalization is needed, so a caller can hand it to
    the manifest model while keeping the raw extraction intact. Payloads whose
    elements all carry a usable id get a shallow copy only, leaving their page
    membership exactly as the extractor wrote it. Malformed containers and
    non-object elements or page descriptors are kept for the model to reject.
    """
    raw_elements = document.get("elements")
    if not isinstance(raw_elements, list):
        return {**document}
    elements = [item for item in raw_elements if isinstance(item, dict)]
    if all(_has_usable_id(element) for element in elements):
        return {**document}
    copied: list[Any] = [
        dict(item) if isinstance(item, dict) else item for item in raw_elements
    ]
    objects: list[dict[str, Any]] = [
        item for item in copied if isinstance(item, dict)
    ]
    _normalize_missing_ids(objects)
    normalized: dict[str, Any] = {**document, "elements": copied}
    if isinstance(document.get("pages"), list):
        ids_by_page = _page_element_ids(objects)
        normalized["pages"] = [
            {**descriptor, "element_ids": ids_by_page.get(descriptor["page_number"], [])}
            if isinstance(descriptor, dict)
            and isinstance(descriptor.get("page_number"), int)
            else descriptor
            for descriptor in document["pages"]
        ]
    return normalized


def _updated_document_summary(
    primary_doc: dict[str, Any],
    page_count: int,
    elements: list[dict[str, Any]],
) -> dict[str, Any] | None:
    existing = primary_doc.get("summary")
    if not isinstance(existing, dict):
        return None
    type_counts = Counter(str(item.get("type")) for item in elements)
    return {
        **existing,
        "page_count": page_count,
        "element_count": len(elements),
        "element_types": dict(type_counts),
    }


def _applied_evidence(
    page_evidence: list[dict[str, Any]],
    routed: AbstractSet[Any],
    secondary_provider: str,
) -> list[dict[str, Any]]:
    """Copy ``page_evidence`` and mark the routed entries without touching the input."""
    updated: list[dict[str, Any]] = []
    for entry in page_evidence:
        copied = dict(entry)
        stats = entry.get("stats")
        if isinstance(stats, dict):
            stats = dict(stats)
            copied["stats"] = stats
        if entry.get("page_number") in routed:
            copied["stats"] = {
                **(stats if isinstance(stats, dict) else {}),
                "applied": secondary_provider,
            }
        updated.append(copied)
    return updated


def route_pages(
    primary_res: dict[str, Any],
    secondary_res: dict[str, Any],
    page_evidence: list[dict[str, Any]],
    *,
    secondary_provider: str,
) -> PageRouteResult:
    """Replace pages routed to ``"mineru"`` with adopted secondary elements.

    Returns a :class:`PageRouteResult` carrying the resulting payload (identical
    to ``primary_res`` when no page was routed), replaced primary elements by
    page, the sorted routed and missing page numbers, and a copy of
    ``page_evidence`` with ``stats["applied"] = secondary_provider`` on routed
    entries. ``page_evidence`` itself is never mutated (#633).

    Primary elements kept in the payload that have no usable ``id`` (missing,
    empty or not a string) receive a deterministic, page-scoped one
    (``element-p{page}-{position}``, or ``element-unpaged-{position}``), and
    ``page.element_ids`` is rebuilt from the final elements, so the routed
    payload stays a valid document for ``ProcessingManifest`` (#664). When no
    page is routed the payload is returned unchanged, id-less elements
    included.
    """
    primary_doc = primary_res.get("document") or {}
    secondary_doc = secondary_res.get("document") or {}
    secondary_by_page = _elements_by_page(secondary_doc.get("elements") or [])
    routed, missing = _select_routed_and_missing(page_evidence, secondary_by_page)
    updated_evidence = _applied_evidence(page_evidence, routed, secondary_provider)
    if not routed:
        return PageRouteResult(
            payload=primary_res,
            replaced={},
            routed_pages=(),
            missing_pages=missing,
            page_evidence=updated_evidence,
        )

    primary_elements = primary_doc.get("elements") or []
    primary_by_page = _elements_by_page(primary_elements)
    unpaged = [
        item
        for item in primary_elements
        if isinstance(item, dict) and _element_page_number(item) is None
    ]
    scales = page_scales(
        primary_doc.get("pages") or [], secondary_doc.get("pages") or [], routed
    )
    adopted = adopt_elements(
        {number: secondary_by_page[number] for number in routed},
        secondary_provider,
        scales,
    )
    elements, replaced = _merge_routed_elements(
        primary_by_page, unpaged, adopted, routed
    )
    _normalize_missing_ids(elements)
    rebuilt_pages = _rebuild_routed_pages(primary_doc, secondary_doc, elements, routed)

    document: dict[str, Any] = {
        **primary_doc,
        "elements": elements,
        "pages": rebuilt_pages,
    }
    summary = _updated_document_summary(primary_doc, len(rebuilt_pages), elements)
    if summary is not None:
        document["summary"] = summary

    return PageRouteResult(
        payload={**primary_res, "document": document},
        replaced=replaced,
        routed_pages=tuple(sorted(routed)),
        missing_pages=missing,
        page_evidence=updated_evidence,
    )


def apply_page_routes(
    primary_res: dict[str, Any],
    secondary_res: dict[str, Any],
    page_evidence: list[dict[str, Any]],
    *,
    secondary_provider: str,
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    """Convenience wrapper around :func:`route_pages` returning ``(payload, replaced)``.

    Use :func:`route_pages` directly when the annotated copy of ``page_evidence``
    is needed; this wrapper keeps the historical two-value return (#633).
    """
    result = route_pages(
        primary_res,
        secondary_res,
        page_evidence,
        secondary_provider=secondary_provider,
    )
    return result.payload, result.replaced


__all__ = [
    "STRUCTURAL_TYPES",
    "TEXT_KINDS",
    "PageRouteResult",
    "adopt_elements",
    "apply_page_routes",
    "element_to_canonical_block",
    "fuse_extraction_payloads",
    "group_payload_by_page",
    "normalize_element_ids",
    "page_content_signature",
    "page_scales",
    "page_similarity",
    "route_pages",
    "scaled_box",
    "structure_signature",
]
