"""Characterization of the manifest builder before its algorithms move to docstruct.

#203 moves the builder's pure algorithms (reading order, box geometry, the
unstructured-page predicate) to docstruct. These tests freeze what the builder
does today, so each migration step can prove parity: same element ids, same
``reading_order`` indexes, same ``page.element_ids``, same boxes and the same
wire payload. A change in behaviour is a separate pull request that updates
these expectations on purpose.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from backend.core.manifest.builder import (
    UNSTRUCTURED_PAGE_LABEL,
    _element_bbox,
    _normalized_element_bbox,
    _refine_reading_order,
    build_processing_manifest,
    is_unstructured_page_placeholder,
)
from backend.core.manifest.models import (
    BoundingBox,
    ManifestElement,
    ProcessingManifest,
    Provenance,
    is_bottom_left,
)
from backend.core.manifest.toolbox_extractor import ToolboxExtraction

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_MANIFESTS = FIXTURES / "manifests"
PAGE_HEIGHT = 800.0

#: Set to regenerate the golden manifests after an intended change.
UPDATE_GOLDEN = os.environ.get("UPDATE_MANIFEST_GOLDEN") == "1"


def _element(
    element_id: str,
    box: tuple[float, float, float, float] | None,
    *,
    element_type: str = "paragraph",
    raw_label: str | None = None,
    origin: str = "TOPLEFT",
    page: int | None = 1,
    reading_order: int = 1,
) -> ManifestElement:
    provenance = []
    if box is not None:
        left, top, right, bottom = box
        if origin == "BOTTOMLEFT" or origin == "UNKNOWN-UP":
            top, bottom = PAGE_HEIGHT - top, PAGE_HEIGHT - bottom
        provenance = [
            Provenance(
                page_number=page or 1,
                bbox=BoundingBox(
                    left=left,
                    top=top,
                    right=right,
                    bottom=bottom,
                    coord_origin="UNKNOWN" if origin.startswith("UNKNOWN") else origin,
                ),
            )
        ]
    return ManifestElement(
        id=element_id,
        type=element_type,
        raw_label=raw_label or element_type,
        reading_order=reading_order,
        hierarchy_level=1,
        page_number=page,
        text=element_id,
        provenance=provenance,
    )


def _numbered(rows: list[tuple]) -> list[ManifestElement]:
    """Rows of ``(id, box, **kwargs)``; reading orders count up in row order."""
    return [
        _element(row[0], row[1], reading_order=index, **(row[2] if len(row) > 2 else {}))
        for index, row in enumerate(rows, start=1)
    ]


def _two_columns(origin: str) -> list[ManifestElement]:
    """Title, two columns, a full-width figure, two more columns (top-left boxes)."""
    rows = [
        ("c2-b", (320, 460, 580, 500)),
        ("c1-a", (20, 100, 280, 140)),
        ("title", (20, 40, 580, 80), {"element_type": "title"}),
        ("figure", (20, 300, 580, 420), {"element_type": "picture"}),
        ("c2-a", (320, 100, 580, 140)),
        ("c1-b", (20, 160, 280, 200)),
        ("c2-d", (320, 520, 580, 560)),
        ("c1-c", (20, 460, 280, 500)),
        ("c1-d", (20, 520, 280, 560)),
        ("c2-b0", (320, 160, 580, 200)),
    ]
    return [
        _element(
            row[0], row[1], reading_order=index, origin=origin, **(row[2] if len(row) > 2 else {})
        )
        for index, row in enumerate(rows, start=1)
    ]


TWO_COLUMN_ORDER = [
    "title", "c1-a", "c1-b", "c2-a", "c2-b0", "figure", "c1-c", "c1-d", "c2-b", "c2-d",
]

CASES: dict[str, tuple[list[ManifestElement], list[str]]] = {
    "one column, reading orders reversed": (
        [
            _element("p4", (20, 400, 580, 440), reading_order=1),
            _element("p3", (20, 300, 580, 340), reading_order=2),
            _element("p2", (20, 200, 580, 240), reading_order=3),
            _element("p1", (20, 100, 580, 140), reading_order=4),
        ],
        ["p1", "p2", "p3", "p4"],
    ),
    "two columns with banners, top-left": (_two_columns("TOPLEFT"), TWO_COLUMN_ORDER),
    "two columns with banners, bottom-left": (_two_columns("BOTTOMLEFT"), TWO_COLUMN_ORDER),
    "two columns with banners, unknown origin with y up": (
        _two_columns("UNKNOWN-UP"),
        TWO_COLUMN_ORDER,
    ),
    "two columns with banners, unknown origin with y down": (
        _two_columns("UNKNOWN"),
        TWO_COLUMN_ORDER,
    ),
    # Today's builder detects two columns only. The middle column's centre sits
    # on the midline, so it joins the right column and the two interleave row
    # by row. Fixing that is a later, separate change (#203, D6).
    "three columns": (
        _numbered(
            [
                ("a1", (20, 100, 200, 140)),
                ("b1", (210, 100, 390, 140)),
                ("c1", (400, 100, 580, 140)),
                ("a2", (20, 160, 200, 200)),
                ("b2", (210, 160, 390, 200)),
                ("c2", (400, 160, 580, 200)),
            ]
        ),
        ["a1", "a2", "b1", "c1", "b2", "c2"],
    ),
    "headers and footers by type and by raw label": (
        _numbered(
            [
                ("page-number", (280, 760, 320, 780), {"raw_label": "page_number"}),
                ("footer", (20, 740, 580, 755), {"element_type": "page_footer"}),
                ("body-2", (20, 200, 580, 240)),
                ("header-raw", (300, 10, 580, 30), {"raw_label": "header"}),
                ("body-1", (20, 100, 580, 140)),
                ("header", (20, 10, 280, 30), {"element_type": "page_header"}),
            ]
        ),
        ["header", "header-raw", "body-1", "body-2", "footer", "page-number"],
    ),
    "groups come first, in input order": (
        _numbered(
            [
                ("body", (20, 100, 580, 140)),
                ("group-low", (20, 600, 580, 700), {"element_type": "group"}),
                ("header", (20, 10, 580, 30), {"element_type": "page_header"}),
                ("group-high", (20, 50, 580, 90), {"element_type": "group"}),
            ]
        ),
        ["group-low", "group-high", "header", "body"],
    ),
    "pages sorted, document-level elements first": (
        [
            _element("p2-b", (20, 200, 580, 240), page=2, reading_order=1),
            _element("p2-a", (20, 100, 580, 140), page=2, reading_order=2),
            _element("doc", None, page=None, element_type="group", reading_order=3),
            _element("p1-b", (20, 200, 580, 240), page=1, reading_order=4),
            _element("p1-a", (20, 100, 580, 140), page=1, reading_order=5),
            _element("p3-only", (20, 100, 580, 140), page=3, reading_order=6),
        ],
        ["doc", "p1-a", "p1-b", "p2-a", "p2-b", "p3-only"],
    ),
    "elements without a box sort as if at the top": (
        _numbered(
            [
                ("boxed-2", (20, 200, 580, 240)),
                ("no-box-a", None),
                ("boxed-1", (20, 100, 580, 140)),
                ("no-box-b", None),
            ]
        ),
        ["no-box-a", "no-box-b", "boxed-1", "boxed-2"],
    ),
    "a single boxed element sorts by top then reading order": (
        _numbered(
            [
                ("no-box", None),
                ("boxed", (20, 100, 580, 140)),
                ("no-box-2", None),
            ]
        ),
        ["no-box", "no-box-2", "boxed"],
    ),
    # Known defect, frozen for parity (#203, D6): with bottom-left boxes the
    # mirrored tops are negative, the column pass starts at ``prev_top = -1.0``
    # and takes none of them, so a page without a full-width banner keeps its
    # input order. The same page in top-left boxes is read column by column.
    "two columns without a banner, bottom-left": (
        [
            _element(row[0], row[1], origin="BOTTOMLEFT", reading_order=index)
            for index, row in enumerate(
                [
                    ("b1", (320, 100, 580, 140)),
                    ("a1", (20, 100, 280, 140)),
                    ("b2", (320, 160, 580, 200)),
                    ("a2", (20, 160, 280, 200)),
                ],
                start=1,
            )
        ],
        ["b1", "a1", "b2", "a2"],
    ),
    "two columns without a banner, top-left": (
        _numbered(
            [
                ("b1", (320, 100, 580, 140)),
                ("a1", (20, 100, 280, 140)),
                ("b2", (320, 160, 580, 200)),
                ("a2", (20, 160, 280, 200)),
            ]
        ),
        ["a1", "a2", "b1", "b2"],
    ),
    "unboxed elements on a multi-column page go last": (
        _numbered(
            [
                ("no-box", None),
                ("a1", (20, 100, 280, 140)),
                ("b1", (320, 100, 580, 140)),
                ("a2", (20, 160, 280, 200)),
                ("b2", (320, 160, 580, 200)),
            ]
        ),
        ["a1", "a2", "b1", "b2", "no-box"],
    ),
    "ties keep the incoming reading order": (
        [
            _element("second", (20, 100, 580, 140), reading_order=2),
            _element("first", (20, 100, 580, 140), reading_order=1),
            _element("third", (20, 100, 580, 140), reading_order=3),
        ],
        ["first", "second", "third"],
    ),
    "a page with one element is kept as is": (
        [
            _element("only", (20, 100, 580, 140), page=1, reading_order=7),
            _element("p2", (20, 100, 580, 140), page=2, reading_order=3),
        ],
        ["only", "p2"],
    ),
}


@pytest.mark.parametrize("case", list(CASES))
def test_reading_order_matches_the_current_builder(case: str) -> None:
    elements, expected = CASES[case]

    refined = _refine_reading_order(elements)

    assert [element.id for element in refined] == expected
    assert [element.reading_order for element in refined] == list(
        range(1, len(expected) + 1)
    )


def test_reading_order_of_nothing_is_nothing() -> None:
    assert _refine_reading_order([]) == []


def test_refinement_returns_the_same_element_objects() -> None:
    elements, _ = CASES["two columns with banners, top-left"]
    before = {id(element) for element in elements}

    refined = _refine_reading_order(elements)

    assert {id(element) for element in refined} == before


# --- Box geometry -------------------------------------------------------------

BOX_CASES = {
    # origin: (stored box, screen box from _element_bbox, page fractions)
    "TOPLEFT": ((60, 80, 300, 160), (60, 80, 300, 160), (0.1, 0.1, 0.5, 0.2)),
    "BOTTOMLEFT": ((60, 720, 300, 640), (60, -720, 300, -640), (0.1, 0.1, 0.5, 0.2)),
    "UNKNOWN, y up": ((60, 720, 300, 640), (60, -720, 300, -640), (0.1, 0.1, 0.5, 0.2)),
    "UNKNOWN, y down": ((60, 80, 300, 160), (60, 80, 300, 160), (0.1, 0.1, 0.5, 0.2)),
}


@pytest.mark.parametrize("case", list(BOX_CASES))
def test_element_boxes_keep_their_origin(case: str) -> None:
    stored, screen, fractions = BOX_CASES[case]
    origin = case.split(",")[0]
    element = ManifestElement(
        id="e",
        type="paragraph",
        raw_label="text",
        reading_order=1,
        hierarchy_level=1,
        page_number=1,
        provenance=[
            Provenance(
                page_number=1,
                bbox=BoundingBox(
                    left=stored[0],
                    top=stored[1],
                    right=stored[2],
                    bottom=stored[3],
                    coord_origin=origin,
                ),
            )
        ],
    )

    assert _element_bbox(element) == screen
    assert _normalized_element_bbox(element, {1: (600.0, 800.0)}) == pytest.approx(
        fractions
    )


def test_boxes_are_missing_without_provenance_or_page_size() -> None:
    boxed = _element("boxed", (60, 80, 300, 160))
    unboxed = _element("unboxed", None)
    no_page = _element("no-page", (60, 80, 300, 160), page=None)

    assert _element_bbox(unboxed) is None
    assert _normalized_element_bbox(unboxed, {1: (600.0, 800.0)}) is None
    assert _normalized_element_bbox(no_page, {1: (600.0, 800.0)}) is None
    assert _normalized_element_bbox(boxed, None) is None
    assert _normalized_element_bbox(boxed, {2: (600.0, 800.0)}) is None
    assert _normalized_element_bbox(boxed, {1: (None, 800.0)}) is None
    assert _normalized_element_bbox(boxed, {1: (600.0, 0.0)}) is None


@pytest.mark.parametrize(
    ("origin", "top", "bottom", "expected"),
    [
        ("BOTTOMLEFT", 10.0, 20.0, True),
        ("bottomleft", 10.0, 20.0, True),
        ("TOPLEFT", 20.0, 10.0, False),
        ("UNKNOWN", 20.0, 10.0, True),
        ("UNKNOWN", 10.0, 20.0, False),
        ("UNKNOWN", 10.0, 10.0, False),
        (None, 20.0, 10.0, True),
        ("", 10.0, 20.0, False),
    ],
)
def test_is_bottom_left(origin, top, bottom, expected) -> None:
    assert is_bottom_left(origin, top, bottom) is expected


def test_unstructured_page_placeholder_needs_label_and_flag() -> None:
    placeholder = _element("p", None, element_type="unknown", raw_label=UNSTRUCTURED_PAGE_LABEL)
    placeholder.metadata["unstructured_page"] = True
    label_only = _element("l", None, element_type="unknown", raw_label=UNSTRUCTURED_PAGE_LABEL)
    flag_only = _element("f", None, element_type="unknown", raw_label="text")
    flag_only.metadata["unstructured_page"] = True

    assert is_unstructured_page_placeholder(placeholder) is True
    assert is_unstructured_page_placeholder(label_only) is False
    assert is_unstructured_page_placeholder(flag_only) is False


# --- Manifest built end to end -----------------------------------------------

TIMESTAMP = datetime(2026, 10, 20, tzinfo=timezone.utc)


def _two_page_response() -> dict:
    """A Toolbox response with boxes, two pages and an out-of-order header."""

    def element(n, element_type, page, box, raw_label=None, origin="BOTTOMLEFT"):
        left, top, right, bottom = box
        return {
            "id": f"element-{n:06d}",
            "type": element_type,
            "raw_label": raw_label or element_type,
            "reading_order": n,
            "hierarchy_level": 1,
            "page_number": page,
            "text": f"text {n}",
            "provenance": [
                {
                    "page_number": page,
                    "bbox": {
                        "left": left,
                        "top": top,
                        "right": right,
                        "bottom": bottom,
                        "coord_origin": origin,
                    },
                }
            ],
        }

    elements = [
        element(1, "paragraph", 1, (20, 500, 580, 460)),
        element(2, "page_header", 1, (20, 790, 580, 770)),
        element(3, "heading", 1, (20, 700, 580, 660), "section_header"),
        element(4, "paragraph", 2, (320, 700, 580, 660)),
        element(5, "paragraph", 2, (20, 700, 280, 660)),
        element(6, "paragraph", 2, (320, 600, 580, 560)),
        element(7, "paragraph", 2, (20, 600, 280, 560)),
        element(8, "page_footer", 2, (20, 30, 580, 10), "page_number"),
    ]
    pages = [
        {"page_number": 1, "width": 600.0, "height": 800.0,
         "element_ids": ["element-000001", "element-000002", "element-000003"]},
        {"page_number": 2, "width": 600.0, "height": 800.0,
         "element_ids": [f"element-{n:06d}" for n in range(4, 9)]},
    ]
    fixture = json.loads((FIXTURES / "toolbox-v2-contract.json").read_text("utf-8"))
    summary = {
        "page_count": len(pages),
        "element_count": len(elements),
        "observation_count": 0,
        "obligation_count": 0,
        "element_types": {"heading": 1, "page_footer": 1, "page_header": 1, "paragraph": 5},
    }
    document = {
        **fixture["document"], "pages": pages, "elements": elements, "summary": summary,
    }
    return {**fixture, "document": document}


def _build(tmp_path: Path, response: dict, *, refine: bool) -> ProcessingManifest:
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-test")
    extraction = ToolboxExtraction(
        document=response,
        started_at=TIMESTAMP,
        completed_at=TIMESTAMP,
        duration_ms=5,
        version="toolbox-test",
        configuration={"ocr": False},
    )
    return build_processing_manifest(source, extraction, refine_reading_order=refine)


def _wire(manifest: ProcessingManifest) -> dict:
    """The manifest as written to disk, without the machine-specific path."""
    payload = manifest.model_dump(mode="json", by_alias=True)
    payload["source"]["path"] = "<source>"
    return payload


def test_refined_manifest_recomposes_page_element_ids(tmp_path: Path) -> None:
    manifest = _build(tmp_path, _two_page_response(), refine=True)

    # Page 2 keeps the Toolbox order, not column order: its boxes are
    # bottom-left, so their mirrored tops are negative, and the column pass
    # only takes boxes below its ``prev_top = -1.0`` start. Every column then
    # falls through to "unseen, in input order". This is today's behaviour,
    # frozen for parity; fixing it is a separate change (#203, D6).
    assert [element.id for element in manifest.elements] == [
        "element-000002", "element-000003", "element-000001",
        "element-000004", "element-000005", "element-000006", "element-000007",
        "element-000008",
    ]
    assert [element.reading_order for element in manifest.elements] == list(range(1, 9))
    assert {page.page_number: page.element_ids for page in manifest.pages} == {
        1: ["element-000002", "element-000003", "element-000001"],
        2: ["element-000004", "element-000005", "element-000006",
            "element-000007", "element-000008"],
    }


GOLDEN_CASES = {
    "toolbox-v2-contract": (
        lambda: json.loads((FIXTURES / "toolbox-v2-contract.json").read_text("utf-8")),
        False,
    ),
    "two-pages-refined": (_two_page_response, True),
}


@pytest.mark.parametrize("name", list(GOLDEN_CASES))
def test_manifest_wire_payload_matches_the_golden_file(tmp_path: Path, name: str) -> None:
    response, refine = GOLDEN_CASES[name]
    payload = _wire(_build(tmp_path, response(), refine=refine))
    golden = GOLDEN_MANIFESTS / f"{name}.json"

    if UPDATE_GOLDEN:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")

    assert payload == json.loads(golden.read_text("utf-8"))


@pytest.mark.parametrize("name", list(GOLDEN_CASES))
def test_golden_manifest_round_trips_unchanged(name: str) -> None:
    payload = json.loads((GOLDEN_MANIFESTS / f"{name}.json").read_text("utf-8"))

    manifest = ProcessingManifest.model_validate(payload)

    assert manifest.model_dump(mode="json", by_alias=True) == payload
