"""execute_capability: allowlist, wire format and envelope validation."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from acessilia_sdk.toolbox import (
    TOOLBOX_CAPABILITIES,
    ToolboxArtifactNotFound,
    ToolboxAuthenticationError,
    ToolboxCapabilityClient,
    ToolboxCapabilityError,
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
    execute_capability,
)

BASE_URL = "http://toolbox.test"
OCR_ROUTE = f"{BASE_URL}/v1/capabilities/document.ocr:execute"
SUCCEEDED = {"status": "succeeded", "document": {}}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("capability_id", "message"),
    [
        ("music.omr", "não registrada"),
        ("dataset.sync", "não é executada via :execute"),
    ],
)
async def test_refuses_capabilities_outside_the_allowlist(
    capability_id: str, message: str
) -> None:
    with respx.mock(assert_all_called=False) as router:
        route = router.post(url__regex=r".*")
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(ToolboxCapabilityError, match=message):
                await execute_capability(
                    http,
                    capability_id,
                    provider="any",
                    upload=("x.txt", b"x", "text/plain"),
                )
        assert not route.called


@pytest.mark.asyncio
async def test_requires_an_input() -> None:
    async with httpx.AsyncClient(base_url=BASE_URL) as http:
        with pytest.raises(ValueError, match="file_path ou artifact_id"):
            await execute_capability(http, "document.ocr", provider="p")


@pytest.mark.asyncio
async def test_artifact_request_sends_form_fields() -> None:
    with respx.mock() as router:
        route = router.post(OCR_ROUTE).mock(
            return_value=httpx.Response(200, json=SUCCEEDED)
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            await execute_capability(
                http,
                "document.ocr",
                provider="docling-ocr",
                artifact_id="a1",
                language="pt-BR",
                parameters={"force_ocr": True},
                no_cache=True,
            )
    body = route.calls.last.request.content.decode()
    form = dict(item.split("=", 1) for item in body.split("&"))
    assert form["artifact_id"] == "a1"
    assert form["provider"] == "docling-ocr"
    assert form["language"] == "pt-BR"
    assert form["no_cache"] == "true"
    # The exact contract version the SDK was written against.
    assert form["version"] == str(TOOLBOX_CAPABILITIES["document.ocr"].contract_version)
    assert json.loads(httpx.QueryParams(body)["parameters"]) == {"force_ocr": True}


@pytest.mark.asyncio
async def test_file_upload_uses_the_extension_media_type(tmp_path: Path) -> None:
    source = tmp_path / "page.png"
    source.write_bytes(b"\x89PNG")
    with respx.mock() as router:
        route = router.post(OCR_ROUTE).mock(
            return_value=httpx.Response(200, json=SUCCEEDED)
        )
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            await execute_capability(
                http, "document.ocr", provider="p", file_path=source
            )
    body = route.calls.last.request.content
    assert b'filename="page.png"' in body
    assert b"Content-Type: image/png" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "error", "message"),
    [
        (httpx.Response(200, text="<html>proxy</html>"), ToolboxContractViolation, "JSON válido"),
        (httpx.Response(200, json=["x"]), ToolboxContractViolation, "objeto JSON"),
        (httpx.Response(200, json={"status": "failed"}), ToolboxContractViolation, "OCR falhou"),
        (httpx.Response(401, json={"detail": "no"}), ToolboxAuthenticationError, "Autenticação"),
        (httpx.Response(404, json={"detail": "x"}), ToolboxArtifactNotFound, "não encontrado"),
        (httpx.Response(503, json={"detail": "x"}), ToolboxProviderUnavailable, "indisponível"),
    ],
)
async def test_maps_failures_to_toolbox_errors(response, error, message) -> None:
    with respx.mock() as router:
        router.post(OCR_ROUTE).mock(return_value=response)
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(error, match=message):
                await execute_capability(
                    http, "document.ocr", provider="p", artifact_id="a1"
                )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("side_effect", "error"),
    [
        (httpx.ReadTimeout("slow"), ToolboxTimeout),
        (httpx.ConnectError("refused"), ToolboxProviderUnavailable),
    ],
)
async def test_maps_transport_failures(side_effect, error) -> None:
    with respx.mock() as router:
        router.post(OCR_ROUTE).mock(side_effect=side_effect)
        async with httpx.AsyncClient(base_url=BASE_URL) as http:
            with pytest.raises(error):
                await execute_capability(
                    http, "document.ocr", provider="p", artifact_id="a1"
                )


class _OcrClient(ToolboxCapabilityClient):
    provider_key = "toolbox_ocr_provider"


@pytest.mark.asyncio
async def test_client_uses_the_registry_default_and_sends_the_key() -> None:
    client = _OcrClient(base_url=BASE_URL + "/", api_key="secret")
    try:
        assert client.base_url == BASE_URL
        assert client.provider == "docling-ocr"
        with respx.mock() as router:
            route = router.post(OCR_ROUTE).mock(
                return_value=httpx.Response(200, json=SUCCEEDED)
            )
            await client._execute("document.ocr", artifact_id="a1")
        request = route.calls.last.request
        assert request.headers["Authorization"] == "Bearer secret"
        assert b"provider=docling-ocr" in request.content
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_client_without_key_sends_no_authorization() -> None:
    client = _OcrClient(base_url=BASE_URL, provider="mineru-ocr")
    try:
        with respx.mock() as router:
            route = router.post(OCR_ROUTE).mock(
                return_value=httpx.Response(200, json=SUCCEEDED)
            )
            await client._execute("document.ocr", artifact_id="a1")
        assert "Authorization" not in route.calls.last.request.headers
    finally:
        await client.close()


def test_registry_ids_are_unique_and_versioned() -> None:
    assert all(spec.contract_version >= 1 for spec in TOOLBOX_CAPABILITIES.values())
    assert all(spec.id == key for key, spec in TOOLBOX_CAPABILITIES.items())
