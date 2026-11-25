"""The inputs ``pdf.render@2`` opens, pre-validation, and image downscaling (#402, #612)."""

from __future__ import annotations

import hashlib
import json
import struct
import zlib
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from acessilia_sdk.toolbox import ToolboxProviderUnavailable
from acessilia_sdk.toolbox.clients import pdf
from acessilia_sdk.toolbox.clients.pdf import (
    ToolboxPdfClient,
    check_renderable,
    downscale_image,
)
from acessilia_sdk.toolbox.transport import media_type_for

BASE = "http://toolbox.test"


def _minimal_png(width: int, height: int) -> bytes:
    """Build a valid PNG header carrying ``width`` x ``height`` in its IHDR chunk."""
    ihdr_data = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    ihdr_crc = zlib.crc32(b"IHDR" + ihdr_data) & 0xFFFFFFFF
    ihdr = struct.pack(">I", len(ihdr_data)) + b"IHDR" + ihdr_data + struct.pack(">I", ihdr_crc)
    iend_crc = zlib.crc32(b"IEND") & 0xFFFFFFFF
    iend = struct.pack(">I", 0) + b"IEND" + struct.pack(">I", iend_crc)
    return b"\x89PNG\r\n\x1a\n" + ihdr + iend


def _minimal_jpeg(width: int, height: int) -> bytes:
    """Build a minimal JPEG SOF0 header carrying ``width`` x ``height``."""
    sof0_payload = struct.pack(">BHHB", 8, height, width, 1)
    sof0 = b"\xff\xc0" + struct.pack(">H", len(sof0_payload) + 2) + sof0_payload
    return b"\xff\xd8" + sof0 + b"\xff\xd9"


def _parameters(request: httpx.Request) -> dict:
    body = request.content
    if b"Content-Disposition" in body:
        part = body.split(b'name="parameters"', 1)[1].split(b"\r\n\r\n", 1)[1]
        return json.loads(part.split(b"\r\n", 1)[0])
    return json.loads(parse_qs(body.decode())["parameters"][0])


def _no_cache(request: httpx.Request) -> bool:
    body = request.content
    if b"Content-Disposition" in body:
        return b'name="no_cache"' in body
    return "no_cache" in parse_qs(body.decode())


def _mock_render(respx_mock, out_png: bytes):
    png_id = "sha256:" + hashlib.sha256(out_png).hexdigest()
    route = respx_mock.post(f"{BASE}/v1/capabilities/pdf.render:execute").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "succeeded",
                "capability": "pdf.render@2",
                "provider": "pymupdf-pdf",
                "document": {
                    "artifact_id": png_id,
                    "media_type": "image/png",
                    "size_bytes": len(out_png),
                    "page_number": 1,
                    "page_count": 1,
                    "page_width": 200,
                    "page_height": 120,
                    "clip": {"left": 0, "top": 0, "right": 200, "bottom": 120},
                    "scale": 0.5,
                    "dpi": 150.0,
                    "width_px": 200,
                    "height_px": 120,
                    "source_media_type": "image/png",
                    "source_filename": "image.png",
                },
            },
        )
    )
    respx_mock.get(f"{BASE}/v1/artifacts/{png_id}").mock(
        return_value=httpx.Response(200, content=out_png)
    )
    return route


def test_pdf_png_and_jpeg_are_rendered_and_exported() -> None:
    assert pdf.RENDER_MEDIA_TYPES == frozenset({"application/pdf", "image/png", "image/jpeg"})
    assert "RENDER_MEDIA_TYPES" in pdf.__all__
    assert "check_renderable" in pdf.__all__
    assert "downscale_image" in pdf.__all__
    assert "plan_downscale" in pdf.__all__


def test_every_suffix_the_transport_labels_as_renderable_is_listed() -> None:
    for suffix in (".pdf", ".png", ".jpg", ".jpeg"):
        assert media_type_for(Path(f"page{suffix}")) in pdf.RENDER_MEDIA_TYPES
    for suffix in (".tif", ".tiff", ".bmp", ".gif", ".webp"):
        assert media_type_for(Path(f"page{suffix}")) not in pdf.RENDER_MEDIA_TYPES


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("doc.pdf", "application/pdf"),
        ("scan.png", "image/png"),
        ("photo.jpg", "image/jpeg"),
        ("photo.jpeg", "image/jpeg"),
    ],
)
def test_check_renderable_accepts_supported_sources(filename: str, expected: str) -> None:
    assert check_renderable(Path(filename)) == expected
    assert check_renderable(Path(filename), expected) == expected


def test_check_renderable_rejects_mismatched_media_type() -> None:
    with pytest.raises(ValueError, match="would be sent as application/pdf"):
        check_renderable(Path("doc.pdf"), "image/png")


@pytest.mark.parametrize(
    ("filename", "media_type"),
    [
        ("scan.gif", "image/gif"),
        ("scan.bmp", "image/bmp"),
        ("scan.tiff", "image/tiff"),
        ("scan.webp", "image/webp"),
    ],
)
def test_check_renderable_rejects_non_renderable_rasters(filename: str, media_type: str) -> None:
    with pytest.raises(ValueError, match=f"renders PDF, PNG and JPEG inputs, not {media_type}"):
        check_renderable(Path(filename), media_type)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_filename"),
    [
        (_minimal_png(400, 240), b'filename="image.png"'),
        (_minimal_jpeg(400, 240), b'filename="image.jpg"'),
    ],
    ids=["png", "jpeg"],
)
async def test_downscale_image_scales_longest_side_on_toolbox(
    respx_mock, payload: bytes, expected_filename: bytes
) -> None:
    out_png = _minimal_png(200, 120)
    route = _mock_render(respx_mock, out_png)
    client = ToolboxPdfClient(base_url=BASE, provider="pymupdf-pdf", timeout_seconds=5)
    try:
        result = await downscale_image(client, payload, scale=0.5, use_remote_cache=False)
    finally:
        await client.close()

    assert result == out_png
    req = route.calls.last.request
    assert _parameters(req) == {"page_number": 1, "dpi": 150, "max_side": 200}
    assert expected_filename in req.content
    assert _no_cache(req)


@pytest.mark.asyncio
async def test_downscale_image_returns_none_for_unshrinkable_or_unknown_bytes(respx_mock) -> None:
    route = respx_mock.post(f"{BASE}/v1/capabilities/pdf.render:execute").mock(
        return_value=httpx.Response(500)
    )
    client = ToolboxPdfClient(base_url=BASE, provider="pymupdf-pdf", timeout_seconds=5)
    try:
        assert await downscale_image(client, b"not an image") is None
        assert await downscale_image(client, _minimal_png(1, 1), scale=0.5) is None
        assert await downscale_image(client, _minimal_png(400, 240), scale=1.0) is None
        assert await downscale_image(client, _minimal_png(400, 240), scale=1.5) is None
    finally:
        await client.close()

    assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_scale", [0, -0.5, float("nan"), float("inf"), True])
async def test_downscale_image_rejects_invalid_scale(bad_scale) -> None:
    client = ToolboxPdfClient(base_url=BASE, provider="pymupdf-pdf", timeout_seconds=5)
    try:
        with pytest.raises(ValueError, match="finite positive"):
            await downscale_image(client, _minimal_png(400, 240), scale=bad_scale)
    finally:
        await client.close()


@pytest.mark.parametrize(
    ("payload", "expected"),
    [
        (_minimal_png(400, 240), (200, ".png")),
        (_minimal_jpeg(400, 240), (200, ".jpg")),
        (_minimal_png(240, 400), (200, ".png")),
        (_minimal_png(401, 240), (200, ".png")),
    ],
    ids=["png", "jpeg", "portrait", "truncated"],
)
def test_plan_downscale_reads_the_longest_side_and_the_suffix(payload, expected) -> None:
    """The plan is the render's own ``max_side``, truncating as the render does."""
    assert pdf.plan_downscale(payload) == expected


def test_plan_downscale_declines_unknown_and_unshrinkable_payloads() -> None:
    assert pdf.plan_downscale(b"not an image") is None
    assert pdf.plan_downscale(_minimal_png(400, 240), scale=1.0) is None
    assert pdf.plan_downscale(_minimal_png(400, 240), scale=1.5) is None
    # max(1, int(1 * 0.5)) == 1 is already the longest side: no render helps.
    assert pdf.plan_downscale(_minimal_png(1, 1), scale=0.5) is None


@pytest.mark.parametrize("bad_scale", [0, -0.5, float("nan"), float("inf"), True])
def test_plan_downscale_rejects_invalid_scale(bad_scale) -> None:
    with pytest.raises(ValueError, match="finite positive"):
        pdf.plan_downscale(_minimal_png(400, 240), scale=bad_scale)


@pytest.mark.asyncio
async def test_downscale_image_propagates_toolbox_errors_unchanged(respx_mock) -> None:
    respx_mock.post(f"{BASE}/v1/capabilities/pdf.render:execute").mock(
        return_value=httpx.Response(
            503,
            json={"status": "failed", "error": {"code": "provider_unavailable", "message": "down"}},
        )
    )
    client = ToolboxPdfClient(base_url=BASE, provider="pymupdf-pdf", timeout_seconds=5)
    try:
        with pytest.raises(ToolboxProviderUnavailable):
            await downscale_image(client, _minimal_png(400, 240), scale=0.5)
    finally:
        await client.close()
