import tempfile
from pathlib import Path

from backend.export.exporters.txt_exporter import export_txt
from backend.export.exporters.docx_exporter import export_docx
from backend.export.exporters.pdf_exporter import export_pdf_ua


def test_export_txt():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test.txt"
        result = export_txt("Hello world", out)
        assert result.exists()
        assert result.read_text(encoding="utf-8") == "Hello world"


def test_export_docx_renders_on_the_toolbox(monkeypatch):
    calls = []

    def fake_toolbox(ast, output_path, *, lang):
        calls.append(lang)
        output_path.write_bytes(b"PK\x03\x04")
        return {}

    monkeypatch.setattr("backend.export.pandoc_exporter.settings.toolbox_docx_enabled", True)
    monkeypatch.setattr("backend.export.pandoc_exporter.toolbox_export_docx", fake_toolbox)
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test.docx"
        result = export_docx("# Titulo\n\nParagrafo.", out, "test.docx")
        assert result.read_bytes() == b"PK\x03\x04"
        assert calls == ["pt-BR"]


def test_export_txt_empty():
    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "empty.txt"
        result = export_txt("Conteudo minimo", out)
        assert result.exists()


def test_export_pdf_ua_calls_accessible_exporter(monkeypatch):
    called = {}

    def _fake_export_accessible_document(text, output_path, **kwargs):
        called["format_name"] = kwargs.get("format_name")
        called["profile_name"] = kwargs.get("profile_name")
        output_path.write_text("ok", encoding="utf-8")
        return output_path

    monkeypatch.setattr(
        "backend.export.exporters.pdf_exporter.export_accessible_document",
        _fake_export_accessible_document,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        out = Path(tmpdir) / "test.pdf_ua.pdf"
        result = export_pdf_ua("Texto exemplo", out, "test.pdf")
        assert result.exists()
        assert called["format_name"] == "pdf_ua"
        assert called["profile_name"] == "pdf_ua"
