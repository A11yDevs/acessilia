from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from backend.core.manifest.pymupdf_extractor import PyMuPDFManifestExtractor


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
