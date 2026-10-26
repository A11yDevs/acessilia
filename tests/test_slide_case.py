"""Scorecard of the slide-deck case (scripts/bench/slide_case.py).

The case is synthetic, so the suite does not need the acessilia-dataset clone.
"""

import pytest

from scripts.bench import slide_case

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
