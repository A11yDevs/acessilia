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
    MathCapabilityUnavailable,
    toolbox_convert_latex,
    recognized_formulas,
    toolbox_recognize_formula,
    toolbox_verbalize_latex,
)
from backend.tools.toolbox_ocr_tools import toolbox_ocr_text

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"
TOOLBOX_URL = settings.toolbox_base_url.rstrip("/")

SAMPLE_MATH_CONVERT_RESPONSE = {
    "status": "succeeded",
    "capability": "math.convert",
    "provider": "math-speech",
    "document": {
        "latex": "E = mc^2",
        "mathml": "<math><mi>E</mi><mo>=</mo><mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></math>",
        "direction": "latex-to-mathml",
    },
}

SAMPLE_MATH_VERBALIZE_RESPONSE = {
    "status": "succeeded",
    "capability": "math.verbalize",
    "provider": "math-speech",
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
    def test_convert_unavailable_is_explicit(self):
        """Toolbox unavailable → an error, never a silent local fallback (ADR-0007)."""
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
        with pytest.raises(MathCapabilityUnavailable) as excinfo:
            toolbox_convert_latex("E = mc^2")
        assert excinfo.value.capability == "math.convert"
        assert excinfo.value.reason == "ToolboxProviderUnavailable"

    @respx.mock
    def test_convert_rejected_latex_is_empty(self):
        """Invalid input is a formula without MathML, not an outage."""
        respx.post(f"{TOOLBOX_URL}/v1/capabilities/math.convert:execute").mock(
            return_value=httpx.Response(
                400, json={"code": "invalid_input", "message": "invalid_latex: MissingCloseBrace"}
            )
        )
        assert toolbox_convert_latex(r"\frac{a}{") == ""

    @respx.mock
    def test_verbalize_success(self):
        route = respx.post(
            f"{TOOLBOX_URL}/v1/capabilities/math.verbalize:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_MATH_VERBALIZE_RESPONSE)

        result = toolbox_verbalize_latex("E = mc^2", language="pt-BR")
        assert "elevado" in result

    @respx.mock
    def test_verbalize_unavailable_is_explicit(self):
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
        with pytest.raises(MathCapabilityUnavailable) as excinfo:
            toolbox_verbalize_latex("E = mc^2")
        assert excinfo.value.capability == "math.verbalize"

    @respx.mock
    def test_verbalize_rejected_latex_is_empty(self):
        respx.post(f"{TOOLBOX_URL}/v1/capabilities/math.verbalize:execute").mock(
            return_value=httpx.Response(400, json={"code": "invalid_input", "message": "x"})
        )
        assert toolbox_verbalize_latex(r"\frac{a}{") == ""

    @respx.mock
    def test_recognize_fallback(self):
        """Invalid image → empty list (Toolbox offline)."""
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
        result = toolbox_recognize_formula(b"not-a-real-image")
        assert result == []

    @respx.mock
    def test_recognize_unavailable_can_be_explicit(self):
        """Batch callers opt into the error so an outage costs one timeout."""
        respx.route().mock(side_effect=httpx.ConnectError("synthetic offline provider"))
        with pytest.raises(MathCapabilityUnavailable) as excinfo:
            toolbox_recognize_formula(b"not-a-real-image", raise_on_unavailable=True)
        assert excinfo.value.capability == "math.recognize"
        assert excinfo.value.reason == "ToolboxProviderUnavailable"

    @respx.mock
    def test_recognize_reads_a_latex_document(self):
        """pp-formulanet and rapid-latex-ocr answer with one artifact/latex@1 expression."""
        respx.post(f"{TOOLBOX_URL}/v1/capabilities/math.recognize:execute").mock(
            return_value=httpx.Response(200, json={
                "status": "succeeded",
                "capability": "math.recognize@1",
                "provider": "pp-formulanet",
                "document": {"latex": r"\frac{1}{2}a t^{2}", "bbox": [0, 0, 438, 78]},
            })
        )
        assert toolbox_recognize_formula(b"png", raise_on_unavailable=True) == [
            {"latex": r"\frac{1}{2}a t^{2}", "bbox": [0, 0, 438, 78]}
        ]

    @respx.mock
    def test_recognize_reads_a_formula_list(self):
        """docling-math lists the formulas of a page."""
        formulas = [{"latex": "x^2", "confidence": 0.9, "page": 1, "bbox": [0, 0, 1, 1]}]
        respx.post(f"{TOOLBOX_URL}/v1/capabilities/math.recognize:execute").mock(
            return_value=httpx.Response(200, json={
                "status": "succeeded",
                "capability": "math.recognize@1",
                "provider": "docling-math",
                "document": {"formulas": formulas, "formula_count": 1, "raw_text": "x2"},
            })
        )
        assert toolbox_recognize_formula(b"png") == formulas

    def test_recognized_formulas_without_latex_is_empty(self):
        assert recognized_formulas({"latex": "  "}) == []
        assert recognized_formulas({"formulas": [], "formula_count": 0}) == []
        assert recognized_formulas(None) == []


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