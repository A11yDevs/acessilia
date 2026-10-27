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

from docstruct.fusion.judge import should_judge
from docstruct.fusion.page_select import page_norm, ratio

from backend.core.manifest.builder import (
    MAX_ID_SUFFIX,
    VLM_JUDGE_METHODS,
    _derive_v23_processing_needs,
)
from backend.core.manifest.models import ManifestElement
from backend.pipeline.fusion import (
    _similarity,
    apply_page_routes,
    fuse_extraction_payloads,
)

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


#: A page of about 110 words, and the same page as a second OCR engine might
#: read it: four word-internal typos, one word split and two merged.
PAGE = (
    PROSE
    + " Equilibrium is reached when the forward and reverse reactions proceed at "
    "the same rate, so the concentrations stop changing even though both "
    "reactions continue. A catalyst lowers the activation energy and speeds up "
    "both directions without shifting the equilibrium itself. "
    + PROSE
)
NOISY = (
    PAGE.replace("concentration", "concentratiom", 1)
    .replace("temperature", "temperatnre", 1)
    .replace("collision", "colision", 1)
    .replace("solutions", "so1utions", 1)
    .replace("everyday", "every day", 1)
    .replace("in detail", "indetail", 1)
    .replace("activation energy", "activationenergy", 1)
)


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

    def test_ocr_noise_is_not_a_divergence_and_matches_the_judges_gate(self):
        """The evidence and should_judge must agree on a typo-level page."""
        assert len(page_norm(PAGE).split()) > 100
        [stats] = _evidence(_payload(PAGE), _payload(NOISY))

        assert stats["provider_divergence"] is False
        assert stats["text_divergence"] is False
        assert should_judge(PAGE, NOISY) is False

    def test_similarity_is_the_judges_ratio(self):
        for other in (NOISY, PAGE.replace("the", "a"), PROSE):
            assert abs(
                _similarity(PAGE, other) - ratio(page_norm(PAGE), page_norm(other))
            ) < 1e-9

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

    def test_the_document_obligation_has_a_compact_id(self):
        pages = [
            _page(n, route="docling", reason="default_docling", similarity=0.5)
            for n in range(1, 51)
        ]
        _, obligations = _derive_v23_processing_needs(
            [
                ManifestElement(
                    id=f"element-{page:03d}{index:03d}",
                    type="paragraph",
                    raw_label="paragraph",
                    reading_order=page * 100 + index,
                    hierarchy_level=0,
                    text=f"Body {page}.{index}.",
                    page_number=page,
                )
                for page in range(1, 51)
                for index in range(20)
            ],
            fusion_evidence={"pages": pages},
            fusion_judge_max_pages=0,
        )
        [fuse] = [item for item in obligations if item.kind == "fuse-providers"]

        assert len(fuse.target_ids) == 1000
        assert len(fuse.id) <= len("obligation-fuse-providers-") + MAX_ID_SUFFIX

    def test_evidence_without_a_route_stays_eligible(self):
        legacy = _page(1, route="docling", reason="", similarity=0.5)
        del legacy["stats"]["route"]

        assert _judged_pages(_obligations([legacy], budget=1)) == ["element-1"]


TABLE_A = (
    "<table><tr><td>Reactant</td><td>Rate constant</td><td>Order</td></tr>"
    "<tr><td>Hydrogen peroxide</td><td>0.0012</td><td>first</td></tr>"
    "<tr><td>Nitrogen dioxide</td><td>0.54</td><td>second</td></tr></table>"
)
#: The same table as another extractor might read it: a row lost, and the
#: numbers of the other one misread.
TABLE_B = (
    "<table><tr><td>Reactant</td><td>Rate constant</td><td>Order</td></tr>"
    "<tr><td>Nitrogen dioxide</td><td>5.4</td><td>2</td></tr></table>"
)


def _table_page(table: str) -> dict:
    return {
        "status": "succeeded",
        "provider": "test",
        "document": {
            "elements": [
                {"type": "paragraph", "text": PROSE, "reading_order": 1, "page": 0},
                {"type": "table", "text": table, "reading_order": 2, "page": 0},
            ]
        },
    }


class TestBudgetOverRealEvidence:
    def _judged(self, primary: dict, secondary: dict) -> list[str]:
        fused = fuse_extraction_payloads(
            primary, secondary, primary_provider="docling", secondary_provider="mineru"
        )
        elements = [
            ManifestElement(
                id="element-1",
                type="paragraph",
                raw_label="paragraph",
                reading_order=1,
                hierarchy_level=0,
                text=PROSE,
                page_number=1,
            ),
            ManifestElement(
                id="element-2",
                type="table",
                raw_label="table",
                reading_order=2,
                hierarchy_level=0,
                text=TABLE_A,
                page_number=1,
            ),
        ]
        _, obligations = _derive_v23_processing_needs(
            elements,
            fusion_evidence=fused["fusion_evidence"],
            fusion_judge_max_pages=5,
        )
        return _judged_pages(obligations)

    def test_matching_prose_with_different_tables_gets_the_judge(self):
        """text_similarity leaves tables out; the both_table gate must not."""
        [stats] = _evidence(_table_page(TABLE_A), _table_page(TABLE_B))
        assert stats["route_reason"] == "both_table->mineru"
        assert stats["text_divergence"] is False

        assert self._judged(_table_page(TABLE_A), _table_page(TABLE_B)) == [
            "element-1",
            "element-2",
        ]

    def test_identical_table_pages_are_not_judged(self):
        assert self._judged(_table_page(TABLE_A), _table_page(TABLE_A)) == []


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

    def test_a_parent_on_another_taken_page_is_kept(self):
        secondary = _doc(
            [
                _doc_element("element-000001", 1, 1, "mineru list head"),
                _doc_element(
                    "element-000002", 2, 2, "mineru list tail", parent_id="element-000001"
                ),
                _doc_element("element-000003", 2, 3, "mineru other", parent_id="gone"),
            ],
            pages=3,
        )

        payload, _ = apply_page_routes(
            self.PRIMARY, secondary, _routes("mineru", "mineru"), secondary_provider="mineru"
        )

        parents = {e["id"]: e.get("parent_id") for e in payload["document"]["elements"]}
        assert parents["mineru-element-000002"] == "mineru-element-000001"
        assert parents["mineru-element-000003"] is None

    def test_elements_without_an_id_get_distinct_ids_across_pages(self):
        secondary = _doc(
            [
                {**_doc_element("x", 1, 1, "mineru page 1"), "id": None},
                {**_doc_element("x", 2, 2, "mineru page 2"), "id": None},
            ],
            pages=3,
        )

        payload, _ = apply_page_routes(
            self.PRIMARY, secondary, _routes("mineru", "mineru"), secondary_provider="mineru"
        )

        ids = [e["id"] for e in payload["document"]["elements"]]
        assert len(ids) == len(set(ids))
        assert {"mineru-p1-1", "mineru-p2-1"} <= set(ids)

    def test_adopted_boxes_are_scaled_to_the_primary_page(self):
        box = {"left": 10, "top": 20, "right": 110, "bottom": 220, "coord_origin": "TOPLEFT"}
        secondary = _doc(
            [
                _doc_element(
                    "element-000001",
                    2,
                    1,
                    "mineru page 2",
                    provenance=[{"page_number": 2, "bbox": box}],
                )
            ],
            pages=3,
        )
        for page in secondary["document"]["pages"]:
            page["width"], page["height"] = 200, 400

        payload, _ = apply_page_routes(
            self.PRIMARY, secondary, _routes("docling", "mineru"), secondary_provider="mineru"
        )

        [taken] = [e for e in payload["document"]["elements"] if e["page_number"] == 2]
        assert taken["provenance"][0]["bbox"] == {
            "left": 5.0, "top": 5.0, "right": 55.0, "bottom": 55.0, "coord_origin": "TOPLEFT",
        }
        assert payload["document"]["pages"][1]["width"] == 100

    def test_a_payload_with_zero_based_pages_is_routed(self):
        def zero_based(doc: dict) -> dict:
            elements = []
            for element in doc["document"]["elements"]:
                element = dict(element)
                element["page"] = element.pop("page_number") - 1
                elements.append(element)
            return {**doc, "document": {**doc["document"], "elements": elements}}

        payload, replaced = apply_page_routes(
            zero_based(self.PRIMARY),
            zero_based(self.SECONDARY),
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )

        assert [e["text"] for e in payload["document"]["elements"]] == [
            "docling page 1",
            "mineru caption page 2",
            "mineru table page 2",
            "docling page 3",
        ]
        assert list(replaced) == [2]
        assert payload["document"]["pages"][1]["element_ids"] == [
            "mineru-element-000002",
            "mineru-element-000003",
        ]


def test_additional_table_same_type_routes_to_secondary():
    primary = _payload(PROSE)
    primary['document']['elements'].append({'type': 'table', 'text': '', 'page': 0, 'bbox': [0, 0, 10, 10]})
    secondary = _payload(PROSE)
    secondary['document']['elements'].extend([
        {'type': 'table', 'text': '', 'page': 0, 'bbox': [0, 0, 10, 10]},
        {'type': 'table', 'text': '', 'page': 0, 'bbox': [0, 20, 10, 30]},
    ])
    [stats] = _evidence(primary, secondary)
    assert stats['route'] == 'mineru'
    assert stats['route_reason'] == 'secondary_structure_superset'


def test_structural_conflict_with_different_text_requires_review():
    primary = _payload(PROSE)
    primary['document']['elements'].append({'type': 'picture', 'text': '', 'page': 0, 'bbox': [0, 0, 10, 10]})
    secondary = _payload('Different prose that must not overwrite the primary.')
    secondary['document']['elements'].append({'type': 'table', 'text': '', 'page': 0, 'bbox': [0, 20, 10, 30]})
    [stats] = _evidence(primary, secondary)
    assert (stats['route'], stats['route_reason']) == ('docling', 'structure_ambiguous')
    evidence = [{'page_number': 1, 'stats': stats}]
    [review] = [o for o in _obligations(evidence, 0) if o.kind == 'adjudicate-page']
    assert review.admissible_methods == ['human-review']
    [judge] = [o for o in _obligations(evidence, 1) if o.kind == 'adjudicate-page']
    assert judge.admissible_methods == VLM_JUDGE_METHODS


def test_secondary_with_extra_table_cannot_discard_primary_table_content():
    primary = _payload(PROSE)
    primary['document']['elements'].append({'type': 'table', 'text': 'primary values', 'page': 0, 'bbox': [0, 0, 10, 10]})
    secondary = _payload(PROSE)
    secondary['document']['elements'].extend([
        {'type': 'table', 'text': 'different values', 'page': 0, 'bbox': [0, 0, 10, 10]},
        {'type': 'table', 'text': '', 'page': 0, 'bbox': [0, 20, 10, 30]},
    ])
    [stats] = _evidence(primary, secondary)
    assert (stats['route'], stats['route_reason']) == ('docling', 'structure_ambiguous')


def test_structure_evidence_routes_the_page_and_preserves_primary_text():
    primary = _doc([_doc_element('p1', 1, 1, PROSE)], pages=1)
    table = {
        'id': 't1', 'type': 'table', 'text': '', 'reading_order': 2,
        'page_number': 1, 'bbox': [10, 10, 50, 50],
    }
    secondary = _doc([_doc_element('p2', 1, 1, PROSE), table], pages=1)
    fused = fuse_extraction_payloads(
        primary, secondary, primary_provider='docling', secondary_provider='mineru'
    )
    routed, replaced = apply_page_routes(
        primary, secondary, fused['fusion_evidence']['pages'], secondary_provider='mineru'
    )
    assert [item['text'] for item in routed['document']['elements']] == [PROSE, '']
    assert routed['document']['elements'][1]['type'] == 'table'
    assert replaced[1] == primary['document']['elements']
