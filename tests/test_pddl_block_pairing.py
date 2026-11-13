"""Pairing a manifest element with a secondary provider's block (#402).

Characterization of the orchestrator's ``_pair_block``, written on develop
before its matching rule moved to docstruct. The skeleton order and the table
fusion call it; tests/test_provider_choice_methods.py covers them end to end.
"""

from __future__ import annotations

import pytest

from backend.core.pipeline.secondary import (
    _SecondaryExtraction,
    _pair_block,
)
from backend.core.manifest.models import BoundingBox, PageDescriptor, Provenance
from tests.pddl_support import build_element, build_manifest

W, H = 600.0, 800.0


def _element(text, box=None):
    element = build_element("e1", "paragraph", text=text)
    element.page_number = 1
    element.provenance = [] if box is None else [Provenance(page_number=1, bbox=BoundingBox(
        left=box[0], top=box[1], right=box[2], bottom=box[3], coord_origin="TOPLEFT"))]
    return element


def _block(text, box=None):
    block = {"type": "text", "text": text, "page_number": 1}
    if box is not None:
        block["provenance"] = [{"page_number": 1, "bbox": {
            "left": box[0], "top": H - box[1], "right": box[2], "bottom": H - box[3],
            "coord_origin": "BOTTOMLEFT"}}]
    return block


def _pair(element, blocks, used=()):
    manifest = build_manifest([element], [])
    manifest.pages = [PageDescriptor(page_number=1, width=W, height=H, element_ids=["e1"])]
    secondary = _SecondaryExtraction(provider="mineru", pages={1: blocks}, sizes={1: (W, H)})
    return _pair_block(element, manifest, blocks, secondary, set(used))


BOX = (60, 80, 300, 160)


def test_the_block_with_the_best_overlap_is_paired() -> None:
    blocks = [_block("x", (60, 120, 300, 200)), _block("y", BOX), _block("z", (320, 80, 560, 160))]

    assert _pair(_element("texto", BOX), blocks) == 1


def test_a_used_block_is_skipped() -> None:
    blocks = [_block("x", (60, 120, 300, 200)), _block("y", BOX)]

    assert _pair(_element("texto", BOX), blocks, used={1}) == 0


def test_an_overlap_below_the_threshold_falls_back_to_the_text() -> None:
    # IoU of (60, 80, 300, 160) and (60, 140, 300, 220) is 20 / 140 < 0.3.
    blocks = [_block("outro", (60, 140, 300, 220)), _block("o mesmo texto aqui", (320, 400, 560, 500))]

    assert _pair(_element("o mesmo texto aqui", BOX), blocks) == 1


def test_without_a_box_the_text_pairs_with_whitespace_folded() -> None:
    blocks = [_block("outra coisa"), _block("  o mesmo\n texto  ")]

    assert _pair(_element("o mesmo texto"), blocks) == 1


@pytest.mark.parametrize(
    ("text", "blocks"),
    [
        pytest.param("   ", [_block("   ")], id="blank-element"),
        pytest.param("abcdefghij", [_block("abcdefg...")], id="ratio-below"),
        pytest.param("abc", [_block(""), {"type": "text", "page_number": 1}], id="no-candidate-text"),
        pytest.param("abc", [], id="no-candidates"),
    ],
)
def test_no_pair(text, blocks) -> None:
    assert _pair(_element(text), blocks) is None


def test_the_text_ratio_threshold_is_inclusive() -> None:
    # Ratio of "abcde" and "abcdx" is 0.8.
    assert _pair(_element("abcde"), [_block("abcdx")]) == 0


def test_ties_go_to_the_later_block() -> None:
    assert _pair(_element("texto", BOX), [_block("a", BOX), _block("b", BOX)]) == 1
    assert _pair(_element("mesmo"), [_block("mesmo"), _block("mesmo")]) == 1


def test_a_reversed_element_box_is_ordered_first() -> None:
    reversed_box = (BOX[2], BOX[3], BOX[0], BOX[1])

    assert _pair(_element("texto", reversed_box), [_block("x", BOX)]) == 0
