"""Formula diagnostics use real PDFs and the existing Toolbox region adapter."""

from unittest.mock import AsyncMock

import fitz
import pytest

from backend.tools.toolbox_client import (
    ToolboxClient,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
)
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


@pytest.mark.parametrize("diagnostic_name", [
    "benchmark_formula_extraction",
    "benchmark_formula_grandezas_medidas",
    "test_formula_arxiv",
])
@pytest.mark.parametrize("error_type", [
    ToolboxProviderUnavailable,
    ToolboxContractViolation,
])
def test_formula_diagnostics_reject_toolbox_failure(
    diagnostic_name, error_type, formula_pdf, monkeypatch, tmp_path, capsys
):
    """An unavailable or failed provider must not produce Docling metrics."""
    import importlib
    import sys

    from PIL import Image

    diagnostic = importlib.import_module(f"scripts.{diagnostic_name}")
    source, extraction = formula_pdf
    extraction.side_effect = error_type("Docling extraction failed")

    if diagnostic_name == "benchmark_formula_extraction":
        monkeypatch.setattr(sys, "argv", [diagnostic_name])
        monkeypatch.setattr(diagnostic, "FORMULAS", [("equation", "E=mc^2")])
        monkeypatch.setattr(
            diagnostic, "download_formula",
            lambda _latex, dest: Image.new("RGB", (32, 32), "white").save(dest),
        )
    elif diagnostic_name == "benchmark_formula_grandezas_medidas":
        monkeypatch.setattr(diagnostic, "PDF", source)
    else:
        monkeypatch.setattr(diagnostic, "WORKDIR", tmp_path / "arxiv")
        monkeypatch.setattr(diagnostic, "PAPERS", [("paper", "test-id", "Test paper")])
        monkeypatch.setattr(
            diagnostic, "_download",
            lambda _id, dest: dest.write_bytes(source.read_bytes()),
        )

    with pytest.raises(error_type, match="Docling extraction failed"):
        diagnostic.main()

    extraction.assert_awaited_once()
    output = capsys.readouterr().out
    assert "## Resultados" not in output
    assert "### Resumo" not in output
    assert "provider=docling" not in output
