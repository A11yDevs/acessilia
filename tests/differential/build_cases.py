"""Write the differential cases (``cases/<name>/case.json``, #849).

``python -m tests.differential.build_cases`` rebuilds every case from the
core's models, so each document is a valid extraction. A case is data: edit
this file and rebuild, then record the references again
(``scripts/record_differential_references.py``).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "libs" / "core" / "tests"))

from pddl_support import build_element, build_manifest  # noqa: E402

from acessilia_core.manifest.models import BoundingBox, PageDescriptor, Provenance  # noqa: E402

WIDTH, HEIGHT = 612.0, 792.0
PROSE = (
    "This document describes the experiment in enough detail for the text to be long, "
    "so that the document is not taken as mostly visual. "
)


def _element(element_id, element_type, text, top, bottom, order, *, left=72.0, right=540.0, page=1, **metadata):
    element = build_element(element_id, element_type, text=text, reading_order=order, metadata=metadata or None)
    element.page_number = page
    element.provenance = [Provenance(page_number=page, bbox=BoundingBox(
        left=left, top=top, right=right, bottom=bottom, coord_origin="TOPLEFT"))]
    return element


def _span(text, font, x, size=11.96, baseline=225.96):
    width = max(len(text), 1) * size * 0.5
    return {"text": text, "font": font, "size": size, "flags": 4,
            "bbox": [x, baseline - size * 0.75, x + width, baseline + size * 0.25],
            "origin": [x, baseline]}


def _line(*spans):
    boxes = [span["bbox"] for span in spans]
    return {"bbox": [min(b[0] for b in boxes), min(b[1] for b in boxes),
                     max(b[2] for b in boxes), max(b[3] for b in boxes)], "spans": list(spans)}


_TABLE_2KG = "| Quantity | Value |\n|---|---|\n| Mass | 2 kg |"
_TABLE_3KG = "| Quantity | Value |\n|---|---|\n| Mass | 3 kg |\n| Speed | 4 m/s |\n| Start | s 0 ∈ R |"


def _ast(*rows: tuple[str, str]) -> dict[str, Any]:
    header = {"cells": [{"text": "Quantity", "header": True}, {"text": "Value", "header": True}]}
    return {"body": [header, *({"cells": [{"text": a}, {"text": b}]} for a, b in rows)]}


CASES: dict[str, dict[str, Any]] = {
    "text-and-picture": {
        "description": "Prose with one picture and its caption: the picture descriptions (M1).",
        "elements": [
            _element("h1", "heading", "Experiment report", 60, 80, 1),
            _element("p1", "paragraph", PROSE * 3, 90, 200, 2),
            _element("pic1", "picture", "", 220, 420, 3),
            _element("cap1", "caption", "Figure 1: the equipment set up.", 425, 440, 4),
            _element("p2", "paragraph", PROSE * 2, 450, 560, 5),
        ],
        "vision": {"pic1": {"description": "Photograph of a bench with an oscilloscope and cables."}},
    },
    "tables": {
        "description": "A table without structure, read from its image, and a structured one: the table enrichment (M2).",
        "elements": [
            _element("p1", "paragraph", PROSE * 3, 60, 170, 1),
            _element("t1", "table", "Quantity Value Mass 2 kg", 180, 300, 2),
            _element("t2", "table", "", 320, 420, 3, table_ast={"body": [
                {"cells": [{"text": "Time", "header": True}, {"text": "Position", "header": True}]},
                {"cells": [{"text": "0 s"}, {"text": "0 m"}]},
            ]}),
            _element("p2", "paragraph", PROSE * 2, 440, 540, 4),
        ],
        "vision": {"t1": {"kind": "table", "rows": [
            {"cells": [{"text": "Quantity", "header": True, "scope": "col"},
                       {"text": "Value", "header": True, "scope": "col"}]},
            {"cells": [{"text": "Mass"}, {"text": "2 kg"}]},
        ]}},
    },
    "formulas": {
        "description": "A formula without LaTeX markup (classified, then read: M4a, M3), one with LaTeX, and a picture the vision model reads as a formula (M1, #846).",
        "elements": [
            _element("p1", "paragraph", PROSE * 3, 60, 170, 1),
            _element("f1", "formula", "s ( t ) = t 3", 180, 200, 2),
            _element("f2", "formula", "v = \\frac{d}{t}", 210, 230, 3),
            _element("p2", "paragraph", PROSE * 2, 240, 340, 4),
            _element("pic1", "picture", "", 350, 400, 5),
            _element("p3", "paragraph", PROSE * 2, 410, 520, 6),
        ],
        "vision": {
            "f1": {"kind": "formula", "formula_latex": "s(t) = t^3", "description": "s of t equals t cubed"},
            "pic1": {"kind": "formula", "formula_latex": "E = mc^2", "description": "E equals m c squared"},
        },
        # pic1: math.recognize reads nothing, so the model's LaTeX stays.
        "latex": {"f1": "s(t) = t^{3}", "pic1": ""},
    },
    "mostly-visual": {
        "description": "A one-page document with no text content and no picture: its placeholder visuals are described.",
        "elements": [
            _element("g1", "paragraph", "", 60, 380, 1),
            _element("g2", "paragraph", "Fig", 400, 720, 2),
        ],
        "vision": {
            "g1": {"description": "Bar chart of the yearly output from 2020 to 2024."},
            "g2": {"description": "Map of Brazil with its regions coloured."},
        },
    },
    "inline-math": {
        "description": "Prose whose math the text layer's fonts mark as $…$ (M4b), and a formula that reads its variables.",
        "elements": [
            _element("p0", "paragraph", PROSE * 2, 60, 180, 1),
            _element("p1", "paragraph", "inicial ´ e s 0 ∈ R , h = 0", 210, 232, 2, left=50.0, right=560.0),
            _element("f1", "formula", "h(12 + h)", 290, 305, 3),
            _element("p2", "paragraph", PROSE * 2, 320, 430, 4),
        ],
        "vision": {"f1": {"kind": "formula", "formula_latex": "h(12 + h)", "description": "h times 12 plus h"}},
        # math.recognize reads nothing, so the classification's LaTeX stays.
        "latex": {"f1": ""},
        "text_spans": {"1": [_line(
            _span("inicial", "CMR12", 60), _span("´e", "CMR12", 110), _span("s", "CMMI12", 130),
            _span("0", "CMR8", 137, size=7.97, baseline=227.76), _span("∈", "CMSY10", 145),
            _span("R", "MSBM10", 155), _span(",", "CMR12", 163), _span("h", "CMMI12", 175),
            _span("̸", "CMSY10", 183), _span("= 0", "CMR12", 183),
        )]},
    },
    "multi-page": {
        "description": "Three pages: a picture, a formula without LaTeX markup and a table read from its image, each on its own page.",
        "elements": [
            _element("h1", "heading", "Experiment report", 60, 80, 1),
            _element("p1", "paragraph", PROSE * 3, 90, 200, 2),
            _element("pic1", "picture", "", 220, 420, 3),
            _element("p2", "paragraph", PROSE * 2, 60, 170, 4, page=2),
            _element("f1", "formula", "s ( t ) = t 3", 200, 230, 5, page=2),
            _element("p3", "paragraph", PROSE * 2, 60, 170, 6, page=3),
            _element("t1", "table", "Quantity Value Mass 2 kg", 200, 320, 7, page=3),
        ],
        "vision": {
            "pic1": {"description": "Photograph of a bench with an oscilloscope and cables."},
            "f1": {"kind": "formula", "formula_latex": "s(t) = t^3", "description": "s of t equals t cubed"},
            "t1": {"kind": "table", "rows": [
                {"cells": [{"text": "Quantity", "header": True}, {"text": "Value", "header": True}]},
                {"cells": [{"text": "Mass"}, {"text": "2 kg"}]},
            ]},
        },
        "latex": {"f1": "s(t) = t^{3}"},
    },
    "dual-provider": {
        "description": (
            "Two providers (FUSION_MODE=dual), three pages. Page 1: the providers disagree on the "
            "structure, so the page is adjudicated (the judge keeps the primary). Page 2: their tables "
            "diverge, and select-table-source adopts the secondary's cells, which the inline math "
            "marks again (inline_math_stale, M4b). Page 3: both providers have math, so the page is "
            "routed to the secondary (both_formula->mineru): its formula is read from the "
            "secondary's region, and rescue-omitted puts back the sentence with inline math only "
            "the primary kept (#887), which the inline math marks on the replan, dropping the "
            "conversions made before it."
        ),
        "environment": {"FUSION_MODE": "dual"},
        "elements": [
            _element("p1", "paragraph", PROSE * 2, 60, 170, 1),
            _element("p2", "paragraph", "A sentence only the primary provider kept about the cart.", 180, 200, 2),
            _element("p3", "paragraph", PROSE * 2, 420, 530, 3),
            _element("q1", "paragraph", PROSE * 2, 60, 170, 4, page=2),
            _element("t1", "table", _TABLE_2KG, 200, 300, 5, page=2, table_ast=_ast(("Mass", "2 kg"))),
            _element("u1", "paragraph", PROSE * 2, 60, 170, 6, page=3),
            _element("u2", "paragraph", "See the cart at $v_0$.", 180, 195, 7, page=3),
            _element("u3", "paragraph", PROSE * 2, 420, 530, 8, page=3),
        ],
        "secondary": [
            _element("s1", "paragraph", PROSE * 2, 60, 170, 1),
            _element("s2", "formula", "v = \\frac{d}{t}", 250, 280, 2),
            _element("s3", "paragraph", PROSE * 2, 420, 530, 3),
            _element("r1", "paragraph", PROSE * 2, 60, 170, 4, page=2),
            _element("r2", "table", _TABLE_3KG, 200, 300, 5, page=2,
                     table_ast=_ast(("Mass", "3 kg"), ("Speed", "4 m/s"), ("Start", "s 0 ∈ R"))),
            _element("v1", "paragraph", PROSE * 2, 60, 170, 6, page=3),
            _element("v2", "formula", "a = v t", 250, 280, 7, page=3),
            _element("v4", "paragraph", "The cart starts at $v$ and speeds up.", 300, 315, 8, page=3),
            _element("v3", "paragraph", PROSE * 2, 420, 530, 9, page=3),
        ],
        # Page 3 is routed to the secondary: its formula, without LaTeX markup,
        # is classified and read from the secondary's region.
        "vision": {
            "v2": {"kind": "formula", "formula_latex": "a = \\frac{v}{t}", "description": "a equals v over t"},
        },
        "latex": {"v2": "a = \\frac{v}{t}"},
        # The adopted table's last row is math the text layer's fonts mark
        # again once the table is stale (M4b).
        "text_spans": {"2": [_line(
            _span("Start", "CMR12", 80, baseline=285.0), _span("s", "CMMI12", 330, baseline=285.0),
            _span("0", "CMR8", 337, size=7.97, baseline=286.8), _span("∈", "CMSY10", 345, baseline=285.0),
            _span("R", "MSBM10", 355, baseline=285.0),
        )]},
        # The judge keeps the primary on the adjudicated page.
        "judge": {"page-1": 0.2},
    },
    "degraded": {
        "description": (
            "The Toolbox degrades: math.recognize and document.text.spans are unavailable, and the "
            "vision model fails on one of two pictures. The formula falls back to the vision model, "
            "the inline math is unavailable, and the second picture is left without a description."
        ),
        "failures": {"capabilities": ["math.recognize", "document.text.spans"], "vision": ["pic2"]},
        "elements": [
            _element("p1", "paragraph", PROSE * 3, 60, 170, 1),
            _element("pic1", "picture", "", 180, 330, 2),
            _element("pic2", "picture", "", 340, 480, 3),
            _element("f1", "formula", "s ( t ) = t 3", 500, 530, 4),
            _element("p2", "paragraph", "inicial ´ e s 0 ∈ R , h = 0", 540, 560, 5, left=50.0, right=560.0),
            _element("p3", "paragraph", PROSE * 2, 580, 700, 6),
        ],
        "vision": {
            "pic1": {"description": "Photograph of a bench with an oscilloscope and cables."},
            "f1": {"kind": "formula", "formula_latex": "s(t) = t^3", "description": "s of t equals t cubed"},
        },
    },
}


def _document(elements) -> dict[str, Any]:
    """A manifest-compatible extraction of ``elements``, one page per page number."""
    manifest = build_manifest(elements, [])
    numbers = sorted({element.page_number or 1 for element in elements})
    manifest.pages = [
        PageDescriptor(page_number=number, width=WIDTH, height=HEIGHT,
                       element_ids=[element.id for element in elements if (element.page_number or 1) == number])
        for number in numbers
    ]
    manifest.summary.page_count = len(numbers)
    document = manifest.model_dump(mode="json", exclude_none=True)
    for key in ("source", "extractor", "obligations", "observations", "manifest_id", "created_at"):
        document.pop(key, None)
    return document


def build(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    case: dict[str, Any] = {"description": spec["description"], "document": _document(spec["elements"])}
    if "secondary" in spec:
        case["secondary_document"] = _document(spec["secondary"])
    for key in ("environment", "primary_provider", "secondary_provider", "vision", "latex", "text_spans", "judge", "failures"):
        if key in spec:
            case[key] = spec[key]
    return case


def main() -> None:
    for name, spec in CASES.items():
        target = HERE / "cases" / name / "case.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(build(name, spec), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(target.relative_to(HERE))


if __name__ == "__main__":
    main()
