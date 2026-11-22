"""The document part of the manifest schema agrees with docstruct (#203, D1).

docstruct owns the document's types and invariants (``docstruct.manifest``);
the wire schema ``processing-manifest:1.1.0`` is not generated from them. This
contract test checks the two mechanically instead:

- every document type in the schema's ``$defs``, and the document fields of
  the manifest itself, have exactly the fields, types, nullability, defaults,
  bounds and enums that ``docstruct.manifest.field_specs`` declares;
- the golden manifests convert to docstruct and back without loss;
- the core and docstruct accept and reject the same documents: the cases are
  docstruct's shared catalog (``docstruct.manifest_cases``), which the SDK and
  the Toolbox run too (#470, criterion 4).
"""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from acessilia_core.manifest.models import ProcessingManifest
from acessilia_core.manifest.schema import processing_manifest_schema
from docstruct.manifest import (
    MSG_FIELD_NOT_ALLOWED,
    MSG_FIELD_OUT_OF_RANGE,
    MSG_FIELD_WRONG_TYPE,
    WIRE_NAMES,
    StructuredDocument,
    field_specs,
    structured_document_from_payload,
    structured_document_to_payload,
    validate_structured_document,
)
from docstruct.manifest_cases import (
    BROKEN,
    SUPPORTED,
    document_findings,
    example_document,
)
from tests.locale_support import use_server_locale

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


def _with_summary(payload: dict) -> dict:
    """The core's summary follows the document: a case changes the document
    only, so the counts are recomputed after it."""
    summary = payload["summary"]
    summary["page_count"] = len(payload["pages"])
    summary["element_count"] = len(payload["elements"])
    types: dict[str, int] = {}
    for element in payload["elements"]:
        types[element["type"]] = types.get(element["type"], 0) + 1
    summary["element_types"] = dict(sorted(types.items()))
    return payload


def _example_manifest() -> dict:
    """docstruct's shared example document, inside a core manifest."""
    return _with_summary({**_golden(), **example_document()})


#: The two documents the shared cases are applied to: a golden manifest and
#: docstruct's example.
BASES = {"golden": _golden, "docstruct example": _example_manifest}


def _break(case: str, base: str = "golden") -> dict:
    payload = copy.deepcopy(BASES[base]())
    BROKEN[case](payload)
    return _with_summary(payload)


def _core_accepts(payload: dict) -> bool:
    try:
        ProcessingManifest.model_validate(payload)
    except ValidationError:
        return False
    return True


def test_the_shared_example_is_a_valid_core_manifest() -> None:
    assert _core_accepts(_example_manifest())


FIELD_MESSAGES = (MSG_FIELD_WRONG_TYPE, MSG_FIELD_OUT_OF_RANGE, MSG_FIELD_NOT_ALLOWED)


def _location(path: str) -> tuple:
    """``elements[0].provenance[0].bbox`` as a Pydantic error location."""
    return tuple(int(part) if part.isdigit() else part for part in re.findall(r"[^.\[\]]+", path))


@pytest.mark.parametrize("base", list(BASES))
@pytest.mark.parametrize("case", list(BROKEN))
def test_core_and_docstruct_reject_the_same_documents(case: str, base: str) -> None:
    """For the same reason, not only both (review of #591): a field finding at
    the same location, an unknown field as one, and an invariant with
    docstruct's message, which the core raises for its first finding."""
    from acessilia_core.i18n import t

    payload = _break(case, base)
    findings = document_findings(payload)
    assert findings != []
    message, context = findings[0]

    with pytest.raises(ValidationError) as raised:
        ProcessingManifest.model_validate(payload)

    errors = raised.value.errors()
    if message == "refused":
        assert any(error["type"] == "extra_forbidden" for error in errors), errors
    elif message in FIELD_MESSAGES:
        assert _location(context["path"]) in [tuple(error["loc"]) for error in errors], errors
    else:
        assert t(message).format(**context) in str(raised.value)


@pytest.mark.parametrize("base", list(BASES))
@pytest.mark.parametrize("case", list(SUPPORTED))
def test_core_and_docstruct_keep_the_same_documents(case: str, base: str) -> None:
    payload = copy.deepcopy(BASES[base]())
    SUPPORTED[case](payload)
    _with_summary(payload)

    assert document_findings(payload) == []
    assert _core_accepts(payload)


def test_unknown_fields_are_refused_as_by_the_schema() -> None:
    payload = _break("unknown element field")

    with pytest.raises(ValidationError):
        ProcessingManifest.model_validate(payload)
    with pytest.raises(ValueError, match="unknown fields"):
        structured_document_from_payload(payload)


@pytest.mark.parametrize("golden", GOLDEN, ids=lambda path: path.stem)
def test_core_adapter_round_trips_a_manifest(golden: Path) -> None:
    from acessilia_core.manifest.document_adapter import (
        to_structured_document,
        with_structured_document,
    )

    payload = json.loads(golden.read_text("utf-8"))
    manifest = ProcessingManifest.model_validate(payload)

    rebuilt = with_structured_document(manifest, to_structured_document(manifest))

    assert rebuilt.model_dump(mode="json", by_alias=True) == payload


def test_core_adapter_revalidates_the_whole_manifest() -> None:
    from acessilia_core.manifest.document_adapter import (
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
    from acessilia_core.i18n import t
    from scripts.gen_locale_catalogs import TRANSLATIONS

    use_server_locale(monkeypatch, locale)
    name, kwargs = DOCUMENT_INVARIANT_MESSAGES[case]
    msgid = getattr(model, name)
    expected = (TRANSLATIONS["pt_BR"][msgid] if locale == "pt_BR" else msgid).format(**kwargs)

    assert t(msgid).format(**kwargs) == expected
    with pytest.raises(ValidationError, match=re.escape(expected)):
        ProcessingManifest.model_validate(_break(case))


MIXED_INTERVALS = {
    "naive start, aware end": ("2026-10-20T00:00:00", "2026-10-20T00:00:00+00:00"),
    "aware start, naive end": ("2026-10-20T00:00:00+00:00", "2026-10-20T00:00:00"),
}


@pytest.mark.parametrize("case", list(MIXED_INTERVALS))
def test_mixed_timezones_are_a_validation_error_not_a_type_error(case) -> None:
    from acessilia_core.i18n import t
    from acessilia_core.i18n.log_messages import MSG_TIMESTAMPS_MIXED_TIMEZONES
    from acessilia_core.manifest.models import ExtractorRun, ObligationAttempt

    started_at, completed_at = MIXED_INTERVALS[case]
    expected = re.escape(t(MSG_TIMESTAMPS_MIXED_TIMEZONES))

    payload = _golden()
    payload["extractor"]["started_at"] = started_at
    payload["extractor"]["completed_at"] = completed_at

    with pytest.raises(ValidationError, match=expected):
        ProcessingManifest.model_validate(payload)
    with pytest.raises(ValidationError, match=expected):
        ExtractorRun.model_validate(
            {"version": "1", "started_at": started_at, "completed_at": completed_at, "duration_ms": 0}
        )
    with pytest.raises(ValidationError, match=expected):
        ObligationAttempt.model_validate(
            {"method": "m", "status": "failed", "started_at": started_at, "completed_at": completed_at}
        )
