"""Dual fusion spends model and Toolbox time only where it can matter.

Before, two extractors that disagreed on a single token flagged a page as
divergent, every such page got an adjudicate-page and a fuse-providers
obligation, each fuse-providers step re-extracted the whole document, and the
VLM judge ran on every page the deterministic router sent to MinerU, which is
every page with a formula or table on both sides. The verdict could not be
applied, and a verdict for MinerU failed the job (that case is covered in
test_noncritical_obligations.py).
"""

from __future__ import annotations

from backend.core.manifest.builder import (
    VLM_JUDGE_METHODS,
    _derive_v23_processing_needs,
)
from backend.core.manifest.models import ManifestElement
from backend.pipeline.fusion import fuse_extraction_payloads

PROSE = (
    "The reaction rate depends on the concentration of the reactants and on the "
    "temperature of the system, as the collision theory explains in detail for "
    "gases and solutions alike, with many examples from everyday chemistry."
)


def _payload(*texts_by_page: str) -> dict:
    return {
        "status": "succeeded",
        "provider": "test",
        "document": {
            "elements": [
                {"type": "paragraph", "text": text, "reading_order": page, "page": page}
                for page, text in enumerate(texts_by_page)
            ]
        },
    }


def _evidence(primary: dict, secondary: dict) -> list[dict]:
    fused = fuse_extraction_payloads(
        primary, secondary, primary_provider="docling", secondary_provider="mineru"
    )
    return [page["stats"] for page in fused["fusion_evidence"]["pages"]]


class TestEvidence:
    def test_a_one_word_difference_is_not_a_divergence(self):
        [stats] = _evidence(_payload(PROSE), _payload(PROSE.replace("alike", "too")))

        assert stats["similarity"] >= 0.97
        assert stats["text_divergence"] is False
        assert stats["provider_divergence"] is False

    def test_different_transcriptions_diverge_and_carry_the_deterministic_route(self):
        [stats] = _evidence(
            _payload(PROSE), _payload("A completely different page about tables.")
        )

        assert stats["text_divergence"] is True
        assert stats["provider_divergence"] is True
        assert stats["route"] in {"docling", "mineru"}
        assert stats["route_reason"]


def _page_elements(pages: int) -> list[ManifestElement]:
    return [
        ManifestElement(
            id=f"element-{page}",
            type="paragraph",
            raw_label="paragraph",
            reading_order=page,
            hierarchy_level=0,
            text=f"Body of page {page}.",
            page_number=page,
        )
        for page in range(1, pages + 1)
    ]


def _page(number: int, *, route: str, reason: str, similarity: float) -> dict:
    return {
        "page_number": number,
        "stats": {
            "provider_count": 2,
            "provider_divergence": True,
            "text_divergence": True,
            "table_divergence": False,
            "similarity": similarity,
            "text_similarity": similarity,
            "route": route,
            "route_reason": reason,
        },
    }


def _obligations(pages: list[dict], budget: int):
    _, obligations = _derive_v23_processing_needs(
        _page_elements(len(pages)),
        fusion_evidence={"pages": pages},
        fusion_judge_max_pages=budget,
    )
    return obligations


def _judged_pages(obligations) -> list[str]:
    return sorted(
        target
        for item in obligations
        if item.kind == "adjudicate-page"
        for target in item.target_ids
    )


PAGES = (
    _page(1, route="docling", reason="default_docling", similarity=0.5),
    _page(2, route="mineru", reason="only_mineru_table", similarity=0.4),
    _page(3, route="mineru", reason="both_formula->mineru", similarity=0.9),
    _page(4, route="mineru", reason="both_formula->mineru", similarity=0.6),
    _page(5, route="mineru", reason="both_table->mineru", similarity=0.7),
)


class TestAdjudicationBudget:
    def test_only_the_most_divergent_ambiguous_pages_get_the_vlm_judge(self):
        obligations = _obligations(list(PAGES), budget=2)

        # Pages 1 (kept docling) and 2 (structural fact) are settled by the
        # deterministic router; of the ambiguous 3, 4 and 5, the two least
        # similar are judged.
        assert _judged_pages(obligations) == ["element-4", "element-5"]
        assert all(
            item.admissible_methods == VLM_JUDGE_METHODS
            for item in obligations
            if item.kind == "adjudicate-page"
        )

    def test_a_zero_budget_turns_the_judge_off(self):
        assert _judged_pages(_obligations(list(PAGES), budget=0)) == []

    def test_fuse_providers_is_one_obligation_per_document(self):
        fuse = [
            item for item in _obligations(list(PAGES), budget=0)
            if item.kind == "fuse-providers"
        ]

        assert len(fuse) == 1
        assert fuse[0].target_ids == [f"element-{page}" for page in range(1, 6)]

    def test_evidence_without_a_route_stays_eligible(self):
        legacy = _page(1, route="docling", reason="", similarity=0.5)
        del legacy["stats"]["route"]

        assert _judged_pages(_obligations([legacy], budget=1)) == ["element-1"]
