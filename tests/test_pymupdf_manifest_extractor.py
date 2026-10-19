from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.core.manifest.pymupdf_extractor import PyMuPDFManifestExtractor
from backend.core.manifest.builder import build_processing_manifest
from backend.core.manifest.models import BoundingBox, Provenance
from backend.agents.pddl_orchestrator import _extract_picture_bytes, _render_inspection_region
from tests.pddl_support import build_element as _element


def _make_sample_pdf(path: Path) -> None:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "CAPÍTULO 1", fontsize=18)
    page.insert_text((72, 120), "Paragrafo simples para manifesto", fontsize=11)
    doc.save(path)
    doc.close()


def test_pymupdf_manifest_extractor_builds_pseudo_document(tmp_path: Path):
    source = tmp_path / "sample.pdf"
    _make_sample_pdf(source)

    extractor = PyMuPDFManifestExtractor()
    extraction = extractor.extract(source)

    assert extraction.configuration["extractor"] == "pymupdf"
    assert build_processing_manifest(source, extraction).extractor.name == "pymupdf"
    assert extraction.duration_ms >= 0
    assert extraction.version.startswith("pymupdf-")

    items = list(extraction.document.iterate_items())
    assert len(items) >= 2  # root + ao menos um bloco de texto
    assert extraction.document.num_pages() == 1
    assert 1 in extraction.document.pages


def test_pymupdf_manifest_extractor_infers_heading(tmp_path: Path):
    source = tmp_path / "sample_heading.pdf"
    _make_sample_pdf(source)

    extractor = PyMuPDFManifestExtractor()
    extraction = extractor.extract(source)

    labels = [
        getattr(getattr(item, "label", None), "value", None)
        for item, _ in extraction.document.iterate_items()
    ]
    assert "heading" in labels


@pytest.mark.parametrize("include_images", [True, False])
@pytest.mark.parametrize("with_text", [True, False])
def test_image_inclusion_matches_configuration(tmp_path, include_images, with_text):
    source = tmp_path / "image.pdf"
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    image.clear_with(0)
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        page.insert_image(fitz.Rect(20, 20, 90, 80), stream=image.tobytes("png"))
        if with_text:
            page.insert_text((20, 95), "Body text")
        pdf.save(source)
    extraction = PyMuPDFManifestExtractor(include_images=include_images).extract(source)
    items = [item for item, _ in extraction.document.iterate_items()]
    pictures = [item for item in items if getattr(getattr(item, "label", None), "value", None) == "picture"]
    assert len(pictures) == int(include_images)
    assert any(getattr(item, "text", "") == "Body text" for item in items) == with_text


def _pixels(png: bytes) -> tuple[int, int, bytes]:
    """Size and samples; the PNG metadata (e.g. resolution) may differ."""
    pixmap = fitz.Pixmap(png)
    return pixmap.width, pixmap.height, pixmap.samples


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
@pytest.mark.parametrize("origin", ["TOPLEFT", "BOTTOMLEFT"])
def test_rotated_picture_provenance_renders_only_source_region(
    tmp_path, rotation, origin, fake_toolbox_render
):
    source = tmp_path / "rotated.pdf"
    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 8, 8), False)
    image.clear_with(0)
    with fitz.open() as pdf:
        page = pdf.new_page(width=200, height=100)
        page.insert_image(fitz.Rect(120, 20, 190, 80), stream=image.tobytes("png"), keep_proportion=False)
        page.insert_text((120, 95), "TARGET", fontsize=10)
        page.set_rotation(rotation)
        pdf.save(source)
    extraction = PyMuPDFManifestExtractor().extract(source)
    items = [item for item, _ in extraction.document.iterate_items()]
    picture = next(item for item in items if getattr(getattr(item, "label", None), "value", None) == "picture")
    with fitz.open(source) as pdf:
        page = pdf[0]
        expected = page.get_image_rects(page.get_images()[0][0])[0] * page.rotation_matrix
        expected_png = page.get_pixmap(clip=expected, dpi=160).tobytes("png")
        # Text and images must both fit the declared, displayed coordinate space.
        for item in items:
            if getattr(item, "prov", None):
                box = item.prov[0].bbox
                assert fitz.Rect(box.l, box.t, box.r, box.b) in page.rect
    box = picture.prov[0].bbox
    assert [box.l, box.t, box.r, box.b] == pytest.approx(list(expected))
    height = extraction.document.pages[1].size.height
    element = _element("picture", "unknown")
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=box.l, right=box.r,
        top=box.t if origin == "TOPLEFT" else height-box.t,
        bottom=box.b if origin == "TOPLEFT" else height-box.b,
        coord_origin=origin,
    ))]
    # Rendered by the Toolbox (pdf.render@2); the fake renders real pixels.
    rendered, number, rectangle = _render_inspection_region(source, element)
    assert number == 1
    assert rectangle == pytest.approx(list(expected))
    assert _pixels(rendered) == _pixels(expected_png)
    enriched, number = _extract_picture_bytes(source, element, 1)
    assert _pixels(enriched) == _pixels(expected_png)
    pixmap = fitz.Pixmap(rendered)
    assert max(pixmap.samples) == 0  # black picture, no white page margin


def _one_page_pdf(path: Path) -> Path:
    with fitz.open() as pdf:
        pdf.new_page(width=200, height=100)
        pdf.save(path)
    return path


def _picture(left, top, right, bottom):
    element = _element("picture", "picture")
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=left, top=top, right=right, bottom=bottom, coord_origin="TOPLEFT",
    ))]
    return element


@pytest.mark.parametrize(
    "box",
    [
        (300, 200, 400, 300),  # outside the page: refused by the Toolbox
        (10, 10, 12, 60),  # a sliver
    ],
)
def test_a_picture_box_that_is_not_a_picture_falls_back_to_the_page(
    tmp_path, fake_toolbox_render, box
):
    source = _one_page_pdf(tmp_path / "doc.pdf")

    image, number = _extract_picture_bytes(source, _picture(*box), 1)

    assert number == 1
    assert fitz.Pixmap(image).width >= 200 * 160 / 72  # the whole page
    first, page = fake_toolbox_render.parameters
    assert "clip" in first and "clip" not in page


def test_a_non_finite_picture_box_renders_the_page_once(tmp_path, fake_toolbox_render):
    source = _one_page_pdf(tmp_path / "doc.pdf")

    image, _ = _extract_picture_bytes(source, _picture(10, float("nan"), 90, 60), 1)

    assert image is not None
    [parameters] = fake_toolbox_render.parameters
    assert "clip" not in parameters


def test_an_unavailable_toolbox_is_not_retried_as_a_page(tmp_path, monkeypatch):
    from acessilia_sdk.toolbox import ToolboxProviderUnavailable

    from backend.agents import pddl_orchestrator as pddl

    attempts = []

    def unavailable(*args, **kwargs):
        attempts.append(kwargs.get("clip"))
        raise ToolboxProviderUnavailable("down")

    monkeypatch.setattr(pddl, "_toolbox_render", unavailable)
    source = _one_page_pdf(tmp_path / "doc.pdf")

    assert _extract_picture_bytes(source, _picture(10, 10, 90, 60), 1) == (None, 1)
    assert attempts == [(10.0, 10.0, 90.0, 60.0)]
