import tempfile
from pathlib import Path

from renderers.docx_renderer import render_docx
from renderers.html_renderer import render_html
from renderers.pdf_renderer import render_pdf
from renderers.txt_renderer import render_txt


def _sample_document() -> dict:
    return {
        "title": "Documento exemplo",
        "language": "pt-BR",
        "metadata": {"origem": "teste"},
        "sections": [
            {
                "id": "sec-1",
                "title": "Seção principal",
                "level": 1,
                "blocks": [
                    {
                        "id": "blk-1",
                        "type": "paragraph",
                        "text": "Paragrafo simples.",
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-2",
                        "type": "paragraph",
                        "text": "Conteudo tecnico.",
                        "verbosity": "technical",
                    },
                    {
                        "id": "blk-3",
                        "type": "list",
                        "ordered": False,
                        "items": ["Item 1", "Item 2"],
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-4",
                        "type": "table",
                        "rows": [["Coluna A", "Coluna B"], ["1", "2"]],
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-5",
                        "type": "details",
                        "title": "Observacao",
                        "text": "Texto recolhivel.",
                        "verbosity": "basic",
                    },
                ],
                "children": [
                    {
                        "id": "sec-1-1",
                        "title": "Subseção",
                        "level": 2,
                        "blocks": [
                            {
                                "id": "blk-6",
                                "type": "paragraph",
                                "text": "Filho da seção.",
                                "verbosity": "basic",
                            }
                        ],
                        "children": [],
                    }
                ],
            }
        ],
    }


def test_render_txt_filters_technical_blocks_and_renders_tables():
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "saida.txt"

        result = render_txt(_sample_document(), output, profile_name="txt")

        text = result.read_text(encoding="utf-8")
        assert "Conteudo tecnico." not in text
        assert "Paragrafo simples." in text
        assert "- Item 1" in text
        assert "Coluna A | Coluna B" in text
        assert "Filho da seção." in text


def test_render_html_includes_toc_table_and_metadata():
    with tempfile.TemporaryDirectory() as tmpdir:
        output = Path(tmpdir) / "saida.html"

        result = render_html(_sample_document(), output, profile_name="html")

        html = result.read_text(encoding="utf-8")
        assert '<nav class="toc"' in html
        assert '<table id="blk-4">' in html
        assert '<aside class="meta"' in html
        assert "Observacao" in html


def test_render_docx_and_pdf_create_files():
    with tempfile.TemporaryDirectory() as tmpdir:
        docx_output = Path(tmpdir) / "saida.docx"
        pdf_output = Path(tmpdir) / "saida.pdf"

        docx_result = render_docx(
            _sample_document(),
            docx_output,
            profile_name="docx",
            filename="arquivo.docx",
        )
        pdf_result = render_pdf(
            _sample_document(),
            pdf_output,
            profile_name="pdf",
            title="Documento exemplo",
        )

        assert docx_result.exists()
        assert docx_result.suffix == ".docx"
        assert pdf_result.exists()
        assert pdf_result.stat().st_size > 0


def test_render_pdf_handles_outline_level_jump():
    document = {
        "title": "Documento com salto",
        "language": "pt-BR",
        "metadata": {},
        "sections": [
            {
                "id": "sec-l2",
                "title": "Titulo nivel 2",
                "level": 2,
                "blocks": [],
                "children": [],
            }
        ],
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        pdf_output = Path(tmpdir) / "salto_outline.pdf"
        result = render_pdf(
            document,
            pdf_output,
            profile_name="pdf",
            title="Documento com salto",
        )

        assert result.exists()
        assert result.stat().st_size > 0
