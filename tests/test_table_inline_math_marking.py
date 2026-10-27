"""The core writes the inline math of PDF table cells as $…$ from the text layer's fonts (#260)."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from backend.agents import pddl_orchestrator
from backend.core.manifest.models import BoundingBox, PageDescriptor, Provenance
from tests.pddl_support import build_element, build_manifest

HEIGHT = 792.0
FRACTION = r"\frac{s(3+h)-s(3)}{(3+h)-3}"


def _span(text, font, size, bbox, baseline):
    return {"text": text, "font": font, "size": size, "flags": 4,
            "bbox": list(bbox), "origin": [bbox[0], baseline]}


#: The reference case's second table (page 5), prose words in English.
LINES = [
    [_span("h", "CMMI12", 11.96, (180.12, 261.03, 186.85, 272.99), 270.00),
     _span("̸", "CMSY10", 11.96, (186.85, 261.03, 186.85, 272.99), 270.00),
     _span(" = 0", "CMR12", 11.96, (186.85, 261.03, 208.53, 273.00), 270.00)],
    [_span("final", "CMR12", 11.96, (220.44, 261.03, 261.04, 273.00), 270.00),
     _span(" time", "CMR12", 11.96, (261.04, 261.03, 287.16, 273.00), 270.00)],
    [_span("mean", "CMR12", 11.96, (329.16, 261.03, 382.00, 273.00), 270.00),
     _span(" speed", "CMR12", 11.96, (382.00, 261.03, 416.49, 273.00), 270.00)],
    [_span("t", "CMMI12", 11.96, (230.28, 278.43, 234.50, 290.39), 287.40),
     _span(" = 3 +", "CMR12", 11.96, (234.50, 278.43, 267.94, 290.40), 287.40),
     _span(" h", "CMMI12", 11.96, (267.94, 278.43, 277.33, 290.39), 287.40)],
    [_span("s", "CMMI8", 7.97, (349.08, 273.78, 352.99, 281.75), 281.64),
     _span("(3+", "CMR8", 7.97, (353.04, 275.66, 367.06, 283.63), 281.64),
     _span("h", "CMMI8", 7.97, (367.08, 273.78, 371.96, 281.75), 281.64),
     _span(")", "CMR8", 7.97, (372.00, 275.66, 375.29, 283.63), 281.64),
     _span("−", "CMSY8", 7.97, (375.24, 273.88, 381.82, 281.85), 281.64),
     _span("s", "CMMI8", 7.97, (381.84, 273.78, 385.75, 281.75), 281.64),
     _span("(3)", "CMR8", 7.97, (385.80, 275.66, 396.53, 283.63), 281.64)],
    [_span("(3+", "CMR8", 7.97, (356.28, 285.50, 370.30, 293.47), 291.48),
     _span("h", "CMMI8", 7.97, (370.32, 283.62, 375.20, 291.59), 291.48),
     _span(")", "CMR8", 7.97, (375.24, 285.50, 378.53, 293.47), 291.48),
     _span("−", "CMSY8", 7.97, (378.48, 283.72, 385.06, 291.69), 291.48),
     _span("3", "CMR8", 7.97, (385.08, 285.50, 389.31, 293.47), 291.48)],
    [_span("1", "CMR12", 11.96, (191.40, 297.03, 197.25, 309.00), 306.00)],
    [_span("4", "CMR12", 11.96, (250.92, 297.03, 256.77, 309.00), 306.00)],
    [_span("−", "CMSY10", 11.96, (299.16, 297.03, 308.45, 308.99), 306.00),
     _span("0", "CMR12", 11.96, (308.40, 297.03, 314.25, 309.00), 306.00),
     _span(",", "CMMI12", 11.96, (314.28, 297.03, 317.52, 308.99), 306.00),
     _span(" 0833", "CMR12", 11.96, (317.52, 297.03, 343.05, 309.00), 306.00),
     _span(" (approximately)", "CMR12", 11.96, (343.05, 297.03, 446.38, 309.00), 306.00)],
]
#: A paragraph above the table, on the same page.
PARAGRAPH = [_span("then", "CMR12", 11.96, (60.0, 201.0, 85.0, 213.0), 210.0),
             _span(" x", "CMMI12", 11.96, (85.0, 201.0, 95.0, 213.0), 210.0)]


def _box(left, top, right, bottom):
    # Docling boxes come with a bottom-left origin.
    return [Provenance(page_number=1, bbox=BoundingBox(
        left=left, top=HEIGHT - top, right=right, bottom=HEIGHT - bottom, coord_origin="BOTTOMLEFT"))]


def _cells(*texts):
    return {"cells": [{"text": text} for text in texts]}


def _manifest():
    paragraph = build_element("p1", "paragraph", text="then x", reading_order=1)
    paragraph.provenance = _box(55, 199, 100, 215)
    table = build_element("t1", "table", text="", reading_order=2)
    table.provenance = _box(173, 254, 453, 311)
    table.metadata["table_ast"] = {"body": [
        _cells("h = 0", "final time t = 3+ h", "mean speed s (3+ h ) - s (3) (3+ h ) - 3"),
        _cells("1", "4", "- 0 , 0833 (approximately)"),
    ]}
    slash = build_element("slash", "paragraph", text="̸", reading_order=3)
    slash.provenance = _box(185, 260, 189, 274)
    manifest = build_manifest([paragraph, table, slash], [])
    manifest.pages = [PageDescriptor(page_number=1, height=HEIGHT, width=612.0,
                                     element_ids=["p1", "t1", "slash"])]
    return manifest


@pytest.fixture
def spans(monkeypatch):
    calls = []

    async def fetch(source_path, pages, *, artifact_id=None, client=None):
        calls.append(pages)
        return {1: {"page_number": 1, "width": 612.0, "height": HEIGHT, "rotation": 0,
                    "lines": [{"bbox": [0, 0, 0, 0], "spans": line} for line in [PARAGRAPH, *LINES]]}}

    monkeypatch.setattr("backend.tools.text_spans.fetch_text_spans", fetch)
    from backend.config.settings import settings
    monkeypatch.setattr(settings, "inline_math_detection", "fonts")
    return calls


def _run(manifest, text_spans=None):
    return asyncio.run(
        pddl_orchestrator._mark_table_inline_math(manifest, Path("/tmp/amostra.pdf"), text_spans)
    )


def _texts(table):
    return [cell["text"] for row in table.metadata["table_ast"]["body"] for cell in row["cells"]]


def test_each_cell_gets_its_inline_math(spans):
    manifest = _manifest()

    counts = _run(manifest)

    table = manifest.elements[1]
    assert _texts(table) == [
        r"$h\neq0$", "final time $t=3+h$", f"mean speed ${FRACTION}$",
        "1", "4", "$-0,0833$ (approximately)",
    ]
    assert table.metadata["inline_math_detection"] == {"marked": 4, "unmatched": 0}
    assert counts == {"elements": 1, "marked": 4, "unmatched": 0}
    assert spans == [[1]]
    # The paragraph is the prose step's.
    assert manifest.elements[0].text == "then x"


def test_the_composed_slash_is_claimed_by_the_table(spans):
    manifest = _manifest()

    _run(manifest)

    assert manifest.elements[2].metadata["negation_overlay"] == {"outcome": "inline-math", "host": "t1"}


def test_a_marked_table_is_not_marked_again(spans):
    manifest = _manifest()
    _run(manifest)

    assert _run(manifest)["elements"] == 0
    assert _texts(manifest.elements[1])[0] == r"$h\neq0$"


def test_the_prose_and_table_steps_fetch_a_page_once(spans):
    manifest = _manifest()
    reader = pddl_orchestrator._TextSpanReader(manifest, Path("/tmp/amostra.pdf"))

    asyncio.run(pddl_orchestrator._mark_inline_math(manifest, Path("/tmp/amostra.pdf"), reader))
    _run(manifest, reader)

    assert manifest.elements[0].text == "then $x$"
    assert _texts(manifest.elements[1])[0] == r"$h\neq0$"
    assert spans == [[1]]


def test_an_unavailable_capability_is_asked_once(monkeypatch, spans):
    from acessilia_sdk.toolbox.errors import ToolboxError

    calls = []

    async def failing(*args, **kwargs):
        calls.append(args)
        raise ToolboxError("document.text.spans is not in the catalogue")

    monkeypatch.setattr("backend.tools.text_spans.fetch_text_spans", failing)
    manifest = _manifest()
    reader = pddl_orchestrator._TextSpanReader(manifest, Path("/tmp/amostra.pdf"))

    asyncio.run(pddl_orchestrator._mark_inline_math(manifest, Path("/tmp/amostra.pdf"), reader))
    assert _run(manifest, reader)["marked"] == 0

    assert len(calls) == 1
    assert _texts(manifest.elements[1])[0] == "h = 0"
    assert manifest.extractor.configuration["inline_math_detection"] == "unavailable"


def test_off_does_not_call_the_toolbox(monkeypatch, spans):
    from backend.config.settings import settings

    monkeypatch.setattr(settings, "inline_math_detection", "off")
    manifest = _manifest()

    _run(manifest)

    assert spans == []
    assert _texts(manifest.elements[1])[0] == "h = 0"


def test_the_unicode_repair_leaves_the_marked_cells_alone(spans):
    from docstruct.text.unicode_repair import UnicodeRepairContext

    manifest = _manifest()
    _run(manifest)
    table = manifest.elements[1]
    before = _texts(table)

    pddl_orchestrator._repair_table_cells(table, UnicodeRepairContext(
        language="pt-BR", block_type="prose", allow_spacing_diacritics=True,
        allow_standalone_spacing_diacritics=True, allow_legacy_tex_artifacts=True,
    ))

    assert _texts(table) == before


def test_an_unclaimed_slash_is_not_composed_inside_a_marked_cell(spans):
    manifest = _manifest()
    _run(manifest)
    # A slash whose box the claim missed reaches the reattachment: the only "="
    # left in the header row is inside $t=3+h$, which must stay as detected.
    slash = manifest.elements[2]
    slash.metadata.pop("negation_overlay")
    before = _texts(manifest.elements[1])

    outcomes = pddl_orchestrator._reattach_negation_overlays(manifest)

    assert _texts(manifest.elements[1]) == before
    assert outcomes == {"no-candidate": 1}
