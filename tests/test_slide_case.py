"""Scorecard of the slide-deck case (scripts/bench/slide_case.py).

The case is synthetic, so the suite does not need the acessilia-dataset clone.
"""

import json

import pytest

from scripts.bench import slide_case
from scripts.bench.dataset_reference import EvaluationSelection

ROWS = [
    {"id": "s01-x01", "page": "1", "kind": "text", "expected": "Grandezas e Medidas"},
    {"id": "s01-i01", "page": "1", "kind": "image", "expected": "Atom;DNA;1 nm|1nm;spheres"},
    {"id": "s02-t01", "page": "2", "kind": "table", "expected": "rows=2;columns=3;header=1"},
    {"id": "s02-t01-h", "page": "2", "kind": "table-header", "expected": "Prefix | symbol | power"},
    {"id": "s02-t01-r01", "page": "2", "kind": "table-row", "expected": "yota | Y | 10²⁴"},
    {"id": "s02-t01-r02", "page": "2", "kind": "table-row", "expected": "zeta | Z | 10²¹"},
    {"id": "s02-f01", "page": "2", "kind": "formula", "expected": r"n = \frac{\text{massa}}{\text{Massa molar}}"},
]

EXPECTATIONS = {
    "text": {
        "must_not_match": [
            {"id": "undescribed-picture", "pattern": "Image without a text description"},
            {"id": "label-list-alt", "pattern": "(?:[^;\\s](?:[^;]{0,13}[^;\\s])?;\\s){3}"},
        ]
    },
    "structure": {"slide_count": 2},
}

GOOD = """Grandezas e Medidas
1.1 Slide 1 de 2: Grandezas e Medidas
The picture shows spheres: the Atom (1 nm), the DNA.
1.2 Slide 2 de 2
Prefix      symbol     power
yota        Y          10²⁴
zeta        Z          10²¹
n = massa / Massa molar
"""

#: The degraded output of 006.pdf v5: labels instead of a description, and a
#: table collapsed into one row.
DEGRADED = """Grandezas e Medidas
1.1 Slide 1 de 2: Grandezas e Medidas
Atom; DNA; 1nm; 10nm; Cells
1.2 Slide 2 de 2
Prefix symbol power
yota zeta exa peta tera giga mega kilo hecto deca  Y Z E P T G M k h da  10²⁴ 10²¹ 10¹⁸
Image without a text description.
"""


def _card(text, output="out"):
    return slide_case.score_text(ROWS, EXPECTATIONS, text, output)


def test_a_good_output_passes_every_object():
    card = _card(GOOD)

    assert card.slides_found == 2
    assert all(o.passed for o in card.objects), [o for o in card.objects if not o.passed]
    assert card.violations == {}


def test_a_degraded_output_fails_where_a_reader_loses_something():
    card = _card(DEGRADED)
    failed = {o.id for o in card.objects if not o.passed}

    # The labels alone miss what only a description says ("spheres").
    assert "s01-i01" in failed
    # The collapsed table: no row is found whole.
    assert {"s02-t01-r01", "s02-t01-r02"} <= failed
    assert card.violations == {1: ["label-list-alt"], 2: ["undescribed-picture"]}


#: A header cell that wraps, as pdftotext -layout prints 006.pdf slide 15:
#: its second line lands between the cells of the next line.
WRAPPED_LAYOUT = """1.1 Slide 1 de 2
1.2 Slide 2 de 2
            power of
Prefix      symbol    ten
yota        Y          10²⁴
"""
WRAPPED_STREAM = """1.1 Slide 1 de 2
1.2 Slide 2 de 2
Prefix
symbol
power of ten
yota Y 10²⁴
"""


def test_a_wrapped_header_cell_is_found_in_the_stream_order():
    rows = [
        {"id": "h", "page": "2", "kind": "table-header", "expected": "Prefix | symbol | power of ten"},
    ]

    layout_only = slide_case.score_text(rows, EXPECTATIONS, WRAPPED_LAYOUT, "out")
    both = slide_case.score_text(
        rows, EXPECTATIONS, WRAPPED_LAYOUT, "out", stream_text=WRAPPED_STREAM
    )

    assert not layout_only.objects[0].passed
    assert both.objects[0].passed
    # The report tells a row the layout lost from one it reads right.
    assert both.objects[0].detail == slide_case.STREAM_ORDER_DETAIL
    assert both.summary()["stream_order"] == 1
    assert "| Rows found only in stream order | 1 |" in both.to_markdown()
    assert "Rows found only in stream order: 0 → 1" in slide_case.compare(layout_only, both)


def test_a_heading_right_after_a_page_break_starts_its_slide():
    # pdftotext -raw ends a page with its footer number and no newline.
    text = "1.1 Slide 1 de 2\nintro\n1\f1.2 Slide 2 de 2\nPrefix symbol power\n"

    assert slide_case.split_slides(text).keys() == {1, 2}


def test_a_row_the_layout_reads_right_is_not_marked_as_stream_order():
    card = slide_case.score_text(ROWS, EXPECTATIONS, GOOD, "out", stream_text=GOOD)

    assert card.summary()["stream_order"] == 0


def test_compare_shows_a_row_that_moved_to_the_stream_order():
    rows = [
        {"id": "h", "page": "2", "kind": "table-header", "expected": "Prefix | symbol | power of ten"},
    ]
    layout_ok = WRAPPED_STREAM.replace("Prefix\nsymbol\npower of ten", "Prefix symbol power of ten")
    base = slide_case.score_text(rows, EXPECTATIONS, layout_ok, "v4", stream_text=WRAPPED_STREAM)
    candidate = slide_case.score_text(
        rows, EXPECTATIONS, WRAPPED_LAYOUT, "v5", stream_text=WRAPPED_STREAM
    )

    report = slide_case.compare(base, candidate)

    # Same score, but the layout lost the row: the slide is still listed.
    assert "| 2 · | 1/1 | 1/1 | +0 | 0 → 1 |  |" in report
    assert "Slides worse: none" in report


#: 006.pdf v5 slide 5 in stream order: the last names, then every symbol and
#: power, close enough for "deca | da | 10¹" to fit in ROW_GAP.
COLLAPSED_STREAM = """1.1 Slide 1 de 2
1.2 Slide 2 de 2
Prefix symbol power
yota zeta
Y Z 10²⁴ 10²¹
"""


def test_the_stream_order_does_not_rescue_a_collapsed_table():
    card = slide_case.score_text(
        ROWS, EXPECTATIONS, DEGRADED, "out", stream_text=COLLAPSED_STREAM
    )
    failed = {o.id for o in card.objects if not o.passed}

    assert {"s02-t01-r01", "s02-t01-r02"} <= failed


def test_a_printed_list_spaced_before_its_semicolons_is_not_a_label_list():
    text = "1.1 Slide 1 de 2\nNaCl ; C ; Na ; Fe; Al2O3 ; Fe3O4\n1.2 Slide 2 de 2\n"

    assert _card(text).violations == {}


def test_compare_names_the_slides_that_got_worse():
    report = slide_case.compare(_card(GOOD, "v4"), _card(DEGRADED, "v5"))

    assert "Slides worse: 1, 2" in report


@pytest.mark.parametrize(
    "printed, expected",
    [("10²⁴", "1024"), ("H₂SO₄", "h2so4"), ("1 µm", "1μm"), ("B—Cl", "b-cl"), ("apresen-\n tam", "apresentam")],
)
def test_normalization_reads_scripts_dashes_and_broken_lines_alike(printed, expected):
    assert slide_case.normalize(printed) == expected


def test_an_unknown_kind_is_refused():
    with pytest.raises(ValueError, match="unknown ground-truth kind"):
        slide_case.score_object({"id": "x", "page": "1", "kind": "chart", "expected": ""}, "")


def test_page_selection_filters_objects_and_dependent_expectations():
    card = slide_case.score_text(
        ROWS, EXPECTATIONS, GOOD, "out",
        selection=EvaluationSelection(pages=(1,)),
    )

    assert {item.id for item in card.objects} == {"s01-x01", "s01-i01"}
    assert all("p2" not in criterion_id for criterion_id in card.criteria_ids)
    assert any(item["id"] == "s02-t01-r01" for item in card.not_evaluated)
    assert any(item["id"] == "structure:slide-count" for item in card.not_evaluated)


def test_object_selection_keeps_only_that_criterion_and_reports_shape_limit():
    card = slide_case.score_text(
        ROWS, EXPECTATIONS, GOOD, "out",
        selection=EvaluationSelection(object_ids=("s02-t01-r01",)),
    )

    assert [item.id for item in card.objects] == ["s02-t01-r01"]
    assert card.criteria_ids == ["s02-t01-r01"]
    shape = next(item for item in card.not_evaluated if item["id"] == "s02-t01")
    assert "unsupported criterion" in shape["reason"]
    assert "not evaluated" in card.summary()["objects_passed"] or "1/1" in card.summary()["objects_passed"]


def test_task_selection_and_comparison_gate_require_identical_criteria():
    safety = slide_case.score_text(
        ROWS, EXPECTATIONS, GOOD, "out",
        selection=EvaluationSelection(tasks=("presentation_output_safety",)),
    )
    assert safety.objects == []
    assert safety.criteria_ids
    assert "not evaluated" in safety.summary()["objects_passed"]

    full = _card(GOOD)
    report = slide_case.compare(full, safety)
    assert report.startswith("COMPARABILITY: INCOMPARABLE")
    assert "No regression verdict" in report


def test_compare_requires_at_least_one_executed_criterion(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(slide_case, "resolve_case", lambda *args, **kwargs: (ROWS, EXPECTATIONS, {}))
    base = tmp_path / "base.txt"
    candidate = tmp_path / "candidate.txt"
    base.write_text(GOOD, encoding="utf-8")
    candidate.write_text(GOOD, encoding="utf-8")

    assert slide_case.main([
        "compare", str(base), str(candidate),
        "--task", "presentation_structure", "--object-id", "s02-t01",
    ]) == 2
    output = capsys.readouterr().out
    assert "COMPARABILITY: INSUFFICIENT EVIDENCE" in output
    assert "No regression verdict" in output
    assert "Slides worse" not in output


def test_missing_selected_slide_fails_its_safety_checks_and_comparison():
    selected = EvaluationSelection(pages=(1,))
    base = slide_case.score_text(
        ROWS, EXPECTATIONS, GOOD, "base.txt", selection=selected
    )
    candidate = slide_case.score_text(
        ROWS, EXPECTATIONS, "", "candidate.txt", selection=selected
    )

    assert base.safety_checks and all(check.passed for check in base.safety_checks)
    assert candidate.safety_checks and all(not check.passed for check in candidate.safety_checks)
    assert all(check.detail == "selected slide missing" for check in candidate.safety_checks)
    report = slide_case.compare(base, candidate)
    assert (
        "Checks worse: s01-i01, s01-x01, safety:label-list-alt:p1, safety:undescribed-picture:p1"
        in report
    )
    assert "Slides worse: 1" in report


def test_safety_task_scope_does_not_shrink_when_output_omits_a_slide():
    selection = EvaluationSelection(tasks=("presentation_output_safety",))
    base = slide_case.score_text(
        ROWS, EXPECTATIONS, GOOD, "base.txt", selection=selection
    )
    candidate = slide_case.score_text(
        ROWS, EXPECTATIONS, GOOD.split("Slide 2", 1)[0], "candidate.txt",
        selection=selection,
    )

    assert base.criteria_ids == candidate.criteria_ids
    assert {check.page for check in candidate.safety_checks if not check.passed} == {2}
    assert "Slides worse: 2" in slide_case.compare(base, candidate)


@pytest.mark.parametrize(
    "selection",
    (
        EvaluationSelection(tasks=("presentation_slide_content",)),
        EvaluationSelection(object_ids=("s01-i01",)),
    ),
)
def test_partial_image_evaluation_preserves_the_fallback_threshold(selection):
    text = "Slide 1 de 2\nAtom; DNA; 1 nm; Cells\n"
    full = slide_case.score_text(ROWS, EXPECTATIONS, text, "full.txt")
    partial = slide_case.score_text(ROWS, EXPECTATIONS, text, "partial.txt", selection=selection)

    image = next(item for item in full.objects if item.id == "s01-i01")
    assert image.score == 0.75
    assert not image.passed
    assert next(item for item in partial.objects if item.id == image.id) == image
    assert not partial.safety_checks


def test_comparison_reports_object_regression_when_slide_total_stays_equal():
    rows = [
        {"id": f"s01-{word}", "page": "1", "kind": "text", "expected": f"Phrase {word}"}
        for word in ("alpha", "beta")
    ]
    base = slide_case.score_text(rows, {}, "Slide 1 de 1\nPhrase alpha", "base.txt")
    candidate = slide_case.score_text(rows, {}, "Slide 1 de 1\nPhrase beta", "candidate.txt")

    report = slide_case.compare(base, candidate)
    assert "Objects passed: 1/2 → 1/2" in report
    assert "Checks worse: s01-alpha" in report
    assert "Checks improved: s01-beta" in report
    assert "Slides worse: 1" in report


def test_comparison_rejects_different_references_with_identical_criterion_ids():
    row = {"id": "s01-a", "page": "1", "kind": "text", "expected": "Alpha"}
    base = slide_case.score_text([row], {}, "Slide 1 de 1\nAlpha", "base.txt")
    candidate = slide_case.score_text(
        [{**row, "expected": "Beta"}], {}, "Slide 1 de 1\nBeta", "candidate.txt"
    )
    assert base.criteria_ids == candidate.criteria_ids
    assert "Dataset references_digest" in slide_case.compare(base, candidate)

    base.dataset.clear()
    candidate.dataset.clear()
    report = slide_case.compare(base, candidate)
    assert report.startswith("COMPARABILITY: INCOMPARABLE")
    assert "missing reference digest" in report


def test_page_selection_unknown_to_reference_is_an_error():
    with pytest.raises(slide_case.DatasetReferenceError, match="absent from the reference"):
        slide_case.score_text(ROWS, EXPECTATIONS, GOOD, "out", selection=EvaluationSelection(pages=(3,)))


def test_score_command_clears_previous_scorecards_when_retry_fails(tmp_path):
    root = tmp_path / "dataset"
    case = root / "input" / "presentation-reference"
    case.mkdir(parents=True)
    (case / "ground_truth.csv").write_text(
        "id,manifest_id,page,kind,expected\ns01-a,006,1,text,Alpha\n", encoding="utf-8"
    )
    (case / "expectations.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "slides.txt"
    output.write_text("Slide 1 de 1\nAlpha\n", encoding="utf-8")
    out = tmp_path / "out"
    args = ["--dataset", str(root), "score", "--txt", str(output), "--out", str(out)]

    assert slide_case.main(args) == 0
    assert (out / "scorecard.json").is_file()
    assert (out / "scorecard.md").is_file()

    saved = out / "saved-output.txt"
    output.rename(saved)
    assert slide_case.main(args) == 1
    assert not (out / "scorecard.json").exists()
    assert not (out / "scorecard.md").exists()
    assert saved.is_file()
    metadata = json.loads((out / "run-metadata.json").read_text(encoding="utf-8"))
    assert metadata["status"] == "missing_artifact"


def test_cross_format_comparison_requires_an_explicit_extraction_protocol():
    base = slide_case.score_text(ROWS, EXPECTATIONS, GOOD, "base.txt")
    candidate = slide_case.score_text(ROWS, EXPECTATIONS, GOOD, "candidate.pdf", stream_text=GOOD)

    assert slide_case.compare(base, candidate).startswith("COMPARABILITY: INCOMPARABLE")
    accepted = slide_case.compare(
        base, candidate, cross_format_method="pdftotext-layout-raw-v1"
    )
    assert "Cross-format extraction: pdftotext-layout-raw-v1" in accepted
    allowed = slide_case.compare(
        base, candidate, cross_format_method="pdftotext-layout-raw-v1"
    )
    assert not allowed.startswith("COMPARABILITY: INCOMPARABLE")
