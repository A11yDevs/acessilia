"""Tests for Toolbox-backed tools (Math, OCR).

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

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"
TOOLBOX_URL = settings.toolbox_base_url.rstrip("/")

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


class TestMathTools:
    @respx.mock
    def test_convert_success(self):
        route = respx.post(
            f"{TOOLBOX_URL}/v1/capabilities/math.convert:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_MATH_CONVERT_RESPONSE)

        result = toolbox_convert_latex("E = mc^2", direction="latex-to-mathml")
        assert "<math>" in result

    @respx.mock
    def test_convert_fallback(self):
        """Toolbox unavailable → empty string."""
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
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

    @respx.mock
    def test_verbalize_fallback(self):
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
        result = toolbox_verbalize_latex("E = mc^2")
        assert result == ""

    @respx.mock
    def test_recognize_fallback(self):
        """Invalid image → empty list (Toolbox offline)."""
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
        result = toolbox_recognize_formula(b"not-a-real-image")
        assert result == []


class TestOcrTools:
    @respx.mock
    def test_ocr_fallback(self):
        """Toolbox offline → empty string. No real PDF fixture required."""
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
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