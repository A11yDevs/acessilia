"""Ranking the recognizer's formula candidates (#402).

Characterization of the orchestrator's ``_ranked_formula_candidates``, written
on develop before it moved to docstruct, as
``docstruct.text.latex.ranked_latex_candidates``. The
existing tests in tests/test_formula_recognition.py cover the main ranking;
these pin the edges.
"""

from __future__ import annotations

import copy

from docstruct.text.latex import ranked_latex_candidates as ranked


def test_a_confidence_keeps_its_type_and_other_keys_stay() -> None:
    result = ranked([{"latex": "x", "confidence": 1, "bbox": [0, 0, 1, 1], "page": 3}])

    assert result == [{"latex": "x", "confidence": 1, "bbox": [0, 0, 1, 1], "page": 3}]
    assert type(result[0]["confidence"]) is int


def test_a_confidence_that_is_not_a_number_becomes_none() -> None:
    result = ranked([{"latex": "s", "confidence": "0.9"}, {"latex": "l", "confidence": [1]}])

    assert [c["confidence"] for c in result] == [None, None]


def test_a_negative_confidence_ranks_below_none() -> None:
    result = ranked([{"latex": "neg", "confidence": -0.5}, {"latex": "none"}, {"latex": "zero", "confidence": 0}])

    assert [c["latex"] for c in result] == ["none", "zero", "neg"]


def test_the_latex_is_read_as_text_and_normalized() -> None:
    result = ranked([{"latex": None}, {"latex": 12}, {"latex": "  $$x^2$$  "}, {}])

    assert [c["latex"] for c in result] == ["12", "x^2"]


def test_the_input_is_left_as_it_was() -> None:
    candidates = [{"latex": "$a$", "confidence": float("nan")}, {"latex": "b", "confidence": 0.5}]
    before = copy.deepcopy(candidates)

    ranked(iter(candidates))

    assert repr(candidates) == repr(before)
