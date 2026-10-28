"""Multi-provider fusion (Phase 4 of the docstruct plan).

Orchestration: toolbox extracts with two providers → docstruct.fusion
merges the blocks (Hungarian text+bbox alignment) → final canonical
document.

This layer is the only one that knows both the toolbox and the lib; the
lib stays pure. With FUSION_MODE=single (default) this module is not
engaged.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import Any

from rapidfuzz import fuzz

from backend.tools.logger import logger
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from backend.tools.toolbox_client import (
    ToolboxArtifactNotFound,
    ToolboxError,
    ToolboxProviderUnavailable,
    make_toolbox_client,
)
from docstruct.fusion import block_to_diff, merge_blocks
from docstruct.fusion.adjudication import decide_v1
from docstruct.fusion.judge import DEFAULT_MAX_RATIO
from docstruct.fusion.page_select import page_norm
from docstruct.fusion.types import DiffBlock
from docstruct.policy import FusionPolicy

#: Kinds whose text decides whether the two providers transcribed a page alike.
TEXT_KINDS = frozenset({"text", "heading", "title"})


def _element_to_canonical_block(el: dict, page_index: int) -> dict:
    """Processing manifest element → canonical block (dict) with bbox."""
    etype = str(el.get("type", "")).lower()
    text = (el.get("text") or "").strip()
    bbox = el.get("bbox")
    provenance = el.get("provenance") or []
    if not bbox and provenance:
        bbox = provenance[0].get("bbox")
    if isinstance(bbox, dict):
        bbox = [bbox.get(key) for key in ("left", "top", "right", "bottom")]
    block: dict[str, Any] = {
        "type": etype or "paragraph",
        "text": text,
        "metadata": {
            "reading_order": el.get("reading_order") or 0,
            "page_size": el.get("page_size"),
            "coord_origin": el.get("coord_origin") or "",
        },
    }
    if bbox and all(isinstance(v, (int, float)) for v in bbox):
        block["bbox"] = [float(v) for v in bbox]
        block["page_index"] = page_index
    return block


def _payload_to_blocks(payload: dict) -> list[dict]:
    """Extract the canonical block list (dict) from an extraction payload.

    Supports the processing manifest shape (document.elements ordered by
    reading_order). Payloads without usable elements return an empty list.
    """
    doc = payload.get("document", payload)
    elements = doc.get("elements") or []
    blocks: list[dict] = []
    page = 0
    for el in sorted(elements, key=lambda e: e.get("reading_order") or 0):
        text = (el.get("text") or "").strip()
        if not text:
            continue
        blocks.append(_element_to_canonical_block(el, el.get("page") or page))
    return blocks


def _blocks_to_text(blocks: list[dict]) -> str:
    """Serialize merged blocks into simple markdown (heading + body)."""
    parts: list[str] = []
    for b in blocks:
        etype = b["type"]
        text = b["text"]
        if etype in ("heading", "title", "section_header"):
            level = int(b["metadata"].get("hierarchy_level") or 1)
            parts.append(f"{'#' * max(1, min(level, 6))} {text}")
        else:
            parts.append(text)
    return "\n\n".join(parts)


def _structure_client(provider: str) -> ToolboxStructureClient:
    """A structure-extraction client for ``provider``, configured from settings."""
    return make_toolbox_client(ToolboxStructureClient, provider=provider)


async def extract_fused(
    file_path,
    *,
    language: str = "pt-BR",
    policy: FusionPolicy | None = None,
    primary_provider: str | None = None,
    secondary_provider: str | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Extract with the primary + secondary providers and merge the results.

    Returns a payload in the same shape as ``extract_structure`` (document
    with elements), so it plugs into the existing canonical bridge without
    changes to consumers.

    When ``artifact_id`` names the document already stored in the Toolbox, both
    providers read it from there instead of receiving a new upload each; if the
    Toolbox no longer has it, the file is sent as before.

    Transient failures (timeouts, unavailable instances) are retried by the
    SDK client (``TOOLBOX_RETRIES``, docs/adr/0006); invalid requests are not
    repeated.

    Fallback: if one provider reports a Toolbox error, uses the other result
    and logs which provider failed. Unexpected errors are propagated.
    """
    from backend.config.settings import settings

    policy = policy or FusionPolicy()
    primary = primary_provider or settings.toolbox_provider
    secondary = secondary_provider or settings.fusion_secondary_provider

    failures: dict[str, Exception] = {}

    async def _extract(provider: str) -> dict | None:
        client = _structure_client(provider)
        try:
            if artifact_id:
                try:
                    return await client.extract_structure(
                        artifact_id=artifact_id,
                        language=language,
                        use_remote_cache=settings.toolbox_use_remote_cache,
                    )
                except ToolboxArtifactNotFound:
                    logger.info(
                        "Fusion: artifact {} not in the Toolbox; uploading for {}",
                        artifact_id,
                        provider,
                    )
            return await client.extract_structure(
                file_path,
                language=language,
                use_remote_cache=settings.toolbox_use_remote_cache,
            )
        except ToolboxError as exc:
            failures[provider] = exc
            logger.info("Fusion: provider {} failed ({})", provider, type(exc).__name__)
            return None
        finally:
            await client.close()

    primary_res, secondary_res = await asyncio.gather(
        _extract(primary), _extract(secondary)
    )
    if primary_res is None and secondary_res is None:
        raise ToolboxProviderUnavailable("No provider available for extraction")
    if primary_res is None:
        return secondary_res
    if secondary_res is None:
        return primary_res

    return fuse_extraction_payloads(
        primary_res,
        secondary_res,
        primary_provider=primary,
        secondary_provider=secondary,
        policy=policy,
    )


def fuse_extraction_payloads(
    primary_res: dict[str, Any],
    secondary_res: dict[str, Any],
    *,
    primary_provider: str,
    secondary_provider: str,
    policy: FusionPolicy | None = None,
) -> dict[str, Any]:
    """Fuse two already-extracted payloads and return output plus evidence."""
    policy = policy or FusionPolicy()
    stats: Counter = Counter()
    merged_page_blocks: list[tuple[int, str]] = []
    page_evidence: list[dict[str, Any]] = []
    # Group by page when the payload carries pages; otherwise treat as 1 page.
    pages_d = _group_by_page(primary_res)
    pages_m = _group_by_page(secondary_res)
    from docstruct.fusion.repetition import guard_page

    for page_key in sorted(set(pages_d) | set(pages_m)):
        # Text alignment and structural presence are separate evidence. Empty
        # figures/tables must survive comparison without becoming paragraphs.
        d_blocks = [_canonical_to_diff(b) for b in pages_d.get(page_key, []) if b["text"]]
        m_blocks = [_canonical_to_diff(b) for b in pages_m.get(page_key, []) if b["text"]]
        page_stats: Counter = Counter()
        m_pics = [
            diff.box
            for b in pages_m.get(page_key, [])
            if b["type"] == "picture" and "bbox" in b
            if (diff := _canonical_to_diff(b)).box is not None
        ]
        out, page_stats = merge_blocks(
            d_blocks, m_blocks, policy, min_len=0, m_pics=m_pics, stats=page_stats
        )
        stats.update(page_stats)
        docling_text = "\n\n".join(block.md for block in d_blocks)
        mineru_text = "\n\n".join(block.md for block in m_blocks)

        guarded_blocks: list[str] = []
        repetition_tokens_cut = 0
        for block_text in out:
            guarded, cut, _ = guard_page(
                block_text, docling_text, mineru_text
            )
            guarded_blocks.append(guarded)
            repetition_tokens_cut += cut
        out = guarded_blocks
        evidence_stats = dict(page_stats)
        evidence_stats["provider_count"] = 2
        # Divergence is a similarity below the judge's own gate (should_judge,
        # 0.97, on the same character scale), not inequality: two extractors
        # almost never agree on every token or block label, and exact comparison
        # flagged nearly every page, each one becoming adjudication and fusion
        # work.
        similarity = _similarity(docling_text, mineru_text)
        text_similarity = _similarity(
            "\n\n".join(b.text for b in d_blocks if b.kind in TEXT_KINDS),
            "\n\n".join(b.text for b in m_blocks if b.kind in TEXT_KINDS),
        )
        evidence_stats["similarity"] = round(similarity, 4)
        evidence_stats["text_similarity"] = round(text_similarity, 4)
        structure_d = _structure_signature(pages_d.get(page_key, []))
        structure_m = _structure_signature(pages_m.get(page_key, []))
        evidence_stats["structure_divergence"] = structure_d != structure_m
        evidence_stats["structure_counts"] = {
            primary_provider: dict(Counter(b["type"] for b in pages_d.get(page_key, []) if b["type"] in STRUCTURAL_TYPES)),
            secondary_provider: dict(Counter(b["type"] for b in pages_m.get(page_key, []) if b["type"] in STRUCTURAL_TYPES)),
        }
        evidence_stats["provider_divergence"] = similarity < DEFAULT_MAX_RATIO or structure_d != structure_m
        evidence_stats["text_divergence"] = text_similarity < DEFAULT_MAX_RATIO
        # Deterministic adjudication (docstruct's v1 page router), recorded with
        # the evidence so the manifest builder can leave the VLM judge for the
        # pages the rule cannot settle.
        route, route_reason = decide_v1(docling_text, mineru_text)
        # Structural evidence complements the deterministic text/table/formula
        # rules; it must not override their near-empty or explicit table/formula
        # decisions. Bounding boxes are provider-specific, so compare type and
        # normalized content instead of exact coordinates.
        if structure_d != structure_m and route_reason == "default_docling":
            def structure_content(blocks: list[dict]) -> Counter:
                return Counter(
                    (b["type"], " ".join((b.get("text") or "").split()))
                    for b in blocks if b["type"] in STRUCTURAL_TYPES
                )

            primary_content = structure_content(pages_d.get(page_key, []))
            secondary_content = structure_content(pages_m.get(page_key, []))
            primary_structure_counts = Counter(
                b["type"] for b in pages_d.get(page_key, []) if b["type"] in STRUCTURAL_TYPES
            )
            secondary_structure_counts = Counter(
                b["type"] for b in pages_m.get(page_key, []) if b["type"] in STRUCTURAL_TYPES
            )
            secondary_adds_structure = bool(
                secondary_structure_counts - primary_structure_counts
            )
            if (
                secondary_adds_structure
                and not primary_content - secondary_content
                and text_similarity >= DEFAULT_MAX_RATIO
            ):
                route, route_reason = "mineru", "secondary_structure_superset"
            else:
                route, route_reason = "docling", "structure_ambiguous"
        evidence_stats["route"] = route
        evidence_stats["route_reason"] = route_reason
        evidence_stats["table_divergence"] = (
            _page_content_signature(d_blocks, kinds={"table"})
            != _page_content_signature(m_blocks, kinds={"table"})
            or _structure_signature(pages_d.get(page_key, []), kinds={"table"})
            != _structure_signature(pages_m.get(page_key, []), kinds={"table"})
        )
        if repetition_tokens_cut:
            evidence_stats["repetition_tokens_cut"] = repetition_tokens_cut
            stats["repetition_tokens_cut"] += repetition_tokens_cut
        page_evidence.append(
            {"page_number": page_key + 1, "stats": evidence_stats}
        )
        merged_page_blocks.extend((page_key, block) for block in out)

    logger.info(
        "Fusion done: {} final blocks, decisions: {}",
        len(merged_page_blocks),
        dict(stats),
    )
    return {
        "status": "succeeded",
        "provider": f"{primary_provider}+{secondary_provider}",
        "document": {
            "elements": [
                {
                    "type": "paragraph",
                    "text": md,
                    "reading_order": i + 1,
                    "page": page_key,
                    "page_number": page_key + 1,
                }
                for i, (page_key, md) in enumerate(merged_page_blocks)
            ]
        },
        "fusion_stats": dict(stats),
        "fusion_evidence": {"pages": page_evidence},
    }


def _canonical_to_diff(block: dict):
    """Canonical block (dict) → lib DiffBlock."""
    from docstruct.types import CanonicalBlock

    return block_to_diff(CanonicalBlock(**_canon_kwargs(block)))


def apply_page_routes(
    primary_res: dict[str, Any],
    secondary_res: dict[str, Any],
    page_evidence: list[dict[str, Any]],
    *,
    secondary_provider: str,
) -> tuple[dict[str, Any], dict[int, list[dict[str, Any]]]]:
    """Put the secondary provider's page where the deterministic router prefers it.

    ``decide_v1`` names its second candidate "mineru": it routes a page there
    when the primary side is nearly empty, when only the secondary found a table
    or a formula, or when both did (MinerU's tables scored higher in the
    experiments: TEDS 62.3 against 39.1). Text pages stay with the primary
    provider, which scored higher on running text.

    Returns the payload the manifest is built from and, for each replaced page,
    the primary elements it replaced, kept so the VLM judge can compare the two.
    The secondary elements get ids of their own (both providers number from 1),
    ``metadata.provider`` and boxes in the primary page's frame; reading order
    is renumbered across the document. Without a routed page, the primary
    payload is returned unchanged.
    """
    primary_doc = primary_res.get("document") or {}
    secondary_doc = secondary_res.get("document") or {}
    secondary_by_page = _elements_by_page(secondary_doc.get("elements") or [])
    preferred = {
        page.get("page_number")
        for page in page_evidence
        if (page.get("stats") or {}).get("route") == "mineru"
    }
    routed = {number for number in preferred if secondary_by_page.get(number)}
    if preferred - routed:
        logger.warning(
            "Fusion: {} has no elements on pages {} the router sent to it; "
            "they stay with the primary provider",
            secondary_provider,
            sorted(preferred - routed, key=str),
        )
    if not routed:
        return primary_res, {}

    primary_by_page = _elements_by_page(primary_doc.get("elements") or [])
    unpaged = [
        element for element in primary_doc.get("elements") or []
        if isinstance(element, dict) and _element_page_number(element) is None
    ]
    scales = _page_scales(
        primary_doc.get("pages") or [], secondary_doc.get("pages") or [], routed
    )
    adopted = _adopt_elements(
        {number: secondary_by_page[number] for number in routed},
        secondary_provider,
        scales,
    )
    replaced: dict[int, list[dict[str, Any]]] = {}
    elements: list[dict[str, Any]] = []
    for page_number in sorted(set(primary_by_page) | routed):
        if page_number in routed:
            replaced[page_number] = primary_by_page.get(page_number, [])
            elements.extend(adopted[page_number])
        else:
            elements.extend(dict(element) for element in primary_by_page[page_number])
    elements.extend(dict(element) for element in unpaged)
    for order, element in enumerate(elements, start=1):
        element["reading_order"] = order
    for page in page_evidence:
        if page.get("page_number") in routed:
            page.setdefault("stats", {})["applied"] = secondary_provider

    pages = {
        page["page_number"]: dict(page)
        for page in primary_doc.get("pages") or []
        if isinstance(page, dict) and isinstance(page.get("page_number"), int)
    }
    for page in secondary_doc.get("pages") or []:
        if isinstance(page, dict) and page.get("page_number") in routed:
            pages.setdefault(page["page_number"], dict(page))
    for number, page in pages.items():
        page["element_ids"] = [
            element["id"] for element in elements if _element_page_number(element) == number
        ]
    document = {
        **primary_doc,
        "elements": elements,
        "pages": [pages[number] for number in sorted(pages)],
    }
    if isinstance(primary_doc.get("summary"), dict):
        document["summary"] = {
            **primary_doc["summary"],
            "page_count": len(pages),
            "element_count": len(elements),
            "element_types": dict(Counter(str(e.get("type")) for e in elements)),
        }
    logger.info(
        "Fusion: {} pages taken from {} by the deterministic router: {}",
        len(routed),
        secondary_provider,
        sorted(routed),
    )
    return {**primary_res, "document": document}, replaced


def _element_page_number(element: dict[str, Any]) -> int | None:
    """1-based page of a payload element, read like ``_group_by_page`` reads it.

    The fusion evidence numbers pages this way, so routing has to as well: a
    payload carrying only the 0-based ``page`` would otherwise match no route.
    """
    page = element.get("page_number")
    if isinstance(page, int):
        return page
    page = element.get("page")
    return page + 1 if isinstance(page, int) else None


def _elements_by_page(elements: list[Any]) -> dict[int, list[dict[str, Any]]]:
    by_page: dict[int, list[dict[str, Any]]] = {}
    for element in sorted(
        (e for e in elements if isinstance(e, dict)),
        key=lambda e: e.get("reading_order") or 0,
    ):
        page = _element_page_number(element)
        if page is not None:
            by_page.setdefault(page, []).append(element)
    return by_page


def _page_scales(
    primary_pages: list[Any], secondary_pages: list[Any], routed: set[int]
) -> dict[int, tuple[float, float]]:
    """Factors taking a routed page's secondary boxes into the primary page frame.

    The manifest keeps the primary page descriptor, and its boxes are normalised
    against that page's size downstream, so a provider rendering the page at
    another size would otherwise misplace every adopted box.
    """

    def sizes(pages: list[Any]) -> dict[int, tuple[float, float]]:
        return {
            page["page_number"]: (float(page["width"]), float(page["height"]))
            for page in pages
            if isinstance(page, dict)
            and page.get("page_number") in routed
            and isinstance(page.get("width"), (int, float))
            and isinstance(page.get("height"), (int, float))
            and page["width"] > 0
            and page["height"] > 0
        }

    primary, secondary = sizes(primary_pages), sizes(secondary_pages)
    return {
        number: (primary[number][0] / width, primary[number][1] / height)
        for number, (width, height) in secondary.items()
        if number in primary and primary[number] != (width, height)
    }


def _scaled_box(box: Any, scale: tuple[float, float]) -> Any:
    sx, sy = scale
    if isinstance(box, dict):
        return {
            **box,
            **{
                key: box[key] * (sx if key in {"left", "right"} else sy)
                for key in ("left", "top", "right", "bottom")
                if isinstance(box.get(key), (int, float))
            },
        }
    if isinstance(box, (list, tuple)) and len(box) == 4 and all(
        isinstance(value, (int, float)) for value in box
    ):
        return [box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy]
    return box


def _adopt_elements(
    pages: dict[int, list[dict[str, Any]]],
    provider: str,
    scales: dict[int, tuple[float, float]],
) -> dict[int, list[dict[str, Any]]]:
    """Copies of the routed secondary pages' elements, ready for the manifest.

    Ids are mapped across all routed pages before parents are, so a group that
    spans two taken pages keeps its parent; a parent on a page that was not
    taken is dropped. An element without an id gets one from its page and
    position, unique in the document.
    """
    ids = {
        element["id"]: f"{provider}-{element['id']}"
        for elements in pages.values()
        for element in elements
        if element.get("id")
    }
    adopted: dict[int, list[dict[str, Any]]] = {}
    for number, elements in pages.items():
        scale = scales.get(number)
        copies = []
        for position, element in enumerate(elements, start=1):
            copy = dict(element)
            copy["id"] = ids.get(element.get("id"), f"{provider}-p{number}-{position}")
            copy["parent_id"] = ids.get(element.get("parent_id"))
            copy["metadata"] = {**(element.get("metadata") or {}), "provider": provider}
            if scale is not None:
                if "bbox" in copy:
                    copy["bbox"] = _scaled_box(copy["bbox"], scale)
                if isinstance(copy.get("provenance"), list):
                    copy["provenance"] = [
                        {**item, "bbox": _scaled_box(item["bbox"], scale)}
                        if isinstance(item, dict) and item.get("bbox") is not None
                        else item
                        for item in copy["provenance"]
                    ]
            copies.append(copy)
        adopted[number] = copies
    return adopted


def _similarity(a: str, b: str) -> float:
    """Character similarity in ``[0, 1]`` of two page transcriptions.

    The metric ``should_judge`` compares with 0.97: docstruct's ``ratio``
    (character LCS over ``page_norm``), which equals ``rapidfuzz.fuzz.ratio``.
    docstruct's own implementation is pure Python and takes about 2 s on a
    3,500-character page; rapidfuzz takes well under a millisecond, so the
    evidence and the judge agree on which pages diverge.
    """
    norm_a, norm_b = page_norm(a), page_norm(b)
    if not norm_a and not norm_b:
        return 1.0
    if not norm_a or not norm_b:
        return 0.0
    return fuzz.ratio(norm_a, norm_b) / 100


def _page_content_signature(
    blocks: list[DiffBlock],
    *,
    kinds: set[str] | None = None,
) -> list[tuple[str, str]]:
    from docstruct.fusion.repetition import token_norm

    return sorted(
        (block.kind, token)
        for block in blocks
        if kinds is None or block.kind in kinds
        for token in token_norm(block.text).split()
    )


def _canon_kwargs(block: dict) -> dict:
    bbox = block.get("bbox")
    return {
        "id": str(block.get("metadata", {}).get("reading_order", 0)),
        "type": block["type"],
        "text": block["text"],
        "bbox": tuple(bbox) if bbox else None,
        "page_index": block.get("page_index"),
        "metadata": block.get("metadata", {}),
    }


STRUCTURAL_TYPES = {"picture", "table", "formula"}


def _structure_signature(
    blocks: list[dict], *, kinds: set[str] = STRUCTURAL_TYPES
) -> list[tuple[str, int]]:
    """Count structural elements by kind without comparing provider-specific boxes."""
    return sorted(Counter(b["type"] for b in blocks if b["type"] in kinds).items())


def _group_by_page(payload: dict) -> dict[int, list[dict]]:
    """Group payload elements by page (default: page 0)."""
    doc = payload.get("document", payload)
    groups: dict[int, list[dict]] = {}
    for el in doc.get("elements") or []:
        if not (el.get("text") or "").strip() and el.get("type") not in STRUCTURAL_TYPES:
            continue
        if el.get("page_number") is not None:
            page = max(0, int(el["page_number"]) - 1)
        else:
            page = int(el.get("page") or 0)
        groups.setdefault(page, []).append(_element_to_canonical_block(el, page))
    return groups
