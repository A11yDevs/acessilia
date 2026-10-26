"""Tests for reattaching a detached negation slash (docstruct.text.negation_overlay).

The reference case is a legacy TeX text layer where "h ≠ 0" is extracted
as "h = 0" plus a separate U+0338 element; composing the wrong "=" would
invert a true statement, so ambiguity must leave the text alone.
"""
from __future__ import annotations

from docstruct.text.negation_overlay import (
    compose_negation,
    is_detached_overlay,
    locate_in_grid,
    locate_in_text,
    negates,
)

PARAGRAPH = (
    "Procedendo como acima, podemos construir uma tabela que fornece, para cada valor "
    "h = 0, a velocidade media do carro entre o instante inicial t = 2 e o instante "
    "final t = 2 + h . Listamos abaixo alguns valores dessa tabela:"
)


def test_relations_with_a_negated_form():
    assert all(negates(char) for char in "=<>∈⊂≤≥≡")
    assert not any(negates(char) for char in "a-+~0")


def test_detached_overlay_is_only_slashes():
    assert is_detached_overlay("̸")
    assert is_detached_overlay(" ̸\n")
    assert not is_detached_overlay("x̸")
    assert not is_detached_overlay("")
    assert not is_detached_overlay(None)


def test_compose_negation():
    assert compose_negation("h = 0", 2) == "h ≠ 0"
    assert compose_negation("x ∈ A", 2) == "x ∉ A"


def test_locates_the_relation_on_its_line():
    """Second line, at its left edge: the '=' of 'valor h = 0', not 't = 2'."""
    index = locate_in_text(PARAGRAPH, lines=3, line_position=1.1, x_fraction=0.02)
    assert index == PARAGRAPH.index("h = 0") + 2


def test_a_single_line_formula():
    text = "Dom( vm 2 ) = [ - 2 , 0) ∪ (0 , + ∞ ) = { h ∈ R : h ≥ - 2 e h = 0 } ."
    index = locate_in_text(text, lines=1, line_position=0.5, x_fraction=0.91)
    assert index == text.rindex("=")


def test_equidistant_candidates_are_ambiguous():
    assert locate_in_text("a = b = c", lines=1, line_position=0.0, x_fraction=0.5) is None


def test_neighbouring_candidates_are_ambiguous_even_at_distance_zero():
    """Two relations a couple of characters apart: the estimate is too rough."""
    text = "a=b=c"
    exact = text.index("=") / len(text)
    assert locate_in_text(text, lines=1, line_position=0.0, x_fraction=exact) is None


def test_a_slash_right_over_a_well_separated_relation_is_accepted():
    text = "x = y = z"
    exact = text.index("=") / len(text)
    assert locate_in_text(text, lines=1, line_position=0.0, x_fraction=exact) == 2


def test_a_candidate_off_the_estimated_line_is_refused():
    text = "a = b " + "x" * 200
    assert locate_in_text(text, lines=3, line_position=2.5, x_fraction=0.9) is None


def test_no_candidate():
    assert locate_in_text("sem relacao", lines=1, line_position=0, x_fraction=0.5) is None


def test_grid_picks_the_closest_column_in_the_row():
    rows = [["h = 0", "instante final t = 2+ h", "velocidade"], ["2", "4", "28"]]
    assert locate_in_grid(rows, row_position=0.5, column_position=0.25) == (0, 0, 2)


def test_grid_refuses_ambiguous_columns_and_cells():
    assert locate_in_grid([["x = 1", "y = 2"]], row_position=0.2, column_position=1.0) is None
    assert locate_in_grid([["a = b = c", "x"]], row_position=0.2, column_position=0.4) is None
    assert locate_in_grid([["a = b"]], row_position=3.0, column_position=0.5) is None
