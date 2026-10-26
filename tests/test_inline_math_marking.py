"""The core writes the inline math of PDF prose as $…$ from the text layer's fonts (#265)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.agents import pddl_orchestrator
from backend.core.manifest.models import BoundingBox, PageDescriptor, Provenance
from tests.pddl_support import build_element, build_manifest

HEIGHT = 792.0


def _span(text, font, x, size=11.96, baseline=225.96):
    width = max(len(text), 1) * size * 0.5
    return {
        "text": text, "font": font, "size": size, "flags": 4,
        "bbox": [x, baseline - size * 0.75, x + width, baseline + size * 0.25],
        "origin": [x, baseline],
    }


def _page(*lines):
    return {"page_number": 1, "width": 612.0, "height": HEIGHT, "rotation": 0,
            "lines": [{"bbox": [0, 0, 0, 0], "spans": list(line)} for line in lines]}


PARAGRAPH_LINE = [
    _span("inicial", "CMR12", 60), _span("´e", "CMR12", 110), _span("s", "CMMI12", 130),
    _span("0", "CMR8", 137, size=7.97, baseline=227.76), _span("∈", "CMSY10", 145),
    _span("R", "MSBM10", 155), _span(",", "CMR12", 163), _span("h", "CMMI12", 175),
    _span("̸", "CMSY10", 183), _span("= 0", "CMR12", 183),
]
#: A display formula below the paragraph: its spans must not reach the paragraph.
DISPLAY_LINE = [_span("x", "CMMI12", 200, baseline=300.0), _span("= 1", "CMR12", 210, baseline=300.0)]


def _element(element_id, element_type, text, top, bottom, left=50.0, right=560.0, reading_order=1):
    element = build_element(element_id, element_type, text=text, reading_order=reading_order)
    # Docling boxes come with a bottom-left origin.
    element.provenance = [Provenance(page_number=1, bbox=BoundingBox(
        left=left, top=HEIGHT - top, right=right, bottom=HEIGHT - bottom, coord_origin="BOTTOMLEFT"))]
    return element


def _manifest():
    paragraph = _element("p1", "paragraph", "inicial ´ e s 0 ∈ R , h = 0", 210, 232)
    slash = _element("slash", "paragraph", "̸", 214, 228, left=181, right=186, reading_order=2)
    formula = _element("f1", "formula", "x = 1", 290, 305, reading_order=3)
    manifest = build_manifest([paragraph, slash, formula], [])
    manifest.pages = [PageDescriptor(page_number=1, height=HEIGHT, width=612.0,
                                     element_ids=["p1", "slash", "f1"])]
    return manifest


@pytest.fixture
def spans(monkeypatch):
    calls = []

    async def fetch(source_path, pages, *, artifact_id=None, client=None):
        calls.append(pages)
        return {1: _page(PARAGRAPH_LINE, DISPLAY_LINE)}

    monkeypatch.setattr("backend.tools.text_spans.fetch_text_spans", fetch)
    from backend.config.settings import settings
    monkeypatch.setattr(settings, "inline_math_detection", "fonts")
    return calls


def _run(manifest):
    return asyncio.run(pddl_orchestrator._mark_inline_math(manifest, Path("/tmp/amostra.pdf")))


def test_prose_gets_its_inline_math_and_formulas_are_left_alone(spans):
    manifest = _manifest()

    counts = _run(manifest)

    paragraph, _, formula = manifest.elements
    assert paragraph.text == r"inicial ´ e $s_0\in\mathbb{R}$, $h\neq0$"
    assert paragraph.metadata["inline_math_detection"] == {"marked": 2, "unmatched": 0}
    assert formula.text == "x = 1"
    assert counts == {"elements": 1, "marked": 2, "unmatched": 0}
    assert spans == [[1]]
    assert manifest.extractor.configuration["inline_math_detection"] == "fonts"


def test_the_composed_slash_is_claimed_so_the_reattachment_skips_it(spans):
    manifest = _manifest()

    _run(manifest)

    slash = manifest.elements[1]
    assert slash.metadata["negation_overlay"] == {"outcome": "inline-math", "host": "p1"}


def test_an_unavailable_capability_leaves_the_text(monkeypatch, spans):
    from acessilia_sdk.toolbox.errors import ToolboxError

    async def failing(*args, **kwargs):
        raise ToolboxError("document.text.spans is not in the catalogue")

    monkeypatch.setattr("backend.tools.text_spans.fetch_text_spans", failing)
    manifest = _manifest()

    assert _run(manifest)["marked"] == 0
    assert manifest.elements[0].text == "inicial ´ e s 0 ∈ R , h = 0"
    assert manifest.extractor.configuration["inline_math_detection"] == "unavailable"


def test_off_does_not_call_the_toolbox(monkeypatch, spans):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "inline_math_detection", "off")
    manifest = _manifest()

    _run(manifest)

    assert spans == []
    assert manifest.elements[0].text == "inicial ´ e s 0 ∈ R , h = 0"


def test_other_media_are_skipped(spans):
    manifest = _manifest()
    manifest.source.media_type = "image/png"

    _run(manifest)

    assert spans == []
