"""``rescue-omitted`` restores the primary provider's text a page lost (#236).

The manifest is the primary provider's extraction, except for the pages the
deterministic router took from the secondary provider; the secondary-extraction
artifact keeps the primary elements those pages replaced.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
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
    PageDescriptor,
    ProcessingManifest,
    Provenance,
    SourceDocument,
)
from acessilia_core.pipeline.handlers.registry import METHOD_HANDLERS
from acessilia_core.pipeline.handlers.rescue import (
    _handle_rescue_omitted_method,
    is_legitimate_text,
)
from acessilia_core.pipeline.obligations import NON_CRITICAL_OBLIGATION_KINDS

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

    result = _handle_rescue_omitted_method(manifest, "o-1")

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


def test_a_second_run_restores_nothing(tmp_path):
    manifest = _routed_page(tmp_path)
    _handle_rescue_omitted_method(manifest, "o-1")
    before = [e.id for e in manifest.elements]

    result = _handle_rescue_omitted_method(manifest, "o-1")

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

    result = _handle_rescue_omitted_method(manifest, "o-1")

    assert result.success
    assert _texts(manifest) == [f"{first} {second}"]


def test_text_inside_a_primary_picture_is_not_rescued(tmp_path):
    elements = [_adopted("m-1", "picture", "", MIDDLE, 1)]
    replaced = {1: [
        _row("d-1", "picture", "", MIDDLE, 1),
        _row("d-2", "paragraph", "A legible label inside the figure", MIDDLE, 2,
             parent_id="d-1"),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    result = _handle_rescue_omitted_method(manifest, "o-1")

    assert result.success
    assert len(manifest.elements) == 1


def test_a_block_omitted_at_the_top_goes_before_the_first_element(tmp_path):
    elements = [_adopted("m-1", "paragraph", "The body text of the page.", MIDDLE, 1)]
    replaced = {1: [
        _row("d-1", "paragraph", LOST, TOP, 1),
        _row("d-2", "paragraph", "The body text of the page.", MIDDLE, 2),
    ]}
    manifest = _manifest(tmp_path, elements, replaced=replaced)

    _handle_rescue_omitted_method(manifest, "o-1")

    assert _texts(manifest) == [LOST, "The body text of the page."]


def test_a_page_that_kept_the_primary_extraction_is_left_alone(tmp_path):
    elements = [_el("d-1", "paragraph", "Text from Docling.", MIDDLE, 1)]
    manifest = _manifest(tmp_path, elements)

    result = _handle_rescue_omitted_method(manifest, "o-1")

    assert result.success and result.validated
    assert "Pages 1 keep the primary provider's extraction" in result.message
    assert _texts(manifest) == ["Text from Docling."]


def test_does_not_require_the_calibrated_pair(tmp_path):
    manifest = _routed_page(tmp_path, secondary_provider="mineru-hyb")
    for element in manifest.elements:
        if element.metadata.get("provider") == "mineru":
            element.metadata["provider"] = "mineru-hyb"

    result = _handle_rescue_omitted_method(manifest, "o-1")

    assert result.success
    assert LOST in _texts(manifest)


def test_a_page_the_text_fusion_rewrote_fails(tmp_path):
    elements = [
        _el("d-1", "paragraph", "Fused text.", MIDDLE, 1,
            metadata={"fusion_provider": "docling+mineru"}),
    ]
    manifest = _manifest(tmp_path, elements)

    result = _handle_rescue_omitted_method(manifest, "o-1")

    assert not result.success
    assert "rewritten by the text fusion" in result.message


def test_an_adopted_page_without_the_replaced_primary_fails(tmp_path):
    elements = [_adopted("m-1", "paragraph", "Text from MinerU.", MIDDLE, 1)]
    manifest = _manifest(tmp_path, elements)

    result = _handle_rescue_omitted_method(manifest, "o-1")

    assert not result.success
    assert "came from mineru" in result.message
    assert len(manifest.elements) == 1


def test_fails_without_the_secondary_extraction(tmp_path):
    elements = [_el("d-1", "paragraph", "Some text.", MIDDLE, 1)]
    manifest = _manifest(tmp_path, elements, with_artifact=False)

    result = _handle_rescue_omitted_method(manifest, "o-1")

    assert not result.success


def test_an_unknown_obligation_fails(tmp_path):
    manifest = _routed_page(tmp_path)

    assert not _handle_rescue_omitted_method(manifest, "o-missing").success


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
