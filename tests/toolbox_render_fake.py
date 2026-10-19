"""A fake ``pdf.render@2`` over mocked HTTP, for tests that render real pages.

Production code never renders locally (docs/adr/0003): pages and regions go to
the Toolbox through the SDK. These tests still want real pixels, so the fake
answers the Toolbox routes and renders with PyMuPDF here, following the same
contract as the Toolbox provider (clip origin conversion, intersection,
``max_side``, the 20 MP limit, refusals as HTTP 422). It also records every
request, so tests can check what the core asked for.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import default as email_policy
from typing import Any

import fitz
import httpx
import pytest
import respx

BASE_URL = "http://toolbox-render.test"
EXECUTE = f"{BASE_URL}/v1/capabilities/pdf.render:execute"
MAX_RENDER_PIXELS = 20_000_000
FILETYPES = {"application/pdf": "pdf", "image/png": "png", "image/jpeg": "jpeg"}


@dataclass
class FakeRender:
    """Requests received, as ``{"parameters", "version", "media_type", "artifact_id"}``."""

    requests: list[dict[str, Any]] = field(default_factory=list)
    stored: dict[str, bytes] = field(default_factory=dict)
    #: Source documents the Toolbox already holds, by artifact id.
    sources: dict[str, tuple[bytes, str]] = field(default_factory=dict)

    @property
    def parameters(self) -> list[dict[str, Any]]:
        return [request["parameters"] for request in self.requests]


def _form(request: httpx.Request) -> dict[str, tuple[bytes, str | None]]:
    content_type = request.headers["content-type"]
    if content_type.startswith("multipart/form-data"):
        message = BytesParser(policy=email_policy).parsebytes(
            f"Content-Type: {content_type}\r\n\r\n".encode() + request.content
        )
        return {
            part.get_param("name", header="content-disposition"): (
                part.get_payload(decode=True),
                part.get_content_type() if part.get_filename() else None,
            )
            for part in message.iter_parts()
        }
    fields = httpx.QueryParams(request.content.decode())
    return {key: (value.encode(), None) for key, value in fields.items()}


def _refuse(detail: str) -> httpx.Response:
    return httpx.Response(422, json={"detail": detail})


def _render(fake: FakeRender, request: httpx.Request) -> httpx.Response:
    form = _form(request)
    version = form.get("version", (b"", None))[0].decode()
    parameters = json.loads(form.get("parameters", (b"{}", None))[0])
    artifact_id = form.get("artifact_id", (b"", None))[0].decode() or None
    if artifact_id:
        if artifact_id not in fake.sources:
            return httpx.Response(404, json={"detail": f"artifact {artifact_id} not found"})
        payload, media_type = fake.sources[artifact_id]
    else:
        payload, media_type = form["file"]
    fake.requests.append(
        {"parameters": parameters, "version": version, "media_type": media_type,
         "artifact_id": artifact_id}
    )
    if version != "2":
        return _refuse(f"expected pdf.render@2, got version {version!r}")

    page_number = parameters.get("page_number", 1)
    dpi = parameters.get("dpi", 150)
    max_side = parameters.get("max_side")
    try:
        doc = fitz.open(stream=payload, filetype=FILETYPES[media_type])
    except Exception as error:  # noqa: BLE001 - mirror the Toolbox refusal
        return _refuse(f"cannot open the input: {error}")
    try:
        if not 1 <= page_number <= len(doc):
            return _refuse(f"page {page_number} out of range (1-{len(doc)})")
        page = doc[page_number - 1]
        rect = page.rect
        clip = parameters.get("clip")
        if clip is not None:
            values = [float(clip[key]) for key in ("left", "top", "right", "bottom")]
            if not all(math.isfinite(value) for value in values):
                return _refuse("clip coordinates must be finite")
            left, top, right, bottom = values
            if clip.get("origin", "TOPLEFT") == "BOTTOMLEFT":
                top, bottom = page.rect.height - top, page.rect.height - bottom
            rect = fitz.Rect(
                min(left, right), min(top, bottom), max(left, right), max(top, bottom)
            ) & page.rect
            if rect.is_empty or rect.width < 1 or rect.height < 1:
                return _refuse("clip does not intersect the page")
        scale = dpi / 72
        if max_side is not None:
            scale = min(scale, max_side / max(rect.width, rect.height))
        if rect.width * scale * rect.height * scale > MAX_RENDER_PIXELS:
            return _refuse(f"render exceeds {MAX_RENDER_PIXELS} pixels; lower dpi or set max_side")
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        png = pix.tobytes("png")
        artifact = "sha256:" + hashlib.sha256(png).hexdigest()
        fake.stored[artifact] = png
        document = {
            "artifact_id": artifact,
            "media_type": "image/png",
            "size_bytes": len(png),
            "page_number": page_number,
            "page_count": len(doc),
            "page_width": page.rect.width,
            "page_height": page.rect.height,
            "clip": {"left": rect.x0, "top": rect.y0, "right": rect.x1, "bottom": rect.y1},
            "scale": scale,
            "dpi": scale * 72,
            "width_px": pix.width,
            "height_px": pix.height,
            "source_media_type": media_type,
            "source_filename": "source",
        }
    finally:
        doc.close()
    return httpx.Response(
        200,
        json={"status": "succeeded", "capability": "pdf.render@2", "document": document},
    )


def _artifact(fake: FakeRender, request: httpx.Request) -> httpx.Response:
    artifact_id = request.url.path.rsplit("/", 1)[-1]
    content = fake.stored.get(artifact_id)
    if content is None:
        return httpx.Response(404, json={"detail": "artifact not found"})
    return httpx.Response(200, content=content)


@pytest.fixture
def fake_toolbox_render(monkeypatch):
    """Route the core's Toolbox clients to the fake renderer for one test."""
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "toolbox_base_url", BASE_URL)
    monkeypatch.setattr(settings, "toolbox_base_urls", "")
    monkeypatch.setattr(settings, "toolbox_api_key", "")
    monkeypatch.setattr(settings, "toolbox_retries", 0)
    fake = FakeRender()
    with respx.mock(assert_all_called=False) as router:
        router.post(EXECUTE).mock(side_effect=lambda request: _render(fake, request))
        router.get(url__regex=rf"{BASE_URL}/v1/artifacts/.+").mock(
            side_effect=lambda request: _artifact(fake, request)
        )
        # The availability gate reads the catalogue before planning.
        router.get(f"{BASE_URL}/v1/capabilities").mock(
            return_value=httpx.Response(200, json=[{"id": "pdf.render", "version": 2}])
        )
        router.get(f"{BASE_URL}/v1/providers").mock(
            return_value=httpx.Response(
                200, json=[{"id": "pymupdf-pdf", "capabilities": ["pdf.render"]}]
            )
        )
        yield fake
