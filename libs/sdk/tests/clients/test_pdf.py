"""Testes para o ToolboxPdfClient.

Usa resp HTTPX mockadas para validar URLs, parâmetros, timeout e parsing de erro.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import pytest

from acessilia_sdk.toolbox import (
    ToolboxContractViolation,
    ToolboxProviderUnavailable,
    ToolboxTimeout,
)
from acessilia_sdk.toolbox.clients.pdf import ToolboxPdfClient

FIXTURE_PDF = Path(__file__).parent / "fixtures" / "sample.pdf"

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

PNG = b"\x89PNG\r\n\x1a\nrendered-page"
PNG_ID = "sha256:" + hashlib.sha256(PNG).hexdigest()
SAMPLE_RENDER_RESPONSE = {
    "status": "succeeded",
    "capability": "pdf.render@2",
    "provider": "pymupdf-pdf",
    "document": {
        "artifact_id": PNG_ID,
        "media_type": "image/png",
        "size_bytes": len(PNG),
        "page_number": 1,
        "page_count": 3,
        "page_width": 595,
        "page_height": 842,
        "clip": {"left": 0, "top": 0, "right": 595, "bottom": 842},
        "scale": 2.0,
        "dpi": 144.0,
        "width_px": 1190,
        "height_px": 1684,
        "source_media_type": "application/pdf",
        "source_filename": "sample.pdf",
    },
    "provenance": {"duration_ms": 300, "provider_version": "1.28.2"},
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


def _mock_render(respx_mock, response=None):
    route = respx_mock.post("http://localhost:8002/v1/capabilities/pdf.render:execute")
    route.return_value = httpx.Response(200, json=response or SAMPLE_RENDER_RESPONSE)
    respx_mock.get(f"http://localhost:8002/v1/artifacts/{PNG_ID}").mock(
        return_value=httpx.Response(200, content=PNG)
    )
    return route


def _form_parameters(route) -> dict:
    import json
    from urllib.parse import parse_qs

    body = route.calls.last.request.content
    if b"Content-Disposition" in body:
        part = body.split(b'name="parameters"', 1)[1].split(b"\r\n\r\n", 1)[1]
        return json.loads(part.split(b"\r\n", 1)[0])
    return json.loads(parse_qs(body.decode())["parameters"][0])


@pytest.mark.asyncio
async def test_render_returns_the_verified_png_and_the_applied_transformation(
    respx_mock, client
):
    route = _mock_render(respx_mock)

    page = await client.render(file_path=FIXTURE_PDF, page_number=1)

    assert page.image == PNG
    assert page.clip == (0.0, 0.0, 595.0, 842.0)
    assert page.page_count == 3
    assert page.document["scale"] == 2.0
    # The version field itself is covered by test_transport.
    assert _form_parameters(route) == {"page_number": 1, "dpi": 150}


@pytest.mark.asyncio
async def test_render_sends_clip_and_max_side(respx_mock, client):
    route = _mock_render(
        respx_mock,
        {**SAMPLE_RENDER_RESPONSE, "document": {**SAMPLE_RENDER_RESPONSE["document"], "page_number": 2}},
    )

    await client.render(
        artifact_id="sha256:" + "a" * 64,
        page_number=2,
        dpi=160,
        max_side=1600,
        clip=(10, 80, 90, 30),
        clip_origin="BOTTOMLEFT",
    )

    assert _form_parameters(route) == {
        "page_number": 2,
        "dpi": 160,
        "max_side": 1600,
        "clip": {"left": 10, "top": 80, "right": 90, "bottom": 30, "origin": "BOTTOMLEFT"},
    }


_DOCUMENT = SAMPLE_RENDER_RESPONSE["document"]


def _without(key: str) -> dict:
    return {k: v for k, v in _DOCUMENT.items() if k != key}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("document", "message"),
    [
        ({**_DOCUMENT, "media_type": "image/jpeg"}, "not image/png"),
        (_without("artifact_id"), "no image artifact"),
        (_without("clip"), "applied clip"),
        ({**_DOCUMENT, "clip": {"left": 0, "top": 0, "right": 595}}, "applied clip"),
        ({**_DOCUMENT, "clip": {**_DOCUMENT["clip"], "bottom": None}}, "applied clip"),
        ({**_DOCUMENT, "clip": {**_DOCUMENT["clip"], "bottom": "842"}}, "applied clip"),
        (
            {**_DOCUMENT, "clip": {**_DOCUMENT["clip"], "origin": "BOTTOMLEFT"}},
            "applied clip",
        ),
        ({**_DOCUMENT, "page_number": 2}, "rendered page 2"),
        (_without("page_count"), "page_count"),
        ({**_DOCUMENT, "size_bytes": len(PNG) + 1}, "bytes"),
    ],
)
async def test_render_rejects_a_result_outside_the_v2_contract(
    respx_mock, client, document, message
):
    _mock_render(respx_mock, {**SAMPLE_RENDER_RESPONSE, "document": document})
    with pytest.raises(ToolboxContractViolation, match=message):
        await client.render(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_render_refuses_an_oversized_png(respx_mock, client, monkeypatch):
    import functools

    from acessilia_sdk.toolbox.clients import pdf

    monkeypatch.setattr(pdf, "read_artifact", functools.partial(pdf.read_artifact, max_bytes=4))
    _mock_render(respx_mock)
    with pytest.raises(ToolboxContractViolation, match="exceeds 4 bytes"):
        await client.render(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_render_rejects_a_tampered_png(respx_mock, client):
    _mock_render(respx_mock)
    respx_mock.get(f"http://localhost:8002/v1/artifacts/{PNG_ID}").mock(
        return_value=httpx.Response(200, content=PNG + b"x")
    )
    with pytest.raises(ToolboxContractViolation, match="does not match"):
        await client.render(file_path=FIXTURE_PDF)


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

# ---------------------------------------------------------------------------
# document.text.spans
# ---------------------------------------------------------------------------

SAMPLE_SPANS_RESPONSE = {
    "status": "succeeded",
    "capability": "document.text.spans",
    "provider": "pymupdf-pdf",
    "document": {
        "page_count": 3,
        "coord_origin": "TOPLEFT",
        "pages": [
            {
                "page_number": 2, "width": 612.0, "height": 792.0, "rotation": 0,
                "lines": [{"bbox": [64.9, 214.0, 532.7, 230.8], "spans": [
                    {"text": "s", "font": "CMMI12", "size": 11.96, "flags": 4,
                     "bbox": [498.96, 216.99, 504.47, 228.95], "origin": [498.96, 225.96]},
                ]}],
            }
        ],
    },
}


def _mock_spans(respx_mock, response=None):
    route = respx_mock.post("http://localhost:8002/v1/capabilities/document.text.spans:execute")
    route.return_value = httpx.Response(200, json=response or SAMPLE_SPANS_RESPONSE)
    return route


@pytest.mark.asyncio
async def test_text_spans_sends_the_pages_and_returns_the_document(respx_mock, client):
    route = _mock_spans(respx_mock)

    document = await client.text_spans(file_path=FIXTURE_PDF, pages=[2])

    assert document["pages"][0]["lines"][0]["spans"][0]["font"] == "CMMI12"
    assert _form_parameters(route) == {"pages": [2]}


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ["text", "font", "size", "bbox", "origin"])
async def test_text_spans_refuses_a_malformed_span(respx_mock, client, missing):
    page = SAMPLE_SPANS_RESPONSE["document"]["pages"][0]
    span = {key: value for key, value in page["lines"][0]["spans"][0].items() if key != missing}
    malformed = {**page, "lines": [{**page["lines"][0], "spans": [span]}]}
    _mock_spans(
        respx_mock,
        {**SAMPLE_SPANS_RESPONSE, "document": {**SAMPLE_SPANS_RESPONSE["document"], "pages": [malformed]}},
    )

    with pytest.raises(ToolboxContractViolation):
        await client.text_spans(file_path=FIXTURE_PDF)


@pytest.mark.asyncio
async def test_text_spans_refuses_another_coordinate_origin(respx_mock, client):
    _mock_spans(
        respx_mock,
        {**SAMPLE_SPANS_RESPONSE, "document": {**SAMPLE_SPANS_RESPONSE["document"], "coord_origin": "BOTTOMLEFT"}},
    )

    with pytest.raises(ToolboxContractViolation):
        await client.text_spans(file_path=FIXTURE_PDF)
