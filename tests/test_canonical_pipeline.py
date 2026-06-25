import tempfile
from pathlib import Path

from exporters.pandoc_exporter import export_accessible_document
from pipeline.canonical_builder import build_canonical_document
from pipeline.validators import validate_canonical_document
from pipeline.validators import validate_output_text


def test_build_canonical_document_creates_sections_and_ids():
    document = build_canonical_document(
        "# Titulo\n\nParagrafo com **negrito**.\n\n- Item 1\n- Item 2",
        title="Titulo",
    )

    assert document["title"] == "Titulo"
    assert document["sections"]
    assert validate_canonical_document(document) == []


def test_build_canonical_document_accepts_structured_payload():
    payload = {
        "text": "# Titulo\n\nParagrafo simples.",
        "page_count": 2,
        "mode": "normal",
        "pages": [
            {
                "page_number": 1,
                "text": "# Titulo",
                "blocks": [{"type": "heading", "level": 1, "text": "Titulo"}],
            },
            {
                "page_number": 2,
                "text": "Paragrafo simples.",
                "blocks": [
                    {"type": "paragraph", "text": "Paragrafo simples."},
                ],
            },
        ],
    }

    document = build_canonical_document(payload, title="Titulo")

    assert document["metadata"]["page_count"] == 2
    assert document["metadata"]["mode"] == "normal"
    assert document["sections"]


def test_validate_output_text_flags_markdown_leaks():
    errors = validate_output_text("Texto com **marcacao** e `codigo`.", "pdf")

    assert errors


def test_export_accessible_document_txt_and_html():
    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "saida.txt"
        html_path = Path(tmpdir) / "saida.html"

        txt_result = export_accessible_document(
            "# Titulo\n\nParagrafo simples.",
            txt_path,
            format_name="txt",
            title="Titulo",
        )
        html_result = export_accessible_document(
            "# Titulo\n\nParagrafo simples.",
            html_path,
            format_name="html",
            title="Titulo",
        )

        assert txt_result.read_text(encoding="utf-8") == ("Titulo\nParagrafo simples.")
        assert html_result.exists()
        html_content = html_result.read_text(encoding="utf-8")
        assert "<nav" in html_content


def test_export_accessible_document_sanitizes_legacy_canonical_dict():
    legacy_document = {
        "schema_version": "1.0.0",
        "id": "doc-legacy",
        "title": "Titulo",
        "language": "pt-BR",
        "sections": [
            {
                "id": "sec-1",
                "title": "Titulo",
                "level": 1,
                "blocks": [
                    {
                        "id": "blk-1",
                        "type": "paragraph",
                        "text": "Texto com **marcacao** antiga.",
                    }
                ],
                "children": [],
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "legacy.txt"
        result = export_accessible_document(
            legacy_document,
            txt_path,
            format_name="txt",
            title="Titulo",
        )

        content = result.read_text(encoding="utf-8")
        assert "**" not in content
        assert "Texto com marcacao antiga." in content


def test_export_accessible_document_sanitizes_legacy_block_markdown():
    legacy_document = {
        "schema_version": "1.0.0",
        "id": "doc-legacy-2",
        "title": "Titulo",
        "language": "pt-BR",
        "sections": [
            {
                "id": "sec-1",
                "title": "Titulo",
                "level": 1,
                "blocks": [
                    {
                        "id": "blk-1",
                        "type": "paragraph",
                        "text": "# Capitulo\n- Item A\n1. Item B",
                    }
                ],
                "children": [],
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        txt_path = Path(tmpdir) / "legacy_block.txt"
        result = export_accessible_document(
            legacy_document,
            txt_path,
            format_name="txt",
            title="Titulo",
        )

        content = result.read_text(encoding="utf-8")
        assert "#" not in content
        assert "- " not in content
        assert "1. " not in content
        assert "Capitulo" in content
        assert "Item A" in content
        assert "Item B" in content
