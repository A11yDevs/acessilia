"""Formula diagnostics use real PDFs and the existing Toolbox region adapter."""

from unittest.mock import AsyncMock

import fitz
import pytest

from backend.tools.toolbox_client import ToolboxClient
from backend.tools.toolbox_structurer import ToolboxStructurer


@pytest.fixture
def formula_pdf(tmp_path, monkeypatch):
    source = tmp_path / "formulas.pdf"
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 72), "Introduction")
        pdf.new_page().insert_text((72, 72), "E=mc^2")
        pdf.save(source)

    extraction = AsyncMock(return_value={
        "status": "succeeded", "provider": "docling",
        "document": {"elements": [{
            "type": "formula", "text": "E=mc^2", "page_number": 1,
            "bbox": {"left": 72, "top": 60, "right": 160, "bottom": 80},
        }]},
    })
    monkeypatch.setattr(ToolboxClient, "extract_structure", extraction)
    return source, extraction


def test_formula_comparison_reads_docling_regions(formula_pdf):
    from scripts.benchmark_formula_extraction import Case, run_docling

    source, extraction = formula_pdf
    case = Case("equation", "clean", "E=mc^2", source, pdf_path=source)
    structurer = ToolboxStructurer(client=ToolboxClient(provider="docling"))
    run_docling(case, structurer)

    assert structurer._client.provider == "docling"
    assert case.detected_as_formula is True
    assert case.docling_latex == "E=mc^2"
    assert case.all_region_types == ["formula"]
    extraction.assert_awaited_once()


def test_presentation_diagnostic_preserves_page_counts(formula_pdf, monkeypatch, capsys):
    from scripts import benchmark_formula_grandezas_medidas as diagnostic

    source, extraction = formula_pdf
    monkeypatch.setattr(diagnostic, "PDF", source)
    diagnostic.main()

    output = capsys.readouterr().out
    assert "pagina 1/2:" in output
    assert "pagina 2/2:" in output
    assert "Formulas detectadas: 1" in output
    assert "E=mc^2" in output
    # The existing adapter fetches the full document once and reuses its page data.
    extraction.assert_awaited_once()


def test_arxiv_diagnostic_selects_the_math_page(formula_pdf, monkeypatch, tmp_path, capsys):
    from scripts import test_formula_arxiv as diagnostic

    source, extraction = formula_pdf
    monkeypatch.setattr(diagnostic, "WORKDIR", tmp_path / "arxiv")
    monkeypatch.setattr(diagnostic, "PAPERS", [("paper", "test-id", "Test paper")])
    monkeypatch.setattr(diagnostic, "_download", lambda _id, dest: dest.write_bytes(source.read_bytes()))
    diagnostic.main()

    output = capsys.readouterr().out
    assert "pagina 2:" in output
    assert "1 formula(s) detectada(s)" in output
    assert "E=mc^2" in output
    page_pdf = extraction.call_args.kwargs["file_path"]
    with fitz.open(page_pdf) as pdf:
        assert len(pdf) == 1
        assert "E=mc^2" in pdf[0].get_text()
