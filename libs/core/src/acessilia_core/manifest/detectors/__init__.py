"""Pure document-need detectors that feed the PDDL planner.

Each detector inspects elements (and optional page sizes or dual-provider
fusion evidence) and yields :class:`NeedCandidate` values without mutating the
manifest. :func:`inspect_document_needs` runs the full set and materializes
deduplicated :class:`Observation` and :class:`Obligation` lists.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from acessilia_core.manifest.detectors.fusion import (
    detect_fusion_needs,
    detect_page_fusion_needs,
    needs_vlm_judge,
    pages_for_vlm_judge,
)
from acessilia_core.manifest.detectors.layout import (
    detect_line_numbers_need,
    detect_page_layout_needs,
    detect_reading_order_need,
    detect_tail_join_need,
    detect_verse_chunk_need,
)
from acessilia_core.manifest.detectors.text import (
    TEXT_NORMALIZATION_ELEMENT_TYPES,
    UNICODE_REPAIR_ELEMENT_TYPES,
    detect_legacy_unicode_needs,
    detect_text_and_formula_normalizations,
    unicode_repair_text,
)
from acessilia_core.manifest.detectors.types import (
    MAX_ID_SUFFIX,
    VLM_JUDGE_METHODS,
    NeedCandidate,
    PageSizes,
    materialize_needs,
    normalized_element_bbox,
    obligation_suffix,
    oriented_bbox,
)
from acessilia_core.manifest.models import ManifestElement, Obligation, Observation


def collect_document_needs(
    elements: list[ManifestElement],
    *,
    page_sizes: PageSizes | None = None,
    fusion_evidence: Any = None,
    fusion_stats: Any = None,
    fusion_judge_max_pages: int = 0,
    legacy_unicode_repair: str = "off",
) -> list[NeedCandidate]:
    """Run every document detector and return raw need candidates in canonical order."""
    by_page: dict[int | None, list[ManifestElement]] = {}
    for element in elements:
        by_page.setdefault(element.page_number, []).append(element)

    candidates: list[NeedCandidate] = []
    candidates.extend(detect_text_and_formula_normalizations(elements))
    candidates.extend(
        detect_legacy_unicode_needs(
            elements, legacy_unicode_repair=legacy_unicode_repair
        )
    )
    candidates.extend(detect_page_layout_needs(by_page, page_sizes=page_sizes))
    candidates.extend(
        detect_fusion_needs(
            elements,
            by_page,
            fusion_evidence=fusion_evidence,
            fusion_stats=fusion_stats,
            fusion_judge_max_pages=fusion_judge_max_pages,
        )
    )
    return candidates


def inspect_document_needs(
    elements: list[ManifestElement],
    *,
    obligation_specs: Mapping[str, tuple[str, list[str]]],
    method_costs: Mapping[str, int],
    page_sizes: PageSizes | None = None,
    fusion_evidence: Any = None,
    fusion_stats: Any = None,
    fusion_judge_max_pages: int = 0,
    legacy_unicode_repair: str = "off",
    secondary_extraction_available: bool = False,
) -> tuple[list[Observation], list[Obligation]]:
    """Inspect document elements and fusion evidence to emit observations and obligations."""
    candidates = collect_document_needs(
        elements,
        page_sizes=page_sizes,
        fusion_evidence=fusion_evidence,
        fusion_stats=fusion_stats,
        fusion_judge_max_pages=fusion_judge_max_pages,
        legacy_unicode_repair=legacy_unicode_repair,
    )
    return materialize_needs(
        candidates,
        obligation_specs=obligation_specs,
        method_costs=method_costs,
        secondary_extraction_available=secondary_extraction_available,
    )


__all__ = [
    "MAX_ID_SUFFIX",
    "TEXT_NORMALIZATION_ELEMENT_TYPES",
    "UNICODE_REPAIR_ELEMENT_TYPES",
    "VLM_JUDGE_METHODS",
    "NeedCandidate",
    "PageSizes",
    "collect_document_needs",
    "detect_fusion_needs",
    "detect_legacy_unicode_needs",
    "detect_line_numbers_need",
    "detect_page_fusion_needs",
    "detect_page_layout_needs",
    "detect_reading_order_need",
    "detect_tail_join_need",
    "detect_text_and_formula_normalizations",
    "detect_verse_chunk_need",
    "inspect_document_needs",
    "materialize_needs",
    "needs_vlm_judge",
    "normalized_element_bbox",
    "obligation_suffix",
    "oriented_bbox",
    "pages_for_vlm_judge",
    "unicode_repair_text",
]
