"""Pairing a block with a candidate block (docstruct.fusion.similarity).

Moved from the core's PDDL payload (#402); the core covers the same rule end
to end in tests/test_pddl_block_pairing.py.
"""

from __future__ import annotations

import pytest

from docstruct.fusion.similarity import iou, ordered_box, pair_block

BOX = (0.1, 0.1, 0.5, 0.2)


def _pair(box, text, boxes, texts, used=(), min_iou=0.3, min_text_ratio=0.8):
    return pair_block(box, text, boxes, texts, set(used), min_iou=min_iou, min_text_ratio=min_text_ratio)


def test_ordered_box() -> None:
    assert ordered_box(0.5, 0.2, 0.1, 0.1) == BOX
    assert ordered_box(*BOX) == BOX


def test_the_best_overlap_wins() -> None:
    boxes = [(0.1, 0.15, 0.5, 0.25), BOX, (0.6, 0.1, 0.9, 0.2)]

    assert _pair(BOX, "a", boxes, ["x", "y", "z"]) == 1
    assert _pair(BOX, "a", boxes, ["x", "y", "z"], used={1}) == 0


def test_the_overlap_threshold_is_inclusive() -> None:
    other = (0.1, 0.1, 0.5, 0.15)
    ratio = iou(BOX, other)

    assert _pair(BOX, "", [other], ["x"], min_iou=ratio) == 0
    assert _pair(BOX, "", [other], ["x"], min_iou=ratio + 1e-9) is None


def test_the_element_box_is_ordered_before_the_overlap() -> None:
    assert _pair((0.5, 0.2, 0.1, 0.1), "", [BOX], ["x"]) == 0


def test_candidates_without_a_box_pair_by_text() -> None:
    assert _pair(BOX, "o mesmo texto", [None, None], ["outro", " o  mesmo\ntexto "]) == 1


def test_without_a_box_the_text_pairs() -> None:
    assert _pair(None, "abcde", [], ["abcdx", "zzzzz"]) == 0
    assert _pair(None, "abcde", [], ["abcdx"], min_text_ratio=0.81) is None


def test_ties_go_to_the_later_candidate() -> None:
    assert _pair(BOX, "", [BOX, BOX], ["a", "b"]) == 1
    assert _pair(None, "mesmo", [], ["mesmo", "mesmo"]) == 1


@pytest.mark.parametrize(
    ("text", "texts", "used"),
    [
        pytest.param("  ", ["  "], (), id="blank"),
        pytest.param("abc", ["", None], (), id="no-candidate-text"),
        pytest.param("abc", ["abc"], (0,), id="used"),
        pytest.param("abc", [], (), id="no-candidates"),
    ],
)
def test_no_pair(text, texts, used) -> None:
    assert _pair(None, text, [], texts, used) is None


def test_a_non_string_candidate_text_is_compared_as_text() -> None:
    assert _pair(None, "12", [], [12]) == 0
