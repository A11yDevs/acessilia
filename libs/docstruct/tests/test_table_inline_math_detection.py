"""Inline math of table cells from the text layer's fonts (#260).

The spans are the reference case's second table (page 5), as the Toolbox's
``document.text.spans`` returns them, with the prose words in English: the
fonts, sizes and boxes are the real ones.
"""
from docstruct.text.inline_math import (
    InlineMathDetection,
    InlineMathRun,
    TextSpan,
    assign_runs_to_cells,
    detect_inline_math,
    splice_inline_math,
)


def _spans(*parts):
    return [
        TextSpan(text, font, size, bbox, (bbox[0], baseline))
        for text, font, size, bbox, baseline in parts
    ]


HEADER = [
    _spans(("h", "CMMI12", 11.96, (180.12, 261.03, 186.85, 272.99), 270.00),
           ("̸", "CMSY10", 11.96, (186.85, 261.03, 186.85, 272.99), 270.00),
           (" = 0", "CMR12", 11.96, (186.85, 261.03, 208.53, 273.00), 270.00)),
    _spans(("final", "CMR12", 11.96, (220.44, 261.03, 261.04, 273.00), 270.00),
           (" ", "CMR12", 11.96, (261.04, 261.03, 265.08, 273.00), 270.00),
           ("time", "CMR12", 11.96, (265.08, 261.03, 287.16, 273.00), 270.00)),
    _spans(("mean", "CMR12", 11.96, (329.16, 261.03, 382.00, 273.00), 270.00),
           (" ", "CMR12", 11.96, (382.00, 261.03, 386.04, 273.00), 270.00),
           ("speed", "CMR12", 11.96, (386.04, 261.03, 416.49, 273.00), 270.00)),
    _spans(("t", "CMMI12", 11.96, (230.28, 278.43, 234.50, 290.39), 287.40),
           (" = 3 +", "CMR12", 11.96, (234.50, 278.43, 267.94, 290.40), 287.40),
           (" h", "CMMI12", 11.96, (267.94, 278.43, 277.33, 290.39), 287.40)),
    # The fraction: numerator and denominator at 8 pt, no rule in the text layer.
    _spans(("s", "CMMI8", 7.97, (349.08, 273.78, 352.99, 281.75), 281.64),
           ("(3+", "CMR8", 7.97, (353.04, 275.66, 367.06, 283.63), 281.64),
           ("h", "CMMI8", 7.97, (367.08, 273.78, 371.96, 281.75), 281.64),
           (")", "CMR8", 7.97, (372.00, 275.66, 375.29, 283.63), 281.64),
           ("−", "CMSY8", 7.97, (375.24, 273.88, 381.82, 281.85), 281.64),
           ("s", "CMMI8", 7.97, (381.84, 273.78, 385.75, 281.75), 281.64),
           ("(3)", "CMR8", 7.97, (385.80, 275.66, 396.53, 283.63), 281.64)),
    _spans(("(3+", "CMR8", 7.97, (356.28, 285.50, 370.30, 293.47), 291.48),
           ("h", "CMMI8", 7.97, (370.32, 283.62, 375.20, 291.59), 291.48),
           (")", "CMR8", 7.97, (375.24, 285.50, 378.53, 293.47), 291.48),
           ("−", "CMSY8", 7.97, (378.48, 283.72, 385.06, 291.69), 291.48),
           ("3", "CMR8", 7.97, (385.08, 285.50, 389.31, 293.47), 291.48)),
]
ROW = [
    _spans(("1", "CMR12", 11.96, (191.40, 297.03, 197.25, 309.00), 306.00)),
    _spans(("4", "CMR12", 11.96, (250.92, 297.03, 256.77, 309.00), 306.00)),
    _spans(("−", "CMSY10", 11.96, (299.16, 297.03, 308.45, 308.99), 306.00),
           ("0", "CMR12", 11.96, (308.40, 297.03, 314.25, 309.00), 306.00),
           (",", "CMMI12", 11.96, (314.28, 297.03, 317.52, 308.99), 306.00),
           (" 0833", "CMR12", 11.96, (317.52, 297.03, 343.05, 309.00), 306.00),
           (" ", "CMR12", 11.96, (343.05, 297.03, 346.80, 309.00), 306.00),
           ("(approximately)", "CMR12", 11.96, (346.80, 297.03, 446.38, 309.00), 306.00)),
]
FRACTION = r"\frac{s(3+h)-s(3)}{(3+h)-3}"
#: The cells as the structure extractor writes them.
CELLS = [
    "h ≠ 0", "final time t = 3+ h", "mean speed s (3+ h ) - s (3) (3+ h ) - 3",
    "1", "4", "- 0 , 0833 (approximately)",
]


def _latex(lines):
    return [run.latex for run in detect_inline_math(lines).runs]


def test_the_table_lines_give_each_cells_math():
    assert _latex(HEADER + ROW) == [r"h\neq0", "t=3+h", FRACTION, "-0,0833"]


def test_the_fraction_needs_the_text_around_it_to_be_larger():
    # Alone, the 8 pt lines are the body: two formulas, not a fraction.
    assert _latex(HEADER[4:6]) == ["s(3+h)-s(3)", "(3+h)-3"]


def test_lines_off_each_others_centre_are_not_a_fraction():
    shifted = [
        TextSpan(span.text, span.font, span.size,
                 (span.bbox[0] + 30, span.bbox[1], span.bbox[2] + 30, span.bbox[3]), span.origin)
        for span in HEADER[5]
    ]

    assert FRACTION not in _latex(HEADER[:5] + [shifted] + ROW)


def test_body_size_lines_stacked_are_not_a_fraction():
    upper = _spans(("x", "CMMI12", 11.96, (100.0, 261.0, 106.0, 273.0), 270.0),
                   (" = 1", "CMR12", 11.96, (106.0, 261.0, 128.0, 273.0), 270.0))
    lower = _spans(("y", "CMMI12", 11.96, (100.0, 275.0, 106.0, 287.0), 284.0),
                   (" = 2", "CMR12", 11.96, (106.0, 275.0, 128.0, 287.0), 284.0))

    assert _latex([upper, lower]) == ["x=1", "y=2"]


def test_a_math_comma_with_tex_spacing_between_digits_is_decimal():
    line = _spans(("x", "CMMI12", 11.96, (100.0, 261.0, 106.0, 273.0), 270.0),
                  (" = 2", "CMR12", 11.96, (106.0, 261.0, 128.0, 273.0), 270.0),
                  (",", "CMMI12", 11.96, (128.0, 261.0, 131.0, 273.0), 270.0),
                  (" 5", "CMR12", 11.96, (131.0, 261.0, 140.0, 273.0), 270.0))

    assert _latex([line]) == ["x=2,5"]


def test_a_text_comma_followed_by_a_space_is_prose():
    line = _spans(("x", "CMMI12", 11.96, (100.0, 261.0, 106.0, 273.0), 270.0),
                  (" = 2,", "CMR12", 11.96, (106.0, 261.0, 131.0, 273.0), 270.0),
                  (" 5", "CMR12", 11.96, (131.0, 261.0, 140.0, 273.0), 270.0))

    assert _latex([line]) == ["x=2"]


def test_the_runs_reach_their_cells():
    detections, left_out = assign_runs_to_cells(detect_inline_math(HEADER + ROW), CELLS)

    spliced = [splice_inline_math(cell, detection).text for cell, detection in zip(CELLS, detections)]
    assert spliced == [
        r"$h\neq0$", "final time $t=3+h$", f"mean speed ${FRACTION}$",
        "1", "4", "$-0,0833$ (approximately)",
    ]
    assert left_out == []


def _run(flat):
    return InlineMathRun(latex=flat, flat=flat, start=0, end=len(flat), bbox=(0, 0, 0, 0))


def test_a_cell_that_is_the_run_comes_first():
    detection = InlineMathDetection(flat="h", runs=[_run("h")])

    detections, left_out = assign_runs_to_cells(detection, ["t = 2+ h", "h"])

    assert [len(cell.runs) for cell in detections] == [0, 1]
    assert left_out == []


def test_identical_cells_take_the_occurrences_in_order():
    detection = InlineMathDetection(flat="x=1x=1", runs=[_run("x=1"), _run("x=1")])

    detections, _ = assign_runs_to_cells(detection, ["x = 1", "2", "x = 1"])

    assert [len(cell.runs) for cell in detections] == [1, 0, 1]
    assert detections[2].runs[0].start == 0


def test_a_run_two_different_cells_hold_is_left_out():
    detection = InlineMathDetection(flat="h", runs=[_run("h")])

    detections, left_out = assign_runs_to_cells(detection, ["t = 2+ h", "s ( h )"])

    assert all(not cell.runs for cell in detections)
    assert left_out == detection.runs


def test_masking_blanks_the_math_spans_and_keeps_the_indexes():
    from docstruct.text.math_spans import mask_inline_math

    text = "final time $t=3+h$ and h = 0"

    masked = mask_inline_math(text)

    assert len(masked) == len(text)
    assert "=" not in masked[:18]
    assert masked.index("=") == text.rindex("=")
