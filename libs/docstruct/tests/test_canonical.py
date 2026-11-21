"""The public contract of ``build_canonical_document`` (#647)."""

from docstruct.canonical import build_canonical_document


def test_id_factory_takes_no_arguments() -> None:
    """The declared factory is zero-argument, like every caller passes."""
    document = build_canonical_document("text", id_factory=lambda: "doc-custom")

    assert document["id"] == "doc-custom"


def test_a_chapter_heading_takes_the_first_subheading_as_its_title() -> None:
    document = build_canonical_document(
        {
            "pages": [
                {
                    "blocks": [
                        {"type": "heading", "level": 1, "text": "CAPÍTULO 1"},
                        {"type": "heading", "level": 2, "text": "Introdução"},
                        {"type": "paragraph", "text": "Conteúdo."},
                    ]
                }
            ]
        }
    )

    assert document["title"] == "CAPÍTULO 1 - Introdução"
