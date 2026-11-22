"""Isolated characterization tests for the manifest need detectors (#612).

Each detector under ``acessilia_core.manifest.detectors`` is pure: it inspects
elements (and optional geometry or fusion evidence) and returns
``NeedCandidate`` records without mutating the manifest. These tests pin each
detector's output, evidence shape and edge cases on its own, plus the
materialization step and the ``inspect_document_needs`` facade.
"""

from __future__ import annotations

from acessilia_core.manifest import builder
from acessilia_core.manifest.detectors import (
    MAX_ID_SUFFIX,
    VLM_JUDGE_METHODS,
    NeedCandidate,
    detect_fusion_needs,
    detect_legacy_unicode_needs,
    detect_line_numbers_need,
    detect_page_fusion_needs,
    detect_page_layout_needs,
    detect_reading_order_need,
    detect_tail_join_need,
    detect_text_and_formula_normalizations,
    detect_verse_chunk_need,
    materialize_needs,
    needs_vlm_judge,
    obligation_suffix,
    pages_for_vlm_judge,
)
from acessilia_core.manifest.models import BoundingBox, ManifestElement, Provenance
from docstruct.fusion.types import DiffBlock


def _element(
    element_id: str,
    element_type: str = "paragraph",
    *,
    text: str | None = None,
    page_number: int | None = 1,
    reading_order: int = 1,
    bbox: tuple[float, float, float, float] | None = None,
    metadata: dict | None = None,
) -> ManifestElement:
    provenance = []
    if bbox is not None:
        left, top, right, bottom = bbox
        provenance.append(
            Provenance(
                page_number=page_number or 1,
                bbox=BoundingBox(
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                    coord_origin="TOPLEFT",
                ),
            )
        )
    return ManifestElement(
        id=element_id,
        type=element_type,
        raw_label=element_type,
        reading_order=reading_order,
        hierarchy_level=1,
        text=text,
        page_number=page_number,
        provenance=provenance,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# 1. Text and formula normalization
# ---------------------------------------------------------------------------


def test_detect_text_and_formula_normalizations_emits_both_in_order() -> None:
    formula = _element("el-f", "formula", text=r"\( x + 1 \)")
    prose = _element("el-p", "paragraph", text="ef\ufb01cient\u00a0text")
    clean = _element("el-c", "paragraph", text="Already clean text.")
    code = _element("el-code", "code", text="ef\ufb01cient\u00a0code")

    candidates = detect_text_and_formula_normalizations([formula, prose, clean, code])

    assert [c.kind for c in candidates] == ["normalize-formula", "normalize-text"]
    assert candidates[0].targets == [formula]
    assert candidates[0].evidence["before"] == r"\( x + 1 \)"
    assert candidates[0].evidence["after"] != candidates[0].evidence["before"]
    assert candidates[1].targets == [prose]
    assert candidates[1].evidence == {
        "before": "ef\ufb01cient\u00a0text",
        "after": "efficient text",
    }


# ---------------------------------------------------------------------------
# 2. Legacy Unicode repair
# ---------------------------------------------------------------------------


def test_detect_legacy_unicode_respects_modes_and_table_ast() -> None:
    decomposed = _element("el-1", "paragraph", text="Bras\u0131\u0301lia")
    replacement_only = _element("el-2", "paragraph", text="broken\ufffdword")
    table = _element(
        "el-3",
        "table",
        text=None,
        metadata={
            "table_ast": {
                "caption": "Ca\u0301lculo",
                "headers": [["A"]],
                "rows": [["1"]],
            }
        },
    )

    assert detect_legacy_unicode_needs([decomposed], legacy_unicode_repair="off") == []
    assert detect_legacy_unicode_needs([decomposed], legacy_unicode_repair="bogus") == []

    detected = detect_legacy_unicode_needs(
        [decomposed, replacement_only, table], legacy_unicode_repair="detect"
    )
    assert len(detected) == 1
    assert detected[0].kind == "repair-legacy-unicode"
    assert detected[0].emit_obligation is False
    assert [e.id for e in detected[0].targets] == ["el-1", "el-2", "el-3"]
    assert detected[0].evidence["elements"] == 3
    assert detected[0].evidence["replacement_characters"] == 1
    assert detected[0].evidence["dotless"] >= 1
    assert set(detected[0].evidence) == {
        "elements",
        "combining_runs",
        "combining_marks",
        "dotless",
        "spacing_diacritics",
        "spacing_word_internal",
        "replacement_characters",
    }

    repaired = detect_legacy_unicode_needs(
        [decomposed, replacement_only, table], legacy_unicode_repair="repair"
    )
    assert len(repaired) == 1
    assert repaired[0].emit_obligation is True
    assert [e.id for e in repaired[0].targets] == ["el-1", "el-3"]


# ---------------------------------------------------------------------------
# 3. Reading order (XY-Cut)
# ---------------------------------------------------------------------------


def test_detect_reading_order_need_flags_swapped_columns_and_skips_slide_headings() -> None:
    # Right column appears before left column in reading_order.
    slide_heading = _element(
        "el-slide",
        "heading",
        text="Slide 1 of 1",
        reading_order=1,
        bbox=(400, 20, 550, 50),
        metadata={"slide_role": "slide_heading"},
    )
    right_col = _element(
        "el-right", "paragraph", text="Right column", reading_order=2, bbox=(350, 100, 560, 220)
    )
    left_col = _element(
        "el-left", "paragraph", text="Left column", reading_order=3, bbox=(40, 100, 250, 220)
    )
    page_sizes = {1: (600.0, 800.0)}

    candidate = detect_reading_order_need(
        1, [slide_heading, right_col, left_col], page_sizes=page_sizes
    )
    assert candidate is not None
    assert candidate.kind == "refine-reading-order"
    assert [e.id for e in candidate.targets] == ["el-right", "el-left"]
    assert candidate.evidence == {
        "page_number": 1,
        "order_before": ["el-right", "el-left"],
        "order_after": ["el-left", "el-right"],
    }

    # Already in left-then-right order -> no need emitted.
    left_col.reading_order = 1
    right_col.reading_order = 2
    assert detect_reading_order_need(1, [left_col, right_col], page_sizes=page_sizes) is None


# ---------------------------------------------------------------------------
# 4. Verse / record chunking
# ---------------------------------------------------------------------------


def test_detect_verse_chunk_need_fires_on_long_record_block() -> None:
    record_text = "\n".join(f"Entry {index} {index}" for index in range(1, 45))
    el = _element("el-rec", "paragraph", text=record_text)
    blocks = [DiffBlock(md=record_text, kind="text", box=None, text=record_text, type="paragraph")]

    candidate = detect_verse_chunk_need([el], blocks)
    assert candidate is not None
    assert candidate.kind == "chunk-verse"
    assert candidate.targets == [el]
    assert candidate.evidence["chunks"] >= 2

    prose = _element("el-prose", "paragraph", text="A single normal paragraph.")
    prose_blocks = [
        DiffBlock(md=prose.text or "", kind="text", box=None, text=prose.text or "", type="paragraph")
    ]
    assert detect_verse_chunk_need([prose], prose_blocks) is None


# ---------------------------------------------------------------------------
# 5. Marginal line numbers
# ---------------------------------------------------------------------------


def test_detect_line_numbers_need_fires_on_numbered_lines() -> None:
    lines = ("word " * 30) + " 10 more words 15 more words 20 more words 25"
    el = _element("el-verse", "paragraph", text=lines)
    blocks = [DiffBlock(md=lines, kind="text", box=None, text=lines, type="paragraph")]

    candidate = detect_line_numbers_need([el], blocks)
    assert candidate is not None
    assert candidate.kind == "extract-line-numbers"
    assert candidate.targets == [el]
    assert candidate.evidence["count"] >= 1


# ---------------------------------------------------------------------------
# 6. Tail-join blocks
# ---------------------------------------------------------------------------


def test_detect_tail_join_need_joins_short_trailing_blocks() -> None:
    body = _element("el-1", "paragraph", text="A long body block", reading_order=1)
    tail_a = _element("el-2", "page_header", text="Running head", reading_order=2)
    tail_b = _element("el-3", "page_footer", text="42", reading_order=3)
    elements = [body, tail_a, tail_b]
    blocks = [
        DiffBlock(md=body.text or "", kind="text", box=None, text=body.text or "", type="paragraph"),
        DiffBlock(md="Running head", kind="text", box=None, text="Running head", type="page_header", role="header"),
        DiffBlock(md="42", kind="text", box=None, text="42", type="page_footer", role="footer"),
    ]

    candidate = detect_tail_join_need(elements, blocks)
    assert candidate is not None
    assert candidate.kind == "join-tail-blocks"
    assert candidate.evidence["before_count"] == 3
    assert candidate.evidence["after_count"] < 3
    assert len(candidate.targets) == 3 - candidate.evidence["after_count"] + 1


def test_detect_page_layout_needs_runs_all_page_detectors() -> None:
    right = _element("el-r", "paragraph", text="Right " * 15, reading_order=1, bbox=(350, 100, 560, 220))
    left = _element("el-l", "paragraph", text="Left " * 15, reading_order=2, bbox=(40, 100, 250, 220))
    header = _element("el-h", "page_header", text="Running head", reading_order=3)
    footer = _element("el-f", "page_footer", text="42", reading_order=4)

    candidates = detect_page_layout_needs(
        {1: [right, left, header, footer]},
        page_sizes={1: (600.0, 800.0)},
    )
    kinds = [c.kind for c in candidates]
    assert "refine-reading-order" in kinds
    assert "join-tail-blocks" in kinds


# ---------------------------------------------------------------------------
# 7. Dual-provider fusion and VLM judge
# ---------------------------------------------------------------------------


def test_detect_page_fusion_needs_covers_judge_rescue_table_and_repetition() -> None:
    para = _element("el-1", "paragraph", text="Hello")
    table = _element("el-2", "table", text=None)
    stats = {
        "route": "mineru",
        "route_reason": "structure_ambiguous",
        "provider_divergence": True,
        "dropped-mineru": 2,
        "table_divergence": True,
        "repetition_tokens_cut": 120,
    }

    with_judge = detect_page_fusion_needs([para, table], stats, 1, judge=True)
    by_kind = {c.kind: c for c in with_judge}
    assert set(by_kind) == {
        "adjudicate-page",
        "rescue-omitted-block",
        "select-table-source",
        "guard-repetition",
    }
    assert by_kind["adjudicate-page"].methods == VLM_JUDGE_METHODS
    assert by_kind["select-table-source"].targets == [table]
    assert by_kind["guard-repetition"].evidence == {"page_number": 1, "tokens_cut": 120}

    without_judge = detect_page_fusion_needs([para, table], stats, 1, judge=False)
    adjudicate = next(c for c in without_judge if c.kind == "adjudicate-page")
    assert adjudicate.methods == ["human-review"]


def test_detect_fusion_needs_emits_single_document_fuse_providers_and_respects_budget() -> None:
    p1 = _element("el-1", "paragraph", text="Page 1", page_number=1)
    p2 = _element("el-2", "paragraph", text="Page 2", page_number=2)
    evidence = {
        "pages": [
            {
                "page_number": 1,
                "stats": {
                    "route": "mineru",
                    "route_reason": "both_table->mineru",
                    "provider_divergence": True,
                    "similarity": 0.80,
                },
            },
            {
                "page_number": 2,
                "stats": {
                    "route": "mineru",
                    "route_reason": "both_table->mineru",
                    "provider_divergence": True,
                    "similarity": 0.40,
                },
            },
        ]
    }
    assert needs_vlm_judge(evidence["pages"][0]["stats"]) is True
    entries = [
        (1, evidence["pages"][0]["stats"], [p1]),
        (2, evidence["pages"][1]["stats"], [p2]),
    ]
    assert pages_for_vlm_judge(entries, 1) == {2}

    candidates = detect_fusion_needs(
        [p1, p2],
        {1: [p1], 2: [p2]},
        fusion_evidence=evidence,
        fusion_judge_max_pages=1,
    )
    adjudicates = [c for c in candidates if c.kind == "adjudicate-page"]
    fuses = [c for c in candidates if c.kind == "fuse-providers"]
    assert len(adjudicates) == 1
    assert adjudicates[0].evidence["page_number"] == 2
    assert len(fuses) == 1
    assert fuses[0].evidence == {"pages": [1, 2]}
    assert [e.id for e in fuses[0].targets] == ["el-1", "el-2"]


def test_detect_fusion_needs_aggregate_stats_fallback() -> None:
    p1 = _element("el-1", "paragraph", text="Some text")
    stats = {"text_divergence": True, "provider_divergence": True}

    candidates = detect_fusion_needs(
        [p1],
        {1: [p1]},
        fusion_evidence=None,
        fusion_stats=stats,
        fusion_judge_max_pages=1,
    )
    kinds = [c.kind for c in candidates]
    assert kinds == ["adjudicate-page", "fuse-providers"]


# ---------------------------------------------------------------------------
# 8. Materialization & facade parity
# ---------------------------------------------------------------------------


def test_materialize_needs_deduplicates_filters_skeleton_order_and_hashes_long_ids() -> None:
    el1 = _element("element-000001", "paragraph", text="A")
    el2 = _element("element-000002", "paragraph", text="B")
    nameless = ManifestElement.model_construct(
        id="", type="paragraph", raw_label="paragraph", reading_order=3, text="C"
    )
    candidates = [
        NeedCandidate("refine-reading-order", [el1, el2, el1, nameless], {"page_number": 1}),
        NeedCandidate("refine-reading-order", [el1, el2], {"page_number": 1}),
        NeedCandidate("repair-legacy-unicode", [el1], {"elements": 1}, emit_obligation=False),
    ]

    obs_no_sec, obls_no_sec = materialize_needs(
        candidates,
        obligation_specs=builder.V23_OBLIGATION_BY_KIND,
        method_costs=builder.DEFAULT_METHOD_COSTS,
        secondary_extraction_available=False,
    )
    assert len(obs_no_sec) == 2
    assert len(obls_no_sec) == 1
    assert obls_no_sec[0].target_ids == ["element-000001", "element-000002"]
    assert "skeleton-order" not in obls_no_sec[0].admissible_methods

    _, obls_with_sec = materialize_needs(
        candidates,
        obligation_specs=builder.V23_OBLIGATION_BY_KIND,
        method_costs=builder.DEFAULT_METHOD_COSTS,
        secondary_extraction_available=True,
    )
    assert "skeleton-order" in obls_with_sec[0].admissible_methods

    long_ids = [f"element-{i:06d}" for i in range(40)]
    suffix = obligation_suffix(long_ids)
    assert len(suffix) <= MAX_ID_SUFFIX
    assert suffix.startswith("40-targets-")


def test_builder_inspect_document_needs_materializes_with_default_catalog() -> None:
    formula = _element("el-1", "formula", text=r"\( x^2 \)")
    obs, obls = builder.inspect_document_needs([formula])
    assert [o.kind for o in obs] == ["normalize-formula-detected"]
    assert [o.kind for o in obls] == ["normalize-formula"]
