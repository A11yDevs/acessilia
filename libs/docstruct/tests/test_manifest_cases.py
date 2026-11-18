"""The shared contract cases break, or keep, what their names say (#470).

``docstruct.manifest_cases`` is run by the core, the SDK and the Toolbox
against their own models. Here docstruct checks the catalog itself: the
example is valid, each broken case is refused by exactly the rule its name
gives, and each supported case stays valid.
"""

from __future__ import annotations

import copy

import pytest

import docstruct.manifest as model
from docstruct.manifest_cases import (
    BROKEN,
    DOCUMENT_FIELDS,
    SUPPORTED,
    document_findings,
    example_document,
)

#: Each broken case's findings: the message's constant name, and the path of
#: a field finding. Only "page number 0 in provenance" breaks two rules, by
#: nature: page 0 is out of range and is no page of the document.
EXPECTED = {
    "duplicate element id": {("MSG_DUPLICATE_ELEMENT_IDS", None)},
    "empty id": {("MSG_FIELD_OUT_OF_RANGE", "elements[0].id")},
    "missing parent": {("MSG_UNKNOWN_PARENT", None)},
    "own parent": {("MSG_SELF_PARENT", None)},
    "parent cycle": {("MSG_PARENT_CYCLE", None)},
    "child parent reference disagrees with parent source reference": {
        ("MSG_PARENT_REF_MISMATCH", None),
    },
    "duplicate page number": {("MSG_DUPLICATE_PAGE_NUMBERS", None)},
    "page lists an unknown element": {("MSG_PAGE_UNKNOWN_ELEMENTS", None)},
    "page repeats an element": {("MSG_PAGE_DUPLICATE_ELEMENT_IDS", None)},
    "element references an unknown page": {("MSG_ELEMENT_UNKNOWN_PAGE", None)},
    "provenance references an unknown page": {
        ("MSG_PROVENANCE_UNKNOWN_PAGE", "elements[0].provenance[0]"),
    },
    "zero page width": {("MSG_FIELD_OUT_OF_RANGE", "pages[0].width")},
    "reading order below 1": {("MSG_FIELD_OUT_OF_RANGE", "elements[0].reading_order")},
    "negative hierarchy level": {("MSG_FIELD_OUT_OF_RANGE", "elements[0].hierarchy_level")},
    "unknown element type": {("MSG_FIELD_NOT_ALLOWED", "elements[0].type")},
    "confidence above 1": {("MSG_FIELD_OUT_OF_RANGE", "elements[0].confidence")},
    "page number 0 in provenance": {
        ("MSG_FIELD_OUT_OF_RANGE", "elements[0].provenance[0].page_number"),
        ("MSG_PROVENANCE_UNKNOWN_PAGE", "elements[0].provenance[0]"),
    },
    "unknown coordinate origin": {
        ("MSG_FIELD_NOT_ALLOWED", "elements[0].provenance[0].bbox.coord_origin"),
    },
    "negative char offset": {
        ("MSG_FIELD_OUT_OF_RANGE", "elements[0].provenance[0].char_start"),
    },
    "reversed char range": {("MSG_CHAR_RANGE_REVERSED", "elements[0].provenance[0]")},
    "one-letter language": {("MSG_FIELD_OUT_OF_RANGE", "language")},
    "empty title": {("MSG_FIELD_OUT_OF_RANGE", "title")},
    "unknown element field": {("refused", None)},
}

_NAMES = {getattr(model, name): name for name in dir(model) if name.startswith("MSG_")}


def _flat() -> dict:
    """No references and no parents: the shape the cases first assumed."""
    payload = example_document()
    for element in payload["elements"]:
        element.update(source_ref=None, parent_ref=None, parent_id=None)
    return payload


def _deeper_hierarchy() -> dict:
    """The example (the third element a child of the first), plus a fourth
    that is a child of the second: both elements the cases change have a
    child, with matching references (review of #591)."""
    payload = example_document()
    second, third = payload["elements"][1], payload["elements"][2]
    fourth = copy.deepcopy(third)
    fourth.update(
        id="element-000004", reading_order=4, text="text 4", source_ref="#/texts/3",
        parent_id=second["id"], parent_ref=second["source_ref"],
    )
    payload["elements"].append(fourth)
    payload["pages"][1]["element_ids"].append(fourth["id"])
    return payload


def _one_page() -> dict:
    """Everything on a single page, as in some of the Toolbox's snapshots:
    the cases need one page, not two (review of acessilia-toolbox#164)."""
    payload = example_document()
    moved = payload["pages"].pop()
    payload["pages"][0]["element_ids"].extend(moved["element_ids"])
    for element in payload["elements"]:
        element["page_number"] = 1
        for provenance in element["provenance"]:
            provenance["page_number"] = 1
    return payload


#: The documents each case is applied to: the example (references and one
#: child), a flat document, a deeper hierarchy, and a single page.
BASES = {
    "example": example_document,
    "flat": _flat,
    "deeper hierarchy": _deeper_hierarchy,
    "one page": _one_page,
}


def _findings(change, base: str = "example") -> set[tuple[str, str | None]]:
    payload = BASES[base]()
    change(payload)
    return {
        (_NAMES.get(message, message), context.get("path"))
        for message, context in document_findings(payload)
    }


@pytest.mark.parametrize("base", list(BASES))
def test_every_base_is_valid(base: str) -> None:
    assert document_findings(BASES[base]()) == []


def test_the_example_is_a_valid_document_part() -> None:
    example = example_document()

    assert set(example) == set(DOCUMENT_FIELDS)
    assert document_findings(example) == []


def test_each_call_returns_a_fresh_example() -> None:
    first = example_document()
    first["elements"].clear()

    assert example_document()["elements"]


def test_every_broken_case_has_its_expected_rule() -> None:
    assert set(EXPECTED) == set(BROKEN)


@pytest.mark.parametrize("base", list(BASES))
@pytest.mark.parametrize("case", list(BROKEN))
def test_a_broken_case_breaks_exactly_its_rule(case: str, base: str) -> None:
    assert _findings(BROKEN[case], base) == EXPECTED[case]


@pytest.mark.parametrize("base", list(BASES))
@pytest.mark.parametrize("case", list(SUPPORTED))
def test_a_supported_case_stays_valid(case: str, base: str) -> None:
    assert _findings(SUPPORTED[case], base) == set()


@pytest.mark.parametrize("case", list(BROKEN) + list(SUPPORTED))
def test_a_case_changes_only_the_document_fields(case: str) -> None:
    """A component applies the cases to its own manifest: they must leave
    its process fields alone."""
    payload = {**example_document(), "summary": {"page_count": 2}, "obligations": []}
    before = copy.deepcopy(payload)

    {**BROKEN, **SUPPORTED}[case](payload)

    assert {key: payload[key] for key in ("summary", "obligations")} == {
        key: before[key] for key in ("summary", "obligations")
    }
    assert set(payload) == set(before)


def test_a_case_changes_the_document_it_is_given() -> None:
    """The cases work on any document with a page and two elements, not
    only on the example: here, one with other ids and page numbers."""
    payload = example_document()
    renamed = {element["id"]: f"other-{index}" for index, element in enumerate(payload["elements"])}
    for element in payload["elements"]:
        element["id"] = renamed[element["id"]]
        if element["parent_id"] is not None:
            element["parent_id"] = renamed[element["parent_id"]]
    for page in payload["pages"]:
        page["element_ids"] = [renamed[item] for item in page["element_ids"]]
    assert document_findings(payload) == []

    for case, change in BROKEN.items():
        broken = copy.deepcopy(payload)
        change(broken)
        assert document_findings(broken), case
    for case, change in SUPPORTED.items():
        kept = copy.deepcopy(payload)
        change(kept)
        assert document_findings(kept) == [], case
