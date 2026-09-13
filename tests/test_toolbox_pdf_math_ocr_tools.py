"""Tests for Toolbox-backed tools (PDF, Math, OCR).

Sync functions wrapping async calls via asyncio.run().
Uses respx for HTTP mocking.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from backend.config.settings import settings
from backend.tools.toolbox_math_tools import (
    toolbox_convert_latex,
    toolbox_recognize_formula,
    toolbox_verbalize_latex,
)
from backend.tools.toolbox_ocr_tools import toolbox_ocr_text
from backend.tools.toolbox_pdf_tools import toolbox_split_pdf, toolbox_render_page

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"
TOOLBOX_URL = settings.toolbox_base_url.rstrip("/")

MINI_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
)

SAMPLE_MATH_CONVERT_RESPONSE = {
    "status": "succeeded",
    "capability": "math.convert",
    "provider": "pure-math",
    "document": {
        "latex": "E = mc^2",
        "mathml": "<math><mi>E</mi><mo>=</mo><mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></math>",
        "direction": "latex-to-mathml",
    },
}

SAMPLE_MATH_VERBALIZE_RESPONSE = {
    "status": "succeeded",
    "capability": "math.verbalize",
    "provider": "pure-math",
    "document": {
        "latex": "E = mc^2",
        "verbalized": "E igual a m c elevado a 2",
        "language": "pt-BR",
    },
}

SAMPLE_OCR_RESPONSE = {
    "status": "succeeded",
    "capability": "document.ocr",
    "provider": "docling-ocr",
    "document": {
        "items": [{"text": "Texto reconhecido.", "confidence": 0.95}],
        "item_count": 1,
        "full_text": "Texto reconhecido.",
        "language": "pt-BR",
    },
}

SAMPLE_SPLIT_RESPONSE = {
    "status": "succeeded",
    "capability": "pdf.split",
    "provider": "docling",
    "document": {
        "source_filename": "java-oo-3pgs.pdf",
        "page_count": 3,
    },
}

SAMPLE_RENDER_RESPONSE = {
    "status": "succeeded",
    "capability": "pdf.render",
    "provider": "docling",
    "document": {
        "page_number": 1,
        "image_bytes_base64": MINI_PNG_BASE64,
        "size_bytes": 68,
    },
}


def _make_test_pdf(tmp_path: Path, pages: int = 2) -> Path:
    """Create a minimal multi-page PDF for testing."""
    import fitz

    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    for _ in range(pages):
        doc.new_page(width=200, height=200)
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


class TestPdfTools:
    @respx.mock
    def test_split_success(self, tmp_path):
        route = respx.post(f"{TOOLBOX_URL}/v1/capabilities/pdf.split:execute")
        route.return_value = httpx.Response(200, json=SAMPLE_SPLIT_RESPONSE)

        pdf = _make_test_pdf(tmp_path, pages=3)
        result = toolbox_split_pdf(pdf, tmp_path, max_pages=5)
        assert len(result) == 3
        for p in result:
            assert p.exists()
            assert p.suffix == ".pdf"

    def test_split_fallback(self, tmp_path):
        """Toolbox offline → local-only split."""
        pdf = _make_test_pdf(tmp_path, pages=2)
        result = toolbox_split_pdf(pdf, tmp_path, max_pages=5)
        assert len(result) == 2

    @respx.mock
    def test_render_success(self, tmp_path):
        route = respx.post(f"{TOOLBOX_URL}/v1/capabilities/pdf.render:execute")
        route.return_value = httpx.Response(200, json=SAMPLE_RENDER_RESPONSE)

        pdf = _make_test_pdf(tmp_path)
        result = toolbox_render_page(pdf, page_number=1)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_render_fallback_page_number(self, tmp_path):
        """Fallback renders the exact requested page (not just page 1)."""
        pdf = _make_test_pdf(tmp_path, pages=2)
        result = toolbox_render_page(pdf, page_number=2)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"

    def test_render_fallback(self, tmp_path):
        """Toolbox offline → local PyMuPDF render."""
        pdf = _make_test_pdf(tmp_path)
        result = toolbox_render_page(pdf, page_number=1)
        assert isinstance(result, bytes)
        assert result[:4] == b"\x89PNG"


class TestMathTools:
    @respx.mock
    def test_convert_success(self):
        route = respx.post(
            f"{TOOLBOX_URL}/v1/capabilities/math.convert:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_MATH_CONVERT_RESPONSE)

        result = toolbox_convert_latex("E = mc^2", direction="latex-to-mathml")
        assert "<math>" in result

    def test_convert_fallback(self):
        """Toolbox unavailable → empty string."""
        result = toolbox_convert_latex("E = mc^2")
        assert result == ""

    @respx.mock
    def test_verbalize_success(self):
        route = respx.post(
            f"{TOOLBOX_URL}/v1/capabilities/math.verbalize:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_MATH_VERBALIZE_RESPONSE)

        result = toolbox_verbalize_latex("E = mc^2", language="pt-BR")
        assert "elevado" in result

    def test_verbalize_fallback(self):
        result = toolbox_verbalize_latex("E = mc^2")
        assert result == ""

    def test_recognize_fallback(self):
        """Invalid image → empty list (Toolbox offline)."""
        result = toolbox_recognize_formula(b"not-a-real-image")
        assert result == []


class TestOcrTools:
    def test_ocr_fallback(self):
        """Toolbox offline → empty string. No real PDF fixture required."""
        result = toolbox_ocr_text(Path("/nonexistent/file.pdf"))
        assert result == ""

    @respx.mock
    def test_ocr_success(self):
        route = respx.post(
            f"{TOOLBOX_URL}/v1/capabilities/document.ocr:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

        result = toolbox_ocr_text(FIXTURE_PDF, language="pt-BR")
        assert "Texto reconhecido" in result


if __name__ == "__main__":
    pytest.main([__file__])