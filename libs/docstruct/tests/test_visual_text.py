"""Tests for visual text ownership, surrounding context, and deduplication (docstruct.visual_text, #653)."""

from __future__ import annotations

import pytest

from docstruct.manifest import DocumentElement
from docstruct.placeholders import is_mostly_visual
from docstruct.visual_text import (
    MAX_CONTEXT_ITEM_CHARS,
    MAX_CONTEXT_ITEMS,
    MAX_CONTEXT_TOTAL_CHARS,
    SCENE_TEXT_TRANSCRIBED_SHARE,
    analyze_visual_text_ownership,
    collect_picture_context,
    deduplicate_picture_description,
    is_caption_text,
    is_confirmed_logo_description,
    is_document_artifact,
    is_document_page_picture,
    is_prose_sentence,
    is_scene_artifact,
    is_scene_text_covered,
    is_scene_text_fragment,
    is_scene_text_garbage,
    scene_text_residue,
)

#: The 41 OCR fragments extracted from IMG-20261108-WA0017.jpg (#398).
CASE_398_FRAGMENTS: tuple[str, ...] = (
    "\u4e2d",
    "WUNIDADES",
    "ISEJA",
    "FELIZ",
    "AVIDA",
    "EHOJE",
    "FAVELAVIVE",
    "SORTE",
    "GABI",
    "ESCO",
    "SAMBA",
    "TOUR",
    "DEERX",
    "MINHA GENTE",
    "VILA ISABEL",
    "TINHO DAVILA",
    "MERELLES",
    "Luci",
    "MEU LUGAR",
    "NINGU\u00c9MFAZSAMBA",
    "OPORQUE PREFERE",
    "DONA",
    "SERRA",
    "IVONE LARA",
    "MESTRE FULEIRO",
    "MPERI",
    "ARLINDO",
    "SABEDORIA",
    "HUMILDADE",
    "SO DEIXE O",
    "MOCINHO",
    "SAMBA MORRER",
    "ESTAC\u00c3O PIMEIRA",
    "R:T",
    "ZECA",
    "PAGODINHO",
    "PAZ NO MUNDO",
    "SAMBA",
    "BOOK.",
    "MEIER",
    "MORRO",
    "REDU",
)


def _element(
    element_id: str,
    kind: str,
    text: str | None = None,
    *,
    page: int = 1,
    order: int = 1,
    raw_label: str | None = None,
    metadata: dict | None = None,
) -> DocumentElement:
    return DocumentElement(
        id=element_id,
        type=kind,
        raw_label=raw_label or kind,
        reading_order=order,
        hierarchy_level=1,
        text=text,
        page_number=page,
        metadata=metadata or {},
    )


@pytest.mark.parametrize("fragment", CASE_398_FRAGMENTS)
def test_every_case_398_fragment_is_recognized_as_scene_text(fragment: str) -> None:
    assert is_scene_text_fragment(fragment)
    assert not is_prose_sentence(fragment)


def test_case_398_fragments_on_a_standalone_image_are_scene_text_but_uppercase_headings_are_not_visual() -> None:
    elements = [
        _element(f"el-{idx}", "paragraph", text, order=idx)
        for idx, text in enumerate(CASE_398_FRAGMENTS, start=1)
    ]
    elements.append(
        _element("pic", "picture", "", order=99, metadata={"injected_picture": True})
    )
    ownership = analyze_visual_text_ownership(elements, standalone_image=True)
    assert {ownership[el.id].role for el in elements[:-1]} == {"scene_text"}

    # A text document with uppercase headings and no visual region is NOT mostly visual (Note 1).
    uppercase_headings = [
        _element("h1", "heading", "INTRODUCTION", order=1),
        _element("h2", "heading", "METHODS", order=2),
    ]
    assert not is_mostly_visual(uppercase_headings)


def test_scanned_document_prose_is_never_classified_as_scene_ocr() -> None:
    scanned = [
        _element("h1", "heading", "1.1 Instantaneous velocity", order=1),
        _element(
            "p1",
            "paragraph",
            "Let f be a function defined on an open interval around the point x0.",
            order=2,
        ),
        _element("pic", "picture", "Scanned page diagram", order=3, metadata={"injected_picture": True}),
    ]
    assert not is_mostly_visual(scanned)
    ownership = analyze_visual_text_ownership(scanned, standalone_image=True)
    assert ownership["h1"].role == "document_text"
    assert ownership["p1"].role == "document_text"


def test_one_page_form_with_picture_and_uppercase_labels_preserves_labels_as_document_text() -> None:
    """Note 1: Without standalone_image/injected_picture or geometric containment, uppercase labels stay document_text."""
    form_elements = [
        _element("pic-1", "picture", "Applicant badge photo.", order=1),
        _element("lbl-1", "paragraph", "NAME", order=2),
        _element("lbl-2", "paragraph", "ADDRESS", order=3),
    ]
    ownership = analyze_visual_text_ownership(form_elements, standalone_image=False)
    assert ownership["lbl-1"].role == "document_text"
    assert ownership["lbl-2"].role == "document_text"


def test_slide_title_in_uppercase_with_slide_visual_picture_stays_document_text() -> None:
    """Note 1: Slide headings structured by slides.py keep document_text ownership."""
    slide_elements = [
        _element(
            "h-slide",
            "heading",
            "RESULTS",
            order=1,
            metadata={"slide_role": "slide_heading"},
        ),
        _element(
            "pic-slide",
            "picture",
            "Full slide chart.",
            order=2,
            metadata={"slide_visual": True},
        ),
    ]
    ownership = analyze_visual_text_ownership(slide_elements)
    assert ownership["h-slide"].role == "document_text"
    assert ownership["h-slide"].reason == "slide_structure"


def test_ownership_assigns_scene_text_to_standalone_image_picture_including_list_items() -> None:
    """Note 4: Standalone image scene-OCR fragments typed as list_item also become scene_text."""
    elements = [
        _element("el-1", "paragraph", "FAVELAVIVE", order=1),
        _element("el-2", "list_item", "MINHA GENTE", order=2),
        _element("el-3", "list_item", "PAZ NO MUNDO", order=3),
        _element(
            "pic-1",
            "picture",
            "Art installation of painted concrete blocks.",
            order=4,
            metadata={"injected_picture": True},
        ),
    ]
    ownership = analyze_visual_text_ownership(elements, standalone_image=True)
    for key in ("el-1", "el-2", "el-3"):
        assert ownership[key].role == "scene_text"
        assert ownership[key].owner_id == "pic-1"


def test_is_scene_text_covered_checks_distinctive_tokens_and_spaceless_matches() -> None:
    """Note 2: Meaningful scene text is suppressed only when the description covers it."""
    rich_description = (
        "Instalacao artistica com blocos pintados trazendo inscricoes como "
        "'Favela Vive', 'Minha Gente' e 'Paz no Mundo'."
    )
    assert is_scene_text_covered("FAVELAVIVE", rich_description)
    assert is_scene_text_covered("MINHA GENTE", rich_description)
    assert is_scene_text_covered("PAZ NO MUNDO", rich_description)
    # Garbage with no readable word is always treated as covered.
    assert is_scene_text_covered("R:T", "A political world map.")
    # A short word is an inscription, not noise: it must be mentioned to be covered.
    assert not is_scene_text_covered("ZECA", "A political world map.")
    assert is_scene_text_covered("ZECA", "Painted bricks reading 'Zeca Pagodinho'.")

    generic_description = "A colorful art installation photographed at night."
    assert not is_scene_text_covered("FAVELA VIVE", generic_description)
    assert not is_scene_text_covered("PAZ NO MUNDO", generic_description)
    # Coverage via mentioned_elements also counts.
    assert is_scene_text_covered(
        "FAVELA VIVE", generic_description, mentioned_elements=["Favela Vive"]
    )


def test_captions_and_geometrically_contained_fragments_are_distinguished() -> None:
    elements = [
        _element("p-prose", "paragraph", "The experimental setup uses three sensors in series.", order=1),
        _element("pic-1", "picture", "Diagram of the three sensors.", order=2),
        _element("lbl-in", "paragraph", "SENSOR A", order=3),
        _element("ambig-in", "paragraph", " Nominal range ", order=4),
        _element("cap-1", "paragraph", "Figure 1: Schematic of the sensor array.", order=5),
    ]
    boxes = {
        "p-prose": (0.1, 0.1, 0.9, 0.2),
        "pic-1": (0.1, 0.25, 0.9, 0.75),
        "lbl-in": (0.3, 0.4, 0.5, 0.45),
        "ambig-in": (0.3, 0.5, 0.6, 0.55),
        "cap-1": (0.1, 0.78, 0.9, 0.83),
    }
    ownership = analyze_visual_text_ownership(elements, page_boxes=boxes)

    assert ownership["p-prose"].role == "document_text"
    assert ownership["lbl-in"].role == "scene_text"
    assert ownership["lbl-in"].owner_id == "pic-1"
    assert ownership["ambig-in"].role == "uncertain"
    assert ownership["ambig-in"].owner_id == "pic-1"
    assert ownership["cap-1"].role == "caption"
    assert ownership["cap-1"].owner_id == "pic-1"
    assert is_caption_text("Figure 1: Schematic of the sensor array.")


def test_collect_picture_context_separates_surrounding_headers_captions_and_bounds_size() -> None:
    """Note 6: Surrounding context is bounded by item count, item length, and total character budget."""
    long_paragraph = "word " * 200  # 1,000 characters
    elements = [
        _element("hdr-1", "page_header", "University of Brasilia", order=1),
        _element("hdr-2", "page_header", "Department of Mathematics", order=2),
        _element("pic-1", "picture", "University coat of arms.", order=3),
        _element("sc-1", "paragraph", "UNB", order=4),
        _element("cap-1", "caption", "Figure 1: Institutional crest.", order=5),
        _element("p-1", "paragraph", long_paragraph, order=6),
        _element("p-2", "paragraph", long_paragraph, order=7),
        _element("p-3", "paragraph", long_paragraph, order=8),
        _element("p-4", "paragraph", long_paragraph, order=9),
    ]
    boxes = {
        "pic-1": (0.1, 0.1, 0.3, 0.2),
        "sc-1": (0.15, 0.12, 0.25, 0.18),
    }
    ownership = analyze_visual_text_ownership(elements, page_boxes=boxes)
    context = collect_picture_context("pic-1", elements, ownership)

    assert context.header_text == ("University of Brasilia", "Department of Mathematics")
    assert context.caption_text == ("Figure 1: Institutional crest.",)
    assert context.scene_text == ("UNB",)
    assert "University of Brasilia" in context.surrounding_text
    assert "Department of Mathematics" in context.surrounding_text
    assert "UNB" not in context.surrounding_text
    assert len(context.surrounding_text) <= MAX_CONTEXT_ITEMS
    assert all(len(item) <= MAX_CONTEXT_ITEM_CHARS for item in context.surrounding_text)
    assert sum(len(item) for item in context.surrounding_text) <= MAX_CONTEXT_TOTAL_CHARS


def test_deduplicate_picture_description_removes_only_redundant_transcription_sentences() -> None:
    description = (
        "Logotipo institucional composto por duas setas convergentes em verde e amarelo. "
        "A primeira linha e 'Universidade de Brasilia' e a segunda linha e 'Departamento de Matematica'."
    )
    surrounding = ("Universidade de Brasilia", "Departamento de Matematica")

    deduped = deduplicate_picture_description(description, surrounding)

    assert deduped == (
        "Logotipo institucional composto por duas setas convergentes em verde e amarelo."
    )


def test_deduplicate_picture_description_never_empties_description_or_cuts_visual_meaning() -> None:
    single = "Logotipo da Universidade de Brasilia."
    assert (
        deduplicate_picture_description(single, ("Universidade de Brasilia",))
        == single
    )

    meaningful_multi = (
        "Grafico comparando o desempenho do Departamento de Matematica entre 2020 e 2025. "
        "A curva azul cresce 40% no periodo final."
    )
    assert (
        deduplicate_picture_description(
            meaningful_multi,
            ("Universidade de Brasilia", "Departamento de Matematica"),
        )
        == meaningful_multi
    )


@pytest.mark.parametrize(
    ("description", "mentioned", "described", "expected"),
    [
        ("A long description of the logo.", (), False, True),
        ("Institution crest", (), False, True),
        ("QR code for the course page", (), False, False),
        ("A small blue icon.", (), False, False),
        ("Logotipo institucional da UnB.", ("brasao",), True, True),
        ("University coat of arms in green and yellow.", (), True, True),
        ("Fotografia do rosto do autor sorrindo.", ("pessoa",), True, False),
        ("Portrait photo of the author.", (), True, False),
        ("A photo.", (), True, False),
        ("A small blue icon.", (), True, False),
        ("A map of the region.", (), True, False),
        ("A red circle.", (), True, False),
        ("Codigo QR apontando para o site da disciplina.", (), True, False),
        ("Grafico de barras com tres series.", (), True, False),
        ("Logo of UFG next to the author's photograph.", (), True, False),
        ("Logotipo da UFG ao lado da fotografia do autor.", (), True, False),
        ("UFG coat of arms.", ("portrait",), True, False),
    ],
)
def test_is_confirmed_logo_description(
    description: str,
    mentioned: tuple[str, ...],
    described: bool,
    expected: bool,
) -> None:
    assert (
        is_confirmed_logo_description(description, mentioned, described=described)
        is expected
    )


def test_scene_text_residue_keeps_every_meaningful_fragment_without_a_description() -> None:
    """Vision failure or dry run: meaningful fragments are kept once, noise is dropped."""
    residue = scene_text_residue(
        ["MINHA GENTE", "R:T", "\u4e2d", "PAZ NO MUNDO", "MINHA GENTE"],
        None,
        described=False,
    )
    assert residue == ("MINHA GENTE", "PAZ NO MUNDO")


@pytest.mark.parametrize(
    ("fragment", "garbage"),
    [
        ("ZECA", False),
        ("Luci", False),
        ("GABI", False),
        ("BOOK.", False),
        ("PAZ NO MUNDO", False),
        ("R:T", True),
        ("\u4e2d", True),
        ("12/03", True),
        ("  ", True),
        ("", True),
    ],
)
def test_is_scene_text_garbage_keeps_short_words(fragment: str, garbage: bool) -> None:
    """On a photo a single short word is the inscription; only text with no readable word is garbage."""
    assert is_scene_text_garbage(fragment) is garbage


def test_scene_text_residue_drops_misreads_when_the_description_transcribes_the_scene() -> None:
    """A description covering most fragments transcribes the scene; the uncovered rest is OCR misreading."""
    description = (
        "Painted bricks with 'Favela Vive', 'Minha Gente', 'Vila Isabel', "
        "'Zeca Pagodinho' and 'Paz no Mundo'."
    )
    fragments = [
        "FAVELA VIVE",
        "MINHA GENTE",
        "VILA ISABEL",
        "ZECA PAGODINHO",
        "PAZ NO MUNDO",
        "OPORQUE PREFERE",
    ]
    assert scene_text_residue(fragments, description, described=True) == ()


def test_scene_text_residue_keeps_uncovered_fragments_of_a_generic_description() -> None:
    """A description that covers less than the transcription share keeps what it omits."""
    fragments = ["FAVELA VIVE", "PAZ NO MUNDO", "VILA ISABEL"]
    description = "A night photo of a painted installation reading 'Vila Isabel'."
    residue = scene_text_residue(fragments, description, described=True)
    assert 1 / 3 < SCENE_TEXT_TRANSCRIBED_SHARE
    assert residue == ("FAVELA VIVE", "PAZ NO MUNDO")


def test_scene_text_residue_uses_mentioned_elements_as_coverage() -> None:
    """Text the vision model lists in ``mentioned_elements`` counts as conveyed."""
    residue = scene_text_residue(
        ["FAVELA VIVE", "PAZ NO MUNDO"],
        "A colorful art installation.",
        ["Favela Vive", "Paz no Mundo"],
        described=True,
    )
    assert residue == ()


@pytest.mark.parametrize(
    ("inspection", "document", "scene"),
    [
        ({"is_image": True, "artifact_nature": "standalone_image"}, False, True),
        ({"is_image": True}, False, True),
        ({"is_image": True, "artifact_nature": "scanned_page"}, True, False),
        ({"is_image": False, "artifact_nature": "paginated_document"}, True, False),
        ({"is_image": False}, False, False),
        (None, False, False),
    ],
)
def test_artifact_nature_separates_scene_images_from_document_pages(
    inspection: dict | None, document: bool, scene: bool
) -> None:
    """A photographed or scanned page is a document; only a standalone image holds scene text."""
    assert is_document_artifact(inspection) is document
    assert is_scene_artifact(inspection) is scene


def test_injected_picture_of_a_scanned_page_owns_no_scene_text() -> None:
    """Short uppercase lines of a photographed form are document text, not scene text."""
    elements = [
        _element("lbl-1", "paragraph", "NAME", order=1),
        _element("lbl-2", "paragraph", "ADDRESS", order=2),
        _element(
            "pic-1",
            "picture",
            "",
            order=3,
            metadata={
                "injected_picture": True,
                "media_inspection": {"is_image": True, "artifact_nature": "scanned_page"},
            },
        ),
    ]
    ownership = analyze_visual_text_ownership(elements)
    assert {decision.role for decision in ownership.values()} == {"document_text"}


@pytest.mark.parametrize(
    "picture_metadata",
    [
        {"artifact_nature": "scanned_page"},
        {"media_inspection": {"is_image": True, "artifact_nature": "paginated_document"}},
    ],
)
def test_a_document_page_picture_hosts_no_contained_scene_text(picture_metadata: dict) -> None:
    """Short labels geometrically inside a document page's image stay document text."""
    elements = [
        _element("pic-1", "picture", "Scanned form.", order=1, metadata=picture_metadata),
        _element("lbl-1", "paragraph", "NOME COMPLETO", order=2),
        _element("lbl-2", "paragraph", "CPF", order=3),
    ]
    boxes = {
        "pic-1": (0.0, 0.0, 612.0, 792.0),
        "lbl-1": (72.0, 92.0, 260.0, 106.0),
        "lbl-2": (72.0, 132.0, 120.0, 146.0),
    }
    ownership = analyze_visual_text_ownership(elements, page_boxes=boxes)
    assert ownership["lbl-1"].role == "document_text"
    assert ownership["lbl-2"].role == "document_text"

    without_nature = [
        _element("pic-1", "picture", "Scanned form.", order=1),
        *elements[1:],
    ]
    contained = analyze_visual_text_ownership(without_nature, page_boxes=boxes)
    assert contained["lbl-1"].role == "scene_text"


def test_is_document_page_picture_reads_both_recorded_forms() -> None:
    """The nature may be the injected picture's inspection or the stamp from enrichment."""
    assert is_document_page_picture(_element("p", "picture", metadata={"artifact_nature": "scanned_page"}))
    assert not is_document_page_picture(
        _element("p", "picture", metadata={"artifact_nature": "standalone_image"})
    )
    assert not is_document_page_picture(_element("p", "picture"))
