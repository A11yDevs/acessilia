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

from backend.tools.logger import logger
from backend.tools.toolbox_client import (
    ToolboxClient,
    ToolboxProviderUnavailable,
)
from docstruct.fusion import block_to_diff, merge_blocks
from docstruct.policy import FusionPolicy


def _element_to_canonical_block(el: dict, page_index: int) -> dict:
    """Processing manifest element → canonical block (dict) with bbox."""
    etype = str(el.get("type", "")).lower()
    text = (el.get("text") or "").strip()
    bbox = el.get("bbox")
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


async def extract_fused(
    file_path,
    *,
    language: str = "pt-BR",
    policy: FusionPolicy | None = None,
    primary_provider: str | None = None,
    secondary_provider: str | None = None,
) -> dict[str, Any]:
    """Extract with the primary + secondary providers and merge the results.

    Returns a payload in the same shape as ``extract_structure`` (document
    with elements), so it plugs into the existing canonical bridge without
    changes to consumers.

    Fallback: if the secondary provider fails (unavailable, contract
    error), silently uses only the primary (info log).
    """
    from backend.config.settings import settings

    policy = policy or FusionPolicy()
    primary = primary_provider or settings.toolbox_provider
    secondary = secondary_provider or settings.fusion_secondary_provider

    async def _extract(provider: str) -> dict | None:
        client = ToolboxClient(provider=provider)
        try:
            return await client.extract_structure(file_path, language=language)
        except (ToolboxProviderUnavailable, Exception) as exc:  # noqa: BLE001
            logger.info("Fusion: provider {} failed ({})", provider, type(exc).__name__)
            return None

    primary_res, secondary_res = await asyncio.gather(
        _extract(primary), _extract(secondary)
    )
    if primary_res is None and secondary_res is None:
        raise ToolboxProviderUnavailable("No provider available for extraction")
    if primary_res is None:
        return secondary_res
    if secondary_res is None:
        return primary_res

    stats: Counter = Counter()
    merged_blocks: list[str] = []
    # Group by page when the payload carries pages; otherwise treat as 1 page.
    pages_d = _group_by_page(primary_res)
    pages_m = _group_by_page(secondary_res)
    for page_key in sorted(set(pages_d) | set(pages_m)):
        d_blocks = [_canonical_to_diff(b) for b in pages_d.get(page_key, [])]
        m_blocks = [_canonical_to_diff(b) for b in pages_m.get(page_key, [])]
        m_pics = [
            b["bbox"] for b in pages_m.get(page_key, [])
            if b["type"] == "picture" and "bbox" in b
        ]
        out, page_stats = merge_blocks(
            d_blocks, m_blocks, policy, min_len=0, m_pics=m_pics, stats=stats
        )
        stats.update(page_stats)
        merged_blocks.extend(out)

    logger.info(
        "Fusion done: {} final blocks, decisions: {}",
        len(merged_blocks),
        dict(stats),
    )
    return {
        "status": "succeeded",
        "provider": f"{primary}+{secondary}",
        "document": {
            "elements": [
                {"type": "paragraph", "text": md, "reading_order": i}
                for i, md in enumerate(merged_blocks)
            ]
        },
        "fusion_stats": dict(stats),
    }


def _canonical_to_diff(block: dict):
    """Canonical block (dict) → lib DiffBlock."""
    from docstruct.types import CanonicalBlock

    return block_to_diff(CanonicalBlock(**_canon_kwargs(block)))


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


def _group_by_page(payload: dict) -> dict[int, list[dict]]:
    """Group payload elements by page (default: page 0)."""
    doc = payload.get("document", payload)
    groups: dict[int, list[dict]] = {}
    for el in doc.get("elements") or []:
        if not (el.get("text") or "").strip():
            continue
        page = int(el.get("page") or 0)
        groups.setdefault(page, []).append(_element_to_canonical_block(el, page))
    return groups
