"""End-to-end characterization and regression tests for unified visual-text ownership (#653: #263, #325, #398)."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pytest
from acessilia_core.agents.output_schemas import VisionOutput
from acessilia_core.agents.prompt_tools import build_surrounding_text_prompt
from acessilia_core.manifest.models import BoundingBox, ManifestElement, PageDescriptor, Provenance
from acessilia_core.pipeline.enrichment import pictures as picture_stage
from acessilia_core.pipeline.payload import _manifest_pages_to_payload
from core_config_support import model_config, toolbox_config, vision_config
from docstruct.visual_text import MAX_CONTEXT_ITEM_CHARS, MAX_CONTEXT_TOTAL_CHARS
from pddl_support import build_element, build_manifest, build_obligation
from test_page_number_furniture import HEIGHT, WIDTH, _placed

LINE_1_BOX = (117.0, 722.4, 241.4, 711.0)
LINE_2_BOX = (117.0, 705.1, 270.2, 693.7)
LOGO_BOX = (64.3, 723.2, 270.1, 694.0)
FURNITURE = {"content_layer": "furniture"}


class RecordingVision:
    calls: ClassVar[list[dict]] = []
    answers: ClassVar[dict[str, VisionOutput | None]] = {}

    def __init__(self, mode: str, *, region_cache, toolbox, models) -> None:
        pass

    async def describe_region(self, *, image_bytes, errors=None, **kwargs):
        key = image_bytes.decode()
        type(self).calls.append({"id": key, **kwargs})
        answer = type(self).answers.get(key)
        if answer is None and errors is not None:
            errors.append("vision unavailable")
        return answer


@pytest.fixture(autouse=True)
def fake_vision(monkeypatch):
    RecordingVision.calls, RecordingVision.answers = [], {}
    monkeypatch.setattr(picture_stage, "VisionAgent", RecordingVision)
    monkeypatch.setattr(
        picture_stage,
        "_extract_picture_bytes",
        lambda _src, element, fallback, _art, _mt, *, toolbox: (
            element.id.encode(),
            element.page_number or fallback or 1,
        ),
    )


def _vision_answer(description: str, **kwargs) -> VisionOutput:
    return VisionOutput(
        kind="description",
        description=description,
        language="pt-BR",
        confidence=0.92,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_case_398_scene_ocr_fragments_including_list_items_are_suppressed_when_covered() -> None:
    """#398 & Note 4: Scene-OCR paragraphs and list_items are suppressed when covered by the photo description."""
    elements = [
        build_element("el-1", "paragraph", text="FAVELAVIVE"),
        build_element("el-2", "paragraph", text="SAMBA"),
        build_element("el-3", "list_item", text="MINHA GENTE"),
        build_element("el-4", "list_item", text="VILA ISABEL"),
        build_element("el-5", "paragraph", text="ZECA PAGODINHO"),
        build_element("el-6", "paragraph", text="PAZ NO MUNDO"),
    ]
    for idx, el in enumerate(elements, start=1):
        el.reading_order = idx
    manifest = build_manifest(elements, [])
    manifest.pages = [
        PageDescriptor(
            page_number=1,
            width=800.0,
            height=600.0,
            element_ids=[el.id for el in elements],
        )
    ]
    photo_description = (
        "Instalacao artistica noturna formada por blocos de concreto pintados "
        "com inscricoes como 'Favela Vive', 'Samba', 'Minha Gente', 'Vila Isabel', "
        "'Zeca Pagodinho' e 'Paz no Mundo'."
    )
    RecordingVision.answers = {
        "element-injected-picture-000007": _vision_answer(photo_description)
    }

    await picture_stage._enrich_picture_descriptions(
        manifest,
        Path("IMG-20261108-WA0017.jpg"),
        mode="medio",
        media_inspection={"is_image": True, "requires_visual_inspection": True},
        vision=vision_config(retry_pass_delay_seconds=0),
        toolbox=toolbox_config(),
        models=model_config(),
        region_cache=None,
    )

    assert len(manifest.elements) == 7
    for el in manifest.elements[:6]:
        assert el.metadata["visual_text_ownership"] == {
            "role": "scene_text",
            "confidence": 1.0,
            "reason": "standalone_scene_ocr",
            "owner_id": "element-injected-picture-000007",
        }

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["image"]
    assert page["blocks"][0]["alt_text"] == photo_description
    assert page["text"] == photo_description


@pytest.mark.asyncio
async def test_case_398_generic_description_preserves_unmentioned_scene_text() -> None:
    """Note 2: When the VLM returns a generic description that omits the inscriptions, they are not lost."""
    elements = [
        build_element("el-1", "paragraph", text="FAVELA VIVE"),
        build_element("el-2", "paragraph", text="PAZ NO MUNDO"),
    ]
    elements[0].reading_order, elements[1].reading_order = 1, 2
    manifest = build_manifest(elements, [])
    manifest.pages = [
        PageDescriptor(
            page_number=1, width=800.0, height=600.0, element_ids=["el-1", "el-2"]
        )
    ]
    RecordingVision.answers = {
        "element-injected-picture-000003": _vision_answer(
            "A colorful art installation photographed at night."
        )
    }

    await picture_stage._enrich_picture_descriptions(
        manifest,
        Path("IMG-20261108-WA0017.jpg"),
        mode="medio",
        media_inspection={"is_image": True, "requires_visual_inspection": True},
        vision=vision_config(retry_pass_delay_seconds=0),
        toolbox=toolbox_config(),
        models=model_config(),
        region_cache=None,
    )

    [page] = _manifest_pages_to_payload(manifest)
    texts = [b.get("text") or b.get("alt_text") for b in page["blocks"]]
    assert texts == [
        "FAVELA VIVE",
        "PAZ NO MUNDO",
        "A colorful art installation photographed at night.",
    ]


@pytest.mark.asyncio
async def test_case_398_scene_ocr_is_preserved_once_without_duplication_when_vision_fails() -> None:
    """Note 2: When the vision model fails to describe the photo, scene OCR is emitted once (never duplicated)."""
    elements = [
        build_element("el-1", "paragraph", text="MINHA GENTE"),
        build_element("el-2", "paragraph", text="PAZ NO MUNDO"),
    ]
    elements[0].reading_order, elements[1].reading_order = 1, 2
    manifest = build_manifest(elements, [])
    manifest.pages = [
        PageDescriptor(
            page_number=1, width=800.0, height=600.0, element_ids=["el-1", "el-2"]
        )
    ]

    await picture_stage._enrich_picture_descriptions(
        manifest,
        Path("IMG-20261108-WA0017.jpg"),
        mode="medio",
        media_inspection={"is_image": True, "requires_visual_inspection": True},
        vision=vision_config(retry_pass_delay_seconds=0),
        toolbox=toolbox_config(),
        models=model_config(),
        region_cache=None,
    )

    [page] = _manifest_pages_to_payload(manifest)
    texts = [b.get("text") or b.get("alt_text") for b in page["blocks"]]
    assert texts.count("MINHA GENTE") == 1
    assert texts.count("PAZ NO MUNDO") == 1


@pytest.mark.asyncio
async def test_one_page_text_document_with_uppercase_headings_makes_no_vlm_call() -> None:
    """Note 1: A 1-page text document with uppercase headings is not treated as visual or scene OCR."""
    h1 = build_element("h1", "heading", text="INTRODUCTION")
    h2 = build_element("h2", "heading", text="METHODS")
    h1.reading_order, h2.reading_order = 1, 2
    manifest = build_manifest([h1, h2], [])
    manifest.pages = [
        PageDescriptor(
            page_number=1, width=WIDTH, height=HEIGHT, element_ids=["h1", "h2"]
        )
    ]

    await picture_stage._enrich_picture_descriptions(
        manifest,
        Path("article.pdf"),
        mode="medio",
        vision=vision_config(retry_pass_delay_seconds=0),
        toolbox=toolbox_config(),
        models=model_config(),
        region_cache=None,
    )

    assert RecordingVision.calls == []
    assert [el.type for el in manifest.elements] == ["heading", "heading"]
    [page] = _manifest_pages_to_payload(manifest)
    assert [b["text"] for b in page["blocks"]] == ["INTRODUCTION", "METHODS"]


def test_one_page_form_with_picture_and_uppercase_labels_preserves_labels_in_payload() -> None:
    """Note 1: Uppercase form labels outside a picture on a 1-page document are never suppressed."""
    pic = build_element(
        "pic-1",
        "picture",
        text="Applicant portrait and badge.",
        metadata={"vision_description_complete": True},
    )
    lbl1 = build_element("lbl-1", "paragraph", text="NAME")
    lbl2 = build_element("lbl-2", "paragraph", text="ADDRESS")
    for idx, el in enumerate((pic, lbl1, lbl2), start=1):
        el.reading_order = idx
    manifest = build_manifest([pic, lbl1, lbl2], [])
    manifest.pages = [
        PageDescriptor(
            page_number=1,
            width=WIDTH,
            height=HEIGHT,
            element_ids=["pic-1", "lbl-1", "lbl-2"],
        )
    ]

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["image", "paragraph", "paragraph"]
    assert [b.get("text") or b.get("alt_text") for b in page["blocks"]] == [
        "Applicant portrait and badge.",
        "NAME",
        "ADDRESS",
    ]


@pytest.mark.asyncio
async def test_case_263_context_is_passed_to_vision_and_redundant_header_transcription_is_deduplicated() -> None:
    """#263: Surrounding page text is passed to VisionAgent and redundant transcription sentences are stripped."""
    h1 = build_element("hdr-1", "paragraph", text="Universidade de Brasilia")
    h2 = build_element("hdr-2", "paragraph", text="Departamento de Matematica")
    pic = build_element("logo-1", "picture", text="")
    body = build_element(
        "body-1",
        "paragraph",
        text="Notas de aula sobre velocidade instantanea e derivadas.",
    )
    for idx, el in enumerate((h1, h2, pic, body), start=1):
        el.reading_order = idx
    manifest = build_manifest(
        [h1, h2, pic, body],
        [build_obligation("describe-image", ["logo-1"], ["vision-description"])],
    )
    manifest.pages = [
        PageDescriptor(
            page_number=1,
            width=WIDTH,
            height=HEIGHT,
            element_ids=["hdr-1", "hdr-2", "logo-1", "body-1"],
        )
    ]
    RecordingVision.answers = {
        "logo-1": _vision_answer(
            "Logotipo da Universidade de Brasilia composto por setas convergentes. "
            "A primeira linha e 'Universidade de Brasilia' e a segunda linha e 'Departamento de Matematica'."
        )
    }

    await picture_stage._enrich_picture_descriptions(
        manifest,
        Path("velocidade-instantanea.pdf"),
        mode="medio",
        vision=vision_config(retry_pass_delay_seconds=0),
        toolbox=toolbox_config(),
        models=model_config(),
        region_cache=None,
    )

    assert len(RecordingVision.calls) == 1
    assert "Universidade de Brasilia" in RecordingVision.calls[0]["surrounding_text"]
    assert "Departamento de Matematica" in RecordingVision.calls[0]["surrounding_text"]
    assert pic.text == (
        "Logotipo da Universidade de Brasilia composto por setas convergentes."
    )


def test_contained_scene_text_is_not_used_to_deduplicate_its_own_picture_description() -> None:
    """Note 5: Payload ownership uses page boxes so contained scene text does not strip its own image description."""
    pic = ManifestElement(
        id="pic-1",
        type="picture",
        raw_label="picture",
        reading_order=1,
        hierarchy_level=1,
        text=(
            "Diagrama de blocos do circuito. "
            "A primeira linha e 'ENTRADA PRINCIPAL' no bloco superior."
        ),
        page_number=1,
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=50.0,
                    top=100.0,
                    right=500.0,
                    bottom=400.0,
                    coord_origin="TOPLEFT",
                ),
            )
        ],
        metadata={"vision_description_complete": True},
    )
    contained = ManifestElement(
        id="sc-1",
        type="paragraph",
        raw_label="paragraph",
        reading_order=2,
        hierarchy_level=1,
        text="ENTRADA PRINCIPAL",
        page_number=1,
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=150.0,
                    top=150.0,
                    right=350.0,
                    bottom=200.0,
                    coord_origin="TOPLEFT",
                ),
            )
        ],
    )
    manifest = build_manifest([pic, contained], [])
    manifest.pages = [
        PageDescriptor(
            page_number=1,
            width=WIDTH,
            height=HEIGHT,
            element_ids=["pic-1", "sc-1"],
        )
    ]

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["image"]
    assert "ENTRADA PRINCIPAL" in page["blocks"][0]["alt_text"]


@pytest.mark.parametrize(
    "non_logo_description",
    [
        "Portrait photo of the author smiling.",
        "A small blue icon.",
        "A map of the region.",
        "A red circle.",
    ],
)
def test_case_325_non_logo_picture_beside_page_header_keeps_its_description(
    non_logo_description: str,
) -> None:
    """#325 & Note 3: An author photo, icon, map or generic shape beside a page header is not called 'Logo.'."""
    line_1 = _placed(
        "line-1",
        "page_header",
        "University of Brasilia",
        LINE_1_BOX,
        metadata=FURNITURE,
        reading_order=1,
    )
    picture = _placed(
        "pic-header",
        "picture",
        non_logo_description,
        LOGO_BOX,
        metadata={"vision_description_complete": True},
        reading_order=2,
    )
    line_2 = _placed(
        "line-2",
        "page_header",
        "Department of Mathematics",
        LINE_2_BOX,
        metadata=FURNITURE,
        reading_order=3,
    )
    body = _placed(
        "body",
        "paragraph",
        "Lecture notes on calculus.",
        (72, 650, 540, 600),
        reading_order=4,
    )
    manifest = build_manifest([line_1, picture, line_2, body], [])
    manifest.pages[0].width, manifest.pages[0].height = WIDTH, HEIGHT

    [page] = _manifest_pages_to_payload(manifest)
    blocks = page["blocks"]

    assert [b["type"] for b in blocks] == ["paragraph", "image", "paragraph", "paragraph"]
    assert blocks[1]["alt_text"] == non_logo_description
    assert all("Logo." not in (b.get("text") or "") for b in blocks)


def test_surrounding_text_prompt_bounds_item_and_total_char_overhead() -> None:
    """Note 6: Prompt context formatting caps per-item and total character overhead."""
    huge_items = ["palavra " * 100 for _ in range(10)]
    prompt_block = build_surrounding_text_prompt(huge_items)
    bullet_lines = [
        line.removeprefix("- ")
        for line in prompt_block.splitlines()
        if line.startswith("- ")
    ]
    assert 1 <= len(bullet_lines) <= 6
    assert all(len(line) <= MAX_CONTEXT_ITEM_CHARS for line in bullet_lines)
    assert sum(len(line) for line in bullet_lines) <= MAX_CONTEXT_TOTAL_CHARS


def test_scanned_document_ocr_paragraphs_are_preserved_in_payload() -> None:
    """Safeguard 8.1: Scanned document prose alongside a full-page picture is never suppressed."""
    h1 = ManifestElement(
        id="h-1",
        type="heading",
        raw_label="heading",
        reading_order=1,
        hierarchy_level=1,
        text="Chapter 1: Introduction to Differential Calculus",
        page_number=1,
    )
    p1 = ManifestElement(
        id="p-1",
        type="paragraph",
        raw_label="paragraph",
        reading_order=2,
        hierarchy_level=1,
        text="The derivative measures the instantaneous rate of change of a function.",
        page_number=1,
    )
    pic = ManifestElement(
        id="pic-1",
        type="picture",
        raw_label="picture",
        reading_order=3,
        hierarchy_level=1,
        text="Graph of a secant line approaching the tangent line.",
        page_number=1,
        metadata={"injected_picture": True, "vision_description_complete": True},
    )
    manifest = build_manifest([h1, p1, pic], [])
    manifest.pages = [
        PageDescriptor(
            page_number=1,
            width=WIDTH,
            height=HEIGHT,
            element_ids=["h-1", "p-1", "pic-1"],
        )
    ]

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["heading", "paragraph", "image"]
    assert page["blocks"][0]["text"] == "Chapter 1: Introduction to Differential Calculus"
    assert (
        page["blocks"][1]["text"]
        == "The derivative measures the instantaneous rate of change of a function."
    )
