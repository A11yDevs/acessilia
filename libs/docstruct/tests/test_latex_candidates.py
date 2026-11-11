"""A recognizer's LaTeX candidates, ranked (docstruct.text.latex.ranked_latex_candidates).

Moved from the core's PDDL payload (#402); the core covers it in
tests/test_formula_ranking.py and tests/test_formula_recognition.py.
"""

from __future__ import annotations

import math

import pytest

from docstruct.text.latex import bare_latex, normalize_latex, ranked_latex_candidates


def test_the_latex_is_only_stripped_of_its_delimiters() -> None:
    latex = "$x × y$"
    [candidate] = ranked_latex_candidates([{"latex": latex}])

    assert candidate["latex"] == bare_latex(latex) == "x × y"
    assert normalize_latex(latex) == r"x \times y"


def test_by_decreasing_confidence_with_ties_in_order() -> None:
    result = ranked_latex_candidates([
        {"latex": "a"}, {"latex": "b", "confidence": 0.7}, {"latex": "c", "confidence": 0.0}, {"latex": "d"},
    ])

    assert [c["latex"] for c in result] == ["b", "a", "c", "d"]


@pytest.mark.parametrize("confidence", [True, math.nan, math.inf, "0.9", None])
def test_a_confidence_that_is_not_a_finite_number_is_none(confidence) -> None:
    assert ranked_latex_candidates([{"latex": "x", "confidence": confidence}])[0]["confidence"] is None


def test_empty_latex_is_left_out() -> None:
    assert ranked_latex_candidates([{"latex": " $$ $$ "}, {"latex": None}, {}]) == []
