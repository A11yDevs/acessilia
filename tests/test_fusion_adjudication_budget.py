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
from backend.pipeline.fusion import apply_page_routes, fuse_extraction_payloads

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


def _doc_element(element_id: str, page: int, order: int, text: str, **extra) -> dict:
    return {
        "id": element_id,
        "type": "paragraph",
        "raw_label": "paragraph",
        "reading_order": order,
        "hierarchy_level": 0,
        "text": text,
        "page_number": page,
        **extra,
    }


def _doc(elements: list[dict], pages: int) -> dict:
    return {
        "provider": "test",
        "document": {
            "elements": elements,
            "pages": [
                {"page_number": n, "width": 100, "height": 100, "element_ids": []}
                for n in range(1, pages + 1)
            ],
            "summary": {
                "page_count": pages,
                "element_count": len(elements),
                "observation_count": 0,
                "obligation_count": 0,
                "element_types": {},
            },
        },
    }


def _routes(*routes: str) -> list[dict]:
    return [
        {"page_number": number, "stats": {"route": route}}
        for number, route in enumerate(routes, start=1)
    ]


class TestPageRoutes:
    PRIMARY = _doc(
        [
            _doc_element("element-000001", 1, 1, "docling page 1"),
            _doc_element("element-000002", 2, 2, "docling table page 2"),
            _doc_element("element-000003", 3, 3, "docling page 3"),
        ],
        pages=3,
    )
    SECONDARY = _doc(
        [
            _doc_element("element-000001", 1, 1, "mineru page 1"),
            _doc_element("element-000002", 2, 2, "mineru caption page 2"),
            _doc_element(
                "element-000003", 2, 3, "mineru table page 2", parent_id="element-000002"
            ),
            _doc_element("element-000004", 3, 4, "mineru page 3"),
        ],
        pages=3,
    )

    def test_the_routed_page_takes_the_secondary_elements(self):
        evidence = _routes("docling", "mineru", "docling")

        payload, replaced = apply_page_routes(
            self.PRIMARY, self.SECONDARY, evidence, secondary_provider="mineru"
        )

        document = payload["document"]
        assert [(e["id"], e["text"], e["reading_order"]) for e in document["elements"]] == [
            ("element-000001", "docling page 1", 1),
            ("mineru-element-000002", "mineru caption page 2", 2),
            ("mineru-element-000003", "mineru table page 2", 3),
            ("element-000003", "docling page 3", 4),
        ]
        taken = [e for e in document["elements"] if e["page_number"] == 2]
        assert all(e["metadata"]["provider"] == "mineru" for e in taken)
        assert taken[1]["parent_id"] == "mineru-element-000002"
        assert document["pages"][1]["element_ids"] == [
            "mineru-element-000002",
            "mineru-element-000003",
        ]
        assert document["summary"]["element_count"] == 4
        assert [e["id"] for e in replaced[2]] == ["element-000002"]
        assert evidence[1]["stats"]["applied"] == "mineru"
        assert "applied" not in evidence[0]["stats"]

    def test_without_a_routed_page_the_primary_payload_is_untouched(self):
        payload, replaced = apply_page_routes(
            self.PRIMARY,
            self.SECONDARY,
            _routes("docling", "docling", "docling"),
            secondary_provider="mineru",
        )

        assert payload is self.PRIMARY
        assert replaced == {}

    def test_a_route_to_an_empty_secondary_page_is_ignored(self):
        secondary = _doc([_doc_element("element-000001", 1, 1, "mineru page 1")], pages=3)

        payload, replaced = apply_page_routes(
            self.PRIMARY, secondary, _routes("docling", "mineru"), secondary_provider="mineru"
        )

        assert payload is self.PRIMARY
        assert replaced == {}
