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


async def _enrich_photo(
    manifest,
    *,
    media_inspection: dict | None = None,
) -> None:
    await picture_stage._enrich_picture_descriptions(
        manifest,
        Path("IMG-20261108-WA0017.jpg"),
        mode="medio",
        media_inspection=media_inspection
        or {"is_image": True, "requires_visual_inspection": True},
        vision=vision_config(retry_pass_delay_seconds=0),
        toolbox=toolbox_config(),
        models=model_config(),
        region_cache=None,
    )


def _photo_manifest(texts: list[str], *, element_type: str = "paragraph", language: str = "en"):
    elements = [
        build_element(f"el-{idx}", element_type, text=text)
        for idx, text in enumerate(texts, start=1)
    ]
    for idx, element in enumerate(elements, start=1):
        element.reading_order = idx
    manifest = build_manifest(elements, [])
    manifest.language = language
    manifest.pages = [
        PageDescriptor(
            page_number=1,
            width=1600.0,
            height=739.0,
            element_ids=[element.id for element in elements],
        )
    ]
    picture_id = f"element-injected-picture-{len(elements) + 1:06d}"
    return manifest, picture_id


def _block_texts(page: dict) -> list[str]:
    return [b.get("text") or b.get("alt_text") or "" for b in page["blocks"]]


def _assert_no_scene_text_block(manifest, page: dict) -> None:
    """Invariant (#398, #653): text owned by a picture is never a document-level block."""
    owned = {
        (el.text or "").strip()
        for el in manifest.elements
        if (el.metadata.get("visual_text_ownership") or {}).get("role") == "scene_text"
    }
    assert owned
    for block in page["blocks"]:
        if block["type"] != "image":
            assert (block.get("text") or "").strip() not in owned


#: The real OCR fragments and final description attached to issue #398
#: (``IMG-20261108-WA0017.jpg``): 42 fragment lines, then the description.
ISSUE_398_LINES = (
    Path(__file__).parent / "fixtures" / "visual_text" / "issue_398_ocr_and_description.txt"
).read_text(encoding="utf-8").splitlines()
ISSUE_398_FRAGMENTS = ISSUE_398_LINES[:-1]
ISSUE_398_DESCRIPTION = ISSUE_398_LINES[-1]


@pytest.mark.asyncio
async def test_case_398_real_ocr_and_description_emit_only_the_image() -> None:
    """#398 golden case: the real 42 OCR fragments and description yield only the image description.

    The three fragments the description does not mention (``WUNIDADES``,
    ``TINHO DAVILA``, ``OPORQUE PREFERE``) are OCR misreads of inscriptions it
    already transcribes; they are neither paragraphs nor appended to the alt.
    """
    assert len(ISSUE_398_FRAGMENTS) == 42
    manifest, picture_id = _photo_manifest(ISSUE_398_FRAGMENTS, language="pt-BR")
    RecordingVision.answers = {picture_id: _vision_answer(ISSUE_398_DESCRIPTION)}

    await _enrich_photo(manifest)

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["image"]
    assert page["blocks"][0]["alt_text"] == ISSUE_398_DESCRIPTION
    _assert_no_scene_text_block(manifest, page)


@pytest.mark.asyncio
async def test_case_398_real_ocr_is_carried_once_by_the_image_when_vision_fails() -> None:
    """#398: with no description, the real inscriptions stay with the image, once, never as a preamble."""
    manifest, _picture_id = _photo_manifest(ISSUE_398_FRAGMENTS)

    await _enrich_photo(manifest)

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["image"]
    alt = page["blocks"][0]["alt_text"]
    assert alt.startswith("Image without a text description. Text visible in the image: ")
    carried = alt.removeprefix(
        "Image without a text description. Text visible in the image: "
    ).removesuffix(".").split("; ")
    # Every readable inscription survives, short single words included (ZECA, Luci).
    for fragment in (
        "MINHA GENTE",
        "VILA ISABEL",
        "PAZ NO MUNDO",
        "MESTRE FULEIRO",
        "ZECA",
        "GABI",
        "Luci",
        "DONA",
        "MORRO",
    ):
        assert carried.count(fragment) == 1
    # Only text with no readable word (a stray CJK glyph, ``R:T``) is not carried;
    # the repeated ``SAMBA`` is carried once.
    assert "中" not in carried and "R:T" not in carried
    assert carried.count("SAMBA") == 1
    assert len(carried) == len(set(ISSUE_398_FRAGMENTS)) - 2
    _assert_no_scene_text_block(manifest, page)


@pytest.mark.asyncio
async def test_case_398_generic_description_carries_unmentioned_scene_text_in_alt_text() -> None:
    """A generic description that omits the inscriptions keeps them, inside the image's alt text."""
    manifest, picture_id = _photo_manifest(["FAVELA VIVE", "PAZ NO MUNDO"])
    RecordingVision.answers = {
        picture_id: _vision_answer("A colorful art installation photographed at night.")
    }

    await _enrich_photo(manifest)

    [page] = _manifest_pages_to_payload(manifest)
    assert _block_texts(page) == [
        "A colorful art installation photographed at night. "
        "Text visible in the image: FAVELA VIVE; PAZ NO MUNDO."
    ]
    _assert_no_scene_text_block(manifest, page)


@pytest.mark.asyncio
async def test_case_398_scene_text_follows_the_document_language() -> None:
    """The sentence that carries scene text is written in the document's language."""
    manifest, picture_id = _photo_manifest(["FAVELA VIVE", "PAZ NO MUNDO"], language="pt-BR")
    RecordingVision.answers = {
        picture_id: _vision_answer("Instalacao artistica colorida fotografada a noite.")
    }

    await _enrich_photo(manifest)

    [page] = _manifest_pages_to_payload(manifest)
    assert _block_texts(page) == [
        "Instalacao artistica colorida fotografada a noite. "
        "Texto vis\u00edvel na imagem: FAVELA VIVE; PAZ NO MUNDO."
    ]


@pytest.mark.asyncio
async def test_case_398_scene_ocr_is_preserved_once_without_duplication_when_vision_fails() -> None:
    """When the vision model fails, scene OCR is carried once by the image, never as paragraphs."""
    manifest, _picture_id = _photo_manifest(["MINHA GENTE", "PAZ NO MUNDO"])

    await _enrich_photo(manifest)

    [page] = _manifest_pages_to_payload(manifest)
    assert _block_texts(page) == [
        "Image without a text description. Text visible in the image: MINHA GENTE; PAZ NO MUNDO."
    ]
    _assert_no_scene_text_block(manifest, page)


@pytest.mark.asyncio
@pytest.mark.parametrize("element_type", ["paragraph", "list_item", "heading"])
@pytest.mark.parametrize(
    "description",
    [
        None,
        "A colorful art installation photographed at night.",
        "Painted bricks reading 'Favela Vive' and 'Paz no Mundo'.",
    ],
)
async def test_scene_text_owned_by_a_picture_is_never_a_document_block(
    element_type: str, description: str | None
) -> None:
    """Property: whatever the description and element type, owned scene text never becomes a block."""
    manifest, picture_id = _photo_manifest(
        ["FAVELA VIVE", "PAZ NO MUNDO", "SAMBA"], element_type=element_type
    )
    if description is not None:
        RecordingVision.answers = {picture_id: _vision_answer(description)}

    await _enrich_photo(manifest)

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["image"]
    _assert_no_scene_text_block(manifest, page)


@pytest.mark.asyncio
@pytest.mark.parametrize("nature", ["scanned_page", "paginated_document"])
async def test_photographed_document_page_keeps_its_short_lines_as_document_text(nature: str) -> None:
    """Role by artifact nature: a photographed form's uppercase labels are document text, not scene text."""
    manifest, picture_id = _photo_manifest(["NAME", "ADDRESS", "DATE OF BIRTH"])
    RecordingVision.answers = {picture_id: _vision_answer("A printed registration form.")}

    await _enrich_photo(
        manifest,
        media_inspection={
            "is_image": True,
            "requires_visual_inspection": True,
            "artifact_nature": nature,
        },
    )

    assert all(
        "visual_text_ownership" not in el.metadata
        for el in manifest.elements
        if el.type != "picture"
    )
    [page] = _manifest_pages_to_payload(manifest)
    assert _block_texts(page)[:3] == ["NAME", "ADDRESS", "DATE OF BIRTH"]


def test_slide_with_uppercase_title_and_picture_preserves_the_title() -> None:
    """Note 1: an uppercase slide title beside a described picture stays document text."""
    title = build_element("title-1", "heading", text="RESULTS")
    pic = build_element(
        "pic-1",
        "picture",
        text="Bar chart of accuracy per model.",
        metadata={"vision_description_complete": True},
    )
    title.reading_order, pic.reading_order = 1, 2
    manifest = build_manifest([title, pic], [])
    manifest.pages = [
        PageDescriptor(
            page_number=1, width=WIDTH, height=HEIGHT, element_ids=["title-1", "pic-1"]
        )
    ]

    [page] = _manifest_pages_to_payload(manifest)
    assert [b["type"] for b in page["blocks"]] == ["heading", "image"]
    assert _block_texts(page) == ["RESULTS", "Bar chart of accuracy per model."]


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


def test_scene_text_of_a_letterhead_logo_stays_in_the_flow() -> None:
    """A logo merged into a letterhead is not rendered as an image, so text inside it is not dropped."""
    line_1 = _placed(
        "line-1",
        "page_header",
        "University of Brasilia",
        LINE_1_BOX,
        metadata=FURNITURE,
        reading_order=1,
    )
    logo = _placed(
        "logo",
        "picture",
        "University logo with converging arrows.",
        LOGO_BOX,
        metadata={"vision_description_complete": True},
        reading_order=2,
    )
    inside_logo = _placed(
        "inside-logo",
        "paragraph",
        "CAMPUS DARCY",
        (66.0, 700.0, 112.0, 696.0),
        reading_order=3,
    )
    line_2 = _placed(
        "line-2",
        "page_header",
        "Department of Mathematics",
        LINE_2_BOX,
        metadata=FURNITURE,
        reading_order=4,
    )
    body = _placed(
        "body",
        "paragraph",
        "Lecture notes on calculus.",
        (72, 650, 540, 600),
        reading_order=5,
    )
    manifest = build_manifest([line_1, logo, inside_logo, line_2, body], [])
    manifest.language = "en"
    manifest.pages[0].width, manifest.pages[0].height = WIDTH, HEIGHT

    [page] = _manifest_pages_to_payload(manifest)
    texts = _block_texts(page)

    assert texts[0].startswith("Logo. ")
    assert "CAMPUS DARCY" in texts


PAGE_IMAGE_BOX = (0.0, 792.0, 612.0, 0.0)
FORM_LABEL_BOXES = {
    "lbl-name": (72.0, 700.0, 260.0, 686.0),
    "lbl-birth": (72.0, 660.0, 260.0, 646.0),
    "lbl-cpf": (72.0, 620.0, 120.0, 606.0),
}
FORM_LABELS = {"lbl-name": "NOME COMPLETO", "lbl-birth": "DATE OF BIRTH", "lbl-cpf": "CPF"}


def _scanned_form(picture_metadata: dict) -> list[ManifestElement]:
    page_image = _placed(
        "page-image",
        "picture",
        "Scanned registration form.",
        PAGE_IMAGE_BOX,
        metadata={"vision_description_complete": True, **picture_metadata},
        reading_order=1,
    )
    labels = [
        _placed(element_id, "paragraph", FORM_LABELS[element_id], box, reading_order=idx)
        for idx, (element_id, box) in enumerate(FORM_LABEL_BOXES.items(), start=2)
    ]
    declaration = _placed(
        "declaration",
        "paragraph",
        "I declare that the information above is true.",
        (72.0, 580.0, 540.0, 566.0),
        reading_order=5,
    )
    return [page_image, *labels, declaration]


@pytest.mark.parametrize("nature", ["scanned_page", "paginated_document"])
def test_labels_inside_a_document_page_image_stay_in_the_flow(nature: str) -> None:
    """Safeguard 8.1 with real boxes: form labels inside the page image of a document are not scene text."""
    elements = _scanned_form({"media_inspection": {"is_image": True, "artifact_nature": nature}})
    manifest = build_manifest(elements, [])
    manifest.language = "en"
    manifest.pages[0].width, manifest.pages[0].height = WIDTH, HEIGHT

    [page] = _manifest_pages_to_payload(manifest)

    assert _block_texts(page) == [
        "Scanned registration form.",
        "NOME COMPLETO",
        "DATE OF BIRTH",
        "CPF",
        "I declare that the information above is true.",
    ]


@pytest.mark.asyncio
async def test_enrichment_records_the_document_nature_so_the_payload_keeps_form_labels() -> None:
    """The payload has no media inspection: the nature stamped on pictures keeps its decision aligned."""
    elements = _scanned_form({})
    elements[0].text = ""
    elements[0].metadata.pop("vision_description_complete")
    manifest = build_manifest(
        elements,
        [build_obligation("describe-image", ["page-image"], ["vision-description"])],
    )
    manifest.language = "en"
    manifest.pages[0].width, manifest.pages[0].height = WIDTH, HEIGHT
    RecordingVision.answers = {"page-image": _vision_answer("Scanned registration form.")}

    await _enrich_photo(
        manifest,
        media_inspection={
            "is_image": True,
            "requires_visual_inspection": True,
            "artifact_nature": "scanned_page",
        },
    )

    assert manifest.elements[0].metadata["artifact_nature"] == "scanned_page"
    assert all(
        "visual_text_ownership" not in el.metadata for el in manifest.elements[1:]
    )
    [page] = _manifest_pages_to_payload(manifest)
    assert _block_texts(page)[1:4] == ["NOME COMPLETO", "DATE OF BIRTH", "CPF"]
