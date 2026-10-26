"""Tables read with the right cells in the wrong shape (docstruct.tables.garble)."""

from __future__ import annotations

import pytest

from docstruct.tables.garble import table_garble_reason

#: 006.pdf slide 5, as the extractor read its table of multiples.
SLIDE_5 = [
    ["Prefix", "symbol", "power"],
    [
        "yota zeta exa peta tera giga mega kilo hecto deca",
        "Y Z E P T G M k h da",
        "10^24 10^21 10^18 10^15 10^12 10^9 10^6 10^3 10^2 10^1",
    ],
]

#: 006.pdf slide 15, as the extractor read its chlorine isotope table.
SLIDE_15 = [
    ["Naturally Occurring Isotopes of Chlorine Naturally Occurring Isotopes of Chlorine"],
    ["Isotopes Isotopes", "Atomic Mass (u) Atomic Mass (u)", "Abundance (%) Abundance (%)"],
    ["35Cl 35Cl", "34.97 34.97", "75.76 75.76"],
    ["37Cl 37Cl", "36.97 36.97", "24.24 24.24"],
]


def test_a_table_whose_rows_collapsed_into_one_is_named():
    assert table_garble_reason(SLIDE_5) == "collapsed_rows"


def test_a_table_whose_cells_are_doubled_is_named():
    assert table_garble_reason(SLIDE_15) == "duplicated_cells"


@pytest.mark.parametrize(
    "rows",
    [
        [["Isotope", "Mass", "Abundance"], ["35Cl", "34.97", "75.76"], ["37Cl", "36.97", "24.24"]],
        # Three words per cell is a real row of names.
        [["City", "State", "County"], ["New York City", "New York State", "Kings County NY"]],
        # Four values per cell, but the table already has as many rows.
        [["a b c d", "e f g h"]] * 4,
        # One cell repeated is a coincidence, not a doubled layer.
        [["Total Total", "12"], ["Mean", "3"], ["Max", "7"]],
        [],
    ],
    ids=["clean", "three-word-names", "enough-rows", "one-repeat", "empty"],
)
def test_a_table_read_well_is_not_named(rows):
    assert table_garble_reason(rows) is None
