"""A presentation is structured slide by slide (backend.core.manifest.slides).

Every user-visible heading is resolved through backend.i18n.t, so the
assertions hold under any supported server locale.
"""

from __future__ import annotations

import copy
from datetime import UTC, datetime

import pytest

from backend.core.manifest.builder import build_processing_manifest
from backend.core.manifest.toolbox_extractor import ToolboxExtraction
from backend.i18n import t
from backend.log_messages import MSG_SLIDE_HEADING, MSG_SLIDE_HEADING_WITH_TITLE

NOW = datetime(2026, 10, 23, tzinfo=UTC)
WIDTH, HEIGHT = 960, 540


def _element(element_id, kind, page, order, box, text=None, level=0):
    left, top, right, bottom = box
    return {
        "id": element_id,
        "type": kind,
        "raw_label": kind,
        "reading_order": order,
        "hierarchy_level": level,
        "text": text,
        "page_number": page,
        "provenance": [
            {
                "page_number": page,
                "bbox": {
                    "left": left, "top": top, "right": right, "bottom": bottom,
                    "coord_origin": "TOPLEFT",
                },
            }
        ],
    }


def _deck() -> ToolboxExtraction:
    """Three slides: a titled text slide, a slide with a small picture, and a
    slide that is mostly one picture and has no title."""
    elements = [
        _element("e-1", "title", 1, 1, (60, 40, 900, 100), "Introduction", level=1),
        _element("e-2", "paragraph", 1, 2, (60, 140, 900, 200), "Course goals."),
        _element("e-3", "heading", 2, 3, (60, 40, 900, 100), "Results", level=1),
        _element("e-4", "heading", 2, 4, (60, 120, 900, 160), "Details", level=2),
        _element("e-5", "paragraph", 2, 5, (60, 180, 900, 240), "Growth of 10%."),
        _element("e-6", "picture", 2, 6, (700, 300, 900, 500)),
        _element("e-7", "picture", 3, 7, (60, 40, 900, 480)),
        _element("e-8", "paragraph", 3, 8, (60, 490, 300, 520), "Source: IBGE"),
    ]
    pages = [
        {
            "page_number": number,
            "width": WIDTH,
            "height": HEIGHT,
            "element_ids": [e["id"] for e in elements if e["page_number"] == number],
        }
        for number in (1, 2, 3)
    ]
    return ToolboxExtraction(
        document={
            "status": "succeeded",
            "provider": "docling",
            "document": {
                "elements": elements,
                "pages": pages,
                "title": "Deck",
                "summary": {
                    "page_count": 3,
                    "element_count": len(elements),
                    "observation_count": 0,
                    "obligation_count": 0,
                },
            },
            "provenance": {},
        },
        started_at=NOW,
        completed_at=NOW,
        duration_ms=1,
        version="test",
        configuration={"toolbox_provider": "docling"},
    )


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "lecture.pdf"
    path.write_bytes(b"%PDF-1.4 deck")
    return path


def _build(source, *, presentation=True):
    return build_processing_manifest(
        source, _deck(), refine_reading_order=True, presentation=presentation
    )


def _build_edited(source, extraction, **options):
    """Build an extraction whose elements or pages a test changed."""
    document = extraction.document["document"]
    document["summary"].update(
        page_count=len(document["pages"]), element_count=len(document["elements"])
    )
    return build_processing_manifest(
        source, extraction, refine_reading_order=True, presentation=True, **options
    )


def _headings(manifest):
    return [
        (element.hierarchy_level, element.text, element.page_number)
        for element in sorted(manifest.elements, key=lambda item: item.reading_order)
        if element.type in {"title", "heading"}
    ]


def test_each_slide_opens_with_its_position_and_title(source):
    manifest = _build(source)

    assert _headings(manifest) == [
        # One H1 for the deck: its first slide title.
        (1, "Introduction", 1),
        (2, t(MSG_SLIDE_HEADING_WITH_TITLE).format(number=1, total=3, title="Introduction"), 1),
        (2, t(MSG_SLIDE_HEADING_WITH_TITLE).format(number=2, total=3, title="Results"), 2),
        # The slide's other headings move under its own.
        (3, "Details", 2),
        (2, t(MSG_SLIDE_HEADING).format(number=3, total=3), 3),
    ]
    # The headings already form a valid hierarchy: nothing to repair.
    assert not [o for o in manifest.obligations if o.kind == "repair-heading-hierarchy"]


def test_reading_order_never_crosses_a_slide(source):
    manifest = _build(source)

    ordered = sorted(manifest.elements, key=lambda item: item.reading_order)
    pages = [element.page_number for element in ordered]
    assert pages == sorted(pages)
    assert [element.reading_order for element in ordered] == list(range(1, len(ordered) + 1))
    # Every element, the synthetic ones included, is listed by its page.
    for page in manifest.pages:
        assert page.element_ids == [e.id for e in ordered if e.page_number == page.page_number]


def test_a_mostly_visual_slide_becomes_one_picture_of_the_whole_slide(source):
    manifest = _build(source)

    slide = [e for e in manifest.elements if e.page_number == 3]
    heading, picture = slide
    assert heading.type == "heading"
    assert picture.type == "picture" and picture.metadata["slide_visual"] is True
    # No box: the whole page is rendered for the vision model.
    assert picture.provenance == []
    assert picture.metadata["replaced_element_ids"] == ["e-7", "e-8"]
    # The description replaces the extracted text, which is kept as evidence.
    assert not any(e.text == "Source: IBGE" for e in manifest.elements)
    assert picture.metadata["replaced_text"] == "Source: IBGE"
    [describe] = [o for o in manifest.obligations if o.target_ids == [picture.id]]
    assert describe.kind == "describe-image"


def test_a_slide_with_a_small_picture_keeps_its_content(source):
    manifest = _build(source)

    texts = [e.text for e in manifest.elements if e.page_number == 2]
    assert "Growth of 10%." in texts
    assert any(e.id == "e-6" and e.type == "picture" for e in manifest.elements)


@pytest.mark.parametrize(
    "beside",
    [
        _element("e-9", "list_item", 3, 9, (620, 60, 900, 200), "First point."),
        _element("e-9", "table", 3, 9, (620, 60, 900, 300), "A | B"),
    ],
    ids=["bullets", "table"],
)
def test_a_slide_with_text_beside_its_picture_keeps_its_content(source, beside):
    extraction = _deck()
    document = extraction.document["document"]
    # The picture alone covers 0.6 of the slide: only the text beside it keeps
    # the slide as text.
    document["elements"][6]["provenance"][0]["bbox"].update(
        left=0, top=0, right=WIDTH * 0.6, bottom=HEIGHT
    )
    control = _build_edited(source, copy.deepcopy(extraction))
    assert any(e.metadata.get("slide_visual") for e in control.elements)
    document["elements"].append(beside)
    document["pages"][2]["element_ids"].append("e-9")

    manifest = _build_edited(source, extraction)

    assert not any(e.metadata.get("slide_visual") for e in manifest.elements)
    assert any(e.id == "e-9" for e in manifest.elements)


def test_a_background_picture_does_not_turn_a_text_slide_into_a_picture(source):
    extraction = _deck()
    document = extraction.document["document"]
    document["elements"].append(_element("e-9", "picture", 1, 9, (0, 0, WIDTH, HEIGHT)))
    document["pages"][0]["element_ids"].append("e-9")

    manifest = _build_edited(source, extraction)

    assert "Course goals." in [e.text for e in manifest.elements if e.page_number == 1]
    assert not any(
        e.metadata.get("slide_visual") for e in manifest.elements if e.page_number == 1
    )


def test_overlapping_pictures_are_counted_once(source):
    """Two pictures of 0.3 of the slide that mostly overlap cover less than half."""
    extraction = _deck()
    document = extraction.document["document"]
    document["elements"][6]["provenance"][0]["bbox"].update(
        left=0, top=0, right=WIDTH * 0.6, bottom=HEIGHT * 0.5
    )
    document["elements"].append(
        _element("e-9", "picture", 3, 9, (WIDTH * 0.1, 0, WIDTH * 0.7, HEIGHT * 0.5))
    )
    document["pages"][2]["element_ids"].append("e-9")

    manifest = _build_edited(source, extraction)

    assert not any(e.metadata.get("slide_visual") for e in manifest.elements)


def test_a_slide_nothing_was_extracted_from_is_still_described(source):
    extraction = _deck()
    document = extraction.document["document"]
    document["pages"].append(
        {"page_number": 4, "width": WIDTH, "height": HEIGHT, "element_ids": []}
    )

    manifest = _build_edited(source, extraction)

    heading, picture = [e for e in manifest.elements if e.page_number == 4]
    assert heading.text == t(MSG_SLIDE_HEADING).format(number=4, total=4)
    assert picture.type == "picture" and picture.metadata["slide_visual"] is True
    [describe] = [o for o in manifest.obligations if o.target_ids == [picture.id]]
    assert describe.kind == "describe-image"


def test_the_deck_title_comes_from_the_first_slide_only(source):
    extraction = _deck()
    elements = extraction.document["document"]["elements"]
    elements[0]["type"] = elements[0]["raw_label"] = "paragraph"

    manifest = _build_edited(source, extraction)

    assert _headings(manifest)[0] == (1, "lecture", 1)


@pytest.mark.parametrize("value", ["0", "-0.1", "1.5"])
def test_a_slide_visual_coverage_out_of_range_is_refused_at_startup(monkeypatch, value):
    from backend.config.settings import Settings

    monkeypatch.setenv("SLIDE_VISUAL_COVERAGE", value)
    with pytest.raises(ValueError, match="SLIDE_VISUAL_COVERAGE"):
        Settings()


@pytest.mark.parametrize(
    "heading",
    ["1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18", "https://physics.nist.gov/cuu"],
    ids=["column-numbers", "url"],
)
def test_a_heading_that_does_not_read_as_a_title_is_not_the_slide_title(source, heading):
    """006.pdf: a periodic table's column numbers and a URL were labelled headings."""
    extraction = _deck()
    elements = extraction.document["document"]["elements"]
    elements[2]["text"] = heading

    manifest = build_processing_manifest(
        source, extraction, refine_reading_order=True, presentation=True
    )

    slide_two = [h for h in _headings(manifest) if h[2] == 2]
    # The next heading that reads as a title is the slide title instead.
    assert slide_two[0] == (
        2, t(MSG_SLIDE_HEADING_WITH_TITLE).format(number=2, total=3, title="Details"), 2
    )


def test_a_deck_without_titles_is_named_after_the_file(source):
    extraction = _deck()
    for element in extraction.document["document"]["elements"]:
        if element["type"] in {"title", "heading"}:
            element["type"] = element["raw_label"] = "paragraph"

    manifest = build_processing_manifest(
        source, extraction, refine_reading_order=True, presentation=True
    )

    assert _headings(manifest)[0] == (1, "lecture", 1)


def test_a_document_is_not_restructured(source):
    manifest = _build(source, presentation=False)

    assert not any(e.metadata.get("slide_role") for e in manifest.elements)
    assert len(manifest.elements) == 8


# ── The pipeline around the slide structure ─────────────────────────────


def test_a_presentation_is_not_fused_with_a_second_provider(monkeypatch):
    from unittest.mock import AsyncMock

    from acessilia_sdk.toolbox.clients import ToolboxStructureClient

    from backend.config.settings import settings
    from backend.core.manifest.toolbox_extractor import ToolboxManifestExtractor
    from tests.test_toolbox_manifest_extractor import (
        FIXTURE_PDF,
        SAMPLE_TOOLBOX_RESPONSE,
    )

    monkeypatch.setattr(settings, "fusion_mode", "dual")
    client = AsyncMock(spec=ToolboxStructureClient)
    client.provider = "docling"
    client.base_url = "http://localhost:8002"
    client.extract_structure = AsyncMock(return_value=SAMPLE_TOOLBOX_RESPONSE)

    def no_secondary(*_args, **_kwargs):
        pytest.fail("the secondary provider was called for a presentation")

    monkeypatch.setattr(
        "backend.core.manifest.toolbox_extractor.make_toolbox_client", no_secondary
    )

    result = ToolboxManifestExtractor(client=client, use_artifact_store=False).extract(
        FIXTURE_PDF, dual_fusion=False
    )

    assert "fusion_evidence" not in result.document


@pytest.mark.asyncio
async def test_a_whole_slide_is_described_with_the_page_prompt(source, monkeypatch):
    from backend.agents import pddl_orchestrator as pddl
    from backend.agents.output_schemas import VisionOutput

    manifest = _build(source)
    classifications = {}

    class Vision:
        def __init__(self, **_kwargs):
            pass

        async def describe_region(self, *, classification, page_num, **_kwargs):
            classifications[page_num] = classification
            return VisionOutput(
                kind="description", description="A bar chart.",
                language="pt-BR", confidence=0.9,
            )

    monkeypatch.setattr(pddl, "VisionAgent", Vision)
    monkeypatch.setattr(pddl, "_extract_picture_bytes", lambda _s, element, page, *_a: (b"png", page))

    await pddl._enrich_picture_descriptions(manifest, source, mode="medio")

    # Slide 3 is one picture of the whole slide; slide 2 keeps an embedded one.
    assert classifications == {3: "full_page_image", 2: "embedded_image"}


@pytest.mark.asyncio
async def test_media_inspection_decides_the_structure_before_extraction(
    source, monkeypatch, tmp_path
):
    from types import SimpleNamespace

    from docstruct.validation import validate_canonical_document

    from backend.agents import pddl_orchestrator as pddl
    from backend.pipeline.canonical_builder import build_canonical_document
    from tests.pddl_support import build_orchestrator

    calls = []

    async def inspect(_path):
        calls.append("media.inspect")
        return {"document_genre": "presentation", "genre_signals": ["creator:PowerPoint"]}

    def process(path, **kwargs):
        calls.append(("extract", kwargs.get("presentation")))
        manifest = _build(path, presentation=kwargs["presentation"])
        for element in manifest.elements:
            if element.type == "picture":
                element.text = "A bar chart of the growth per year."
                element.metadata["vision_description_complete"] = True
        return manifest

    async def noop(*_args, **_kwargs):
        return None

    orchestrator = build_orchestrator(max_replans=0)
    orchestrator.information_structural = SimpleNamespace(process=process)
    monkeypatch.setattr(pddl, "inspect_source_media", inspect)
    monkeypatch.setattr(pddl, "_enrich_picture_descriptions", noop)
    monkeypatch.setattr(pddl, "_enrich_table_structures", noop)

    payload = await orchestrator.executar(source, tmp_path, structured_output=True)

    assert calls == ["media.inspect", ("extract", True)]
    assert payload["canonical_metadata"]["pddl_media_inspection"] == {
        "status": "toolbox",
        "error": None,
        "document_genre": "presentation",
        "genre_signals": ["creator:PowerPoint"],
    }
    texts = [
        block.get("text")
        for page in payload["pages"]
        for block in page["blocks"]
        if block["type"] == "heading"
    ]
    assert t(MSG_SLIDE_HEADING_WITH_TITLE).format(number=2, total=3, title="Results") in texts
    canonical = build_canonical_document(payload)
    # One H1, then H2 per slide: the canonical document is valid.
    assert not validate_canonical_document(canonical)


def _with_labels(*extra):
    """The deck with ``extra`` elements added to slide 2, whose picture e-6
    spans (700, 300) to (900, 500)."""
    extraction = _deck()
    document = extraction.document["document"]
    document["elements"].extend(extra)
    document["pages"][1]["element_ids"].extend(element["id"] for element in extra)
    return extraction


def test_labels_on_a_picture_are_folded_into_it(source):
    """006.pdf slide 1: a scale diagram's labels stood as loose paragraphs."""
    extraction = _with_labels(
        _element("l-1", "paragraph", 2, 7, (720, 320, 760, 340), "1nm"),
        _element("l-2", "paragraph", 2, 8, (780, 320, 830, 340), "10nm"),
        _element("l-3", "paragraph", 2, 9, (720, 460, 880, 480), "Lithography resolution"),
    )

    manifest = _build_edited(source, extraction)

    [picture] = [e for e in manifest.elements if e.id == "e-6"]
    assert picture.metadata["figure_labels"] == ["1nm", "10nm", "Lithography resolution"]
    assert picture.metadata["figure_label_ids"] == ["l-1", "l-2", "l-3"]
    ids = {e.id for e in manifest.elements}
    assert not ids & {"l-1", "l-2", "l-3"}
    [page] = [p for p in manifest.pages if p.page_number == 2]
    assert not set(page.element_ids) & {"l-1", "l-2", "l-3"}
    assert not any(
        set(o.target_ids) & {"l-1", "l-2", "l-3"} for o in manifest.obligations
    )
    # The text beside the picture is the slide's own.
    assert "Growth of 10%." in [e.text for e in manifest.elements]


@pytest.mark.parametrize(
    "on_picture",
    [
        _element(
            "l-1", "paragraph", 2, 7, (710, 320, 890, 380),
            "The measured growth was steady across every region we surveyed.",
        ),
        _element("l-1", "formula", 2, 7, (710, 320, 890, 380), "x = y"),
        _element("l-1", "list_item", 2, 7, (710, 320, 890, 380), "First point."),
        _element("l-1", "caption", 2, 7, (710, 460, 890, 480), "Figure 3"),
        _element("l-1", "paragraph", 2, 7, (710, 320, 890, 340), "Grew 10%."),
        _element("l-1", "paragraph", 2, 7, (710, 320, 890, 340), "Source: IBGE, 2024"),
    ],
    ids=["sentence", "formula", "list-item", "caption", "short-sentence", "source-line"],
)
def test_content_on_a_picture_that_is_not_a_label_stays(source, on_picture):
    manifest = _build_edited(source, _with_labels(on_picture))

    assert any(e.id == "l-1" for e in manifest.elements)
    [picture] = [e for e in manifest.elements if e.id == "e-6"]
    assert "figure_labels" not in picture.metadata


def test_a_label_on_nested_pictures_goes_to_the_smallest(source):
    extraction = _with_labels(
        _element("p-2", "picture", 2, 7, (740, 340, 800, 400)),
        _element("l-1", "paragraph", 2, 8, (760, 360, 780, 380), "ADN"),
    )

    manifest = _build_edited(source, extraction)

    pictures = {e.id: e for e in manifest.elements if e.type == "picture"}
    assert pictures["p-2"].metadata["figure_labels"] == ["ADN"]
    assert "figure_labels" not in pictures["e-6"].metadata


def test_labels_stay_when_folding_is_off(source):
    extraction = _with_labels(
        _element("l-1", "paragraph", 2, 7, (720, 320, 760, 340), "1nm"),
    )

    manifest = _build_edited(source, extraction, slide_fold_figure_labels=False)

    assert any(e.id == "l-1" for e in manifest.elements)


def test_garbled_ocr_ending_in_a_period_is_still_a_label(source):
    """006.pdf slide 31 read "P3-" and "Sn4+" as "p3." and "4."."""
    extraction = _with_labels(
        _element("l-1", "paragraph", 2, 7, (720, 320, 760, 340), "p3."),
        _element("l-2", "paragraph", 2, 8, (780, 320, 830, 340), "4."),
    )

    manifest = _build_edited(source, extraction)

    [picture] = [e for e in manifest.elements if e.id == "e-6"]
    assert picture.metadata["figure_labels"] == ["p3.", "4."]


def test_text_on_a_background_picture_is_not_folded(source):
    extraction = _with_labels(
        # Slightly past the slide's edges, as an extractor reports a backdrop:
        # clipped to the slide, it still covers it all.
        _element("bg", "picture", 2, 7, (-10, -10, WIDTH + 10, HEIGHT + 10)),
        _element("l-1", "paragraph", 2, 8, (100, 300, 160, 320), "1nm"),
    )

    manifest = _build_edited(source, extraction)

    assert any(e.id == "l-1" for e in manifest.elements)
    [background] = [e for e in manifest.elements if e.id == "bg"]
    assert "figure_labels" not in background.metadata


def test_a_picture_without_a_box_hosts_no_label(source):
    extraction = _with_labels(
        _element("l-1", "paragraph", 2, 7, (720, 320, 760, 340), "1nm"),
    )
    [picture] = [
        e for e in extraction.document["document"]["elements"] if e["id"] == "e-6"
    ]
    picture["provenance"] = []

    manifest = _build_edited(source, extraction)

    assert any(e.id == "l-1" for e in manifest.elements)


def test_an_undescribed_picture_gives_its_labels_as_alt_text(source):
    """The labels left the running text; a failed description must not drop them."""
    from backend.agents.pddl_orchestrator import _element_to_block

    manifest = _build_edited(
        source,
        _with_labels(
            _element("l-1", "paragraph", 2, 7, (720, 320, 760, 340), "1nm"),
            _element("l-2", "paragraph", 2, 8, (780, 320, 830, 340), "10nm"),
        ),
    )
    [picture] = [e for e in manifest.elements if e.id == "e-6"]

    assert _element_to_block(picture)["alt_text"] == "1nm; 10nm"
    picture.text = "A scale from 1nm to 10nm."
    assert _element_to_block(picture)["alt_text"] == "A scale from 1nm to 10nm."


def _source_box(element):
    box = element.provenance[0].bbox
    return (box.left, box.top, box.right, box.bottom)


def test_a_label_beside_a_picture_grows_its_crop(source):
    """006.pdf slide 12: the nuclide notation sat beside the lamp it came with."""
    extraction = _with_labels(
        _element("l-1", "paragraph", 2, 7, (920, 360, 950, 400), "E Z"),
    )

    manifest = _build_edited(source, extraction)

    assert not any(e.id == "l-1" for e in manifest.elements)
    [picture] = [e for e in manifest.elements if e.id == "e-6"]
    assert picture.metadata["figure_labels"] == ["E Z"]
    # The crop the vision model describes now shows the notation.
    assert _source_box(picture) == (700, 300, 950, 500)


@pytest.mark.parametrize(
    "beside",
    [
        _element("l-1", "caption", 2, 7, (700, 510, 900, 530), "Figure 3"),
        _element("l-1", "paragraph", 2, 7, (700, 510, 900, 530), "Grew 10%."),
        # Within the margin, above: a heading naming the picture.
        _element("l-1", "heading", 2, 7, (700, 270, 900, 290), "Results 2024"),
    ],
    ids=["caption-under-one-picture", "sentence", "heading-above"],
)
def test_text_beside_a_picture_that_is_not_a_label_stays(source, beside):
    manifest = _build_edited(source, _with_labels(beside))

    assert any(e.id == "l-1" for e in manifest.elements)
    [picture] = [e for e in manifest.elements if e.id == "e-6"]
    assert _source_box(picture) == (700, 300, 900, 500)


def test_a_caption_across_two_pictures_merges_them(source):
    """006.pdf slide 18: the sources under four tiles were read across them."""
    extraction = _with_labels(
        _element("p-2", "picture", 2, 7, (500, 300, 680, 500)),
        _element("c-1", "caption", 2, 8, (520, 505, 880, 525), "Tabela CRC Handbook"),
        _element("c-2", "caption", 2, 9, (520, 525, 660, 535), "SBQ 2010"),
    )

    manifest = _build_edited(source, extraction)

    ids = {e.id for e in manifest.elements}
    assert "e-6" not in ids and not ids & {"c-1", "c-2"}
    [picture] = [e for e in manifest.elements if e.id == "p-2"]
    assert picture.metadata["merged_picture_ids"] == ["e-6"]
    assert picture.metadata["figure_labels"] == ["Tabela CRC Handbook", "SBQ 2010"]
    assert _source_box(picture) == (500, 300, 900, 535)


@pytest.mark.parametrize(
    "across",
    [
        _element("c-1", "paragraph", 2, 8, (520, 505, 880, 525), "Sources were checked twice."),
        # Read across stacked pictures, not side by side ones.
        _element("c-1", "caption", 2, 8, (520, 492, 880, 498), "Carbon tiles"),
    ],
    ids=["sentence", "stacked-pictures"],
)
def test_text_across_pictures_that_do_not_form_a_row_does_not_merge_them(source, across):
    extraction = _with_labels(
        (
            _element("p-2", "picture", 2, 7, (500, 300, 680, 500))
            if across["type"] == "paragraph"
            else _element("p-2", "picture", 2, 7, (700, 100, 900, 490))
        ),
        across,
    )
    if across["type"] == "caption":
        # e-6 sits right under p-2.
        [picture] = [
            e for e in extraction.document["document"]["elements"] if e["id"] == "e-6"
        ]
        picture["provenance"][0]["bbox"].update(top=500, bottom=540)

    manifest = _build_edited(source, extraction)

    ids = {e.id for e in manifest.elements}
    assert {"e-6", "p-2", "c-1"} <= ids
    assert not any(e.metadata.get("merged_picture_ids") for e in manifest.elements)


def test_a_chain_of_merges_keeps_every_picture_and_its_text(source):
    """Two caption rows: one merges p-b and e-6, the next merges p-a with the pair."""
    extraction = _with_labels(
        _element("p-a", "picture", 2, 7, (300, 300, 480, 500)),
        _element("p-b", "picture", 2, 8, (500, 300, 680, 500), "Crystal photo"),
        _element("l-1", "paragraph", 2, 9, (320, 320, 360, 340), "1nm"),
        _element("c-1", "caption", 2, 10, (510, 505, 890, 520), "Tabela CRC"),
        _element("c-2", "caption", 2, 11, (320, 525, 890, 535), "SBQ 2010"),
    )

    manifest = _build_edited(source, extraction)

    assert not {e.id for e in manifest.elements} & {"e-6", "p-b", "l-1", "c-1", "c-2"}
    [picture] = [e for e in manifest.elements if e.id == "p-a"]
    assert picture.metadata["merged_picture_ids"] == ["p-b", "e-6"]
    assert picture.metadata["figure_labels"] == ["1nm", "Crystal photo", "Tabela CRC", "SBQ 2010"]
    assert picture.metadata["figure_label_ids"] == ["l-1", "p-b", "c-1", "c-2"]
    assert _source_box(picture) == (300, 300, 900, 535)


def test_a_caption_under_one_picture_beside_a_merged_one_stays(source):
    extraction = _with_labels(
        _element("p-1", "picture", 2, 7, (100, 300, 200, 400)),
        _element("p-2", "picture", 2, 8, (250, 300, 350, 400)),
        _element("p-3", "picture", 2, 9, (400, 300, 500, 400)),
        _element("c-1", "caption", 2, 10, (100, 405, 350, 420), "Tabela SBQ 2010"),
        _element("c-2", "caption", 2, 11, (400, 405, 500, 420), "Fonte CRC"),
    )

    manifest = _build_edited(source, extraction)

    ids = {e.id for e in manifest.elements}
    assert {"p-3", "c-2"} <= ids
    [picture] = [e for e in manifest.elements if e.id == "p-1"]
    assert picture.metadata["figure_labels"] == ["Tabela SBQ 2010"]
    assert _source_box(picture) == (100, 300, 350, 420)


def test_labels_beside_a_picture_do_not_chain_across_the_slide(source):
    extraction = _with_labels(
        _element("p-1", "picture", 2, 7, (100, 250, 300, 350)),
        _element("l-1", "paragraph", 2, 8, (320, 280, 360, 300), "High rate"),
        _element("l-2", "paragraph", 2, 9, (420, 280, 460, 300), "Base case"),
        _element("l-3", "paragraph", 2, 10, (520, 280, 560, 300), "Low case"),
    )

    manifest = _build_edited(source, extraction)

    ids = {e.id for e in manifest.elements}
    assert "l-1" not in ids and {"l-2", "l-3"} <= ids
    [picture] = [e for e in manifest.elements if e.id == "p-1"]
    assert _source_box(picture) == (100, 250, 360, 350)


def test_a_box_of_unknown_origin_grows_along_its_own_axis(source):
    """A box with no origin whose top is above its bottom has y growing upwards."""
    extraction = _with_labels(
        _element("l-1", "paragraph", 2, 7, (920, 360, 950, 400), "E Z"),
    )
    elements = extraction.document["document"]["elements"]
    for element_id, (top, bottom) in {"e-6": (300, 500), "l-1": (360, 400)}.items():
        [element] = [e for e in elements if e["id"] == element_id]
        element["provenance"][0]["bbox"].update(
            coord_origin="UNKNOWN", top=HEIGHT - top, bottom=HEIGHT - bottom
        )

    manifest = _build_edited(source, extraction)

    [picture] = [e for e in manifest.elements if e.id == "e-6"]
    assert picture.metadata["figure_labels"] == ["E Z"]
    assert _source_box(picture) == (700, HEIGHT - 300, 950, HEIGHT - 500)


def test_pictures_with_different_origins_are_not_merged(source):
    extraction = _with_labels(
        _element("p-2", "picture", 2, 7, (500, 300, 680, 500)),
        _element("c-1", "caption", 2, 8, (520, 505, 880, 525), "Tabela CRC Handbook"),
    )
    [picture] = [
        e for e in extraction.document["document"]["elements"] if e["id"] == "p-2"
    ]
    bbox = picture["provenance"][0]["bbox"]
    bbox.update(coord_origin="BOTTOMLEFT", top=HEIGHT - 300, bottom=HEIGHT - 500)

    manifest = _build_edited(source, extraction)

    ids = {e.id for e in manifest.elements}
    assert {"e-6", "p-2", "c-1"} <= ids


def test_absorbing_is_off_with_the_folding(source):
    extraction = _with_labels(
        _element("l-1", "paragraph", 2, 7, (920, 360, 950, 400), "E Z"),
    )

    manifest = _build_edited(source, extraction, slide_fold_figure_labels=False)

    assert any(e.id == "l-1" for e in manifest.elements)


def test_the_slide_heading_is_never_reordered_after_a_grown_picture(source):
    """006.pdf slide 12: the lamp's crop grew to the notation and was read first."""
    extraction = _deck()
    document = extraction.document["document"]
    # Slide 12's boxes: a small title right of a lamp whose top is a little
    # higher, the notation beside the lamp, two paragraphs below.
    document["elements"][0]["provenance"][0]["bbox"].update(
        left=130, top=55, right=259, bottom=82
    )
    document["elements"][1]["provenance"][0]["bbox"].update(
        left=107, top=209, right=775, bottom=272
    )
    document["elements"].extend(
        [
            _element("p-1", "picture", 1, 3, (49, 52, 125, 158)),
            _element("l-1", "paragraph", 1, 4, (192, 108, 230, 157), "E Z"),
            _element("e-9", "paragraph", 1, 5, (107, 276, 773, 336), "A = mass number."),
        ]
    )
    document["pages"][0]["element_ids"].extend(["p-1", "l-1", "e-9"])

    manifest = _build_edited(source, extraction)

    [picture] = [e for e in manifest.elements if e.id == "p-1"]
    assert _source_box(picture) == (49, 52, 230, 158)
    headings = {
        e.id for e in manifest.elements
        if e.metadata.get("slide_role") in {"slide_heading", "deck_title"}
    }
    assert not any(
        set(o.target_ids) & headings
        for o in manifest.obligations
        if o.kind == "refine-reading-order"
    )
