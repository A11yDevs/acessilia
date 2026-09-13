"""Testes para o ToolboxMathClient.

Usa resp HTTPX mockadas para validar URLs, parâmetros, timeout e parsing de erro.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from backend.tools.toolbox_client import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)
from backend.tools.toolbox_math_client import ToolboxMathClient

FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

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
    "provider": "pure-math",
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
    "provider": "pure-math",
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

    assert route.calls.last.request.headers["Content-Type"] == "text/plain"


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

    assert route.calls.last.request.headers["Content-Type"] == "text/plain"


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