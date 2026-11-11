"""Testes para o ToolboxMathClient.

Usa resp HTTPX mockadas para validar URLs, parâmetros, timeout e parsing de erro.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox import (
    ToolboxTimeout,
)
from acessilia_sdk.toolbox.clients.math import ToolboxMathClient, recognized_formulas

FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "sample.pdf"

SAMPLE_RECOGNIZE_RESPONSE = {
    "status": "succeeded",
    "capability": "math.recognize",
    "provider": "docling-math",
    "document": {
        "formulas": [
            {
                "latex": "E = mc^2",
                "confidence": 0.95,
                "page": 1,
                "bbox": [50, 50, 500, 100],
            },
        ],
        "raw_text": "E = mc^2",
        "formula_count": 1,
    },
    "provenance": {
        "duration_ms": 2500,
        "provider_version": "1.32.0",
    },
}

SAMPLE_CONVERT_RESPONSE = {
    "status": "succeeded",
    "capability": "math.convert",
    "provider": "math-speech",
    "document": {
        "latex": "E = mc^2",
        "mathml": '<math xmlns="http://www.w3.org/1998/Math/MathML" display="inline"><mrow><mi>E</mi><mo>=</mo><mi>m</mi><msup><mi>c</mi><mn>2</mn></msup></mrow></math>',
        "direction": "latex-to-mathml",
    },
    "provenance": {
        "duration_ms": 50,
        "provider_version": "1.0.0",
    },
}

SAMPLE_VERBALIZE_RESPONSE = {
    "status": "succeeded",
    "capability": "math.verbalize",
    "provider": "math-speech",
    "document": {
        "latex": "E = mc^2",
        "verbalized": "E igual a m c elevado a 2",
        "language": "pt-BR",
    },
    "provenance": {
        "duration_ms": 30,
        "provider_version": "1.0.0",
    },
}


@pytest.fixture
def client() -> ToolboxMathClient:
    return ToolboxMathClient(
        base_url="http://localhost:8002",
        provider="docling-math",
        timeout_seconds=30,
    )


# ---------------------------------------------------------------------------
# recognize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recognize_direct_upload(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.recognize:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_RECOGNIZE_RESPONSE)

    result = await client.recognize(file_path=FIXTURE_IMAGE)

    assert result["status"] == "succeeded"
    assert result["document"]["formula_count"] == 1
    assert result["document"]["formulas"][0]["latex"] == "E = mc^2"


@pytest.mark.asyncio
async def test_recognize_by_artifact_id(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.recognize:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_RECOGNIZE_RESPONSE)

    result = await client.recognize(artifact_id="sha256:abc123")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_recognize_raises_on_no_input(client):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await client.recognize()


@pytest.mark.asyncio
async def test_recognize_timeout(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.recognize:execute"
    ).side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await client.recognize(file_path=FIXTURE_IMAGE)


# ---------------------------------------------------------------------------
# convert
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_convert_latex_to_mathml(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.convert:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_CONVERT_RESPONSE)

    result = await client.convert("E = mc^2", direction="latex-to-mathml")

    assert result["status"] == "succeeded"
    assert result["document"]["direction"] == "latex-to-mathml"
    assert "<math " in result["document"]["mathml"]


@pytest.mark.asyncio
async def test_convert_sends_multipart_form(respx_mock, client):
    """Provider, parameters and LaTeX use the REST multipart contract."""
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.convert:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_CONVERT_RESPONSE)

    await client.convert("E = mc^2", direction="latex-to-mathml")

    request = route.calls.last.request
    assert request.url.query == b""
    assert b"math-speech" in request.content
    assert b"latex-to-mathml" in request.content
    assert b"formula.tex" in request.content
    assert b"E = mc^2" in request.content


@pytest.mark.asyncio
async def test_convert_sends_content_type_header(respx_mock):
    client = ToolboxMathClient(
        base_url="http://localhost:8002",
        api_key="test-key",
    )

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.convert:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_CONVERT_RESPONSE)

    await client.convert("E = mc^2")

    assert route.calls.last.request.headers["Content-Type"].startswith(
        "multipart/form-data;"
    )
    assert b"Content-Type: text/plain" in route.calls.last.request.content


# ---------------------------------------------------------------------------
# verbalize
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verbalize_latex(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.verbalize:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_VERBALIZE_RESPONSE)

    result = await client.verbalize("E = mc^2")

    assert result["status"] == "succeeded"
    assert result["document"]["verbalized"] == "E igual a m c elevado a 2"
    assert result["document"]["language"] == "pt-BR"


@pytest.mark.asyncio
async def test_verbalize_sends_multipart_form(respx_mock, client):
    """Provider, language and LaTeX use the REST multipart contract."""
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.verbalize:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_VERBALIZE_RESPONSE)

    await client.verbalize("E = mc^2", language="pt-BR")

    request = route.calls.last.request
    assert request.url.query == b""
    assert b"math-speech" in request.content
    assert b"pt-BR" in request.content
    assert b"formula.tex" in request.content
    assert b"E = mc^2" in request.content


@pytest.mark.asyncio
async def test_verbalize_sends_content_type_header(respx_mock):
    client = ToolboxMathClient(
        base_url="http://localhost:8002",
        api_key="test-key",
    )

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.verbalize:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_VERBALIZE_RESPONSE)

    await client.verbalize("E = mc^2")

    assert route.calls.last.request.headers["Content-Type"].startswith(
        "multipart/form-data;"
    )
    assert b"Content-Type: text/plain" in route.calls.last.request.content


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_status(respx_mock, client):
    route = respx_mock.get("http://localhost:8002/v1/health")
    route.return_value = httpx.Response(200, json={"status": "ok"})

    result = await client.health()
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Auth headers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auth_header_is_sent_when_configured(respx_mock):
    client = ToolboxMathClient(
        base_url="http://localhost:8002",
        api_key="secret-key",
    )

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/math.recognize:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_RECOGNIZE_RESPONSE)

    await client.recognize(file_path=FIXTURE_IMAGE)

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-key"

# recognized_formulas: both math.recognize@1 document shapes as one list.
# The first and last two cases were the core's tests of the same function
# (now tests/test_toolbox_math_tools.py) before it moved here (#402).


def test_recognized_formulas_reads_one_latex_expression() -> None:
    """pp-formulanet and rapid-latex-ocr answer with one artifact/latex@1 expression."""
    document = {"latex": r"\frac{1}{2}", "confidence": 0.8, "bbox": [0, 0, 4, 2], "extra": 1}
    assert recognized_formulas(document) == [
        {"latex": r"\frac{1}{2}", "confidence": 0.8, "bbox": [0, 0, 4, 2]}
    ]


def test_recognized_formulas_reads_a_formula_list() -> None:
    """docling-math lists the formulas of a page; each entry is kept as it is."""
    formulas = [{"latex": "x^2", "confidence": 0.9, "page": 1, "bbox": [0, 0, 1, 1], "k": 2}]
    assert recognized_formulas({"formulas": formulas, "formula_count": 1}) == formulas


def test_the_formula_list_wins_over_a_top_level_expression() -> None:
    document = {"formulas": [{"latex": "a"}], "latex": "b"}
    assert recognized_formulas(document) == [{"latex": "a"}]


def test_recognized_formulas_without_latex_is_empty() -> None:
    assert recognized_formulas({"latex": "  "}) == []
    assert recognized_formulas({"formulas": [], "formula_count": 0}) == []
    assert recognized_formulas(None) == []


def test_listed_entries_without_latex_are_left_out() -> None:
    """Both shapes apply the same rule: no LaTeX, no formula."""
    document = {"formulas": [{"latex": "  "}, {"page": 1}, "x", {"latex": "y^2", "page": 2}]}
    assert recognized_formulas(document) == [{"latex": "y^2", "page": 2}]
