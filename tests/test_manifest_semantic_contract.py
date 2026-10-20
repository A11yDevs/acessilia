"""The document part of the manifest schema agrees with docstruct (#203, D1).

docstruct owns the document's types and invariants (``docstruct.manifest``);
the wire schema ``processing-manifest:1.1.0`` is not generated from them. This
contract test checks the two mechanically instead:

- every document type in the schema's ``$defs``, and the document fields of
  the manifest itself, have exactly the fields, types, nullability, defaults,
  bounds and enums that ``docstruct.manifest.field_specs`` declares;
- the golden manifests convert to docstruct and back without loss;
- the core and docstruct accept and reject the same documents.
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.core.manifest.models import ProcessingManifest
from backend.core.manifest.schema import processing_manifest_schema
from docstruct.manifest import (
    WIRE_NAMES,
    StructuredDocument,
    field_specs,
    structured_document_from_payload,
    structured_document_to_payload,
    validate_structured_document,
)

GOLDEN = sorted((Path(__file__).parent / "fixtures" / "manifests").glob("*.json"))
DOCUMENT_FIELDS = ("title", "language", "pages", "elements")
BOUNDS = ("minimum", "exclusiveMinimum", "maximum", "minLength")


def _type_spec(schema: dict) -> dict:
    options = schema.get("anyOf", [schema])
    concrete = [option for option in options if option != {"type": "null"}]
    assert len(concrete) == 1, schema
    (base,) = concrete
    if "$ref" in base:
        spec = {"type": "ref", "ref": base["$ref"].rsplit("/", 1)[-1]}
    else:
        spec = {"type": base["type"]}
        if base["type"] == "array":
            spec["items"] = _type_spec(base["items"])
        if "enum" in base:
            spec["enum"] = base["enum"]
        spec.update({key: base[key] for key in BOUNDS if key in base})
    spec["nullable"] = len(concrete) < len(options)
    return spec


def _wire_specs(properties: dict, required: list[str]) -> dict[str, dict]:
    specs = {}
    for name, schema in properties.items():
        spec = _type_spec(schema)
        spec["required"] = name in required
        if "default" in schema:
            spec["default"] = schema["default"]
        specs[name] = spec
    return specs


SCHEMA = processing_manifest_schema()


@pytest.mark.parametrize("docstruct_type", list(WIRE_NAMES), ids=lambda cls: cls.__name__)
def test_document_type_in_the_schema_matches_docstruct(docstruct_type) -> None:
    definition = SCHEMA["$defs"][WIRE_NAMES[docstruct_type]]

    assert definition["additionalProperties"] is False
    assert _wire_specs(definition["properties"], definition["required"]) == field_specs(
        docstruct_type
    )


def test_document_fields_of_the_manifest_match_docstruct() -> None:
    properties = {name: SCHEMA["properties"][name] for name in DOCUMENT_FIELDS}
    required = [name for name in SCHEMA["required"] if name in DOCUMENT_FIELDS]

    assert _wire_specs(properties, required) == field_specs(StructuredDocument)


@pytest.mark.parametrize("golden", GOLDEN, ids=lambda path: path.stem)
def test_golden_document_round_trips_through_docstruct(golden: Path) -> None:
    payload = json.loads(golden.read_text("utf-8"))

    document = structured_document_from_payload(payload)

    assert structured_document_to_payload(document) == {
        name: payload[name] for name in DOCUMENT_FIELDS
    }
    assert validate_structured_document(document) == []


def _golden(name: str = "two-pages-refined") -> dict:
    path = Path(__file__).parent / "fixtures" / "manifests" / f"{name}.json"
    return json.loads(path.read_text("utf-8"))


def _break(change) -> dict:
    payload = copy.deepcopy(_golden())
    change(payload)
    return payload


def _set(path: str, value):
    def change(payload):
        target = payload
        keys = path.split(".")
        for key in keys[:-1]:
            target = target[int(key)] if key.isdigit() else target[key]
        target[keys[-1]] = value

    return change


def _duplicate_element(payload):
    payload["elements"][1]["id"] = payload["elements"][0]["id"]


def _empty_id(payload):
    # The page drops the id too, so only the length bound is broken.
    payload["elements"][0]["id"] = ""
    payload["pages"][0]["element_ids"].pop(0)


def _cycle(payload):
    first, second = payload["elements"][0], payload["elements"][1]
    first["parent_id"], second["parent_id"] = second["id"], first["id"]


BROKEN = {
    "duplicate element id": _duplicate_element,
    "missing parent": _set("elements.0.parent_id", "nowhere"),
    "own parent": lambda p: p["elements"][0].update(parent_id=p["elements"][0]["id"]),
    "parent cycle": _cycle,
    "duplicate page number": _set("pages.1.page_number", 1),
    "page lists an unknown element": lambda p: p["pages"][0]["element_ids"].append("ghost"),
    "reading order below 1": _set("elements.0.reading_order", 0),
    "negative hierarchy level": _set("elements.0.hierarchy_level", -1),
    "empty id": _empty_id,
    "unknown element type": _set("elements.0.type", "sidebar"),
    "confidence above 1": _set("elements.0.confidence", 1.5),
    "zero page width": _set("pages.0.width", 0),
    "page number 0 in provenance": _set("elements.0.provenance.0.page_number", 0),
    "unknown coordinate origin": _set("elements.0.provenance.0.bbox.coord_origin", "CENTER"),
    "negative char offset": _set("elements.0.provenance.0.char_start", -1),
    "reversed char range": lambda p: p["elements"][0]["provenance"][0].update(char_start=5, char_end=2),
    "one-letter language": _set("language", "p"),
    "empty title": _set("title", ""),
}


@pytest.mark.parametrize("case", list(BROKEN))
def test_core_and_docstruct_reject_the_same_documents(case: str) -> None:
    payload = _break(BROKEN[case])

    with pytest.raises(ValidationError):
        ProcessingManifest.model_validate(payload)
    assert validate_structured_document(structured_document_from_payload(payload)) != []


def test_unknown_fields_are_refused_as_by_the_schema() -> None:
    payload = _break(lambda p: p["elements"][0].update(colour="red"))

    with pytest.raises(ValidationError):
        ProcessingManifest.model_validate(payload)
    with pytest.raises(ValueError, match="unknown fields"):
        structured_document_from_payload(payload)


@pytest.mark.parametrize("golden", GOLDEN, ids=lambda path: path.stem)
def test_core_adapter_round_trips_a_manifest(golden: Path) -> None:
    from backend.core.manifest.document_adapter import (
        to_structured_document,
        with_structured_document,
    )

    payload = json.loads(golden.read_text("utf-8"))
    manifest = ProcessingManifest.model_validate(payload)

    rebuilt = with_structured_document(manifest, to_structured_document(manifest))

    assert rebuilt.model_dump(mode="json", by_alias=True) == payload


def test_core_adapter_revalidates_the_whole_manifest() -> None:
    from backend.core.manifest.document_adapter import (
        to_structured_document,
        with_structured_document,
    )

    manifest = ProcessingManifest.model_validate(_golden())
    document = to_structured_document(manifest)
    document.elements.pop()

    with pytest.raises(ValidationError):
        with_structured_document(manifest, document)


DOCUMENT_INVARIANT_MESSAGES = {
    "duplicate element id": ("MSG_DUPLICATE_ELEMENT_IDS", {"element_ids": ["element-000002"]}),
    "missing parent": ("MSG_UNKNOWN_PARENT", {"element_id": "element-000002", "parent_id": "nowhere"}),
    "own parent": ("MSG_SELF_PARENT", {"element_id": "element-000002"}),
    "parent cycle": ("MSG_PARENT_CYCLE", {}),
    "duplicate page number": ("MSG_DUPLICATE_PAGE_NUMBERS", {}),
    "page lists an unknown element": (
        "MSG_PAGE_UNKNOWN_ELEMENTS", {"page_number": 1, "element_ids": ["ghost"]},
    ),
    "reversed char range": (
        "MSG_CHAR_RANGE_REVERSED",
        {"path": "elements[0].provenance[0]", "char_start": 5, "char_end": 2},
    ),
}


@pytest.mark.parametrize("locale", ["en_US", "pt_BR"])
@pytest.mark.parametrize("case", list(DOCUMENT_INVARIANT_MESSAGES))
def test_core_reports_docstruct_invariants_in_the_active_locale(monkeypatch, locale, case):
    import docstruct.manifest as model
    from backend.i18n import t
    from scripts.gen_locale_catalogs import TRANSLATIONS

    monkeypatch.setenv("LOCALE", locale)
    name, kwargs = DOCUMENT_INVARIANT_MESSAGES[case]
    msgid = getattr(model, name)
    expected = (TRANSLATIONS["pt_BR"][msgid] if locale == "pt_BR" else msgid).format(**kwargs)

    assert t(msgid).format(**kwargs) == expected
    with pytest.raises(ValidationError, match=re.escape(expected)):
        ProcessingManifest.model_validate(_break(BROKEN[case]))


def _mixed_extraction(payload: dict) -> None:
    payload["extractor"]["started_at"] = "2026-10-20T00:00:00"


def test_mixed_timezones_are_a_validation_error_not_a_type_error() -> None:
    from backend.core.manifest.models import ObligationAttempt

    with pytest.raises(ValidationError):
        ProcessingManifest.model_validate(_break(_mixed_extraction))
    with pytest.raises(ValidationError):
        ObligationAttempt.model_validate(
            {
                "method": "m",
                "status": "failed",
                "started_at": "2026-10-20T00:00:00",
                "completed_at": "2026-10-20T00:00:00+00:00",
            }
        )
