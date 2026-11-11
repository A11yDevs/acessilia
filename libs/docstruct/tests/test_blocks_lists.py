"""Lettered-list recovery and list-block merging (docstruct.blocks.lists).

Both moved here from the core's PDDL payload (#402, Phase 3), where the same
behaviour is also covered end to end (tests/test_pddl_payload_lists_and_callouts.py).
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

import pytest

from docstruct.blocks.lists import (
    LETTERED_LIST_SOURCE_MARKER,
    LetteredListRecovery,
    merge_list_blocks,
    recover_empty_lettered_list_items,
)
from docstruct.manifest import DocumentElement


@dataclass
class Element:
    """The attributes ``ListSourceElement`` asks for, and nothing else."""

    id: str
    type: str
    reading_order: int
    text: str | None = ""
    parent_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def _item(order: int, marker: str = "", parent: str = "list") -> Element:
    return Element(f"i{order}", "list_item", order, "", parent, {"marker": marker})


def _para(order: int, text: str, kind: str = "paragraph") -> Element:
    return Element(f"p{order}", kind, order, text)


def _empty() -> LetteredListRecovery:
    return LetteredListRecovery({}, {}, {})


# recover_empty_lettered_list_items


def test_a_sibling_paragraph_fills_the_empty_items_and_keeps_its_prefix() -> None:
    elements = [
        _para(1, "Calculate: a) Alpha b) Beta"),
        _item(2, "a)"),
        _item(3, "b)"),
    ]

    recovery = recover_empty_lettered_list_items(elements)

    assert recovery.items == {"i2": ("Alpha", "a)"), "i3": ("Beta", "b)")}
    assert recovery.consumed == {"p1": "Calculate:"}
    assert recovery.preambles == {}


def test_a_prefix_after_the_first_item_becomes_its_preamble() -> None:
    elements = [_item(1, "a)"), _item(2, "b)"), _para(3, "Calculate: a) Alpha b) Beta")]

    recovery = recover_empty_lettered_list_items(elements)

    assert recovery.preambles == {"i1": ("p3", "Calculate:")}
    assert recovery.consumed == {"p3": ""}


def test_items_without_markers_and_an_unknown_source_are_recovered() -> None:
    elements = [_item(1), _item(2), _para(3, "a) Alpha b) Beta", kind="unknown")]

    recovery = recover_empty_lettered_list_items(elements)

    assert recovery.items == {"i1": ("Alpha", "a)"), "i2": ("Beta", "b)")}


@pytest.mark.parametrize(
    "elements",
    [
        pytest.param([_item(1, "a)"), _item(2, "b)")], id="no-source"),
        pytest.param([_item(1, "a)"), _para(2, "a) Alpha")], id="single-item"),
        pytest.param([_item(1, "1."), _item(2, "2."), _para(3, "a) A b) B")], id="decimal"),
        pytest.param([_item(1, "a)"), _item(2, "c)"), _para(3, "a) A b) B")], id="known-mismatch"),
        pytest.param([_item(1, "a)"), _item(2, "b)"), _para(3, "a) A b) B c) C")], id="count"),
        pytest.param([_item(1, "a)"), _item(2, "b)"), _para(3, "b) A c) B")], id="not-from-a"),
        pytest.param([_item(1, "a)"), _item(2, "b)"), _para(3, "(a) A (b) B")], id="prose"),
        pytest.param(
            [_item(1, "a)"), _item(2, "b)"), _para(3, "a) A b) B"), _para(4, "a) C b) D")],
            id="two-sources",
        ),
        pytest.param(
            [_item(1, "a)", "x"), _item(2, "b)", "x"), _item(3, "a)", "y"), _item(4, "b)", "y"),
             _para(5, "a) A b) B")],
            id="two-groups",
        ),
        pytest.param(
            [_item(1, "a)"), _item(2, "b)"), _para(3, "Exercise", kind="heading"),
             _para(4, "a) A b) B")],
            id="other-section",
        ),
    ],
)
def test_nothing_is_recovered_unless_one_source_fits_one_group_exactly(elements) -> None:
    assert recover_empty_lettered_list_items(elements) == _empty()


def test_the_elements_are_read_and_never_changed() -> None:
    elements = [_item(1, "a)"), _item(2, "b)"), _para(3, "Calculate: a) Alpha b) Beta")]
    before = copy.deepcopy(elements)

    recover_empty_lettered_list_items(elements)

    assert elements == before


def test_docstruct_document_elements_are_list_sources() -> None:
    def element(order: int, kind: str, text: str, **extra: Any) -> DocumentElement:
        return DocumentElement(
            id=f"e{order}", type=kind, raw_label=kind, reading_order=order,
            hierarchy_level=1, text=text, **extra,
        )

    elements = [
        element(1, "list_item", "", parent_id="L", metadata={"marker": "a)"}),
        element(2, "list_item", "", parent_id="L", metadata={"marker": "b)"}),
        element(3, "paragraph", "a) Alpha b) Beta"),
    ]

    assert recover_empty_lettered_list_items(elements).items == {
        "e1": ("Alpha", "a)"), "e2": ("Beta", "b)"),
    }


@pytest.mark.parametrize(
    ("text", "markers"),
    [("a) x", ["a"]), ("x a) y b) z", ["a", "b"]), ("(a) x", []), ("x(a) y", []), ("a)x", [])],
)
def test_the_source_marker_is_a_letter_and_a_parenthesis_after_whitespace(text, markers) -> None:
    assert [m.group("marker") for m in LETTERED_LIST_SOURCE_MARKER.finditer(text)] == markers


# merge_list_blocks


def _list(items: list[str], parent: str | None, ordered: bool = True) -> dict[str, Any]:
    metadata = {"parent_id": parent} if parent else {}
    return {"type": "list", "ordered": ordered, "items": items, "metadata": metadata}


def test_consecutive_items_of_one_source_list_become_one_list() -> None:
    blocks = [_list(["one"], "L"), _list(["two"], "L"), _list(["three"], "L")]

    merged = merge_list_blocks(blocks)

    assert len(merged) == 1
    assert merged[0]["items"] == ["one", "two", "three"]
    assert merged[0] is blocks[0]


@pytest.mark.parametrize(
    "between",
    [
        pytest.param({"type": "formula", "text": "x"}, id="formula"),
        pytest.param(_list(["other"], "M"), id="other-list"),
        pytest.param(_list(["bullet"], "L", ordered=False), id="other-kind"),
    ],
)
def test_a_block_in_between_keeps_the_lists_apart(between) -> None:
    merged = merge_list_blocks([_list(["one"], "L"), between, _list(["two"], "L")])

    assert len(merged) == 3


def test_lists_without_a_source_list_are_never_joined() -> None:
    assert len(merge_list_blocks([_list(["one"], None), _list(["two"], None)])) == 2
