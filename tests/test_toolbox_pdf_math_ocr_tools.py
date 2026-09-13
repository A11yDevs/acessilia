"""Testes para as Toolbox-backed tools (math, ocr).

Funções síncronas que encapsulam chamadas assíncronas via asyncio.run().
Usa respx para mockar HTTP.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from backend.tools.toolbox_math_tools import (
    toolbox_convert_latex,
    toolbox_recognize_formula,
    toolbox_verbalize_latex,
)
from backend.tools.toolbox_ocr_tools import toolbox_ocr_text
from backend.tools.toolbox_pdf_tools import toolbox_split_pdf, toolbox_render_page

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

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
            "http://localhost:8002/v1/capabilities/math.convert:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_MATH_CONVERT_RESPONSE)

        result = toolbox_convert_latex("E = mc^2", direction="latex-to-mathml")
        assert "<math>" in result

    def test_convert_fallback(self):
        """Quando Toolbox falha (rejeita conexão), retorna vazio."""
        result = toolbox_convert_latex("E = mc^2")
        assert result == ""

    @respx.mock
    def test_verbalize_success(self):
        route = respx.post(
            "http://localhost:8002/v1/capabilities/math.verbalize:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_MATH_VERBALIZE_RESPONSE)

        result = toolbox_verbalize_latex("E = mc^2", language="pt-BR")
        assert "elevado" in result

    def test_verbalize_fallback(self):
        result = toolbox_verbalize_latex("E = mc^2")
        assert result == ""

    def test_recognize_fallback(self):
        """Imagem inválida → lista vazia (Toolbox rejeita conexão)."""
        result = toolbox_recognize_formula(b"not-a-real-image")
        assert result == []


class TestOcrTools:
    def test_ocr_fallback(self):
        """Toolbox offline → string vazia."""
        result = toolbox_ocr_text(FIXTURE_PDF)
        assert result == ""

    @respx.mock
    def test_ocr_success(self):
        route = respx.post(
            "http://localhost:8002/v1/capabilities/document.ocr:execute"
        )
        route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

        result = toolbox_ocr_text(FIXTURE_PDF, language="pt-BR")
        assert "Texto reconhecido" in result