"""Semantic model of the processing manifest's document part.

Pure: zero external dependencies, standard library only.

docstruct is the normative source of the document's types and invariants
(ADR-0007, decision 1; #203, D1): pages, elements, their provenance and
boxes, the document title and language. The rest of a processing manifest
(its envelope, origin and process state) belongs to the components that
produce it.

The wire schema (``processing-manifest:1.1.0``) is **not** generated from
these types, so their evolution does not move the public payload. Instead,
``field_specs`` describes each type's fields as constraints, and consumers
verify their wire models against it in contract tests. ``*_from_payload`` and
``*_to_payload`` convert between the wire dicts and these types without loss.
"""
from __future__ import annotations

import dataclasses
import types
import typing
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from docstruct.geometry.boxes import OrientedBox
from docstruct.validation import Finding

ElementType = Literal[
    "title",
    "heading",
    "paragraph",
    "list_item",
    "table",
    "picture",
    "formula",
    "code",
    "caption",
    "footnote",
    "page_header",
    "page_footer",
    "checkbox",
    "key_value",
    "form",
    "group",
    "unknown",
]
CoordOrigin = Literal["TOPLEFT", "BOTTOMLEFT", "UNKNOWN"]


@dataclass(frozen=True)
class BoundingBox(OrientedBox):
    """A box with one of the three origins the manifest knows."""

    coord_origin: CoordOrigin = "UNKNOWN"


@dataclass
class Provenance:
    page_number: int = field(metadata={"ge": 1})
    bbox: BoundingBox | None = None
    char_start: int | None = field(default=None, metadata={"ge": 0})
    char_end: int | None = field(default=None, metadata={"ge": 0})


@dataclass
class PageDescriptor:
    page_number: int = field(metadata={"ge": 1})
    width: float | None = field(default=None, metadata={"gt": 0})
    height: float | None = field(default=None, metadata={"gt": 0})
    element_ids: list[str] = field(default_factory=list)


@dataclass
class DocumentElement:
    id: str = field(metadata={"min_length": 1})
    type: ElementType
    raw_label: str = field(metadata={"min_length": 1})
    reading_order: int = field(metadata={"ge": 1})
    hierarchy_level: int = field(metadata={"ge": 0})
    text: str | None = None
    source_ref: str | None = None
    parent_ref: str | None = None
    parent_id: str | None = None
    page_number: int | None = field(default=None, metadata={"ge": 1})
    confidence: float | None = field(default=None, metadata={"ge": 0, "le": 1})
    provenance: list[Provenance] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StructuredDocument:
    """The document part of a processing manifest."""

    title: str = field(metadata={"min_length": 1})
    language: str = field(metadata={"min_length": 2})
    pages: list[PageDescriptor]
    elements: list[DocumentElement]


#: The name each type has in the wire schema's ``$defs``. ``StructuredDocument``
#: has none: its fields are top-level properties of the manifest.
WIRE_NAMES: dict[type, str] = {
    BoundingBox: "BoundingBox",
    Provenance: "Provenance",
    PageDescriptor: "PageDescriptor",
    DocumentElement: "ManifestElement",
}

# --- Field specifications -----------------------------------------------------

_JSON_TYPES = {str: "string", int: "integer", float: "number", bool: "boolean"}
_CONSTRAINT_KEYWORDS = {
    "ge": "minimum",
    "gt": "exclusiveMinimum",
    "le": "maximum",
    "min_length": "minLength",
}


def field_specs(cls: type) -> dict[str, dict[str, Any]]:
    """Each field of ``cls`` as JSON Schema-like constraints.

    A spec has ``type`` (a JSON type, or ``"ref"`` with ``ref`` naming a wire
    type), ``nullable``, ``required``, ``default`` when the field has a plain
    default, ``items`` for arrays, ``enum`` for literals and the numeric and
    length bounds (``minimum``, ``exclusiveMinimum``, ``maximum``,
    ``minLength``).
    """
    hints = typing.get_type_hints(cls)
    specs: dict[str, dict[str, Any]] = {}
    for item in dataclasses.fields(cls):
        spec = _type_spec(hints[item.name])
        has_default = item.default is not dataclasses.MISSING
        has_factory = item.default_factory is not dataclasses.MISSING
        spec["required"] = not (has_default or has_factory)
        if has_default:
            spec["default"] = item.default
        for key, keyword in _CONSTRAINT_KEYWORDS.items():
            if key in item.metadata:
                spec[keyword] = item.metadata[key]
        specs[item.name] = spec
    return specs


def _type_spec(hint: Any) -> dict[str, Any]:
    args = typing.get_args(hint)
    nullable = False
    if typing.get_origin(hint) in (typing.Union, types.UnionType) and type(None) in args:
        (hint,) = [arg for arg in args if arg is not type(None)]
        nullable = True
    origin = typing.get_origin(hint)
    if origin is Literal:
        spec: dict[str, Any] = {"type": "string", "enum": list(typing.get_args(hint))}
    elif origin is list:
        spec = {"type": "array", "items": _type_spec(typing.get_args(hint)[0])}
    elif origin is dict or hint is dict:
        spec = {"type": "object"}
    elif hint in WIRE_NAMES:
        spec = {"type": "ref", "ref": WIRE_NAMES[hint]}
    else:
        spec = {"type": _JSON_TYPES[hint]}
    spec["nullable"] = nullable
    return spec


# --- Payload adapters -----------------------------------------------------------


def structured_document_from_payload(payload: Mapping[str, Any]) -> StructuredDocument:
    """The document part of a manifest payload (other top-level keys are ignored).

    Strict like the wire schema: an unknown or missing field inside a page,
    element, provenance or box raises ``ValueError``. Values are taken as
    they are, without coercion, so ``*_to_payload`` gives them back unchanged.
    """
    return StructuredDocument(
        title=payload["title"],
        language=payload["language"],
        pages=[_build(PageDescriptor, page) for page in payload["pages"]],
        elements=[_build(DocumentElement, element) for element in payload["elements"]],
    )


def structured_document_to_payload(document: StructuredDocument) -> dict[str, Any]:
    """The wire dict of the document part, every field present."""
    return _dump(document)


def _build(cls: type, data: Mapping[str, Any]) -> Any:
    names = {item.name for item in dataclasses.fields(cls)}
    unknown = set(data) - names
    if unknown:
        raise ValueError(f"{WIRE_NAMES[cls]}: unknown fields {sorted(unknown)}")
    hints = typing.get_type_hints(cls)
    values = {}
    for name, value in data.items():
        target = _payload_target(hints[name])
        if target is not None and value is not None:
            if typing.get_origin(hints[name]) is list:
                value = [_build(target, entry) for entry in value]
            else:
                value = _build(target, value)
        values[name] = value
    try:
        return cls(**values)
    except TypeError as exc:
        raise ValueError(f"{WIRE_NAMES[cls]}: {exc}") from exc


def _payload_target(hint: Any) -> type | None:
    """The docstruct type a field holds, alone or in a list or optional."""
    for candidate in (hint, *typing.get_args(hint)):
        for inner in (candidate, *typing.get_args(candidate)):
            if inner in WIRE_NAMES:
                return inner
    return None


def _dump(value: Any) -> Any:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {item.name: _dump(getattr(value, item.name)) for item in dataclasses.fields(value)}
    if isinstance(value, list):
        return [_dump(entry) for entry in value]
    return value


# --- Validation ---------------------------------------------------------------

MSG_FIELD_OUT_OF_RANGE: str = "{path} = {value!r} breaks {rule}"
MSG_FIELD_NOT_ALLOWED: str = "{path} = {value!r} is not one of {allowed}"
MSG_DUPLICATE_ELEMENT_IDS: str = "Duplicate element ids"
MSG_UNKNOWN_PARENT: str = "Element {element_id} references a missing parent: {parent_id}"
MSG_SELF_PARENT: str = "Element {element_id} is its own parent"
MSG_PARENT_CYCLE: str = "Cycle detected in the element hierarchy"
MSG_DUPLICATE_PAGE_NUMBERS: str = "Duplicate page numbers"
MSG_PAGE_UNKNOWN_ELEMENTS: str = "Page {page_number} references unknown elements: {element_ids}"

_RULES = {
    "ge": lambda value, bound: value >= bound,
    "gt": lambda value, bound: value > bound,
    "le": lambda value, bound: value <= bound,
    "min_length": lambda value, bound: len(value) >= bound,
}
_RULE_TEXT = {"ge": ">= {}", "gt": "> {}", "le": "<= {}", "min_length": "length >= {}"}


def validate_structured_document(document: StructuredDocument) -> list[tuple[str, dict[str, Any]]]:
    """Every field constraint and document invariant ``document`` breaks.

    Findings are ``(msgid, kwargs)`` pairs, as in ``docstruct.validation``;
    an empty list means the document is valid. Field constraints come first,
    then, in this order: unique element ids, existing parents that are not
    the element itself, an acyclic hierarchy, unique page numbers, and pages
    that list known elements only.
    """
    findings = _field_findings(document, "")
    findings.extend(document_invariant_findings(document.pages, document.elements))
    return findings


def document_invariant_findings(
    pages: list[Any], elements: list[Any]
) -> list[tuple[str, dict[str, Any]]]:
    """The document invariants alone, on anything with the fields they read.

    Pages need ``page_number`` and ``element_ids``; elements need ``id`` and
    ``parent_id``. Wire models can therefore be checked without conversion.
    """
    findings: list[tuple[str, dict[str, Any]]] = []
    element_ids = [element.id for element in elements]
    if len(element_ids) != len(set(element_ids)):
        findings.append(Finding(MSG_DUPLICATE_ELEMENT_IDS))

    known = set(element_ids)
    parent_graph: dict[str, str] = {}
    for element in elements:
        if element.parent_id is None:
            continue
        if element.parent_id not in known:
            findings.append(
                Finding(MSG_UNKNOWN_PARENT, element_id=element.id, parent_id=element.parent_id)
            )
        elif element.parent_id == element.id:
            findings.append(Finding(MSG_SELF_PARENT, element_id=element.id))
        else:
            parent_graph[element.id] = element.parent_id
    if _has_cycle(parent_graph):
        findings.append(Finding(MSG_PARENT_CYCLE))

    page_numbers = [page.page_number for page in pages]
    if len(page_numbers) != len(set(page_numbers)):
        findings.append(Finding(MSG_DUPLICATE_PAGE_NUMBERS))
    for page in pages:
        unknown = set(page.element_ids) - known
        if unknown:
            findings.append(
                Finding(
                    MSG_PAGE_UNKNOWN_ELEMENTS,
                    page_number=page.page_number,
                    element_ids=sorted(unknown),
                )
            )
    return findings


def _has_cycle(parent_graph: dict[str, str]) -> bool:
    for start in parent_graph:
        seen: set[str] = set()
        current = start
        while current in parent_graph:
            if current in seen:
                return True
            seen.add(current)
            current = parent_graph[current]
    return False


def _field_findings(value: Any, path: str) -> list[tuple[str, dict[str, Any]]]:
    findings: list[tuple[str, dict[str, Any]]] = []
    specs = field_specs(type(value))
    for item in dataclasses.fields(value):
        current = getattr(value, item.name)
        where = f"{path}.{item.name}" if path else item.name
        if current is None:
            continue
        if "enum" in specs[item.name] and current not in specs[item.name]["enum"]:
            findings.append(
                Finding(
                    MSG_FIELD_NOT_ALLOWED,
                    path=where,
                    value=current,
                    allowed=specs[item.name]["enum"],
                )
            )
        for rule, check in _RULES.items():
            if rule in item.metadata and not check(current, item.metadata[rule]):
                findings.append(
                    Finding(
                        MSG_FIELD_OUT_OF_RANGE,
                        path=where,
                        value=current,
                        rule=_RULE_TEXT[rule].format(item.metadata[rule]),
                    )
                )
        if isinstance(current, list):
            for index, entry in enumerate(current):
                if dataclasses.is_dataclass(entry):
                    findings.extend(_field_findings(entry, f"{where}[{index}]"))
        elif dataclasses.is_dataclass(current):
            findings.extend(_field_findings(current, where))
    return findings


__all__ = [
    "BoundingBox",
    "CoordOrigin",
    "DocumentElement",
    "ElementType",
    "MSG_DUPLICATE_ELEMENT_IDS",
    "MSG_DUPLICATE_PAGE_NUMBERS",
    "MSG_FIELD_NOT_ALLOWED",
    "MSG_FIELD_OUT_OF_RANGE",
    "MSG_PAGE_UNKNOWN_ELEMENTS",
    "MSG_PARENT_CYCLE",
    "MSG_SELF_PARENT",
    "MSG_UNKNOWN_PARENT",
    "PageDescriptor",
    "Provenance",
    "StructuredDocument",
    "WIRE_NAMES",
    "document_invariant_findings",
    "field_specs",
    "structured_document_from_payload",
    "structured_document_to_payload",
    "validate_structured_document",
]
