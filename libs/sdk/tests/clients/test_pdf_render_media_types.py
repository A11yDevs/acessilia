"""The inputs ``pdf.render@2`` opens (#402)."""

from __future__ import annotations

from pathlib import Path

import acessilia_sdk.toolbox.clients.pdf as pdf
from acessilia_sdk.toolbox.transport import media_type_for


def test_pdf_png_and_jpeg_are_rendered_and_exported() -> None:
    assert pdf.RENDER_MEDIA_TYPES == frozenset({"application/pdf", "image/png", "image/jpeg"})
    assert "RENDER_MEDIA_TYPES" in pdf.__all__


def test_every_suffix_the_transport_labels_as_renderable_is_listed() -> None:
    for suffix in (".pdf", ".png", ".jpg", ".jpeg"):
        assert media_type_for(Path(f"page{suffix}")) in pdf.RENDER_MEDIA_TYPES
    for suffix in (".tif", ".tiff", ".bmp", ".gif", ".webp"):
        assert media_type_for(Path(f"page{suffix}")) not in pdf.RENDER_MEDIA_TYPES
