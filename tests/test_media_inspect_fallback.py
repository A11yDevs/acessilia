"""Testes do fallback local determinístico de media.inspect.

Cobre a classificação de imagens raster, páginas escaneadas, PDF multi-página
e payloads indecifráveis (que nunca devem ser "adivinhados").
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from backend.tools.media_inspect import (
    inspect_media_payload,
    inspect_source_media,
)


def png_bytes(width: int, height: int, mode: str = "L") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, (width, height)).save(buf, format="PNG")
    return buf.getvalue()


def test_standalone_image_requires_visual_inspection() -> None:
    result = inspect_media_payload(
        png_bytes(1280, 720),
        "mapa.png",
        "image/png",
    )

    assert result["is_image"] is True
    assert result["artifact_nature"] == "standalone_image"
    assert result["requires_visual_inspection"] is True
    assert result["media_type"] == "image/png"
    assert result["dimensions"]["width"] == 1280
    assert result["dimensions"]["aspect_ratio"] == pytest.approx(1.7778)


def test_portrait_image_requires_visual_inspection_without_content_evidence() -> None:
    # A geometria de uma página A4 não distingue um scan de um infográfico.
    result = inspect_media_payload(
        png_bytes(595, 842),
        "pagina.png",
        "image/png",
    )

    assert result["artifact_nature"] == "standalone_image"
    assert result["requires_visual_inspection"] is True


def test_tiny_thumbnail_is_standalone_image() -> None:
    # Imagens de um único frame são inspecionadas independentemente do tamanho.
    result = inspect_media_payload(
        png_bytes(60, 85),
        "thumb.png",
        "image/png",
    )

    assert result["artifact_nature"] == "standalone_image"
    assert result["requires_visual_inspection"] is True


def test_undecodable_payload_is_unknown_without_guessing() -> None:
    result = inspect_media_payload(
        b"not an image",
        "page.png",
        "image/png",
    )

    assert result["artifact_nature"] == "unknown"
    assert result["dimensions"] is None
    assert result["media_type"] == "application/octet-stream"
    assert result["declared_media_type"] == "image/png"
    assert result["requires_visual_inspection"] is False


def test_real_pdf_is_reported_as_paginated_document() -> None:
    pdf_path = Path(__file__).parent / "fixtures" / "tutorials" / "java-oo-3pgs.pdf"
    payload = pdf_path.read_bytes()
    result = inspect_media_payload(payload, "java-oo-3pgs.pdf", "application/pdf")

    assert result["is_pdf"] is True
    assert result["artifact_nature"] == "paginated_document"
    assert result["page_count"] >= 2
    assert result["requires_visual_inspection"] is False


def test_image_is_detected_from_payload_not_extension() -> None:
    result = inspect_media_payload(
        png_bytes(200, 200),
        "disfarce.txt",
        "text/plain",
    )

    assert result["is_image"] is True
    assert result["media_type"] == "image/png"


@pytest.mark.asyncio
async def test_inspect_source_media_falls_back_to_local(monkeypatch) -> None:
    from backend.config import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "toolbox_media_inspect_enabled", False)

    result = await inspect_source_media(
        Path(__file__).parent / "fixtures" / "images" / "sunset-skyline.jpeg"
    )

    assert result is not None
    assert result["is_image"] is True
    assert result["requires_visual_inspection"] is True


@pytest.mark.asyncio
async def test_inspect_source_media_falls_back_after_toolbox_contract_error(
    monkeypatch,
) -> None:
    from backend.config import settings as settings_module
    from backend.tools.toolbox_client import ToolboxContractViolation

    monkeypatch.setattr(settings_module.settings, "toolbox_media_inspect_enabled", True)

    class InvalidResponseClient:
        async def inspect(self, **_kwargs):
            raise ToolboxContractViolation("invalid response")

        async def close(self):
            pass

    result = await inspect_source_media(
        Path(__file__).parent / "fixtures" / "images" / "sunset-skyline.jpeg",
        client=InvalidResponseClient(),
    )

    assert result is not None
    assert result["is_image"] is True
    assert result["requires_visual_inspection"] is True


@pytest.mark.asyncio
async def test_inspect_source_media_returns_none_for_missing_file() -> None:
    result = await inspect_source_media(Path("/tmp/nao-existe.png"))
    assert result is None
