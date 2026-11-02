"""Scorecard of the whole-document math case (scripts/bench/math_case.py).

The case files are synthetic and written per test, so the suite does not need
the acessilia-dataset clone; tests/test_math_case_e2e.py runs the real one.
"""

import json

import pytest

from scripts.bench import math_case

ROWS = [
    {"id": "p1-d01", "page": "1", "kind": "display", "expected_latex": r"s(t) = \frac{1}{2} a t^2"},
    {"id": "p1-d02", "page": "1", "kind": "display", "expected_latex": r"v(t) = v_0 + a t \tag{1}"},
    {"id": "p2-d01", "page": "2", "kind": "display", "expected_latex": r"\lim_{h \to 0} f(h) = 12"},
    {"id": "p1-i01", "page": "1", "kind": "inline", "expected_latex": r"s_0 \in \mathbb{R}"},
    {"id": "p1-i02", "page": "1", "kind": "inline", "expected_latex": r"t^3"},
    {"id": "p2-t01", "page": "2", "kind": "table-header", "expected_latex": r"h \neq 0"},
    {"id": "p2-t02", "page": "2", "kind": "table-cell", "expected_latex": "-0{,}0833"},
]

EXPECTATIONS = {
    "text": {
        "must_match": [{"id": "not-equal", "pattern": "≠"}],
        "must_not_match": [
            {"id": "orphan-negation", "pattern": "(?<![=<>∈])\\u0338"},
        ],
    },
    "structure": {
        "headings": [{"page": 1, "text": "Calculus", "level": 1}, {"page": 2, "text": "Task", "level": 2}],
        "page_numbers": {"pages": [1, 2], "is_furniture": True},
        "auto_numbered_headings": False,
        "ordered_lists": [{"page": 2, "items": 2, "first_item_starts": "First"}],
        "tables": [{"page": 2, "rows": 2, "columns": 2}],
        "equation_numbers": [{"formula": "p1-d02", "number": "1"}],
    },
    "speech": {"formulas": [{"formula": "p2-d01", "any_of": ["limit"]}]},
}


def _block(id_, type_, page, **fields):
    return {"id": id_, "type": type_, "source_location": {"page_number": page}, **fields}


def _document(blocks, sections=None):
    return {"sections": sections or [{"id": "s1", "title": "Calculus", "level": 1, "blocks": blocks}]}


def _table(page, cells):
    return _block("t", "table", page, table_ast={
        "header": [{"cells": [{"text": cells[0][0]}, {"text": cells[0][1]}]}],
        "body": [{"cells": [{"text": c} for c in row]} for row in cells[1:]],
    })


GOOD = _document([], sections=[
    {"id": "s1", "title": "Calculus", "level": 1, "blocks": [
        _block("m1", "math", 1, text=r"$$s(t) = \frac{1}{2} a t^2$$", alt_text="s of t",
               metadata={"mathml": "<math/>", "formula_recognition": {"method": "math.recognize"}}),
        # The equation number comes as metadata instead of a \tag.
        _block("m2", "math", 1, text=r"v(t) = v_0 + a t", metadata={"equation_number": "1"}),
        _block("p1", "paragraph", 1, text=r"where $s_0 \in \mathbb{R}$ and $t^3$ hold"),
        # A lone digit that is not its page's number: a flattened numerator.
        _block("n1", "paragraph", 1, text="2"),
    ]},
    {"id": "s2", "title": "Task", "level": 2, "blocks": [
        _block("l1", "list", 2, ordered=True, items=["First item"]),
        _block("l2", "list", 2, ordered=True, items=["Second item"]),
        _table(2, [[r"$h \neq 0$", "value"], ["1", "−0,0833 (approx.)"]]),
        _block("m3", "math", 2, text=r"\lim_{h \to 0} f(h) = 12", alt_text="the limit of f"),
    ]},
])

# What a text-layer extraction delivers today.
FLAT = _document([
    _block("m1", "math", 1, text="s(t) = 1\n2\nat2"),
    _block("p1", "paragraph", 1, text="where s 0 ∈ R and t 3 hold"),
    _block("l1", "list", 2, ordered=False, items=["First item"]),
    _block("l2", "list", 2, ordered=False, items=["Second item"]),
    _table(2, [["h = 0", "value"], ["1", "0 , 0833"]]),
    _block("n2", "paragraph", 2, text="2"),
])


def test_a_faithful_document_passes_every_check():
    card = math_case.score_case(
        ROWS, EXPECTATIONS, GOOD, txt="h ≠ 0\nbody\n", pdf_text="Calculus\nTask\nh ≠ 0\n"
    )
    summary = card.summary()

    assert summary["display_found"] == 100.0
    # p1-d02 keeps its subscript but not the \tag: (100 + 50 + 100) / 3.
    assert summary["display_structure_recall"] == pytest.approx(83.3)
    assert summary["display_with_mathml"] == pytest.approx(33.3)
    assert summary["display_methods"] == {"math.recognize": 1, "extractor": 2}
    assert summary["inline_as_math"] == 100.0
    assert summary["table_math_cells"] == 100.0
    assert [c for c in (*card.text, *card.structure, *card.speech) if not c.passed] == []


def test_a_flattened_document_scores_the_losses():
    card = math_case.score_case(ROWS, EXPECTATIONS, FLAT, txt="h = 0\n̸\n2\n")
    summary = card.summary()
    failed = {c.id for c in (*card.text, *card.structure, *card.speech) if not c.passed}

    flat = card.display[0]
    assert flat["matched"] == "m1"
    assert flat["structure_recall"] == 0.0
    # Bag-of-token CDM still credits the letters; the structure recall does not.
    assert flat["cdm"] > 90
    assert summary["display_found"] == pytest.approx(33.3)
    assert summary["inline_as_math"] == 0.0
    assert summary["table_math_cells"] == 0.0
    assert failed == {
        "txt:not-equal", "txt:orphan-negation", "page-numbers:not-in-body",
        "heading:Task", "ordered-list:p2", "equation-number:p1-d02", "speech:p2-d01",
    }


def test_formulas_match_on_their_own_page_only():
    document = _document([_block("m", "math", 2, text=r"s(t) = \frac{1}{2} a t^2")])
    card = math_case.score_case(ROWS[:1], {}, document, txt="")

    assert card.display[0]["matched"] is None
    assert card.display[0]["cdm"] == 0.0


def test_one_block_is_never_matched_to_two_formulas():
    rows = [dict(ROWS[0], id="a"), dict(ROWS[0], id="b")]
    document = _document([_block("m", "math", 1, text=r"s(t) = \frac{1}{2} a t^2")])
    card = math_case.score_case(rows, {}, document, txt="")

    assert sorted(d["matched"] or "" for d in card.display) == ["", "m"]


def test_a_heading_on_another_page_does_not_count():
    document = _document([_block("h", "heading", 3, text="Task", level=2)], sections=[])
    card = math_case.score_case([], EXPECTATIONS, document, txt="")

    check = next(c for c in card.structure if c.id == "heading:Task")
    assert not check.passed
    assert check.detail == "not a heading"


def test_auto_numbered_headings_are_reported_from_the_pdf_text():
    card = math_case.score_case([], EXPECTATIONS, GOOD, txt="", pdf_text="1 Calculus\n1.1 Task\n")

    check = next(c for c in card.structure if c.id == "headings:not-auto-numbered")
    assert not check.passed
    assert "Calculus" in check.detail


def test_structure_recall_ignores_formulas_without_structure():
    assert math_case.structure_recall("x + 1", "x + 1") is None
    assert math_case.structure_recall(r"x^{2}", r"x^2 + y_1") == 50.0


def test_load_case_names_the_missing_clone(tmp_path):
    with pytest.raises(FileNotFoundError, match="acessilia-dataset"):
        math_case.load_case(tmp_path)


def test_score_command_writes_the_scorecard(tmp_path, capsys):
    case = tmp_path / "dataset" / "input" / "math-reference"
    case.mkdir(parents=True)
    with open(case / "ground_truth.csv", "w", encoding="utf-8", newline="") as fh:
        fh.write("id,manifest_id,page,kind,expected_latex,context,notes\n")
        fh.write('p1-d01,036,1,display,"x^2",,\n')
    (case / "expectations.json").write_text(json.dumps({"text": {}}), encoding="utf-8")
    canonical = tmp_path / "doc.json"
    canonical.write_text(json.dumps(_document([_block("m", "math", 1, text="x^2")])), encoding="utf-8")
    txt = tmp_path / "doc.txt"
    txt.write_text("x", encoding="utf-8")

    code = math_case.main([
        "--dataset", str(tmp_path / "dataset"), "score",
        "--canonical", str(canonical), "--txt", str(txt), "--out", str(tmp_path / "out"),
    ])

    assert code == 0
    assert "| Display CDM (mean) | 100.0 |" in capsys.readouterr().out
    report = json.loads((tmp_path / "out" / "scorecard.json").read_text(encoding="utf-8"))
    assert report["summary"]["display_formulas"] == 1
    assert (tmp_path / "out" / "scorecard.md").exists()


def test_structure_recall_sees_set_braces():
    # The CDM tokenizer drops every brace; the recall must still see \{ \}.
    assert math_case.structure_recall(r"h \in R : h \geq 0", r"\{h \in R : h \geq 0\}") == 50.0
    assert math_case.structure_recall(r"\{h \in R : h \geq 0\}", r"\{h \in R : h \geq 0\}") == 100.0


def test_display_delimiters_in_a_table_cell_count_as_math():
    for cell in (r"$$h \neq 0$$", r"\[h \neq 0\]"):
        document = _document([_table(2, [[cell, "v"], ["1", "2"]])])
        card = math_case.score_case([ROWS[5]], {}, document, txt="")

        assert card.tables[0]["as_math"], cell


def test_a_formula_inside_a_list_item_does_not_split_the_list():
    document = _document([
        _block("l1", "list", 2, ordered=True, items=["First item, whose formula is"]),
        _block("m", "math", 2, text=r"\frac{a}{b}"),
        _block("l2", "list", 2, ordered=True, items=["Second item"]),
        _block("p", "paragraph", 2, text="After the list."),
        _block("l3", "list", 2, ordered=True, items=["Another list"]),
    ])
    card = math_case.score_case([], {"structure": EXPECTATIONS["structure"]}, document, txt="")

    check = next(c for c in card.structure if c.id == "ordered-list:p2")
    assert check.passed, check.detail


def test_the_scorecard_says_which_outputs_it_scored():
    txt_only = math_case.score_case([], EXPECTATIONS, GOOD, txt="h ≠ 0\n")
    both = math_case.score_case([], EXPECTATIONS, GOOD, txt="h ≠ 0\n", pdf_text="h ≠ 0\n")

    assert txt_only.summary()["outputs"] == ["txt"]
    assert both.summary()["outputs"] == ["txt", "pdf_ua"]
    assert "| Outputs scored | txt, pdf_ua |" in both.to_markdown()


@pytest.mark.parametrize("continuation", ["paragraph", "table"])
def test_numbered_list_continues_across_item_content(continuation):
    document = _document([
        _block("l1", "list", 2, ordered=True, items=["First item"]),
        _block("content", continuation, 2, text="Content of the first item"),
        _block("l2", "list", 2, ordered=True, start=2, items=["Second item"]),
    ])
    card = math_case.score_case([], {"structure": EXPECTATIONS["structure"]}, document, txt="")
    check = next(c for c in card.structure if c.id == "ordered-list:p2")
    assert check.passed, check.detail


@pytest.mark.parametrize("next_fields", [
    {"ordered": True},
    {"ordered": True, "start": 3},
    {"ordered": False, "start": 2},
    {"ordered": True, "start": 2, "numbering": "lower-alpha"},
])
def test_list_content_does_not_join_an_unrelated_list(next_fields):
    blocks = [
        _block("l1", "list", 2, ordered=True, items=["First item"]),
        _block("p", "paragraph", 2, text="After the list"),
        _block("l2", "list", 2, items=["Unrelated item"], **next_fields),
    ]
    assert len(math_case._list_runs(blocks, 2)) == 2


@pytest.mark.parametrize("boundary,page", [("heading", 2), ("paragraph", 3)])
def test_numbered_list_continuation_stops_at_a_heading_or_page(boundary, page):
    blocks = [
        _block("l1", "list", 2, ordered=True, items=["First item"]),
        _block("boundary", boundary, page, text="New section or page"),
        _block("l2", "list", 2, ordered=True, start=2, items=["Second item"]),
    ]
    assert len(math_case._list_runs(blocks, 2)) == 2


def test_explicit_continuation_follows_multiple_legacy_item_blocks():
    blocks = [
        _block("l1", "list", 2, ordered=True, items=["First"]),
        _block("l2", "list", 2, ordered=True, items=["Second"]),
        _block("t", "table", 2),
        _block("l3", "list", 2, ordered=True, start=3, items=["Third"]),
    ]
    assert math_case._list_runs(blocks, 2) == [
        {"ordered": True, "items": ["First", "Second", "Third"]}
    ]


@pytest.mark.parametrize("second_start", [None, 1])
def test_adjacent_lists_with_different_parents_do_not_hide_a_restart(second_start):
    second = _block("l2", "list", 2, ordered=True, items=["C"],
                    metadata={"parent_id": "second-list"})
    if second_start is not None:
        second["start"] = second_start
    blocks = [
        _block("l1", "list", 2, ordered=True, items=["A", "B"],
               metadata={"parent_id": "first-list"}),
        second,
    ]
    assert [run["items"] for run in math_case._list_runs(blocks, 2)] == [["A", "B"], ["C"]]


@pytest.mark.parametrize("content", [None, "math", "paragraph", "table"])
def test_explicit_continuation_can_change_source_parent(content):
    blocks = [_block("l1", "list", 2, ordered=True, items=["A"],
                     metadata={"parent_id": "first-list"})]
    if content:
        blocks.append(_block("content", content, 2))
    blocks.append(_block("l2", "list", 2, ordered=True, start=2, items=["B"],
                         metadata={"parent_id": "second-list"}))
    assert [run["items"] for run in math_case._list_runs(blocks, 2)] == [["A", "B"]]


@pytest.mark.parametrize("boundary", ["code", "image", "note", "warning", "details", "quote", "unknown"])
def test_non_item_content_ends_a_list_run(boundary):
    blocks = [
        _block("l1", "list", 2, ordered=True, items=["A"]),
        _block("boundary", boundary, 2),
        _block("l2", "list", 2, ordered=True, start=2, items=["B"]),
    ]
    assert [run["items"] for run in math_case._list_runs(blocks, 2)] == [["A"], ["B"]]
