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
from acessilia_sdk.toolbox.clients import ToolboxStructureClient
from backend.tools.toolbox_client import (
    ToolboxArtifactNotFound,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    make_toolbox_client,
)
from docstruct.fusion import block_to_diff, merge_blocks
from docstruct.fusion.types import DiffBlock
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

    Retry a transient timeout/unavailability once, after both initial calls
    finish. Successful extractions and invalid requests are not repeated.

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
                        artifact_id=artifact_id, language=language
                    )
                except ToolboxArtifactNotFound:
                    logger.info(
                        "Fusion: artifact {} not in the Toolbox; uploading for {}",
                        artifact_id,
                        provider,
                    )
            return await client.extract_structure(file_path, language=language)
        except ToolboxError as exc:
            failures[provider] = exc
            logger.info("Fusion: provider {} failed ({})", provider, type(exc).__name__)
            return None
        finally:
            await client.close()

    primary_res, secondary_res = await asyncio.gather(
        _extract(primary), _extract(secondary)
    )

    async def _retry_transient(provider: str, result: dict | None) -> dict | None:
        error = failures.get(provider)
        if result is None and isinstance(
            error, (ToolboxTimeout, ToolboxProviderUnavailable)
        ):
            logger.info(
                "Fusion: retrying provider {} once after transient {}",
                provider,
                type(error).__name__,
            )
            await asyncio.sleep(0.25)
            return await _extract(provider)
        return result

    primary_res, secondary_res = await asyncio.gather(
        _retry_transient(primary, primary_res),
        _retry_transient(secondary, secondary_res),
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
        d_blocks = [_canonical_to_diff(b) for b in pages_d.get(page_key, [])]
        m_blocks = [_canonical_to_diff(b) for b in pages_m.get(page_key, [])]
        page_stats: Counter = Counter()
        m_pics = [
            b["bbox"]
            for b in pages_m.get(page_key, [])
            if b["type"] == "picture" and "bbox" in b
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
        evidence_stats["provider_divergence"] = (
            _page_content_signature(d_blocks)
            != _page_content_signature(m_blocks)
        )
        evidence_stats["text_divergence"] = (
            _page_content_signature(
                d_blocks, kinds={"text", "heading", "title"}
            )
            != _page_content_signature(
                m_blocks, kinds={"text", "heading", "title"}
            )
        )
        evidence_stats["table_divergence"] = (
            _page_content_signature(d_blocks, kinds={"table"})
            != _page_content_signature(m_blocks, kinds={"table"})
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


def _group_by_page(payload: dict) -> dict[int, list[dict]]:
    """Group payload elements by page (default: page 0)."""
    doc = payload.get("document", payload)
    groups: dict[int, list[dict]] = {}
    for el in doc.get("elements") or []:
        if not (el.get("text") or "").strip():
            continue
        if el.get("page_number") is not None:
            page = max(0, int(el["page_number"]) - 1)
        else:
            page = int(el.get("page") or 0)
        groups.setdefault(page, []).append(_element_to_canonical_block(el, page))
    return groups
