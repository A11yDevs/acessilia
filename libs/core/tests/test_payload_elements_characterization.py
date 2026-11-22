"""Characterization tests for pipeline/elements.py and pipeline/payload.py (#612, PR 7).

Pins the key branches of ``_element_to_block``, ``build_pddl_structured_payload``,
and ``_manifest_pages_to_payload`` so modularization keeps output blocks,
technical warnings, canonical metadata, and cacheability identical.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pddl_support import NOW, build_element, build_manifest, build_obligation

from acessilia_core.execution.models import ExecutionReport
from acessilia_core.i18n import n, t
from acessilia_core.i18n.log_messages import MSG_STRUCTURAL_EXTRACTION_DEGRADED
from acessilia_core.manifest.models import (
    BoundingBox,
    ManifestElement,
    ObligationAttempt,
    Observation,
    PageDescriptor,
    ProcessingManifest,
    Provenance,
)
from acessilia_core.pipeline.elements import (
    MSG_UNDESCRIBED_PICTURE_ALT,
    _element_to_block,
)
from acessilia_core.pipeline.payload import (
    MSG_PICTURES_NOT_DESCRIBED,
    MSG_TABLES_NOT_READ,
    _manifest_pages_to_payload,
    build_pddl_structured_payload,
)
from acessilia_core.planning.models import DomainIdentity, NominalPlan, PlanStep


def _element(
    element_id: str,
    element_type: str = "paragraph",
    text: str | None = "Sample text",
    *,
    raw_label: str | None = None,
    reading_order: int = 1,
    hierarchy_level: int = 1,
    page_number: int | None = 1,
    metadata: dict | None = None,
    provenance: list[Provenance] | None = None,
) -> ManifestElement:
    el = build_element(
        element_id,
        element_type,
        text=text,
        metadata=metadata,
        reading_order=reading_order,
    )
    return el.model_copy(
        update={
            "raw_label": raw_label or element_type,
            "hierarchy_level": hierarchy_level,
            "page_number": page_number,
            "provenance": provenance or [],
        }
    )


def _manifest(
    elements: list[ManifestElement],
    *,
    pages: list[PageDescriptor] | None = None,
    observations: list[Observation] | None = None,
    obligations: list | None = None,
    configuration: dict | None = None,
) -> ProcessingManifest:
    manifest = build_manifest(elements, obligations or [])
    if pages is not None:
        manifest.pages = pages
        manifest.summary.page_count = len(pages)
    if observations is not None:
        manifest.observations = observations
        manifest.summary.observation_count = len(observations)
    if configuration is not None:
        manifest.extractor.configuration = configuration
    return manifest


def _plan() -> NominalPlan:
    return NominalPlan(
        plan_id="plan-1",
        generated_at=NOW,
        manifest_id="manifest-actionability",
        manifest_revision=1,
        manifest_sha256="a" * 64,
        planner="heuristic",
        domain=DomainIdentity(
            name="acessilia",
            version="2.3",
            domain_sha256="b" * 64,
            description_sha256="c" * 64,
        ),
        problem_name="prob-1",
        problem_sha256="d" * 64,
        selected_obligations=[],
        expected_total_cost=0,
        steps=[PlanStep(index=0, action="complete-job")],
    )


def _report(status: str = "completed") -> ExecutionReport:
    return ExecutionReport(
        execution_id="exec-1",
        manifest_id="manifest-actionability",
        manifest_revision_before=1,
        manifest_revision_after=1,
        plan_id="plan-1",
        started_at=NOW,
        completed_at=NOW,
        mode="live",
        status=status,
        replan_required=False,
        steps=[],
    )


class TestElementToBlockCharacterization:
    def test_normalizes_metadata_links_and_source_location_with_bbox(self) -> None:
        prov = Provenance(
            page_number=2,
            bbox=BoundingBox(left=1.0, top=2.0, right=30.0, bottom=40.0),
        )
        el = _element(
            "e-1",
            "paragraph",
            "Body",
            metadata={"ref": "#/texts/0", "nested": [{"child": "#/groups/1"}]},
            provenance=[prov],
        )
        block = _element_to_block(el)
        assert block["source_location"] == {
            "page_number": 2,
            "bbox": {"left": 1.0, "top": 2.0, "right": 30.0, "bottom": 40.0},
        }
        assert block["metadata"]["ref"] == "/texts/0"
        assert block["metadata"]["nested"] == [{"child": "/groups/1"}]
        assert block["type"] == "paragraph"
        assert block["text"] == "Body"

    @pytest.mark.parametrize(
        ("callout_type", "expected_type"),
        [
            ("note", "note"),
            ("tip", "note"),
            ("warning", "warning"),
            ("aviso", "warning"),
            ("importante", "warning"),
            ("caution", "warning"),
        ],
    )
    def test_callout_types_and_title_precedence(
        self, callout_type: str, expected_type: str
    ) -> None:
        el = _element(
            "c-1",
            "paragraph",
            "Remember this",
            metadata={
                "callout_id": "call-7",
                "callout_type": callout_type,
                "callout_title": "Meta Title",
            },
        )
        block = _element_to_block(el, callout_titles={"call-7": "Resolved Title"})
        assert block["type"] == expected_type
        assert block["title"] == "Resolved Title"
        assert block["text"] == "Remember this"

        fallback = _element_to_block(el)
        assert fallback["title"] == "Meta Title"

    @pytest.mark.parametrize(
        "extra_meta",
        [
            {"callout_id": "call-1", "callout_role": "title"},
            {"callout_id": "call-1", "slide_role": "slide_heading"},
            {"callout_id": "call-1", "slide_role": "deck_title"},
        ],
    )
    def test_callout_title_and_slide_headings_fall_through_to_element_type(
        self, extra_meta: dict
    ) -> None:
        el = _element("h-1", "heading", "Section", hierarchy_level=2, metadata=extra_meta)
        block = _element_to_block(el)
        assert block["type"] == "heading"
        assert block["level"] == 2

    def test_title_heading_code_formula_picture_and_fallback_types(self) -> None:
        title = _element_to_block(
            _element("t1", "title", "", raw_label="Doc Title", hierarchy_level=3)
        )
        assert (title["type"], title["level"], title["text"]) == ("heading", 1, "Doc Title")

        heading = _element_to_block(_element("h1", "heading", "Sub", hierarchy_level=0))
        assert (heading["type"], heading["level"], heading["text"]) == ("heading", 1, "Sub")

        code = _element_to_block(_element("c1", "code", "x = 1\r\ny = 2"))
        assert code["type"] == "code"
        assert "x = 1" in code["text"]

        formula_with_text = _element_to_block(_element("f1", "formula", "E = mc^2"))
        assert (formula_with_text["type"], formula_with_text["text"]) == ("math", "E = mc^2")

        formula_empty = _element_to_block(_element("f2", "formula", ""))
        assert (formula_empty["type"], formula_empty["text"]) == (
            "paragraph",
            "Formula detectada.",
        )

        pic_empty = _element_to_block(_element("p1", "picture", ""))
        assert (pic_empty["type"], pic_empty["alt_text"]) == (
            "image",
            t(MSG_UNDESCRIBED_PICTURE_ALT),
        )

        unknown = _element_to_block(_element("u1", "caption", "", raw_label="caption_raw"))
        assert (unknown["type"], unknown["text"]) == ("paragraph", "caption_raw")

    def test_list_item_ordered_numbering_and_unordered(self) -> None:
        unordered = _element_to_block(_element("l1", "list_item", "Item A"))
        assert unordered["type"] == "list"
        assert unordered["ordered"] is False
        assert unordered["items"] == ["Item A"]
        assert "start" not in unordered and "numbering" not in unordered

        ordered_alpha = _element_to_block(
            _element("l2", "list_item", "Item C", metadata={"enumerated": True, "marker": "c)"})
        )
        assert ordered_alpha["ordered"] is True
        assert ordered_alpha["start"] == 3
        assert ordered_alpha["numbering"] == "lower-alpha"

    def test_table_with_ast_plain_text_and_placeholder_fallback(self) -> None:
        empty_table = _element_to_block(_element("tb1", "table", ""))
        assert empty_table["type"] == "table"
        assert empty_table["rows"] == [["Tabela detectada"]]
        assert empty_table["table_ast"] is not None

        text_table = _element_to_block(_element("tb2", "table", "Col A | Col B"))
        assert text_table["rows"] == [["Col A | Col B"]]


class TestBuildPddlStructuredPayloadCharacterization:
    def test_clean_completed_run_is_cacheable_with_no_warnings(self) -> None:
        manifest = _manifest([_element("e1", "paragraph", "Hello")])
        payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=manifest,
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=_report("completed"),
            comparison=None,
        )
        assert payload["cacheable"] is True
        assert payload["technical_warnings"] == []
        meta = payload["canonical_metadata"]
        assert meta["pddl_execution_status"] == "completed"
        assert "pddl_extraction_degraded" not in meta
        assert meta["pddl_media_inspection"] is None
        assert meta["pddl_unsatisfied_summary"] is None

    def test_collects_all_warning_sources_and_disables_cache(self) -> None:
        pic_failed = _element(
            "p1", "picture", "", metadata={"vision_failure_reason": "model_failed"}
        )
        table_failed = _element(
            "t1", "table", "", metadata={"table_read_failure": "crop_unavailable"}
        )
        obs = Observation(
            id="obs-1",
            kind="repair-legacy-unicode-detected",
            target_ids=["p1"],
            severity="warning",
            message="Legacy unicode detected",
        )
        manifest = _manifest(
            [pic_failed, table_failed],
            observations=[obs],
            configuration={
                "extraction_degraded": True,
                "extraction_failures": {"mineru": "timeout"},
                "toolbox_provider": "docling",
                "media_inspection": "failed",
                "media_inspection_error": "boom",
                "document_genre": "slides",
                "genre_signals": ["landscape"],
            },
        )
        comparison = SimpleNamespace(comparison=SimpleNamespace(verdict="equivalent"))
        payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=manifest,
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=None,
            comparison=comparison,
        )
        assert payload["cacheable"] is False
        warnings = payload["technical_warnings"]
        assert len(warnings) == 6
        assert warnings[0] == (
            "Executor nao foi executado; somente manifesto e plano foram gerados."
        )
        assert warnings[1] == "Comparacao de planners: equivalent."
        assert warnings[2] == n(*MSG_PICTURES_NOT_DESCRIBED, 1).format(count=1)
        assert warnings[3] == n(*MSG_TABLES_NOT_READ, 1).format(count=1)
        assert "LEGACY_UNICODE_REPAIR=detect" in warnings[4]
        assert warnings[5] == t(MSG_STRUCTURAL_EXTRACTION_DEGRADED).format(
            provider="docling"
        )
        meta = payload["canonical_metadata"]
        assert meta["pddl_extraction_degraded"] is True
        assert meta["pddl_extraction_failures"] == {"mineru": "timeout"}
        assert meta["pddl_media_inspection"]["status"] == "failed"
        assert meta["pddl_visual_failures"] == {
            "pictures": {"model_failed": 1},
            "tables": {"crop_unavailable": 1},
        }

    def test_human_review_only_unsatisfied_obligation_remains_cacheable(self) -> None:
        el = _element("e1", "heading", "Title", hierarchy_level=3)
        attempt = ObligationAttempt(
            method="human-review",
            status="succeeded",
            started_at=NOW,
            completed_at=NOW,
            message="Escalated to human review",
        )
        human_review_ob = build_obligation(
            "repair-heading-hierarchy",
            ["e1"],
            ["human-review"],
        ).model_copy(update={"selected": True, "attempts": [attempt]})
        manifest = _manifest([el], obligations=[human_review_ob])
        payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=manifest,
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=_report("completed"),
            comparison=None,
        )
        assert payload["cacheable"] is True
        assert payload["canonical_metadata"]["pddl_unsatisfied_summary"] is not None
        assert len(payload["technical_warnings"]) == 1

        retry_ob = build_obligation(
            "refine-reading-order",
            ["e1"],
            ["xycut-order"],
        ).model_copy(update={"selected": True})
        retry_payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=_manifest([el], obligations=[retry_ob]),
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=_report("completed"),
            comparison=None,
        )
        assert retry_payload["cacheable"] is False

    def test_status_fusion_toolbox_availability_and_formula_failures_branches(
        self,
    ) -> None:
        base_manifest = _manifest(
            [_element("e1", "paragraph", "Body")],
            configuration={"fusion": {"status": "fused", "pages": 1}},
        )
        dry_run_payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=base_manifest,
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=_report("dry-run-completed"),
            comparison=None,
            toolbox_availability={"docling": True, "mineru": False},
        )
        assert dry_run_payload["cacheable"] is True
        assert dry_run_payload["technical_warnings"] == []
        dry_meta = dry_run_payload["canonical_metadata"]
        assert dry_meta["pddl_toolbox_availability"] == {
            "docling": True,
            "mineru": False,
        }
        assert dry_meta["pddl_fusion"] == {"status": "fused", "pages": 1}

        replan_payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=_manifest([_element("e1", "paragraph", "Body")]),
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=_report("replan-required"),
            comparison=None,
        )
        assert replan_payload["cacheable"] is False
        assert len(replan_payload["technical_warnings"]) == 1

        degraded_fusion_payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=_manifest(
                [_element("e1", "paragraph", "Body")],
                configuration={"fusion": {"status": "degraded", "reason": "fallback"}},
            ),
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=_report("completed"),
            comparison=None,
        )
        assert degraded_fusion_payload["cacheable"] is False
        assert degraded_fusion_payload["canonical_metadata"]["pddl_fusion"] == {
            "status": "degraded",
            "reason": "fallback",
        }

        formula_rec_failed = _element(
            "f1",
            "formula",
            "",
            metadata={"formula_recognition_failure": "recognizer_unavailable"},
        )
        formula_cls_failed = _element(
            "f2",
            "formula",
            "",
            metadata={
                "formula_classification": {
                    "status": "unclassified",
                    "reason": "provider_blocked",
                }
            },
        )
        formula_payload = build_pddl_structured_payload(
            file_path=Path("/tmp/doc.pdf"),
            manifest=_manifest([formula_rec_failed, formula_cls_failed]),
            plan=_plan(),
            planner_backend="heuristic",
            execution_report=_report("completed"),
            comparison=None,
        )
        assert formula_payload["cacheable"] is False
        assert formula_payload["technical_warnings"] == []
        assert formula_payload["canonical_metadata"]["pddl_visual_failures"] == {
            "formulas": {"recognizer_unavailable": 1, "provider_blocked": 1}
        }


class TestManifestPagesToPayloadCharacterization:
    def test_with_page_descriptors_falls_back_when_element_ids_empty_and_keeps_blank_page(
        self,
    ) -> None:
        e1 = _element("e1", "paragraph", "Second", page_number=1, reading_order=2)
        e2 = _element("e2", "paragraph", "First", page_number=1, reading_order=1)
        blank = _element(
            "e3",
            "paragraph",
            "",
            page_number=2,
            reading_order=3,
            metadata={"blank_page": True},
        )
        manifest = _manifest(
            [e1, e2, blank],
            pages=[
                PageDescriptor(page_number=2, element_ids=["e3"]),
                PageDescriptor(page_number=1, element_ids=[]),
            ],
        )
        pages = _manifest_pages_to_payload(manifest)
        assert [p["page_number"] for p in pages] == [1, 2]
        assert [b["text"] for b in pages[0]["blocks"]] == ["First", "Second"]
        assert pages[1]["blocks"] == []

    def test_explicit_page_descriptors_keep_valid_ids_without_fallback_and_drop_unlisted_pages(
        self,
    ) -> None:
        e1 = _element("e1", "paragraph", "Listed", page_number=1, reading_order=1)
        e2 = _element("e2", "paragraph", "Unlisted on p1", page_number=1, reading_order=2)
        e3 = _element("e3", "paragraph", "Unlisted page 2", page_number=2, reading_order=3)
        manifest = _manifest(
            [e1, e2, e3],
            pages=[PageDescriptor(page_number=1, element_ids=["missing-id", "e1"])],
        )
        pages = _manifest_pages_to_payload(manifest)
        assert [p["page_number"] for p in pages] == [1]
        assert [b["text"] for b in pages[0]["blocks"]] == ["Listed"]

    def test_excludes_page_numbers_and_merges_letterhead_members(self) -> None:
        logo = _element(
            "logo",
            "picture",
            "Institution crest",
            page_number=1,
            reading_order=1,
            provenance=[
                Provenance(
                    page_number=1,
                    bbox=BoundingBox(
                        left=5.0,
                        top=2.0,
                        right=15.0,
                        bottom=10.0,
                        coord_origin="TOPLEFT",
                    ),
                )
            ],
        )
        header_line = _element(
            "hdr",
            "page_header",
            "Federal Institute",
            page_number=1,
            reading_order=2,
            provenance=[
                Provenance(
                    page_number=1,
                    bbox=BoundingBox(
                        left=17.0,
                        top=3.0,
                        right=70.0,
                        bottom=9.0,
                        coord_origin="TOPLEFT",
                    ),
                )
            ],
        )
        body = _element("body", "paragraph", "Main content", page_number=1, reading_order=3)
        footer_num = _element(
            "pnum",
            "page_footer",
            "- 1 -",
            page_number=1,
            reading_order=4,
            provenance=[
                Provenance(
                    page_number=1,
                    bbox=BoundingBox(
                        left=45.0,
                        top=92.0,
                        right=55.0,
                        bottom=97.0,
                        coord_origin="TOPLEFT",
                    ),
                )
            ],
        )
        manifest = _manifest(
            [logo, header_line, body, footer_num],
            pages=[
                PageDescriptor(
                    page_number=1,
                    width=100.0,
                    height=100.0,
                    element_ids=["logo", "hdr", "body", "pnum"],
                )
            ],
        )
        pages = _manifest_pages_to_payload(manifest)
        assert len(pages) == 1
        blocks = pages[0]["blocks"]
        assert len(blocks) == 2
        assert blocks[0]["type"] == "paragraph"
        assert blocks[0]["metadata"]["role"] == "header"
        assert blocks[0]["metadata"]["letterhead_members"] == ["logo", "hdr"]
        assert "Federal Institute" in blocks[0]["text"]
        assert blocks[1]["text"] == "Main content"

    def test_without_page_descriptors_groups_by_page_and_skips_excluded_only_pages(
        self,
    ) -> None:
        e1 = _element("e1", "paragraph", "Page two", page_number=2, reading_order=2)
        e2 = _element("e2", "paragraph", "Page one", page_number=1, reading_order=1)
        blank = _element(
            "e3",
            "paragraph",
            "",
            page_number=3,
            reading_order=3,
            metadata={"blank_page": True},
        )
        manifest = _manifest([e1, e2, blank], pages=[])
        pages = _manifest_pages_to_payload(manifest)
        assert [p["page_number"] for p in pages] == [1, 2]
        assert [b["text"] for b in pages[0]["blocks"]] == ["Page one"]
        assert [b["text"] for b in pages[1]["blocks"]] == ["Page two"]
