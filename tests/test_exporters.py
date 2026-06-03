import tempfile
from pathlib import Path

from core.exporters.txt_exporter import export_txt
from core.exporters.docx_exporter import export_docx
from core.exporters.pdf_exporter import export_pdf


def test_export_txt():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test.txt"
        result = export_txt("Hello world", out)
        assert result.exists()
        assert result.read_text(encoding="utf-8") == "Hello world"


def test_export_docx():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test.docx"
        result = export_docx("# Titulo\n\nParagrafo.", out, "test.docx")
        assert result.exists()
        assert result.suffix == ".docx"


def test_export_pdf():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test.pdf"
        result = export_pdf("Texto exemplo", out, "test.pdf")
        assert result.exists()
        assert result.suffix == ".pdf"


def test_export_txt_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "empty.txt"
        result = export_txt("Conteudo minimo", out)
        assert result.exists()
