"""Dual-provider fusion and VLM-judge need detectors for processing manifests."""

from __future__ import annotations

from typing import Any

from acessilia_core.manifest.detectors.types import VLM_JUDGE_METHODS, NeedCandidate
from acessilia_core.manifest.models import ManifestElement


def needs_vlm_judge(stats: dict[str, Any]) -> bool:
    """Whether the deterministic router leaves the page to the VLM judge.

    ``decide_v1`` settles a page from a structural fact (one side nearly empty,
    a table or formula only one provider found) or keeps docling by default;
    only its preference rules, where both providers have a table or a formula
    (``both_table->mineru``, ``both_formula->mineru``), are worth a model call,
    and only when the two pages differ (``provider_divergence``, over all the
    page's content: ``text_divergence`` leaves tables and formulas out, so a
    page whose prose matches and whose tables differ would never be judged).
    Evidence recorded before the router ran has no ``route`` and stays eligible
    on ``text_divergence``, as before.
    """
    route = stats.get("route")
    if route is None:
        return bool(stats.get("text_divergence"))
    if stats.get("route_reason") == "structure_ambiguous":
        return True
    return (
        bool(stats.get("provider_divergence"))
        and route != "docling"
        and str(stats.get("route_reason", "")).startswith("both_")
    )


def pages_for_vlm_judge(
    entries: list[tuple[int, dict[str, Any], list[ManifestElement]]],
    budget: int,
) -> set[int]:
    """The ``budget`` ambiguous pages the providers disagree on the most.

    Ranked by ``similarity``, the measure ``needs_vlm_judge`` gates on
    (``text_similarity`` for evidence recorded before the router ran).
    """
    ambiguous = sorted(
        (
            float(
                stats.get("similarity" if "route" in stats else "text_similarity", 0.0)
            ),
            page_number,
        )
        for page_number, stats, _ in entries
        if isinstance(page_number, int) and needs_vlm_judge(stats)
    )
    return {page_number for _, page_number in ambiguous[: max(budget, 0)]}


def detect_page_fusion_needs(
    targets: list[ManifestElement],
    stats: dict[str, Any],
    page_number: int | None,
    *,
    judge: bool,
) -> list[NeedCandidate]:
    """Per-page fusion needs; ``fuse-providers`` is emitted once by the caller."""
    if not stats:
        return []
    candidates: list[NeedCandidate] = []
    if judge:
        candidates.append(
            NeedCandidate(
                "adjudicate-page",
                targets,
                {"page_number": page_number, "fusion_stats": stats},
                methods=VLM_JUDGE_METHODS,
            )
        )
    elif stats.get("route_reason") == "structure_ambiguous":
        candidates.append(
            NeedCandidate(
                "adjudicate-page",
                targets,
                {"page_number": page_number, "fusion_stats": stats},
                methods=["human-review"],
            )
        )
    if any(key.startswith("dropped-") and value for key, value in stats.items()):
        candidates.append(
            NeedCandidate(
                "rescue-omitted-block",
                targets,
                {"page_number": page_number, "fusion_stats": stats},
            )
        )
    if stats.get("table_divergence"):
        table_targets = [item for item in targets if item.type == "table"]
        if table_targets:
            candidates.append(
                NeedCandidate(
                    "select-table-source",
                    table_targets,
                    {"page_number": page_number, "fusion_stats": stats},
                )
            )
    cut_count = stats.get("repetition_tokens_cut", 0)
    if cut_count:
        candidates.append(
            NeedCandidate(
                "guard-repetition",
                targets,
                {"page_number": page_number, "tokens_cut": cut_count},
            )
        )
    return candidates


def detect_fusion_needs(
    elements: list[ManifestElement],
    by_page: dict[int | None, list[ManifestElement]],
    *,
    fusion_evidence: Any = None,
    fusion_stats: Any = None,
    fusion_judge_max_pages: int = 0,
) -> list[NeedCandidate]:
    """Emit page-level and document-level fusion needs from dual-provider evidence."""
    if isinstance(fusion_evidence, dict):
        return _detect_paged_fusion_needs(
            fusion_evidence.get("pages"),
            by_page,
            fusion_judge_max_pages=fusion_judge_max_pages,
        )
    if isinstance(fusion_stats, dict):
        return _detect_document_fusion_needs(
            elements,
            fusion_stats,
            fusion_judge_max_pages=fusion_judge_max_pages,
        )
    return []


def _detect_paged_fusion_needs(
    pages: Any,
    by_page: dict[int | None, list[ManifestElement]],
    *,
    fusion_judge_max_pages: int,
) -> list[NeedCandidate]:
    if not isinstance(pages, list):
        return []
    entries = _collect_page_entries(pages, by_page)
    judged = pages_for_vlm_judge(entries, fusion_judge_max_pages)
    candidates: list[NeedCandidate] = []
    fused_targets: list[ManifestElement] = []
    fused_pages: list[int] = []
    for page_number, page_stats, page_targets in entries:
        candidates.extend(
            detect_page_fusion_needs(
                page_targets,
                page_stats,
                page_number,
                judge=page_number in judged,
            )
        )
        if page_stats.get("provider_divergence"):
            fused_targets.extend(page_targets)
            fused_pages.append(page_number)
    # One obligation per document: each fuse-providers step works on the
    # whole document, so one per page repeated the same extraction.
    if fused_targets:
        candidates.append(
            NeedCandidate("fuse-providers", fused_targets, {"pages": fused_pages})
        )
    return candidates


def _collect_page_entries(
    pages: list[Any],
    by_page: dict[int | None, list[ManifestElement]],
) -> list[tuple[int, dict[str, Any], list[ManifestElement]]]:
    entries: list[tuple[int, dict[str, Any], list[ManifestElement]]] = []
    for page_data in pages:
        if not isinstance(page_data, dict):
            continue
        page_stats = page_data.get("stats")
        page_number = page_data.get("page_number")
        if not isinstance(page_number, int):
            continue
        page_targets = by_page.get(page_number, [])
        if not isinstance(page_stats, dict) or not page_targets:
            continue
        entries.append((page_number, page_stats, page_targets))
    return entries


def _detect_document_fusion_needs(
    elements: list[ManifestElement],
    stats: dict[str, Any],
    *,
    fusion_judge_max_pages: int,
) -> list[NeedCandidate]:
    targets = [element for element in elements if element.text]
    if not targets:
        return []
    candidates = detect_page_fusion_needs(
        targets,
        stats,
        None,
        judge=fusion_judge_max_pages > 0 and needs_vlm_judge(stats),
    )
    if stats.get("provider_divergence"):
        candidates.append(
            NeedCandidate(
                "fuse-providers",
                targets,
                {"page_number": None, "fusion_stats": stats},
            )
        )
    return candidates
