"""Testes para o ToolboxLayoutClient.

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
from backend.tools.toolbox_layout_client import ToolboxLayoutClient

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"

SAMPLE_LAYOUT_RESPONSE = {
    "status": "succeeded",
    "capability": "document.layout.analyze",
    "provider": "docling-layout",
    "document": {
        "page_count": 1,
        "region_count": 4,
        "pages": [
            {
                "page_number": 1,
                "width": 595,
                "height": 842,
                "regions": [
                    {
                        "type": "text_clean",
                        "label": "paragraph",
                        "bbox": [50, 50, 500, 100],
                        "confidence": 0.98,
                        "text": "Primeiro parágrafo.",
                        "page_number": 1,
                    },
                    {
                        "type": "embedded_image",
                        "label": "picture",
                        "bbox": [50, 120, 500, 300],
                        "confidence": 0.85,
                        "text": "",
                        "page_number": 1,
                    },
                    {
                        "type": "table",
                        "label": "table",
                        "bbox": [50, 320, 500, 450],
                        "confidence": 0.95,
                        "text": "Header1|Header2",
                        "page_number": 1,
                    },
                    {
                        "type": "formula",
                        "label": "formula",
                        "bbox": [50, 470, 500, 520],
                        "confidence": 0.90,
                        "text": "E = mc^2",
                        "page_number": 1,
                    },
                ],
            },
        ],
    },
    "provenance": {
        "duration_ms": 2500,
        "provider_version": "1.32.0",
        "cache_key": "layout:cache:abc123",
    },
}


@pytest.fixture
def client() -> ToolboxLayoutClient:
    return ToolboxLayoutClient(
        base_url="http://localhost:8002",
        provider="docling-layout",
        timeout_seconds=30,
    )


# ---------------------------------------------------------------------------
# analyze (full response)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_direct_upload(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    result = await client.analyze(file_path=FIXTURE_PDF)

    assert result["status"] == "succeeded"
    assert result["capability"] == "document.layout.analyze"
    assert result["provider"] == "docling-layout"
    assert result["document"]["page_count"] == 1
    assert result["document"]["region_count"] == 4


@pytest.mark.asyncio
async def test_analyze_by_artifact_id(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    result = await client.analyze(artifact_id="sha256:abc123")

    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_analyze_raises_on_no_input(client):
    with pytest.raises(ValueError, match="file_path ou artifact_id"):
        await client.analyze()


@pytest.mark.asyncio
async def test_analyze_raises_on_failure_status(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(
        200, json={"status": "failed", "error": "processing error"}
    )

    with pytest.raises(ToolboxContractViolation, match="falhou"):
        await client.analyze(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_analyze_timeout(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    ).side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await client.analyze(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_analyze_connection_error(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    ).side_effect = httpx.RequestError("connection refused")

    with pytest.raises(ToolboxProviderUnavailable):
        await client.analyze(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_analyze_http_422_raises(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(
        422, json={"detail": "unsupported media type"}
    )

    with pytest.raises(ToolboxContractViolation):
        await client.analyze(file_path=FIXTURE_PDF)


# ---------------------------------------------------------------------------
# analyze_pages (conveniência)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_pages_returns_list(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    pages = await client.analyze_pages(file_path=FIXTURE_PDF)

    assert isinstance(pages, list)
    assert len(pages) == 1
    assert pages[0]["page_number"] == 1


@pytest.mark.asyncio
async def test_analyze_pages_contains_regions(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    pages = await client.analyze_pages(file_path=FIXTURE_PDF)
    regions = pages[0]["regions"]

    assert len(regions) == 4
    types = {r["type"] for r in regions}
    assert "text_clean" in types
    assert "embedded_image" in types
    assert "table" in types
    assert "formula" in types


@pytest.mark.asyncio
async def test_analyze_pages_with_dict_pages(respx_mock, client):
    """Testa quando pages vem como dict em vez de list."""
    response = dict(SAMPLE_LAYOUT_RESPONSE)
    response["document"]["pages"] = {
        "1": SAMPLE_LAYOUT_RESPONSE["document"]["pages"][0],
    }

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=response)

    pages = await client.analyze_pages(file_path=FIXTURE_PDF)
    assert len(pages) == 1


# ---------------------------------------------------------------------------
# analyze_page (página específica)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_analyze_page_returns_specific_page(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    page = await client.analyze_page(1, file_path=FIXTURE_PDF)

    assert page is not None
    assert page["page_number"] == 1


@pytest.mark.asyncio
async def test_analyze_page_returns_none_for_missing(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    page = await client.analyze_page(99, file_path=FIXTURE_PDF)

    assert page is None


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
    client = ToolboxLayoutClient(
        base_url="http://localhost:8002",
        api_key="secret-key",
    )

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    await client.analyze(file_path=FIXTURE_PDF)

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-key"


@pytest.mark.asyncio
async def test_no_auth_header_when_not_configured(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.layout.analyze:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_LAYOUT_RESPONSE)

    await client.analyze(file_path=FIXTURE_PDF)

    assert "Authorization" not in route.calls.last.request.headers