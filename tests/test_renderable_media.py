"""Which sources ``pdf.render@2`` opens (#402).

Characterization written on develop before the set of renderable media types
moved to the SDK, next to ``ToolboxPdfClient.render``. The render adapter
refuses the others before any request, and the two formula steps that need a
crop skip a source the Toolbox cannot render.
"""

from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.agents import pddl_orchestrator as pddl
from backend.core.pipeline.handlers import inspection as inspection_handlers
from tests.pddl_support import build_element, build_manifest, build_obligation


def _jpeg() -> bytes:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 40, 30), False)
    pixmap.clear_with(200)
    return pixmap.tobytes("jpg")


def test_a_jpeg_source_is_rendered(fake_toolbox_render, tmp_path) -> None:
    image = tmp_path / "scan.jpg"
    image.write_bytes(_jpeg())

    assert inspection_handlers._render_source_page(image, "image/jpeg", 1).startswith(b"\x89PNG")
    assert fake_toolbox_render.requests[-1]["media_type"] == "image/jpeg"


@pytest.mark.parametrize("suffix, media_type", [(".gif", "image/gif"), (".bmp", "image/bmp")])
def test_other_rasters_are_refused_before_any_request(fake_toolbox_render, tmp_path, suffix, media_type) -> None:
    image = tmp_path / f"scan{suffix}"
    image.write_bytes(b"raster")

    with pytest.raises(ValueError, match=f"renders PDF, PNG and JPEG inputs, not {media_type}"):
        inspection_handlers._render_source_page(image, media_type, 1)
    assert not fake_toolbox_render.requests


def _formula_manifest(media_type: str):
    element = build_element("f1", "formula", text="placeholder")
    obligation = build_obligation("verbalize-formula", [element.id], ["mathml", "human-review"])
    manifest = build_manifest([element], [obligation])
    manifest.source.media_type = media_type
    return manifest


def _record_crops(monkeypatch) -> list:
    crops: list = []

    def crop(*args, **kwargs):
        crops.append(args)
        return None, 0

    monkeypatch.setattr(pddl, "_formula_recognition_crop", crop)
    return crops


DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", [DOCX, "image/tiff"])
async def test_the_formula_steps_skip_a_source_the_toolbox_cannot_render(monkeypatch, media_type) -> None:
    crops = _record_crops(monkeypatch)
    manifest = _formula_manifest(media_type)
    breaker = pddl.ProviderBreaker(3)

    await pddl._classify_formula_regions(manifest, Path("source.x"), mode="medio", breaker=breaker)
    await pddl._enrich_formula_latex(manifest, Path("source.x"), mode="medio", breaker=breaker)

    assert crops == []
    assert manifest.elements[0].text == "placeholder"


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", ["application/pdf", "image/png", "image/jpeg"])
async def test_the_formula_classification_asks_for_a_crop_of_a_renderable_source(monkeypatch, media_type) -> None:
    crops = _record_crops(monkeypatch)
    manifest = _formula_manifest(media_type)

    await pddl._classify_formula_regions(manifest, Path("source.x"), mode="medio",
                                         breaker=pddl.ProviderBreaker(3))

    assert len(crops) == 1
