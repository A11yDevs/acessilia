"""Placing text-layer spans on an element's boxes (docstruct.text.inline_math).

Moved from the core's PDDL payload (#402); the core covers the same rules end
to end in tests/test_inline_math_marking.py and
tests/test_table_inline_math_marking.py.
"""

from __future__ import annotations

import pytest

from docstruct.geometry.boxes import OrientedBox, PageBox, holds_point
from docstruct.text.inline_math import (
    SPAN_BOX_TOLERANCE,
    detect_inline_math_by_page,
    span_lines_on_page,
    top_left_box,
)

HEIGHT = 800.0


def _span(text: str, font: str, x: float, baseline: float = 100.0, size: float = 10.0) -> dict:
    width = len(text) * size * 0.5
    return {"text": text, "font": font, "size": size, "flags": 4,
            "bbox": [x, baseline - size * 0.75, x + width, baseline + size * 0.25],
            "origin": [x, baseline]}


def _page(*lines: list[dict], **changes) -> dict:
    return {"page_number": 1, "width": 600.0, "height": HEIGHT, "rotation": 0,
            "lines": [{"bbox": [0, 0, 0, 0], "spans": list(line)} for line in lines], **changes}


LINE = [_span("onde", "CMR10", 50), _span("x", "CMMI10", 80), _span("= 1", "CMR10", 86)]
#: Below the box: its spans belong to another element.
OTHER = [_span("y", "CMMI10", 80, baseline=200.0)]


def _box(left: float, top: float, right: float, bottom: float, origin: str | None = "TOPLEFT") -> PageBox:
    if origin == "BOTTOMLEFT":
        return OrientedBox(left, HEIGHT - top, right, HEIGHT - bottom, origin)
    return OrientedBox(left, top, right, bottom, origin)


@pytest.mark.parametrize(
    ("origin", "page_height", "manifest_height", "expected"),
    [
        ("TOPLEFT", None, None, (10.0, 20.0, 30.0, 40.0)),
        ("BOTTOMLEFT", HEIGHT, None, (10.0, 20.0, 30.0, 40.0)),
        ("BOTTOMLEFT", None, HEIGHT, (10.0, 20.0, 30.0, 40.0)),
        ("BOTTOMLEFT", None, None, None),
        ("UNKNOWN", HEIGHT, HEIGHT, None),
        (None, HEIGHT, HEIGHT, None),
    ],
    ids=["top-left", "bottom-left", "manifest-height", "no-height", "unknown", "none"],
)
def test_a_box_in_the_spans_top_left_frame(origin, page_height, manifest_height, expected) -> None:
    spans = {1: _page(height=page_height)}

    assert top_left_box(_box(10, 20, 30, 40, origin), 1, spans, {1: manifest_height}) == expected


def test_the_spans_page_height_comes_before_the_manifest_s() -> None:
    box = OrientedBox(0.0, 700.0, 10.0, 690.0, "BOTTOMLEFT")

    assert top_left_box(box, 1, {1: _page(height=800.0)}, {1: 1000.0}) == (0.0, 100.0, 10.0, 110.0)
    assert top_left_box(box, 1, {}, {1: 1000.0}) == (0.0, 300.0, 10.0, 310.0)


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [(5.0, 5.0, True), (12.0, 5.0, True), (12.1, 5.0, False), (5.0, -2.0, True), (5.0, -2.1, False)],
)
def test_a_point_held_by_a_box_and_its_margin(x, y, expected) -> None:
    assert holds_point((0.0, 10.0, 10.0, 0.0), x, y, 2.0) is expected


def test_only_the_spans_centred_in_the_box_are_the_element_s_lines() -> None:
    spans = {1: _page(LINE, OTHER)}

    lines = span_lines_on_page([(1, _box(40, 85, 200, 105))], spans, {}, 1)

    assert [[span.text for span in line] for line in lines] == [["onde", "x", "= 1"]]


def test_a_span_centre_within_the_tolerance_is_kept() -> None:
    # The centre of "x" is at (82.5, 98.75).
    def lines(right: float) -> list[str]:
        found = span_lines_on_page([(1, _box(0, 85, right, 105))], {1: _page(LINE[:2])}, {}, 1)
        return [span.text for line in found for span in line]

    assert lines(82.5 - SPAN_BOX_TOLERANCE) == ["onde", "x"]
    assert lines(82.4 - SPAN_BOX_TOLERANCE) == ["onde"]


@pytest.mark.parametrize(
    ("placements", "spans"),
    [
        pytest.param([(1, None)], {1: _page(LINE)}, id="no-box"),
        pytest.param([(2, _box(40, 85, 200, 105))], {1: _page(LINE)}, id="other-page"),
        pytest.param([(1, _box(40, 85, 200, 105))], {}, id="no-spans"),
        pytest.param([(1, _box(40, 85, 200, 105))], {1: _page(LINE, rotation=90)}, id="rotated"),
        pytest.param([(1, _box(40, 85, 200, 105, "UNKNOWN"))], {1: _page(LINE)}, id="unknown-origin"),
    ],
)
def test_no_lines_without_a_placed_box_on_an_upright_page(placements, spans) -> None:
    assert span_lines_on_page(placements, spans, {}, 1) == []


def test_each_page_is_detected_on_its_own_and_its_runs_carry_it() -> None:
    page_two = {**_page([_span("y", "CMMI10", 80)]), "page_number": 2}
    spans = {1: _page(LINE), 2: page_two}
    placements = [(2, _box(40, 85, 200, 105)), (1, _box(40, 85, 200, 105)), (2, None)]

    detection = detect_inline_math_by_page(placements, spans, {})

    assert [(run.latex, run.page) for run in detection.runs] == [("y", 2), ("x=1", 1)]
    second = detection.runs[1]
    assert detection.flat[second.start:second.end] == second.flat


def test_no_box_no_detection() -> None:
    detection = detect_inline_math_by_page([(1, None)], {1: _page(LINE)}, {})

    assert detection.runs == [] and detection.flat == ""
