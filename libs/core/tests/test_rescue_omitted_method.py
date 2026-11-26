"""``rescue-omitted`` restores the primary provider's text a page lost (#236).

The manifest is the primary provider's extraction, except for the pages the
deterministic router took from the secondary provider; the secondary-extraction
artifact keeps the primary elements those pages replaced.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from core_config_support import core_config, document_config, toolbox_config

from acessilia_core.i18n import reset_request_locale, set_request_locale
from acessilia_core.manifest.builder import (
    DEFAULT_METHOD_COSTS,
    SECONDARY_EXTRACTION_ARTIFACT_ID,
    SECONDARY_EXTRACTION_KIND,
)
from acessilia_core.manifest.models import (
    Artifact,
    BoundingBox,
    ExtractorRun,
    ManifestElement,
    ManifestSummary,
    Obligation,
    ObligationAttempt,
    PageDescriptor,
    ProcessingManifest,
    Provenance,
    SourceDocument,
)
from acessilia_core.pipeline.enrichment import inline_math as inline_math_stage
from acessilia_core.pipeline.handlers.registry import METHOD_HANDLERS
from acessilia_core.pipeline.handlers.rescue import (
    _handle_rescue_omitted_method,
    is_legitimate_text,
)
from acessilia_core.pipeline.obligations import NON_CRITICAL_OBLIGATION_KINDS
from acessilia_core.ports import RunPorts

NOW = datetime(2026, 11, 18, tzinfo=UTC)
W, H = 600.0, 800.0
TOP = (40, 60, 560, 120)
MIDDLE = (40, 200, 560, 300)
LOWER = (40, 400, 560, 500)
BOTTOM = (40, 600, 560, 700)
FOOT = (280, 760, 320, 780)

LOST = "Only the primary provider extracted this paragraph, and the page lost it."


@pytest.fixture(autouse=True)
def _english_messages():
    token = set_request_locale("en_US")
    try:
        yield
    finally:
        reset_request_locale(token)


def _bbox(box) -> dict:
    left, top, right, bottom = box
    return {"left": left, "top": top, "right": right, "bottom": bottom,
            "coord_origin": "TOPLEFT"}


def _el(element_id, kind, text, box, order, page=1, metadata=None) -> ManifestElement:
    return ManifestElement(
        id=element_id,
        type=kind,
        raw_label=kind,
        reading_order=order,
        hierarchy_level=1,
        text=text,
        page_number=page,
        provenance=[Provenance(page_number=page, bbox=BoundingBox(**_bbox(box)))],
        metadata=metadata or {},
    )


def _row(element_id, kind, text, box, order, page=1, parent_id=None) -> dict:
    """A primary (Docling) element the router replaced, as the artifact keeps it."""
    return {
        "id": element_id,
        "type": kind,
        "raw_label": kind,
        "reading_order": order,
        "hierarchy_level": 1,
        "text": text,
        "page_number": page,
        "parent_id": parent_id,
        "provenance": [{"page_number": page, "bbox": _bbox(box)}],
        "metadata": {},
    }


def _adopted(element_id, kind, text, box, order, page=1, provider="mineru"):
    return _el(element_id, kind, text, box, order, page, {"provider": provider})


def _manifest(
    tmp_path: Path,
    elements: list[ManifestElement],
    *,
    replaced: dict[int, list[dict]] | None = None,
    secondary_provider: str = "mineru",
    with_artifact: bool = True,
    targets: list[str] | None = None,
) -> ProcessingManifest:
    pages = sorted({e.page_number for e in elements})
    artifacts = []
    if with_artifact:
        record = {
            "provider": secondary_provider,
            "document": {"document": {
                "pages": [{"page_number": p, "width": W, "height": H} for p in pages],
                "elements": [],
            }},
        }
        if replaced:
            record["replaced_primary_pages"] = {str(k): v for k, v in replaced.items()}
        content = json.dumps(record).encode()
        path = tmp_path / "secondary.json"
        path.write_bytes(content)
        artifacts.append(Artifact(
            id=SECONDARY_EXTRACTION_ARTIFACT_ID,
            kind=SECONDARY_EXTRACTION_KIND,
            path=str(path),
            media_type="application/json",
            sha256=hashlib.sha256(content).hexdigest(),
        ))
    methods = ["rescue-omitted", "human-review"]
    return ProcessingManifest(
        manifest_id="manifest-rescue",
        created_at=NOW,
        source=SourceDocument(
            document_id="doc", filename="doc.pdf", path=str(tmp_path / "doc.pdf"),
            media_type="application/pdf", byte_size=1, sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="1", started_at=NOW, completed_at=NOW, duration_ms=1,
            configuration={"toolbox_provider": "docling"},
        ),
        title="Doc",
        language="pt-BR",
        pages=[
            PageDescriptor(
                page_number=p, width=W, height=H,
                element_ids=[e.id for e in elements if e.page_number == p],
            )
            for p in pages
        ],
        elements=elements,
        obligations=[Obligation(
            id="o-1",
            kind="rescue-omitted-block",
            target_ids=targets or [e.id for e in elements if e.page_number == 1],
            admissible_methods=methods,
            method_costs={m: DEFAULT_METHOD_COSTS[m] for m in methods},
            rationale="test",
        )],
        artifacts=artifacts,
        summary=ManifestSummary(
            page_count=len(pages), element_count=len(elements),
            observation_count=0, obligation_count=1, element_types={},
        ),
    )


def _rescue(manifest, obligation_id="o-1", *, legacy_unicode_repair="off"):
    config = core_config(document={"legacy_unicode_repair": legacy_unicode_repair})
    return _handle_rescue_omitted_method(manifest, obligation_id, config=config)


def _routed_page(tmp_path, **kwargs):
    """Page 1 taken from MinerU, page 2 kept from Docling."""
    elements = [
        _adopted("m-1", "heading", "Introduction", TOP, 1),
        _adopted("m-2", "paragraph", "The first paragraph of the body text.", MIDDLE, 2),
        _adopted("m-3", "table", "a | b", BOTTOM, 3),
        _el("d-9", "paragraph", "The text of page two.", MIDDLE, 4, page=2),
    ]
    replaced = {1: [
        _row("d-1", "heading", "Introduction", TOP, 1),
        _row("d-2", "paragraph", "The first paragraph of the body text.", MIDDLE, 2),
        _row("d-3", "paragraph", LOST, LOWER, 3),
        _row("d-4", "paragraph", "7", FOOT, 4),
    ]}
    return _manifest(tmp_path, elements, replaced=replaced, **kwargs)


def _texts(manifest, page=1):
    return [
        e.text for e in sorted(manifest.elements, key=lambda e: e.reading_order)
        if e.page_number == page
    ]


def test_the_method_is_registered_and_its_kind_is_critical():
    assert "rescue-omitted" in METHOD_HANDLERS
    assert "rescue-omitted-block" not in NON_CRITICAL_OBLIGATION_KINDS


def test_restores_the_primary_block_a_routed_page_lost(tmp_path):
    manifest = _routed_page(tmp_path)

    result = _rescue(manifest)

    assert result.success and result.validated
    assert "Blocks restored from the primary provider: 1 (pages 1)" in result.message
    # Inserted after the block paired with the one before it; the page number
    # stays out.
    assert _texts(manifest) == [
        "Introduction", "The first paragraph of the body text.", LOST, "a | b",
    ]
    rescued = next(e for e in manifest.elements if e.text == LOST)
    assert rescued.id == "element-rescued-p1-d-3"
    assert rescued.metadata["provider"] == "docling"
    assert rescued.metadata["rescued_by"] == "rescue-omitted"
    assert [e.reading_order for e in manifest.elements] == list(range(1, 6))
    assert manifest.pages[0].element_ids == ["m-1", "m-2", rescued.id, "m-3"]
    assert manifest.summary.element_count == 5


def test_the_restored_block_is_marked_by_the_inline_math_step(tmp_path, monkeypatch):
    """#599: the real rescue handler restores a block the second pass marks."""
    text = "The relation h = 0 holds."
    elements = [
        _adopted("m-1", "heading", "Introduction", TOP, 1),
        _adopted("m-2", "paragraph", "The first paragraph of the body text.", MIDDLE, 2),
        _adopted("m-3", "table", "a | b", BOTTOM, 3),
    ]
    replaced = {1: [
        _row("d-1", "heading", "Introduction", TOP, 1),
        _row("d-2", "paragraph", "The first paragraph of the body text.", MIDDLE, 2),
        _row("d-3", "paragraph", text, LOWER, 3),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)
    _rescue(manifest)

    def span(value, font, x, baseline=450.0, size=11.96):
        width = max(len(value), 1) * size * 0.5
        return {
            "text": value, "font": font, "size": size, "flags": 4,
            "bbox": [x, baseline - size * 0.75, x + width, baseline + size * 0.25],
            "origin": [x, baseline],
        }

    async def fetch(source_path, pages, *, toolbox, artifact_id=None, client=None):
        return {1: {
            "page_number": 1, "width": W, "height": H, "rotation": 0,
            "lines": [{"bbox": [0, 0, 0, 0], "spans": [
                span("The relation ", "CMR12", 40),
                span("h", "CMMI12", 117.74),
                span("̸", "CMSY10", 123.72),
                span(" = 0", "CMR12", 123.72),
                span(" holds.", "CMR12", 147.64),
            ]}],
        }}

    monkeypatch.setattr("acessilia_core.toolbox.text_spans.fetch_text_spans", fetch)

    # The inline math step of the replan (#640, M4b) marks the restored block.
    asyncio.run(inline_math_stage._enrich_inline_math(
        manifest, tmp_path / "doc.pdf", document_config(),
        inline_math_stage.run_text_spans(RunPorts.none(), manifest, tmp_path / "doc.pdf", toolbox_config()),
    ))

    rescued = next(e for e in manifest.elements if e.text and "relation" in e.text)
    assert rescued.text == r"The relation $h\neq0$ holds."
    assert manifest.extractor.configuration["inline_math_detection"] == "fonts"


def test_a_second_run_restores_nothing(tmp_path):
    manifest = _routed_page(tmp_path)
    _rescue(manifest)
    before = [e.id for e in manifest.elements]

    result = _rescue(manifest)

    assert result.success
    assert "already carry the primary provider's text" in result.message
    assert [e.id for e in manifest.elements] == before


def test_text_the_secondary_merged_into_another_block_is_not_duplicated(tmp_path):
    first, second = "The first sentence of the paragraph.", "And its second sentence."
    elements = [_adopted("m-1", "paragraph", f"{first} {second}", MIDDLE, 1)]
    replaced = {1: [
        _row("d-1", "paragraph", first, (40, 200, 560, 240), 1),
        _row("d-2", "paragraph", second, (40, 400, 560, 440), 2),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    result = _rescue(manifest)

    assert result.success
    assert _texts(manifest) == [f"{first} {second}"]


@pytest.mark.parametrize(("first", "second"), [("Fig. 2", "Note 1"), ("fig. 2", "NOTE  1")])
def test_short_text_the_secondary_merged_into_another_block_is_not_duplicated(tmp_path, first, second):
    """#891 review: below ``_MIN_CONTAINED_TEXT`` characters the containment
    is a whole-word match, case and spacing folded."""
    elements = [_adopted("m-1", "paragraph", "Fig. 2 Note 1", MIDDLE, 1)]
    replaced = {1: [
        _row("d-1", "paragraph", first, (40, 200, 560, 240), 1),
        _row("d-2", "paragraph", second, (40, 400, 560, 440), 2),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    result = _rescue(manifest)

    assert result.success
    assert _texts(manifest) == ["Fig. 2 Note 1"]


def test_a_short_text_inside_a_longer_word_is_still_rescued(tmp_path):
    """``Note 1`` is not carried by ``Notes 12``: the match is on whole words."""
    elements = [_adopted("m-1", "paragraph", "Notes 12 and more", MIDDLE, 1)]
    replaced = {1: [_row("d-1", "paragraph", "Note 1", (40, 400, 560, 440), 1)]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    _rescue(manifest)

    assert "Note 1" in _texts(manifest)


def test_text_inside_a_primary_picture_is_not_rescued(tmp_path):
    elements = [_adopted("m-1", "picture", "", MIDDLE, 1)]
    replaced = {1: [
        _row("d-1", "picture", "", MIDDLE, 1),
        _row("d-2", "paragraph", "A legible label inside the figure", MIDDLE, 2,
             parent_id="d-1"),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    result = _rescue(manifest)

    assert result.success
    assert len(manifest.elements) == 1


def test_a_block_omitted_at_the_top_goes_before_the_first_element(tmp_path):
    elements = [_adopted("m-1", "paragraph", "The body text of the page.", MIDDLE, 1)]
    replaced = {1: [
        _row("d-1", "paragraph", LOST, TOP, 1),
        _row("d-2", "paragraph", "The body text of the page.", MIDDLE, 2),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    _rescue(manifest)

    assert _texts(manifest) == [LOST, "The body text of the page."]


def test_a_page_that_kept_the_primary_extraction_is_left_alone(tmp_path):
    elements = [_el("d-1", "paragraph", "Text from Docling.", MIDDLE, 1)]
    manifest = _manifest(tmp_path, elements)

    result = _rescue(manifest)

    assert result.success and result.validated
    assert "Pages 1 keep the primary provider's extraction" in result.message
    assert _texts(manifest) == ["Text from Docling."]


def test_does_not_require_the_calibrated_pair(tmp_path):
    manifest = _routed_page(tmp_path, secondary_provider="mineru-hyb")
    for element in manifest.elements:
        if element.metadata.get("provider") == "mineru":
            element.metadata["provider"] = "mineru-hyb"

    result = _rescue(manifest)

    assert result.success
    assert LOST in _texts(manifest)


def test_a_page_the_text_fusion_rewrote_fails(tmp_path):
    elements = [
        _el("d-1", "paragraph", "Fused text.", MIDDLE, 1,
            metadata={"fusion_provider": "docling+mineru"}),
    ]
    manifest = _manifest(tmp_path, elements)

    result = _rescue(manifest)

    assert not result.success
    assert "rewritten by the text fusion" in result.message


def test_an_adopted_page_without_the_replaced_primary_fails(tmp_path):
    elements = [_adopted("m-1", "paragraph", "Text from MinerU.", MIDDLE, 1)]
    manifest = _manifest(tmp_path, elements)

    result = _rescue(manifest)

    assert not result.success
    assert "came from mineru" in result.message
    assert len(manifest.elements) == 1


def test_a_failure_on_one_page_leaves_every_page_unchanged(tmp_path):
    """Review of #592: page 1 could be rescued, but page 2 cannot.

    The executor does not roll back a failed attempt, so the method must not
    leave page 1's rescue behind when it fails for page 2.
    """
    elements = [
        _adopted("m-1", "paragraph", "The first paragraph of the body text.", MIDDLE, 1),
        _adopted("m-2", "paragraph", "Text from MinerU.", MIDDLE, 2, page=2),
    ]
    replaced = {1: [
        _row("d-1", "paragraph", "The first paragraph of the body text.", MIDDLE, 1),
        _row("d-2", "paragraph", LOST, LOWER, 2),
    ]}
    manifest = _manifest(
        tmp_path, elements, replaced=replaced, targets=["m-1", "m-2"]
    )
    before = manifest.model_dump()

    result = _rescue(manifest)

    assert not result.success
    assert "Pages 2 came from mineru" in result.message
    assert manifest.model_dump() == before


def test_fails_without_the_secondary_extraction(tmp_path):
    elements = [_el("d-1", "paragraph", "Some text.", MIDDLE, 1)]
    manifest = _manifest(tmp_path, elements, with_artifact=False)

    result = _rescue(manifest)

    assert not result.success


def test_an_unknown_obligation_fails(tmp_path):
    manifest = _routed_page(tmp_path)

    assert not _rescue(manifest, "o-missing").success


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (LOST, True),
        ("Summary", True),
        ("12", False),
        ("iv", False),
        ("—— ** ——", False),
        ("ab", False),
        ("x7 #% q2 &8 @@", False),
    ],
)
def test_is_legitimate_text(text, expected):
    assert is_legitimate_text(text) is expected


# --- processing needs of the restored blocks (#594) -------------------------


def _single_rescue(tmp_path, row, *, extra=(), obligations=()):
    """Page 1 taken from MinerU, which lost the primary block ``row``."""
    elements = [
        _adopted("m-1", "paragraph", "The first paragraph of the body text.", MIDDLE, 1),
        *extra,
    ]
    replaced = {1: [
        _row("d-1", "paragraph", "The first paragraph of the body text.", MIDDLE, 1),
        row,
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced, targets=["m-1"])
    manifest.obligations.extend(obligations)
    manifest.summary.obligation_count = len(manifest.obligations)
    return manifest


def _new_obligations(manifest):
    return [item for item in manifest.obligations if item.id != "o-1"]


def test_a_restored_block_gets_its_text_normalized(tmp_path):
    manifest = _single_rescue(
        tmp_path, _row("d-2", "paragraph", "A restored\u00a0paragraph of text.", LOWER, 2)
    )

    assert _rescue(manifest).success

    [obligation] = _new_obligations(manifest)
    assert obligation.kind == "normalize-text"
    assert obligation.target_ids == ["element-rescued-p1-d-2"]
    assert any(item.kind == "normalize-text-detected" for item in manifest.observations)
    assert manifest.summary.obligation_count == len(manifest.obligations)


@pytest.mark.parametrize(("mode", "expected"), [("repair", True), ("off", False)])
def test_a_restored_block_gets_its_legacy_unicode_repaired(tmp_path, mode, expected):
    legacy = "The capital moved to Bras\u0131\u0301lia in the sixties."
    manifest = _single_rescue(tmp_path, _row("d-2", "paragraph", legacy, LOWER, 2))

    assert _rescue(manifest, legacy_unicode_repair=mode).success

    repairs = [
        item for item in _new_obligations(manifest) if item.kind == "repair-legacy-unicode"
    ]
    assert bool(repairs) is expected
    if expected:
        assert repairs[0].target_ids == ["element-rescued-p1-d-2"]


def test_page_level_needs_are_not_derived_over_the_restored_blocks(tmp_path):
    """Two restored blocks out of XY order would be a reading-order need."""
    elements = [_adopted("m-1", "paragraph", "The body text of the page.", MIDDLE, 1)]
    replaced = {1: [
        _row("d-1", "paragraph", "A first restored block, on the right.", (320, 400, 560, 500), 1),
        _row("d-2", "paragraph", "A second restored block, on the left.", (40, 400, 280, 500), 2),
        _row("d-3", "paragraph", "The body text of the page.", MIDDLE, 3),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    assert _rescue(manifest).success

    assert len(manifest.elements) == 3
    assert _new_obligations(manifest) == []


def test_a_restored_heading_that_skips_a_level_gets_its_repair(tmp_path):
    heading = _row("d-2", "heading", "Background", LOWER, 2)
    heading["hierarchy_level"] = 3
    manifest = _single_rescue(tmp_path, heading)

    assert _rescue(manifest).success

    [obligation] = _new_obligations(manifest)
    assert obligation.kind == "repair-heading-hierarchy"
    assert obligation.target_ids == ["element-rescued-p1-d-2"]


def test_an_obligation_an_enrichment_removed_does_not_come_back(tmp_path):
    """A picture with no describe-image obligation keeps having none."""
    picture = _el("d-9", "picture", "", MIDDLE, 2, page=2)
    manifest = _single_rescue(
        tmp_path, _row("d-2", "paragraph", LOST, LOWER, 2), extra=[picture]
    )

    assert _rescue(manifest).success

    assert _new_obligations(manifest) == []


def test_an_existing_obligation_and_its_attempts_are_kept(tmp_path):
    """The derivation finds the gap again; the live obligation is not replaced."""
    gap = _adopted("m-h", "heading", "Results", BOTTOM, 2)
    gap.hierarchy_level = 3
    existing = Obligation(
        id="obligation-repair-heading-m-h",
        kind="repair-heading-hierarchy",
        target_ids=["m-h"],
        admissible_methods=["deterministic-heading-repair", "human-review"],
        method_costs={"deterministic-heading-repair": 5, "human-review": 100},
        rationale="gap",
        status="pending",
        attempts=[ObligationAttempt(
            method="deterministic-heading-repair", status="failed",
            started_at=NOW, completed_at=NOW, message="kept",
        )],
    )
    manifest = _single_rescue(
        tmp_path,
        _row("d-2", "paragraph", LOST, LOWER, 2),
        extra=[gap],
        obligations=[existing],
    )

    assert _rescue(manifest).success

    same = [item for item in manifest.obligations if item.kind == "repair-heading-hierarchy"]
    assert same == [existing]
    assert same[0].attempts[0].message == "kept"
