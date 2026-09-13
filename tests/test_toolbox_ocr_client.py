"""Testes para o ToolboxOcrClient.

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
from backend.tools.toolbox_ocr_client import ToolboxOcrClient

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

SAMPLE_OCR_RESPONSE = {
    "status": "succeeded",
    "capability": "document.ocr",
    "provider": "docling-ocr",
    "document": {
        "items": [
            {
                "text": "Texto reconhecido em português.",
                "label": "paragraph",
                "confidence": 0.95,
                "page": 1,
                "bbox": [50, 50, 500, 100],
            },
            {
                "text": "Segundo parágrafo com mais conteúdo.",
                "label": "paragraph",
                "confidence": 0.90,
                "page": 1,
                "bbox": [50, 120, 500, 200],
            },
        ],
        "item_count": 2,
        "full_text": "Texto reconhecido em português.\nSegundo parágrafo com mais conteúdo.",
        "language": "pt-BR",
    },
    "provenance": {
        "duration_ms": 3000,
        "provider_version": "1.32.0",
    },
}


@pytest.fixture
def client() -> ToolboxOcrClient:
    return ToolboxOcrClient(
        base_url="http://localhost:8002",
        provider="docling-ocr",
        timeout_seconds=30,
    )


# ---------------------------------------------------------------------------
# ocr
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ocr_direct_upload(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

    result = await client.ocr(file_path=FIXTURE_PDF)

    assert result["status"] == "succeeded"
    assert result["document"]["item_count"] == 2
    assert "Texto reconhecido" in result["document"]["full_text"]


@pytest.mark.asyncio
async def test_ocr_by_artifact_id(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

    result = await client.ocr(artifact_id="sha256:abc123")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_ocr_with_custom_language(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

    result = await client.ocr(file_path=FIXTURE_PDF, language="en")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_ocr_with_force_ocr_false(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

    result = await client.ocr(file_path=FIXTURE_PDF, force_ocr=False)

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_ocr_raises_on_no_input(client):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await client.ocr()


@pytest.mark.asyncio
async def test_ocr_raises_on_failure_status(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(
        200, json={"status": "failed", "error": "processing error"}
    )

    with pytest.raises(ToolboxContractViolation, match="OCR falhou"):
        await client.ocr(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_ocr_timeout(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    ).side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await client.ocr(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_ocr_connection_error(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    ).side_effect = httpx.RequestError("connection refused")

    with pytest.raises(ToolboxProviderUnavailable):
        await client.ocr(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_ocr_http_422_raises(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(
        422, json={"detail": "unsupported media type"}
    )

    with pytest.raises(ToolboxContractViolation):
        await client.ocr(file_path=FIXTURE_PDF)


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
    client = ToolboxOcrClient(
        base_url="http://localhost:8002",
        api_key="secret-key",
    )

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

    await client.ocr(file_path=FIXTURE_PDF)

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-key"


@pytest.mark.asyncio
async def test_no_auth_header_when_not_configured(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.ocr:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_OCR_RESPONSE)

    await client.ocr(file_path=FIXTURE_PDF)

    assert "Authorization" not in route.calls.last.request.headers