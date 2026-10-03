"""Counterexamples for OCR normalization used by the swallowing guard."""
import pytest

from docstruct.fusion.similarity import swallows


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
