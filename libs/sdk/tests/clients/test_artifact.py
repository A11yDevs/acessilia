"""ToolboxArtifactClient: artifact.store and artifact.retrieve."""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox import (
    ToolboxArtifactNotFound,
    ToolboxContractViolation,
    ToolboxTimeout,
)
from acessilia_sdk.toolbox.clients import ToolboxArtifactClient

BASE_URL = "http://localhost:8002"
FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"
CONTENT = FIXTURE_PDF.read_bytes()
ARTIFACT_ID = "sha256:" + hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def client() -> ToolboxArtifactClient:
    return ToolboxArtifactClient(base_url=BASE_URL, timeout_seconds=30)


def test_has_no_provider(client):
    assert client.provider is None


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["artifact_id", "id"])
async def test_upload_returns_the_artifact_id(respx_mock, client, key):
    route = respx_mock.post(f"{BASE_URL}/v1/artifacts").mock(
        return_value=httpx.Response(201, json={key: ARTIFACT_ID})
    )

    assert await client.upload(FIXTURE_PDF) == ARTIFACT_ID
    body = route.calls.last.request.content
    assert b'filename="sample.pdf"' in body and b"application/pdf" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [httpx.Response(201, json={}), httpx.Response(201, text="<html>")],
)
async def test_upload_requires_an_artifact_id(respx_mock, client, response):
    respx_mock.post(f"{BASE_URL}/v1/artifacts").mock(return_value=response)
    with pytest.raises(ToolboxContractViolation):
        await client.upload(FIXTURE_PDF)


@pytest.mark.asyncio
async def test_upload_timeout(respx_mock, client):
    respx_mock.post(f"{BASE_URL}/v1/artifacts").mock(
        side_effect=httpx.ReadTimeout("slow")
    )
    with pytest.raises(ToolboxTimeout):
        await client.upload(FIXTURE_PDF)


@pytest.mark.asyncio
async def test_upload_sends_the_api_key(respx_mock):
    client = ToolboxArtifactClient(base_url=BASE_URL, api_key="secret")
    route = respx_mock.post(f"{BASE_URL}/v1/artifacts").mock(
        return_value=httpx.Response(201, json={"artifact_id": ARTIFACT_ID})
    )

    await client.upload(FIXTURE_PDF)

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret"


@pytest.mark.asyncio
async def test_download_is_verified(respx_mock, client, tmp_path):
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{ARTIFACT_ID}").mock(
        return_value=httpx.Response(200, content=CONTENT)
    )
    destination = tmp_path / "out.pdf"

    await client.download(ARTIFACT_ID, destination, magic=b"%PDF-")

    assert destination.read_bytes() == CONTENT


@pytest.mark.asyncio
async def test_download_rejects_tampered_content(respx_mock, client, tmp_path):
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{ARTIFACT_ID}").mock(
        return_value=httpx.Response(200, content=CONTENT + b"x")
    )
    with pytest.raises(ToolboxContractViolation, match="does not match"):
        await client.download(ARTIFACT_ID, tmp_path / "out.pdf")


@pytest.mark.asyncio
async def test_download_not_found(respx_mock, client, tmp_path):
    respx_mock.get(f"{BASE_URL}/v1/artifacts/{ARTIFACT_ID}").mock(
        return_value=httpx.Response(404, json={"detail": "gone"})
    )
    with pytest.raises(ToolboxArtifactNotFound):
        await client.download(ARTIFACT_ID, tmp_path / "out.pdf")
