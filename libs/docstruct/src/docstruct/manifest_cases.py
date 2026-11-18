"""Shared contract cases for the manifest's document part (#470, criterion 4).

The core, the SDK and the Toolbox each check a wire model of the processing
manifest against ``docstruct.manifest`` (the Toolbox adopts this catalog with
its pin of docstruct 0.5.5). Each used to break documents its own
way, so the three could drift apart on a case only one of them tested. This
module is the one catalog they all run:

- ``example_document()`` — a small valid document part (two pages, three
  elements, one of them a child), as the ``title``, ``language``, ``pages``
  and ``elements`` fields of a manifest payload;
- ``BROKEN`` — changes that make a document invalid. Each one names the rule
  it breaks;
- ``SUPPORTED`` — changes that a document may have and must stay valid;
- ``document_findings(payload)`` — docstruct's verdict on a payload: an empty
  list when it is valid.

The changes edit the document fields of a payload in place, so a component
applies them to its own manifest (with its own process fields) and compares
its model's verdict with ``document_findings``. A change only needs a document
with at least one page and two elements, the first element listed on a page
and holding a provenance entry: ``example_document()`` is one, and so are the
golden manifests of the core and the Toolbox's snapshots that meet these
conditions (001, 004, 007 and 008; 005 has one element). The changes keep a
hierarchy consistent: a new parent link carries the parent's ``source_ref``
as ``parent_ref``, and the children of an element whose id changes follow it.
A component whose manifest also summarizes the document (page and element
counts) recomputes that summary after a change, since the summary is not
docstruct's.

Pure data and functions: no file, no environment.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from docstruct.manifest import (
    structured_document_from_payload,
    validate_structured_document,
)

#: The manifest fields that make up the document part.
DOCUMENT_FIELDS: tuple[str, ...] = ("title", "language", "pages", "elements")

Change = Callable[[dict[str, Any]], None]


def example_document() -> dict[str, Any]:
    """A fresh, valid document part: two pages and three elements.

    Every element has a source reference, as the Toolbox's documents do, and
    the third is a child of the first, so the cases meet a hierarchy too.
    """

    def element(
        number: int, kind: str, page: int, order: int, **extra: Any
    ) -> dict[str, Any]:
        value = {
            "id": f"element-{number:06d}",
            "type": kind,
            "raw_label": kind,
            "reading_order": order,
            "hierarchy_level": 1,
            "text": f"text {number}",
            "source_ref": f"#/texts/{number - 1}",
            "parent_ref": "#/body",
            "parent_id": None,
            "page_number": page,
            "confidence": None,
            "provenance": [
                {
                    "page_number": page,
                    "bbox": {
                        "left": 20.0,
                        "top": 780.0 - 40.0 * order,
                        "right": 580.0,
                        "bottom": 750.0 - 40.0 * order,
                        "coord_origin": "BOTTOMLEFT",
                    },
                    "char_start": None,
                    "char_end": None,
                }
            ],
            "metadata": {},
        }
        value.update(extra)
        return value

    return {
        "title": "Shared contract example",
        "language": "en-US",
        "pages": [
            {"page_number": 1, "width": 600.0, "height": 800.0,
             "element_ids": ["element-000001", "element-000002"]},
            {"page_number": 2, "width": 600.0, "height": 800.0,
             "element_ids": ["element-000003"]},
        ],
        "elements": [
            element(1, "heading", 1, 1),
            element(2, "paragraph", 1, 2, confidence=0.9),
            element(
                3, "paragraph", 2, 3, parent_id="element-000001", parent_ref="#/texts/0"
            ),
        ],
    }


def document_findings(
    payload: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]]:
    """docstruct's verdict on the document part of ``payload``.

    An empty list when it is valid. A payload docstruct cannot even read (an
    unknown field, a value of the wrong shape) is one finding, ``"refused"``,
    with the reason.
    """
    try:
        document = structured_document_from_payload(payload)
    except (TypeError, ValueError) as exc:
        return [("refused", {"reason": str(exc)})]
    return validate_structured_document(document)


def _first(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["elements"][0]


def _second(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["elements"][1]


def _unlist(payload: dict[str, Any], element_id: str) -> None:
    """Remove ``element_id`` from every page's list."""
    for page in payload["pages"]:
        page["element_ids"] = [
            item for item in page["element_ids"] if item != element_id
        ]


def _children(payload: dict[str, Any], element_id: str) -> list[dict[str, Any]]:
    return [item for item in payload["elements"] if item.get("parent_id") == element_id]


def _point_to(child: dict[str, Any], parent: dict[str, Any]) -> None:
    """Make ``child`` a child of ``parent``, with the matching reference.

    A child's ``parent_ref``, when its parent has a ``source_ref``, must be
    that reference, so it follows the new parent: otherwise a hierarchy case
    would also break that rule (review of #591).
    """
    child["parent_id"] = parent["id"]
    child["parent_ref"] = parent.get("source_ref")


def _detach(element: dict[str, Any]) -> None:
    """``element`` becomes a root: no parent, no parent reference."""
    element["parent_id"] = None
    element["parent_ref"] = None


def _set(change: Callable[[dict[str, Any]], dict[str, Any]], **values: Any) -> Change:
    def apply(payload: dict[str, Any]) -> None:
        change(payload).update(values)

    return apply


def _duplicate_element_id(payload: dict[str, Any]) -> None:
    # The pages drop the second's old id, and the children of both become
    # roots (the shared id would resolve to either parent), so only the
    # duplicate is broken.
    old, shared = _second(payload)["id"], _first(payload)["id"]
    _unlist(payload, old)
    for child in _children(payload, old) + _children(payload, shared):
        _detach(child)
    _second(payload)["id"] = shared


def _empty_id(payload: dict[str, Any]) -> None:
    # The pages drop the id, and its children follow it, so only the length
    # bound is broken.
    old = _first(payload)["id"]
    _unlist(payload, old)
    for child in _children(payload, old):
        child["parent_id"] = ""
    _first(payload)["id"] = ""


def _parent_cycle(payload: dict[str, Any]) -> None:
    first, second = _first(payload), _second(payload)
    _point_to(first, second)
    _point_to(second, first)


def _own_parent(payload: dict[str, Any]) -> None:
    _point_to(_first(payload), _first(payload))


def _duplicate_page_number(payload: dict[str, Any]) -> None:
    # An extra empty page, so no element loses its page.
    first = payload["pages"][0]
    payload["pages"].append({**first, "element_ids": []})


def _page_lists_unknown_element(payload: dict[str, Any]) -> None:
    payload["pages"][0]["element_ids"].append("ghost")


def _page_repeats_element(payload: dict[str, Any]) -> None:
    listed = next(page for page in payload["pages"] if page["element_ids"])
    listed["element_ids"].append(listed["element_ids"][0])


def _missing_page(payload: dict[str, Any]) -> int:
    return max(page["page_number"] for page in payload["pages"]) + 1


def _element_on_unknown_page(payload: dict[str, Any]) -> None:
    _first(payload)["page_number"] = _missing_page(payload)


def _provenance_on_unknown_page(payload: dict[str, Any]) -> None:
    _first(payload)["provenance"][0]["page_number"] = _missing_page(payload)


def _parent_reference_mismatch(payload: dict[str, Any]) -> None:
    parent, child = _first(payload), _second(payload)
    _detach(parent)
    parent["source_ref"] = "source-parent"
    # The parent's other children follow its new reference.
    for other in _children(payload, parent["id"]):
        other["parent_ref"] = "source-parent"
    child.update(parent_id=parent["id"], parent_ref="different-source-parent")


def _reversed_char_range(payload: dict[str, Any]) -> None:
    _first(payload)["provenance"][0].update(char_start=5, char_end=2)


def _provenance(payload: dict[str, Any]) -> dict[str, Any]:
    return _first(payload)["provenance"][0]


def _bbox(payload: dict[str, Any]) -> dict[str, Any]:
    provenance = _provenance(payload)
    if provenance.get("bbox") is None:
        provenance["bbox"] = {"left": 0.0, "top": 10.0, "right": 10.0, "bottom": 0.0}
    return provenance["bbox"]


#: Changes that make a document invalid, by the rule they break. The names
#: are shared: a component reports a disagreement by name.
BROKEN: dict[str, Change] = {
    # Identity and hierarchy.
    "duplicate element id": _duplicate_element_id,
    "empty id": _empty_id,
    "missing parent": _set(_first, parent_id="nowhere"),
    "own parent": _own_parent,
    "parent cycle": _parent_cycle,
    "child parent reference disagrees with parent source reference": (
        _parent_reference_mismatch
    ),
    # Pages.
    "duplicate page number": _duplicate_page_number,
    "page lists an unknown element": _page_lists_unknown_element,
    "page repeats an element": _page_repeats_element,
    "element references an unknown page": _element_on_unknown_page,
    "provenance references an unknown page": _provenance_on_unknown_page,
    "zero page width": lambda payload: payload["pages"][0].update(width=0),
    # Field bounds and enums.
    "reading order below 1": _set(_first, reading_order=0),
    "negative hierarchy level": _set(_first, hierarchy_level=-1),
    "unknown element type": _set(_first, type="sidebar"),
    "confidence above 1": _set(_first, confidence=1.5),
    "page number 0 in provenance": _set(_provenance, page_number=0),
    "unknown coordinate origin": _set(_bbox, coord_origin="CENTER"),
    "negative char offset": _set(_provenance, char_start=-1),
    "reversed char range": _reversed_char_range,
    "one-letter language": lambda payload: payload.update(language="p"),
    "empty title": lambda payload: payload.update(title=""),
    # Shape.
    "unknown element field": _set(_first, colour="red"),
}


def _fragment(payload: dict[str, Any]) -> None:
    payload["pages"] = []


def _unlisted_element(payload: dict[str, Any]) -> None:
    _unlist(payload, _first(payload)["id"])


def _parent_without_source_reference(payload: dict[str, Any]) -> None:
    parent, child = _first(payload), _second(payload)
    _detach(parent)
    parent["source_ref"] = None
    child.update(parent_id=parent["id"], parent_ref="source-reference")


def _child_of_first(payload: dict[str, Any]) -> None:
    # The first becomes a root, so the new link can close no cycle.
    _detach(_first(payload))
    _point_to(_second(payload), _first(payload))


#: Changes a valid document may have, which must keep it valid.
SUPPORTED: dict[str, Change] = {
    "as given": lambda payload: None,
    "fragment without pages": _fragment,
    "element on no page's list": _unlisted_element,
    "parent without a source reference": _parent_without_source_reference,
    "child of another element": _child_of_first,
}


__all__ = [
    "BROKEN",
    "DOCUMENT_FIELDS",
    "SUPPORTED",
    "Change",
    "document_findings",
    "example_document",
]
