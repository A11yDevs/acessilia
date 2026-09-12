"""Testes para o cliente HTTP da Acessilia Toolbox.

Usa resp HTTPX mockadas para validar URLs, multipart, timeout e parsing de erro.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
import respx

from backend.tools.toolbox_client import (
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityError,
    ToolboxClient,
    ToolboxContractViolation,
    ToolboxError,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnsupportedMediaType,
)


FIXTURE_PDF = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"


@pytest.fixture
def client() -> ToolboxClient:
    return ToolboxClient(
        base_url="http://localhost:8002",
        provider="docling",
        timeout_seconds=30,
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_returns_status(respx_mock, client):
    route = respx_mock.get("http://localhost:8002/v1/health")
    route.return_value = httpx.Response(200, json={"status": "ok"})

    result = await client.health()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_health_raises_on_unavailable(respx_mock, client):
    respx_mock.get("http://localhost:8002/v1/health").side_effect = (
        httpx.RequestError("Connection refused")
    )

    with pytest.raises(ToolboxProviderUnavailable):
        await client.health()


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_capabilities_returns_list(respx_mock, client):
    route = respx_mock.get("http://localhost:8002/v1/capabilities")
    route.return_value = httpx.Response(
        200,
        json=[
            {"id": "document.structure.extract", "version": "1"},
            {"id": "artifact.store", "version": "1"},
        ],
    )

    caps = await client.capabilities()
    assert len(caps) == 2
    assert caps[0]["id"] == "document.structure.extract"


@pytest.mark.asyncio
async def test_capabilities_from_wrapped_response(respx_mock, client):
    route = respx_mock.get("http://localhost:8002/v1/capabilities")
    route.return_value = httpx.Response(
        200,
        json={"capabilities": [{"id": "document.structure.extract"}]},
    )

    caps = await client.capabilities()
    assert len(caps) == 1


# ---------------------------------------------------------------------------
# Upload artifact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_upload_artifact_returns_id(respx_mock, client):
    route = respx_mock.post("http://localhost:8002/v1/artifacts")
    route.return_value = httpx.Response(
        200, json={"artifact_id": "sha256:abc123"}
    )

    artifact_id = await client.upload_artifact(FIXTURE_PDF)
    assert artifact_id == "sha256:abc123"


@pytest.mark.asyncio
async def test_upload_artifact_missing_id_raises(respx_mock, client):
    route = respx_mock.post("http://localhost:8002/v1/artifacts")
    route.return_value = httpx.Response(200, json={"status": "ok"})

    with pytest.raises(ToolboxContractViolation, match="sem artifact_id"):
        await client.upload_artifact(FIXTURE_PDF)


@pytest.mark.asyncio
async def test_upload_artifact_timeout(respx_mock, client):
    respx_mock.post("http://localhost:8002/v1/artifacts").side_effect = (
        httpx.TimeoutException("timeout")
    )

    with pytest.raises(ToolboxTimeout):
        await client.upload_artifact(FIXTURE_PDF)


# ---------------------------------------------------------------------------
# Retrieve artifact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retrieve_artifact_writes_file(respx_mock, client, tmp_path):
    route = respx_mock.get("http://localhost:8002/v1/artifacts/sha256:abc")
    route.return_value = httpx.Response(200, content=b"pdf-content")

    out = tmp_path / "downloaded.pdf"
    await client.retrieve_artifact("sha256:abc", out)
    assert out.read_bytes() == b"pdf-content"


@pytest.mark.asyncio
async def test_retrieve_artifact_not_found(respx_mock, client, tmp_path):
    route = respx_mock.get("http://localhost:8002/v1/artifacts/sha256:missing")
    route.return_value = httpx.Response(404, json={"detail": "not found"})

    with pytest.raises(ToolboxArtifactNotFound):
        await client.retrieve_artifact("sha256:missing", tmp_path / "out.pdf")


# ---------------------------------------------------------------------------
# Extract structure
# ---------------------------------------------------------------------------


SAMPLE_EXTRACT_RESPONSE = {
    "status": "succeeded",
    "capability": "document.structure.extract",
    "provider": "docling",
    "document": {
        "elements": [
            {"type": "heading", "text": "Title", "page_number": 1},
            {"type": "paragraph", "text": "Body", "page_number": 1},
        ],
        "pages": [{"page_number": 1, "width": 595, "height": 842}],
    },
    "provenance": {
        "duration_ms": 1500,
        "provider_version": "1.32.0",
        "cache_key": "cache:abc123",
    },
}


@pytest.mark.asyncio
async def test_extract_structure_direct_upload(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_EXTRACT_RESPONSE)

    result = await client.extract_structure(file_path=FIXTURE_PDF)
    assert result["status"] == "succeeded"
    assert len(result["document"]["elements"]) == 2


@pytest.mark.asyncio
async def test_extract_structure_by_artifact_id(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(200, json=SAMPLE_EXTRACT_RESPONSE)

    result = await client.extract_structure(artifact_id="sha256:abc123")
    assert result["status"] == "succeeded"


@pytest.mark.asyncio
async def test_extract_structure_failed_status(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(
        200, json={"status": "failed", "error": "provider error"}
    )

    with pytest.raises(ToolboxContractViolation, match="Extra.* falhou"):
        await client.extract_structure(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_extract_structure_503_raises_provider_unavailable(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(503, json={"detail": "docling offline"})

    with pytest.raises(ToolboxProviderUnavailable):
        await client.extract_structure(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_extract_structure_415_raises_unsupported_media(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(415, json={"detail": "unsupported"})

    with pytest.raises(ToolboxUnsupportedMediaType):
        await client.extract_structure(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_extract_structure_422_raises_contract_violation(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(422, json={"detail": "invalid input"})

    with pytest.raises(ToolboxContractViolation):
        await client.extract_structure(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_extract_structure_400_raises_capability_error(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(400, json={"detail": "bad request"})

    with pytest.raises(ToolboxCapabilityError):
        await client.extract_structure(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_extract_structure_no_file_no_artifact_raises(client):
    with pytest.raises(ValueError, match="Forneça file_path ou artifact_id"):
        await client.extract_structure()


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_status_code_raises_generic_error(respx_mock, client):
    route = respx_mock.get("http://localhost:8002/v1/health")
    route.return_value = httpx.Response(500, json={"detail": "internal"})

    with pytest.raises(ToolboxError, match="500"):
        await client.health()


@pytest.mark.asyncio
async def test_timeout_on_get_raises_timeout(respx_mock, client):
    respx_mock.get("http://localhost:8002/v1/health").side_effect = (
        httpx.TimeoutException("timeout")
    )

    with pytest.raises(ToolboxTimeout):
        await client.health()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_client_with_api_key_sends_auth_header(respx_mock):
    """Quando api_key é fornecida, o header Authorization deve ser enviado."""
    auth_client = ToolboxClient(
        base_url="http://localhost:8002",
        provider="docling",
        timeout_seconds=30,
        api_key="test-key-123",
    )

    route = respx_mock.get("http://localhost:8002/v1/capabilities")
    route.return_value = httpx.Response(200, json=[])

    await auth_client.capabilities()

    request = route.calls[0].request
    assert request.headers.get("Authorization") == "Bearer test-key-123"


@pytest.mark.asyncio
async def test_client_without_api_key_skips_auth_header(respx_mock, client):
    """Quando api_key não é fornecida, o header Authorization não deve ser enviado."""
    route = respx_mock.get("http://localhost:8002/v1/capabilities")
    route.return_value = httpx.Response(200, json=[])

    await client.capabilities()

    request = route.calls[0].request
    assert "Authorization" not in request.headers


@pytest.mark.asyncio
async def test_health_works_with_api_key(respx_mock):
    """Health check (público) funciona mesmo com api_key configurada."""
    auth_client = ToolboxClient(
        base_url="http://localhost:8002",
        provider="docling",
        timeout_seconds=30,
        api_key="test-key-123",
    )

    route = respx_mock.get("http://localhost:8002/v1/health")
    route.return_value = httpx.Response(200, json={"status": "ok"})

    result = await auth_client.health()
    assert result["status"] == "ok"


@pytest.mark.asyncio
async def test_401_raises_authentication_error(respx_mock, client):
    """HTTP 401 deve levantar ToolboxAuthenticationError."""
    route = respx_mock.get("http://localhost:8002/v1/capabilities")
    route.return_value = httpx.Response(
        401, json={"detail": "Missing or invalid token"}
    )

    with pytest.raises(ToolboxAuthenticationError, match="Autenticação falhou"):
        await client.capabilities()


@pytest.mark.asyncio
async def test_upload_artifact_sends_auth_header(respx_mock):
    """upload_artifact com api_key envia header Authorization."""
    auth_client = ToolboxClient(
        base_url="http://localhost:8002",
        provider="docling",
        timeout_seconds=30,
        api_key="test-key-123",
    )

    route = respx_mock.post("http://localhost:8002/v1/artifacts")
    route.return_value = httpx.Response(
        200, json={"artifact_id": "sha256:abc123"}
    )

    await auth_client.upload_artifact(FIXTURE_PDF)

    request = route.calls[0].request
    assert request.headers.get("Authorization") == "Bearer test-key-123"


@pytest.mark.asyncio
async def test_extract_structure_sends_auth_header(respx_mock):
    """extract_structure com api_key envia header Authorization."""
    auth_client = ToolboxClient(
        base_url="http://localhost:8002",
        provider="docling",
        timeout_seconds=30,
        api_key="test-key-123",
    )

    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/document.structure.extract:execute"
    )
    route.return_value = httpx.Response(
        200,
        json={
            "status": "succeeded",
            "capability": "document.structure.extract",
            "provider": "docling",
            "document": {"elements": [], "pages": []},
            "provenance": {"duration_ms": 100, "provider_version": "1.0"},
        },
    )

    await auth_client.extract_structure(file_path=FIXTURE_PDF)

    request = route.calls[0].request
    assert request.headers.get("Authorization") == "Bearer test-key-123"


@pytest.mark.asyncio
async def test_retrieve_artifact_sends_auth_header(respx_mock, tmp_path):
    """retrieve_artifact com api_key envia header Authorization."""
    auth_client = ToolboxClient(
        base_url="http://localhost:8002",
        provider="docling",
        timeout_seconds=30,
        api_key="test-key-123",
    )

    route = respx_mock.get("http://localhost:8002/v1/artifacts/sha256:abc")
    route.return_value = httpx.Response(200, content=b"pdf-content")

    out = tmp_path / "downloaded.pdf"
    await auth_client.retrieve_artifact("sha256:abc", out)

    request = route.calls[0].request
    assert request.headers.get("Authorization") == "Bearer test-key-123"
    assert out.read_bytes() == b"pdf-content"