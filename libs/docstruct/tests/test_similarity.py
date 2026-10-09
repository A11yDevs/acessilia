"""Counterexamples for OCR comparison in swallowing and deduplication guards."""
import pytest

from docstruct.fusion.similarity import is_duplicate, swallows


@pytest.mark.parametrize("left,right", [
    ("Resultado com 1.5 unidades previsto", "Resultado com 15 unidades previsto"),
    ("Resultado 50% confirmado para este grupo", "Resultado 50 confirmado para este grupo"),
    ("Resultado x+y confirmado para este grupo", "Resultado xy confirmado para este grupo"),
    ("Resultado -15 confirmado para este grupo", "Resultado 15 confirmado para este grupo"),
])
def test_punctuation_differences_do_not_make_distinct_texts_identical(left, right):
    assert not swallows(left, [right])


def test_missing_ocr_spaces_still_match():
    assert swallows("Um resultado representativo deste documento", [
        "Umresultadorepresentativodestedocumento",
    ])


def test_word_broken_at_a_line_end_matches_rejoined_word():
    assert swallows("Um resultado repre-\nsentativo deste documento", [
        "Um resultado representativo deste documento",
    ])


@pytest.mark.parametrize("left,right", [
    ("Calibration target for this group is 1.5 units", "Calibration target for this group is 15 units"),
    ("Result of the treatment is 50% for this group", "Result of the treatment is 50 for this group"),
    ("Reported reading for this group is -15 units", "Reported reading for this group is 15 units"),
    ("Calculated result for this group is x+y units", "Calculated result for this group is xy units"),
    ("This long paragraph contains important context. " * 4 + "The final reading is 1.5 units.",
     "This long paragraph contains important context. " * 4 + "The final reading is 15 units."),
])
def test_deduplication_preserves_different_values_even_with_long_shared_context(left, right):
    assert not is_duplicate(left, [right])


def test_deduplication_still_handles_missing_ocr_spaces_and_end_line_hyphenation():
    assert is_duplicate("Um resultado repre-\nsentativo deste documento", [
        "Umresultadorepresentativodestedocumento",
    ])
