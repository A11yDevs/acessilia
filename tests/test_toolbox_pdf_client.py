"""Testes para o ToolboxPdfClient.

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
from backend.tools.toolbox_pdf_client import ToolboxPdfClient

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

SAMPLE_SPLIT_RESPONSE = {
    "status": "succeeded",
    "capability": "pdf.split",
    "provider": "pymupdf-pdf",
    "document": {
        "page_count": 3,
        "pages": [
            {"page_number": 1, "width": 595, "height": 842},
            {"page_number": 2, "width": 595, "height": 842},
            {"page_number": 3, "width": 595, "height": 842},
        ],
        "source_filename": "java-oo-3pgs.pdf",
    },
    "provenance": {
        "duration_ms": 500,
        "provider_version": "1.28.2",
    },
}

SAMPLE_RENDER_RESPONSE = {
    "status": "succeeded",
    "capability": "pdf.render",
    "provider": "pymupdf-pdf",
    "document": {
        "page_number": 1,
        "width": 595,
        "height": 842,
        "image_bytes_base64": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        "size_bytes": 95,
        "source_filename": "java-oo-3pgs.pdf",
    },
    "provenance": {
        "duration_ms": 300,
        "provider_version": "1.28.2",
    },
}


@pytest.fixture
def client() -> ToolboxPdfClient:
    return ToolboxPdfClient(
        base_url="http://localhost:8002",
        provider="pymupdf-pdf",
        timeout_seconds=30,
    )


# ---------------------------------------------------------------------------
# split
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_direct_upload(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.split:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_SPLIT_RESPONSE)

    result = await client.split(file_path=FIXTURE_PDF)

    assert result["status"] == "succeeded"
    assert result["document"]["page_count"] == 3


@pytest.mark.asyncio
async def test_split_by_artifact_id(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.split:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_SPLIT_RESPONSE)

    result = await client.split(artifact_id="sha256:abc123")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_split_raises_on_no_input(client):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await client.split()


@pytest.mark.asyncio
async def test_split_raises_on_failure_status(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.split:execute"
    )
    route.return_value = httpx.Response(
        200, json={"status": "failed", "error": "processing error"}
    )

    with pytest.raises(ToolboxContractViolation, match="Divisão de PDF falhou"):
        await client.split(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_split_timeout(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.split:execute"
    ).side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await client.split(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_split_connection_error(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.split:execute"
    ).side_effect = httpx.RequestError("connection refused")

    with pytest.raises(ToolboxProviderUnavailable):
        await client.split(file_path=FIXTURE_PDF)


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_direct_upload(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.render:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_RENDER_RESPONSE)

    result = await client.render(file_path=FIXTURE_PDF, page_number=1)

    assert result["status"] == "succeeded"
    assert result["document"]["page_number"] == 1
    assert result["document"]["width"] == 595


@pytest.mark.asyncio
async def test_render_by_artifact_id(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.render:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_RENDER_RESPONSE)

    result = await client.render(artifact_id="sha256:abc123", page_number=2)

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_render_with_custom_dpi(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.render:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_RENDER_RESPONSE)

    result = await client.render(
        file_path=FIXTURE_PDF, page_number=1, dpi=300
    )

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_render_raises_on_no_input(client):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await client.render(page_number=1)


@pytest.mark.asyncio
async def test_render_timeout(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.render:execute"
    ).side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await client.render(file_path=FIXTURE_PDF, page_number=1)


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
    client = ToolboxPdfClient(
        base_url="http://localhost:8002",
        api_key="secret-key",
    )

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/pdf.split:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_SPLIT_RESPONSE)

    await client.split(file_path=FIXTURE_PDF)

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-key"