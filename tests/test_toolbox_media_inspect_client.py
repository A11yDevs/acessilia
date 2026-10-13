"""Testes para o ToolboxMediaInspectClient.

Usa resp HTTPX mockadas para validar URL, multipart, provider, timeout e
mapeamento de erros da capacidade media.inspect.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import respx

from backend.tools.toolbox_client import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    ToolboxUnsupportedMediaType,
)
from backend.tools.toolbox_media_inspect_client import ToolboxMediaInspectClient

FIXTURE_IMAGE = Path(__file__).parent / "fixtures" / "images" / "sunset-skyline.jpeg"

SAMPLE_DOCUMENT = {
    "media_type": "image/jpeg",
    "declared_media_type": "image/jpeg",
    "file_size_bytes": 1234,
    "is_image": True,
    "is_pdf": False,
    "page_count": 1,
    "page_count_source": "pillow",
    "dimensions": {"width": 1280, "height": 960, "aspect_ratio": 1.3333},
    "dimensions_source": "pillow",
    "color_mode": "RGB",
    "format": "JPEG",
    "artifact_nature": "standalone_image",
    "requires_visual_inspection": True,
    "metadata": {"filename": "sunset-skyline.jpeg"},
}


@pytest.fixture
def client() -> ToolboxMediaInspectClient:
    return ToolboxMediaInspectClient(
        base_url="http://localhost:8002",
        provider="pure-media-inspect",
        timeout_seconds=30,
    )


@pytest.mark.asyncio
async def test_inspect_uploads_file_and_returns_document(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(
        return_value=respx.MockResponse(
            status_code=200,
            json={
                "status": "succeeded",
                "capability": "media.inspect",
                "provider": "pure-media-inspect",
                "provenance": {"duration_ms": 12},
                "document": SAMPLE_DOCUMENT,
            },
        )
    )

    result = await client.inspect(file_path=FIXTURE_IMAGE)

    assert route.called
    assert result == SAMPLE_DOCUMENT
    assert result["artifact_nature"] == "standalone_image"
    assert result["requires_visual_inspection"] is True

    request = route.calls.last.request
    # No API key configured -> no Authorization header is sent.
    assert "Authorization" not in request.headers
    # Provider sent as form field even with multipart upload
    assert b"pure-media-inspect" in request.content


@pytest.mark.asyncio
async def test_inspect_sends_provider_form_field(respx_mock, client):
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(
        return_value=respx.MockResponse(
            status_code=200,
            json={"status": "succeeded", "document": SAMPLE_DOCUMENT},
        )
    )

    await client.inspect(file_path=FIXTURE_IMAGE)

    content = route.calls.last.request.content
    assert b'name="provider"' in content
    assert b"pure-media-inspect" in content


@pytest.mark.asyncio
async def test_inspect_sends_bearer_api_key(respx_mock):
    client = ToolboxMediaInspectClient(
        base_url="http://localhost:8002",
        provider="pure-media-inspect",
        timeout_seconds=30,
        api_key="test-api-key",
    )
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(
        return_value=respx.MockResponse(
            status_code=200,
            json={"status": "succeeded", "document": SAMPLE_DOCUMENT},
        )
    )

    await client.inspect(file_path=FIXTURE_IMAGE)

    assert route.calls.last.request.headers["Authorization"] == "Bearer test-api-key"
    await client.close()


@pytest.mark.asyncio
async def test_inspect_uses_global_remote_cache_setting_when_unspecified(
    respx_mock, client, monkeypatch
):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "toolbox_use_remote_cache", False)
    route = respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(
        return_value=respx.MockResponse(
            status_code=200,
            json={"status": "succeeded", "document": SAMPLE_DOCUMENT},
        )
    )

    await client.inspect(file_path=FIXTURE_IMAGE)

    assert b'name="no_cache"' in route.calls.last.request.content
    assert b"\r\n\r\ntrue\r\n" in route.calls.last.request.content


@pytest.mark.asyncio
async def test_inspect_raises_on_not_succeeded(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(
        return_value=respx.MockResponse(
            status_code=200,
            json={"status": "failed", "document": None},
        )
    )

    with pytest.raises(ToolboxContractViolation):
        await client.inspect(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_inspect_raises_on_missing_document(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(
        return_value=respx.MockResponse(
            status_code=200,
            json={"status": "succeeded"},
        )
    )

    with pytest.raises(ToolboxContractViolation):
        await client.inspect(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "response",
    [
        respx.MockResponse(
            status_code=200,
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        ),
        respx.MockResponse(status_code=200, json=[]),
    ],
)
async def test_inspect_raises_on_invalid_json_contract(respx_mock, client, response):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(return_value=response)

    with pytest.raises(ToolboxContractViolation):
        await client.inspect(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_inspect_raises_on_timeout(respx_mock, client):
    import httpx

    respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).side_effect = httpx.TimeoutException("timeout")

    with pytest.raises(ToolboxTimeout):
        await client.inspect(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_inspect_raises_on_unavailable(respx_mock, client):
    import httpx

    respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).side_effect = httpx.ConnectError("boom")

    with pytest.raises(ToolboxProviderUnavailable):
        await client.inspect(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_inspect_raises_on_unsupported_media(respx_mock, client):
    respx_mock.post(
        "http://localhost:8002/v1/capabilities/media.inspect:execute"
    ).mock(
        return_value=respx.MockResponse(
            status_code=415,
            json={"code": "unsupported_media_type"},
        )
    )

    with pytest.raises(ToolboxUnsupportedMediaType):
        await client.inspect(file_path=FIXTURE_IMAGE)


@pytest.mark.asyncio
async def test_inspect_requires_source(respx_mock, client):
    with pytest.raises(ValueError):
        await client.inspect()
