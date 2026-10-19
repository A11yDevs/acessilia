"""ToolboxStructureClient: document.structure.extract."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox import (
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxUnsupportedMediaType,
)
from acessilia_sdk.toolbox.clients import ToolboxStructureClient

BASE_URL = "http://localhost:8002"
EXECUTE_URL = f"{BASE_URL}/v1/capabilities/document.structure.extract:execute"
FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"
SUCCEEDED = {
    "status": "succeeded",
    "provider": "docling",
    "document": {"elements": []},
    "provenance": {"duration_ms": 10},
}


@pytest.fixture
def client() -> ToolboxStructureClient:
    return ToolboxStructureClient(base_url=BASE_URL, timeout_seconds=30)


def test_default_provider_comes_from_the_registry(client):
    assert client.provider == "docling"


@pytest.mark.asyncio
async def test_direct_upload(respx_mock, client):
    route = respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(200, json=SUCCEEDED)
    )

    result = await client.extract_structure(file_path=FIXTURE_PDF, language="en")

    assert result == SUCCEEDED
    body = route.calls.last.request.content
    assert b'filename="sample.pdf"' in body
    assert b"application/pdf" in body
    assert b"provider" in body and b"docling" in body
    assert b"no_cache" not in body


@pytest.mark.asyncio
async def test_by_artifact_id_without_cache(respx_mock, client):
    route = respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(200, json=SUCCEEDED)
    )

    await client.extract_structure(artifact_id="sha256:abc", use_remote_cache=False)

    body = route.calls.last.request.content.decode()
    assert "artifact_id=sha256%3Aabc" in body
    assert "no_cache=true" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error"),
    [
        (httpx.Response(200, json={"status": "failed"}), ToolboxContractViolation),
        (httpx.Response(503, json={"detail": "x"}), ToolboxProviderUnavailable),
        (httpx.Response(415, json={"detail": "x"}), ToolboxUnsupportedMediaType),
        (httpx.Response(422, json={"detail": "x"}), ToolboxContractViolation),
        (httpx.Response(400, json={"detail": "x"}), ToolboxCapabilityError),
    ],
)
async def test_maps_failures(respx_mock, client, response, error):
    respx_mock.post(EXECUTE_URL).mock(return_value=response)
    with pytest.raises(error):
        await client.extract_structure(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_requires_an_input(client):
    with pytest.raises(ValueError):
        await client.extract_structure()


@pytest.mark.asyncio
async def test_sends_the_api_key(respx_mock):
    client = ToolboxStructureClient(base_url=BASE_URL, api_key="secret")
    route = respx_mock.post(EXECUTE_URL).mock(
        return_value=httpx.Response(200, json=SUCCEEDED)
    )

    await client.extract_structure(file_path=FIXTURE_PDF)

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"
