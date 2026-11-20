"""Tests for visual text ownership, surrounding context, and deduplication (docstruct.visual_text, #653)."""

from __future__ import annotations

import pytest

from docstruct.manifest import DocumentElement
from docstruct.placeholders import is_mostly_visual
from docstruct.visual_text import (
    analyze_visual_text_ownership,
    collect_picture_context,
    deduplicate_picture_description,
    is_caption_text,
    is_confirmed_logo_description,
    is_prose_sentence,
    is_scene_ocr_collection,
    is_scene_text_fragment,
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


def test_case_398_collection_is_scene_ocr_and_mostly_visual() -> None:
    elements = [
        _element(f"el-{idx}", "paragraph", text, order=idx)
        for idx, text in enumerate(CASE_398_FRAGMENTS, start=1)
    ]
    assert is_scene_ocr_collection(elements)
    assert is_mostly_visual(elements)


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
    assert not is_scene_ocr_collection(scanned)
    assert not is_mostly_visual(scanned)
    ownership = analyze_visual_text_ownership(scanned, standalone_image=True)
    assert ownership["h1"].role == "document_text"
    assert ownership["p1"].role == "document_text"


def test_ownership_assigns_scene_text_to_standalone_image_picture() -> None:
    elements = [
        *[
            _element(f"el-{idx}", "paragraph", text, order=idx)
            for idx, text in enumerate(CASE_398_FRAGMENTS[:6], start=1)
        ],
        _element(
            "pic-1",
            "picture",
            "Art installation of painted concrete blocks.",
            order=7,
            metadata={"injected_picture": True},
        ),
    ]
    ownership = analyze_visual_text_ownership(elements, standalone_image=True)
    for idx in range(1, 7):
        decision = ownership[f"el-{idx}"]
        assert decision.role == "scene_text"
        assert decision.owner_id == "pic-1"


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


def test_collect_picture_context_separates_surrounding_headers_captions_and_scene() -> None:
    elements = [
        _element("hdr-1", "page_header", "University of Brasilia", order=1),
        _element("hdr-2", "page_header", "Department of Mathematics", order=2),
        _element("pic-1", "picture", "University coat of arms.", order=3),
        _element("sc-1", "paragraph", "UNB", order=4),
        _element("cap-1", "caption", "Figure 1: Institutional crest.", order=5),
        _element("p-1", "paragraph", "Calculus lecture notes for first-year students.", order=6),
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
        ("Logotipo institucional da UnB.", ("brasao",), True, True),
        ("University coat of arms in green and yellow.", (), True, True),
        ("Fotografia do rosto do autor sorrindo.", ("pessoa",), True, False),
        ("Portrait photo of the author.", (), True, False),
        ("Codigo QR apontando para o site da disciplina.", (), True, False),
        ("Grafico de barras com tres series.", (), True, False),
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
