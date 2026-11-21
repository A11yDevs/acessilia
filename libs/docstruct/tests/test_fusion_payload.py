"""Tests for pure multi-provider payload fusion and page routing (docstruct.fusion.payload)."""

from __future__ import annotations

import importlib

import pytest
from docstruct.fusion import payload as fusion_payload
from docstruct.fusion.payload import (
    STRUCTURAL_TYPES,
    TEXT_KINDS,
    PageRouteResult,
    adopt_elements,
    apply_page_routes,
    element_to_canonical_block,
    fuse_extraction_payloads,
    group_payload_by_page,
    page_content_signature,
    page_scales,
    page_similarity,
    route_pages,
    scaled_box,
    structure_signature,
)
from docstruct.fusion.types import DiffBlock
from docstruct.manifest import (
    structured_document_from_payload,
    validate_structured_document,
)

PROSE = (
    "Accessibility requires clear document structure, accurate headings, "
    "and reliable reading order across every page of the file."
)


def _doc_element(
    element_id: str,
    page_number: int,
    reading_order: int,
    text: str,
    *,
    element_type: str = "paragraph",
    parent_id: str | None = None,
    provenance: list[dict] | None = None,
) -> dict:
    item: dict = {
        "id": element_id,
        "type": element_type,
        "text": text,
        "page_number": page_number,
        "reading_order": reading_order,
    }
    if parent_id is not None:
        item["parent_id"] = parent_id
    if provenance is not None:
        item["provenance"] = provenance
    return item


def _doc(elements: list[dict], *, pages: int = 3) -> dict:
    return {
        "status": "succeeded",
        "document": {
            "pages": [
                {
                    "page_number": number,
                    "width": 100.0,
                    "height": 200.0,
                    "element_ids": [
                        e["id"]
                        for e in elements
                        if e.get("page_number") == number and e.get("id")
                    ],
                }
                for number in range(1, pages + 1)
            ],
            "elements": elements,
            "summary": {
                "page_count": pages,
                "element_count": len(elements),
                "element_types": {},
            },
        },
    }


def _routes(*providers: str) -> list[dict]:
    return [
        {"page_number": idx, "stats": {"route": route}}
        for idx, route in enumerate(providers, start=1)
    ]


def _manifest_element(
    element_id: str | None,
    page_number: int,
    reading_order: int,
    text: str,
) -> dict:
    """A ``DocumentElement`` shaped for ``structured_document_from_payload``."""
    element: dict = {
        "type": "paragraph",
        "raw_label": "text",
        "reading_order": reading_order,
        "hierarchy_level": 0,
        "text": text,
        "source_ref": None,
        "parent_ref": None,
        "parent_id": None,
        "page_number": page_number,
        "confidence": None,
        "provenance": [],
        "metadata": {},
    }
    if element_id is not None:
        element["id"] = element_id
    return element


class TestPageSimilarity:
    def test_empty_and_identical_cases(self) -> None:
        assert page_similarity("", "") == 1.0
        assert page_similarity("   ", "###") == 1.0
        assert page_similarity("hello", "") == 0.0
        assert page_similarity("", "hello") == 0.0
        assert page_similarity("# Heading\n\nBody.", "Heading body") == 1.0

    def test_rapidfuzz_and_pure_python_fallback_match(self, monkeypatch) -> None:
        pairs = [
            (PROSE, PROSE),
            (PROSE, PROSE[:-1] + "!"),
            ("Short alpha beta gamma", "Short alpha delta gamma"),
            ("Completely unrelated text", "Another different passage altogether"),
            ("<table><tr><td>A</td></tr></table>", "A"),
            # Half-rounding boundary at 4 decimals (0.01875): must match bit for bit.
            ("a" * 3 + "b" * 157, "a" * 3 + "c" * 157),
        ]
        fast_scores = [page_similarity(a, b) for a, b in pairs]
        monkeypatch.setattr(fusion_payload, "_rapidfuzz_fuzz", None)
        pure_scores = [page_similarity(a, b) for a, b in pairs]
        for fast, pure in zip(fast_scores, pure_scores, strict=True):
            assert fast == pure
            assert round(fast, 4) == round(pure, 4)

    def test_fuse_extraction_payloads_matches_bit_for_bit_without_rapidfuzz(self, monkeypatch) -> None:
        primary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": "a" * 3 + "b" * 157, "page_number": 1},
                    {"type": "paragraph", "text": PROSE, "page_number": 2},
                ]
            }
        }
        secondary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": "a" * 3 + "c" * 157, "page_number": 1},
                    {"type": "paragraph", "text": PROSE[:-1] + "!", "page_number": 2},
                ]
            }
        }
        with_accel = fuse_extraction_payloads(
            primary, secondary, primary_provider="docling", secondary_provider="mineru"
        )
        monkeypatch.setattr(fusion_payload, "_rapidfuzz_fuzz", None)
        without_accel = fuse_extraction_payloads(
            primary, secondary, primary_provider="docling", secondary_provider="mineru"
        )
        assert without_accel == with_accel


class TestBlockConversionAndSignatures:
    def test_element_to_canonical_block_reads_dict_bbox_from_provenance(self) -> None:
        block = element_to_canonical_block(
            {
                "type": "HEADING",
                "text": "  Intro  ",
                "reading_order": 3,
                "provenance": [
                    {"bbox": {"left": 1, "top": 2, "right": 3, "bottom": 4}}
                ],
                "page_size": [600, 800],
                "coord_origin": "TOPLEFT",
            },
            page_index=2,
        )
        assert block == {
            "type": "heading",
            "text": "Intro",
            "metadata": {
                "reading_order": 3,
                "page_size": [600, 800],
                "coord_origin": "TOPLEFT",
            },
            "bbox": [1.0, 2.0, 3.0, 4.0],
            "page_index": 2,
        }

    def test_element_to_canonical_block_defaults_type_and_omits_invalid_bbox(self) -> None:
        block = element_to_canonical_block(
            {"text": "Plain", "bbox": [1, "bad", 3, 4]}, page_index=0
        )
        assert block["type"] == "paragraph"
        assert "bbox" not in block
        assert "page_index" not in block

    @pytest.mark.parametrize("kind", sorted(STRUCTURAL_TYPES))
    def test_group_payload_by_page_keeps_empty_structural_elements(self, kind: str) -> None:
        payload = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": "   ", "page_number": 1},
                    {"type": kind, "text": "", "page_number": 2, "bbox": [0, 0, 10, 10]},
                    {"type": "paragraph", "text": "Page one", "page": 0},
                ]
            }
        }
        grouped = group_payload_by_page(payload)
        assert set(grouped) == {0, 1}
        assert [b["text"] for b in grouped[0]] == ["Page one"]
        assert [b["type"] for b in grouped[1]] == [kind]

    def test_structure_and_content_signatures(self) -> None:
        blocks = [
            {"type": "table", "text": "a"},
            {"type": "picture", "text": ""},
            {"type": "table", "text": "b"},
            {"type": "paragraph", "text": "text"},
        ]
        assert structure_signature(blocks) == [("picture", 1), ("table", 2)]
        assert structure_signature(blocks, kinds={"table"}) == [("table", 2)]

        diffs = [
            DiffBlock(kind="table", text="Row One", md="| Row One |", box=None, type="table"),
            DiffBlock(kind="text", text="Ignore me", md="Ignore me", box=None, type="paragraph"),
        ]
        assert page_content_signature(diffs, kinds={"table"}) == [
            ("table", "one"),
            ("table", "row"),
        ]
        assert "text" in TEXT_KINDS

    def test_top_level_docstruct_fusion_reexports(self) -> None:
        fusion_pkg = importlib.import_module("docstruct.fusion")

        assert fusion_pkg.fuse_extraction_payloads is fuse_extraction_payloads
        assert fusion_pkg.route_pages is route_pages
        assert fusion_pkg.apply_page_routes is apply_page_routes
        assert fusion_pkg.PageRouteResult is PageRouteResult


class TestFuseExtractionPayloads:
    def test_fuses_multiple_pages_preserving_page_numbers_and_reading_order(self) -> None:
        primary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": "Page one content.", "page_number": 1},
                    {"type": "paragraph", "text": "Page two content.", "page_number": 2},
                ]
            }
        }
        secondary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": "Page one content.", "page_number": 1},
                    {"type": "paragraph", "text": "Page two content.", "page_number": 2},
                ]
            }
        }
        result = fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
        )
        assert result["status"] == "succeeded"
        assert result["provider"] == "docling+mineru"
        elements = result["document"]["elements"]
        assert [e["page_number"] for e in elements] == [1, 2]
        assert [e["page"] for e in elements] == [0, 1]
        assert [e["reading_order"] for e in elements] == [1, 2]
        assert len(result["fusion_evidence"]["pages"]) == 2
        for page_entry in result["fusion_evidence"]["pages"]:
            stats = page_entry["stats"]
            assert stats["provider_count"] == 2
            assert stats["provider_divergence"] is False
            assert stats["route"] == "docling"
            assert stats["route_reason"] == "default_docling"

    @pytest.mark.parametrize("kind", ["table", "picture", "formula"])
    def test_empty_secondary_structural_element_routes_as_superset_when_text_agrees(
        self, kind: str
    ) -> None:
        primary = {
            "document": {"elements": [{"type": "paragraph", "text": PROSE, "page": 0}]}
        }
        secondary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": PROSE, "page": 0},
                    {"type": kind, "text": "", "page": 0, "bbox": [0, 0, 10, 10]},
                ]
            }
        }
        result = fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
        )
        stats = result["fusion_evidence"]["pages"][0]["stats"]
        assert stats["structure_divergence"] is True
        assert stats["provider_divergence"] is True
        assert stats["text_divergence"] is False
        assert stats["route"] == "mineru"
        assert stats["route_reason"] == "secondary_structure_superset"
        assert stats["structure_counts"] == {"docling": {}, "mineru": {kind: 1}}
        if kind == "table":
            assert stats["table_divergence"] is True

    def test_structural_conflict_with_different_text_marks_structure_ambiguous(self) -> None:
        primary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": PROSE, "page": 0},
                    {"type": "picture", "text": "", "page": 0, "bbox": [0, 0, 10, 10]},
                ]
            }
        }
        secondary = {
            "document": {
                "elements": [
                    {
                        "type": "paragraph",
                        "text": "Different prose that must not overwrite the primary.",
                        "page": 0,
                    },
                    {"type": "table", "text": "", "page": 0, "bbox": [0, 20, 10, 30]},
                ]
            }
        }
        result = fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
        )
        stats = result["fusion_evidence"]["pages"][0]["stats"]
        assert (stats["route"], stats["route_reason"]) == ("docling", "structure_ambiguous")

    def test_primary_only_structure_keeps_primary_without_divergence(self) -> None:
        primary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": PROSE, "page": 0},
                    {"type": "picture", "text": "", "page": 0, "bbox": [0, 0, 10, 10]},
                ]
            }
        }
        secondary = {
            "document": {"elements": [{"type": "paragraph", "text": PROSE, "page": 0}]}
        }
        result = fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
        )
        stats = result["fusion_evidence"]["pages"][0]["stats"]
        assert stats["structure_divergence"] is True
        assert stats["provider_divergence"] is False
        assert (stats["route"], stats["route_reason"]) == ("docling", "default_docling")

    def test_near_empty_decide_v1_route_takes_precedence_over_superset(self) -> None:
        primary = {"document": {"elements": [{"type": "paragraph", "text": "Short.", "page": 0}]}}
        secondary = {
            "document": {
                "elements": [
                    {"type": "paragraph", "text": PROSE, "page": 0},
                    {"type": "picture", "text": "", "page": 0, "bbox": [0, 0, 10, 10]},
                ]
            }
        }
        result = fuse_extraction_payloads(
            primary,
            secondary,
            primary_provider="docling",
            secondary_provider="mineru",
        )
        stats = result["fusion_evidence"]["pages"][0]["stats"]
        assert (stats["route"], stats["route_reason"]) == ("mineru", "docling_near_empty")


class TestScalingAndAdoption:
    def test_page_scales_computes_ratios_only_when_dimensions_differ(self) -> None:
        primary_pages = [
            {"page_number": 1, "width": 100, "height": 200},
            {"page_number": 2, "width": 100, "height": 200},
            {"page_number": 3, "width": 0, "height": 200},
        ]
        secondary_pages = [
            {"page_number": 1, "width": 100, "height": 200},
            {"page_number": 2, "width": 200, "height": 400},
            {"page_number": 3, "width": 200, "height": 400},
        ]
        assert page_scales(primary_pages, secondary_pages, {1, 2, 3}) == {2: (0.5, 0.5)}

    def test_scaled_box_handles_dict_sequence_and_passthrough(self) -> None:
        assert scaled_box(
            {"left": 10, "top": 20, "right": 110, "bottom": 220, "coord_origin": "TOPLEFT"},
            (0.5, 0.25),
        ) == {
            "left": 5.0,
            "top": 5.0,
            "right": 55.0,
            "bottom": 55.0,
            "coord_origin": "TOPLEFT",
        }
        assert scaled_box([10, 20, 30, 40], (2.0, 0.5)) == [20.0, 10.0, 60.0, 20.0]
        assert scaled_box((10, 20, 30, 40), (2.0, 0.5)) == [20.0, 10.0, 60.0, 20.0]
        assert scaled_box("not-a-box", (2.0, 2.0)) == "not-a-box"

    def test_adopt_elements_maps_ids_parents_metadata_and_boxes(self) -> None:
        pages = {
            1: [_doc_element("e1", 1, 1, "head")],
            2: [
                {
                    **_doc_element(
                        "e2",
                        2,
                        2,
                        "child",
                        parent_id="e1",
                        provenance=[{"page_number": 2, "bbox": [10, 20, 30, 40]}],
                    ),
                    "bbox": {"left": 10, "top": 20, "right": 30, "bottom": 40},
                },
                {**_doc_element("e3", 2, 3, "orphan", parent_id="unrouted"), "id": None},
            ],
        }
        adopted = adopt_elements(pages, "mineru", {2: (0.5, 0.5)})
        assert adopted[1][0]["id"] == "mineru-e1"
        assert adopted[1][0]["metadata"]["provider"] == "mineru"
        assert adopted[2][0]["id"] == "mineru-e2"
        assert adopted[2][0]["parent_id"] == "mineru-e1"
        assert adopted[2][0]["bbox"] == {"left": 5.0, "top": 10.0, "right": 15.0, "bottom": 20.0}
        assert adopted[2][0]["provenance"][0]["bbox"] == [5.0, 10.0, 15.0, 20.0]
        assert adopted[2][1]["id"] == "mineru-p2-2"
        assert adopted[2][1]["parent_id"] is None


class TestRoutePagesAndApplyPageRoutes:
    PRIMARY = _doc(
        [
            _doc_element("p1", 1, 1, "docling page 1"),
            _doc_element("p2", 2, 2, "docling page 2"),
            _doc_element("p3", 3, 3, "docling page 3"),
            {"id": "p-unpaged", "type": "paragraph", "text": "unpaged", "reading_order": 4},
        ],
        pages=3,
    )
    SECONDARY = _doc(
        [
            _doc_element("s1", 1, 1, "mineru page 1"),
            _doc_element("s2", 2, 2, "mineru caption"),
            _doc_element("s3", 2, 3, "mineru table", element_type="table", parent_id="s2"),
        ],
        pages=2,
    )

    def test_route_pages_replaces_routed_page_reports_missing_and_updates_summary(self) -> None:
        evidence = _routes("docling", "mineru", "mineru")
        result = route_pages(
            self.PRIMARY, self.SECONDARY, evidence, secondary_provider="mineru"
        )
        assert isinstance(result, PageRouteResult)
        assert result.routed_pages == (2,)
        assert result.missing_pages == (3,)
        assert [e["id"] for e in result.replaced[2]] == ["p2"]

        document = result.payload["document"]
        assert [(e["id"], e["reading_order"]) for e in document["elements"]] == [
            ("p1", 1),
            ("mineru-s2", 2),
            ("mineru-s3", 3),
            ("p3", 4),
            ("p-unpaged", 5),
        ]
        assert document["pages"][1]["element_ids"] == ["mineru-s2", "mineru-s3"]
        assert document["summary"]["element_count"] == 5
        assert document["summary"]["element_types"] == {"paragraph": 4, "table": 1}
        assert result.page_evidence[1]["stats"]["applied"] == "mineru"
        assert "applied" not in result.page_evidence[2]["stats"]
        # #633: the caller's evidence is pure input; the result carries the copy.
        assert "applied" not in evidence[1]["stats"]
        assert evidence is not result.page_evidence
        assert result.page_evidence[0]["stats"] is not evidence[0]["stats"]
        result.page_evidence[0]["stats"]["sentinel"] = "copy-only"
        assert "sentinel" not in evidence[0]["stats"]

    def test_without_routed_pages_primary_payload_identity_is_preserved(self) -> None:
        payload, replaced = apply_page_routes(
            self.PRIMARY,
            self.SECONDARY,
            _routes("docling", "docling", "docling"),
            secondary_provider="mineru",
        )
        assert payload is self.PRIMARY
        assert replaced == {}

    def test_missing_secondary_pages_are_reported_even_when_nothing_is_routed(self) -> None:
        result = route_pages(
            self.PRIMARY,
            self.SECONDARY,
            _routes("docling", "docling", "mineru"),
            secondary_provider="mineru",
        )
        assert result.payload is self.PRIMARY
        assert result.replaced == {}
        assert result.routed_pages == ()
        assert result.missing_pages == (3,)

    def test_zero_based_page_elements_are_routed_and_reindexed(self) -> None:
        def to_zero_based(doc: dict) -> dict:
            elements = []
            for element in doc["document"]["elements"]:
                copied = dict(element)
                if "page_number" in copied:
                    copied["page"] = copied.pop("page_number") - 1
                elements.append(copied)
            return {**doc, "document": {**doc["document"], "elements": elements}}

        payload, replaced = apply_page_routes(
            to_zero_based(self.PRIMARY),
            to_zero_based(self.SECONDARY),
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )
        assert list(replaced) == [2]
        assert payload["document"]["pages"][1]["element_ids"] == ["mineru-s2", "mineru-s3"]

    def test_float_page_number_in_evidence_routes_matching_integer_page(self) -> None:
        evidence = [
            {"page_number": 1, "stats": {"route": "docling"}},
            {"page_number": 2.0, "stats": {"route": "mineru"}},
        ]
        result = route_pages(
            self.PRIMARY, self.SECONDARY, evidence, secondary_provider="mineru"
        )
        assert result.routed_pages == (2.0,)
        assert result.missing_pages == ()
        assert [e["id"] for e in result.replaced[2]] == ["p2"]
        assert result.page_evidence[1]["stats"]["applied"] == "mineru"
        assert "applied" not in evidence[1]["stats"]

    def test_primary_elements_without_id_get_a_deterministic_id(self) -> None:
        """#664: an unrouted primary element without id is normalized, not dropped."""
        primary = _doc(
            [
                _doc_element("p1", 1, 1, "docling page 1"),
                _doc_element("p2", 2, 2, "docling page 2"),
                {
                    "id": None,
                    "type": "paragraph",
                    "text": "primary without id",
                    "page_number": 3,
                    "reading_order": 3,
                },
            ],
            pages=3,
        )
        result = route_pages(
            primary,
            self.SECONDARY,
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )

        document = result.payload["document"]
        normalized = next(
            element
            for element in document["elements"]
            if element.get("text") == "primary without id"
        )
        assert normalized["id"] == "element-p3-1"
        assert document["pages"][2]["element_ids"] == ["element-p3-1"]
        assert document["summary"]["element_count"] == 4
        # #633: the caller's payload is input; normalization happens on copies.
        assert primary["document"]["elements"][2]["id"] is None

    @pytest.mark.parametrize("missing_id", ["absent", ""])
    def test_primary_elements_without_a_usable_id_get_a_deterministic_id(
        self, missing_id: str
    ) -> None:
        """#664: a missing/empty primary id is normalized for page membership."""
        element = {
            "type": "paragraph",
            "text": "primary without usable id",
            "page_number": 3,
            "reading_order": 3,
        }
        if missing_id != "absent":
            element["id"] = missing_id
        primary = _doc(
            [
                _doc_element("p1", 1, 1, "docling page 1"),
                _doc_element("p2", 2, 2, "docling page 2"),
                element,
            ],
            pages=3,
        )

        result = route_pages(
            primary,
            self.SECONDARY,
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )

        document = result.payload["document"]
        normalized = next(
            item
            for item in document["elements"]
            if item.get("text") == "primary without usable id"
        )
        assert normalized["id"] == "element-p3-1"
        assert document["pages"][2]["element_ids"] == ["element-p3-1"]
        assert document["summary"]["element_count"] == 4
        assert primary["document"]["elements"][2].get("id") == (
            "" if missing_id == "" else None
        )

    def test_an_id_less_element_joins_a_page_that_already_lists_ids(self) -> None:
        """#664: an existing element_ids list no longer hides the normalized id."""
        primary = _doc(
            [
                _doc_element("p1", 1, 1, "docling page 1"),
                _doc_element("p2", 2, 2, "docling page 2"),
                _doc_element("p3", 3, 3, "docling page 3"),
                {
                    "type": "paragraph",
                    "text": "primary without id",
                    "page_number": 3,
                    "reading_order": 4,
                },
            ],
            pages=3,
        )

        result = route_pages(
            primary,
            self.SECONDARY,
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )

        assert result.payload["document"]["pages"][2]["element_ids"] == [
            "p3",
            "element-p3-2",
        ]

    def test_a_generated_id_never_collides_with_a_provider_id(self) -> None:
        """#664: the generated id is unique even when its shape is already taken."""
        primary = _doc(
            [
                _doc_element("p1", 1, 1, "docling page 1"),
                _doc_element("p2", 2, 2, "docling page 2"),
                _doc_element("element-p3-2", 3, 3, "docling page 3"),
                {
                    "type": "paragraph",
                    "text": "primary without id",
                    "page_number": 3,
                    "reading_order": 4,
                },
            ],
            pages=3,
        )

        result = route_pages(
            primary,
            self.SECONDARY,
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )

        assert result.payload["document"]["pages"][2]["element_ids"] == [
            "element-p3-2",
            "element-p3-2-2",
        ]

    def test_an_unpaged_id_less_element_gets_an_id_outside_page_membership(self) -> None:
        """#664: unpaged elements still need an id for the manifest, on no page."""
        primary = _doc(
            [
                _doc_element("p1", 1, 1, "docling page 1"),
                _doc_element("p2", 2, 2, "docling page 2"),
                {
                    "type": "paragraph",
                    "text": "unpaged without id",
                    "reading_order": 3,
                },
            ],
            pages=3,
        )

        result = route_pages(
            primary,
            self.SECONDARY,
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )

        document = result.payload["document"]
        normalized = next(
            element
            for element in document["elements"]
            if element.get("text") == "unpaged without id"
        )
        assert normalized["id"] == "element-unpaged-1"
        assert all(
            "element-unpaged-1" not in page["element_ids"]
            for page in document["pages"]
        )

    def test_the_routed_payload_is_a_valid_structured_document(self) -> None:
        """#664: normalization keeps the routed payload valid as a manifest document."""
        primary = {
            "status": "succeeded",
            "document": {
                "title": "Doc",
                "language": "pt-BR",
                "pages": [
                    {
                        "page_number": number,
                        "width": 100.0,
                        "height": 200.0,
                        "element_ids": [],
                    }
                    for number in (1, 2, 3)
                ],
                "elements": [
                    _manifest_element("p1", 1, 1, "primary page 1"),
                    _manifest_element("p2", 2, 2, "primary page 2"),
                    _manifest_element(None, 3, 3, "primary without id"),
                ],
            },
        }
        secondary = {
            "status": "succeeded",
            "document": {
                "title": "Doc",
                "language": "pt-BR",
                "pages": [
                    {
                        "page_number": 2,
                        "width": 100.0,
                        "height": 200.0,
                        "element_ids": ["s2"],
                    }
                ],
                "elements": [_manifest_element("s2", 2, 1, "secondary page 2")],
            },
        }

        result = route_pages(
            primary,
            secondary,
            _routes("docling", "mineru", "docling"),
            secondary_provider="mineru",
        )

        document = structured_document_from_payload(result.payload["document"])
        assert validate_structured_document(document) == []

    def test_apply_page_routes_wrapper_keeps_its_two_value_contract(self) -> None:
        """#633: the historical wrapper does not expose the annotated evidence copy."""
        evidence = _routes("docling", "mineru", "docling")
        apply_page_routes(
            self.PRIMARY, self.SECONDARY, evidence, secondary_provider="mineru"
        )
        assert "applied" not in evidence[1]["stats"]
