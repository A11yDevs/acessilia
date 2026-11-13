"""The crop a formula is recognized from, observed at the Toolbox's HTTP contract.

``_formula_recognition_crop`` is the core's policy around the render: a saved
``region_crop`` is reused, a formula without a page or a usable box is not
rendered (never the whole page), a source ``pdf.render@2`` cannot open is
refused before any request, and a failed render leaves the formula without a
crop instead of failing the job. The render itself (200 dpi, the box as the
clip, a sliver is no crop) is what the request and the answer show, whichever
module sends them.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import fitz
import pytest
from loguru import logger

from backend.agents import pddl_orchestrator as pddl
from backend.core.pipeline.enrichment import formulas as formula_stage
from backend.core.manifest.models import BoundingBox, ManifestElement, Provenance
from tests.pddl_support import build_element

UNKNOWN_SOURCE = "sha256:" + "0" * 64


@pytest.fixture
def pdf(tmp_path: Path) -> Path:
    path = tmp_path / "doc.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((20, 50), "E = mc2", fontsize=24)
    document.save(path)
    document.close()
    return path


def _formula(
    *, page_number: int = 1, box=(10, 20, 110, 70), origin: str = "TOPLEFT"
) -> ManifestElement:
    element = build_element("formula-0", "formula")
    bbox = None
    if box is not None:
        left, top, right, bottom = box
        bbox = BoundingBox(left=left, top=top, right=right, bottom=bottom, coord_origin=origin)
    element.provenance = [Provenance(page_number=page_number, bbox=bbox)]
    return element


def test_the_box_is_rendered_at_200_dpi(fake_toolbox_render, pdf) -> None:
    image, page_number = formula_stage._formula_recognition_crop(
        pdf, _formula(), media_type="application/pdf"
    )

    assert page_number == 1
    assert image is not None and image.startswith(b"\x89PNG")
    assert fake_toolbox_render.parameters == [
        {
            "page_number": 1,
            "dpi": 200,
            "clip": {"left": 10.0, "top": 20.0, "right": 110.0, "bottom": 70.0, "origin": "TOPLEFT"},
        }
    ]
    assert fake_toolbox_render.requests[-1]["media_type"] == "application/pdf"


def test_a_bottom_left_box_is_sent_with_its_origin(fake_toolbox_render, pdf) -> None:
    image, _ = formula_stage._formula_recognition_crop(pdf, _formula(box=(10, 822, 110, 772), origin="BOTTOMLEFT"))

    assert image is not None
    assert fake_toolbox_render.parameters[-1]["clip"]["origin"] == "BOTTOMLEFT"


def test_a_stored_source_is_referenced_instead_of_uploaded(fake_toolbox_render, pdf) -> None:
    stored = "sha256:" + hashlib.sha256(pdf.read_bytes()).hexdigest()
    fake_toolbox_render.sources[stored] = (pdf.read_bytes(), "application/pdf")

    image, _ = formula_stage._formula_recognition_crop(pdf, _formula(), artifact_id=stored)

    assert image is not None
    assert [request["artifact_id"] for request in fake_toolbox_render.requests] == [stored]


def test_a_source_the_toolbox_lost_is_sent_again(fake_toolbox_render, pdf) -> None:
    """The fake records only the requests it serves: the resent file is the one."""
    image, _ = formula_stage._formula_recognition_crop(pdf, _formula(), artifact_id=UNKNOWN_SOURCE)

    assert image is not None
    assert [request["artifact_id"] for request in fake_toolbox_render.requests] == [None]


def test_a_saved_region_crop_is_reused_without_a_render(fake_toolbox_render, pdf, tmp_path) -> None:
    saved = tmp_path / "crop.png"
    saved.write_bytes(b"saved-crop")
    element = _formula()
    element.metadata["region_crop"] = str(saved)

    assert formula_stage._formula_recognition_crop(pdf, element) == (b"saved-crop", 1)
    assert fake_toolbox_render.requests == []


def test_an_unreadable_saved_crop_falls_back_to_the_render(fake_toolbox_render, pdf, tmp_path) -> None:
    element = _formula()
    element.metadata["region_crop"] = str(tmp_path / "missing.png")

    image, page_number = formula_stage._formula_recognition_crop(pdf, element)

    assert image is not None and page_number == 1
    assert len(fake_toolbox_render.requests) == 1


def test_a_formula_without_a_page_is_not_rendered(fake_toolbox_render, pdf) -> None:
    element = build_element("formula-0", "formula")
    element.page_number = None

    assert formula_stage._formula_recognition_crop(pdf, element) == (None, 0)
    assert fake_toolbox_render.requests == []


@pytest.mark.parametrize("box", [None, (math.nan, 20, 110, 70), (10, math.inf, 110, 70)])
def test_a_formula_without_a_usable_box_is_not_rendered(fake_toolbox_render, pdf, box) -> None:
    """Never the whole page: a recognizer would invent a formula from prose."""
    assert formula_stage._formula_recognition_crop(pdf, _formula(box=box)) == (None, 1)
    assert fake_toolbox_render.requests == []


@pytest.mark.parametrize("box", [None, (math.nan, 20, 110, 70)])
@pytest.mark.parametrize(
    ("name", "media_type"), [("doc.docx", None), ("scan.gif", None), ("doc.pdf", "image/png")]
)
def test_an_unusable_box_is_silent_whatever_the_source(
    fake_toolbox_render, tmp_path, pdf, box, name, media_type
) -> None:
    """The box is checked before the source: no request and no warning (as on develop)."""
    source = tmp_path / name
    source.write_bytes(pdf.read_bytes())
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        result = formula_stage._formula_recognition_crop(source, _formula(box=box), media_type=media_type)
    finally:
        logger.remove(sink)

    assert result == (None, 1)
    assert fake_toolbox_render.requests == []
    assert messages == []


def test_a_sliver_of_a_region_is_not_a_formula_crop(fake_toolbox_render, pdf) -> None:
    assert formula_stage._formula_recognition_crop(pdf, _formula(box=(10, 20, 12, 70))) == (None, 1)
    assert len(fake_toolbox_render.requests) == 1


def test_a_refused_render_leaves_the_formula_without_a_crop(fake_toolbox_render, pdf) -> None:
    """A box outside the page: the Toolbox refuses it, the job goes on."""
    element = _formula(box=(700, 900, 800, 950))

    assert formula_stage._formula_recognition_crop(pdf, element) == (None, 1)
    assert len(fake_toolbox_render.requests) == 1


def test_a_failed_render_is_logged(fake_toolbox_render, pdf) -> None:
    messages: list[str] = []
    sink = logger.add(messages.append, level="WARNING", format="{message}")
    try:
        formula_stage._formula_recognition_crop(pdf, _formula(box=(700, 900, 800, 950)))
    finally:
        logger.remove(sink)

    assert any(message.startswith("Formula crop failed for formula-0") for message in messages)


@pytest.mark.parametrize(
    ("name", "media_type"),
    [("doc.pdf", "image/png"), ("scan.gif", "image/gif"), ("doc.docx", None)],
)
def test_a_source_the_render_cannot_open_is_refused_before_any_request(
    fake_toolbox_render, tmp_path, pdf, name, media_type
) -> None:
    source = tmp_path / name
    source.write_bytes(pdf.read_bytes())

    assert formula_stage._formula_recognition_crop(source, _formula(), media_type=media_type) == (None, 1)
    assert fake_toolbox_render.requests == []
