"""docstruct.manifest: the document part of the processing manifest (#203)."""
import pytest

from docstruct.geometry import OrientedBox
from docstruct.manifest import (
    MSG_CHAR_RANGE_REVERSED,
    MSG_DUPLICATE_ELEMENT_IDS,
    MSG_DUPLICATE_PAGE_NUMBERS,
    MSG_FIELD_NOT_ALLOWED,
    MSG_FIELD_OUT_OF_RANGE,
    MSG_FIELD_WRONG_TYPE,
    MSG_PAGE_UNKNOWN_ELEMENTS,
    MSG_PARENT_CYCLE,
    MSG_SELF_PARENT,
    MSG_UNKNOWN_PARENT,
    BoundingBox,
    DocumentElement,
    StructuredDocument,
    field_specs,
    structured_document_from_payload,
    structured_document_to_payload,
    validate_structured_document,
)


def payload():
    return {
        "title": "Doc",
        "language": "pt-BR",
        "pages": [{"page_number": 1, "width": 600.0, "height": 800.0, "element_ids": ["a", "b"]}],
        "elements": [
            {
                "id": "a", "type": "heading", "raw_label": "section_header",
                "reading_order": 1, "hierarchy_level": 1, "text": "Title",
                "source_ref": "#/texts/0", "parent_ref": None, "parent_id": None,
                "page_number": 1, "confidence": 0.9,
                "provenance": [{
                    "page_number": 1,
                    "bbox": {"left": 1.0, "top": 790.0, "right": 9.0, "bottom": 780.0,
                             "coord_origin": "BOTTOMLEFT"},
                    "char_start": 0, "char_end": 5,
                }],
                "metadata": {"docling_class": "SectionHeaderItem"},
            },
            {
                "id": "b", "type": "paragraph", "raw_label": "text", "reading_order": 2,
                "hierarchy_level": 2, "text": None, "source_ref": None, "parent_ref": None,
                "parent_id": "a", "page_number": 1, "confidence": None,
                "provenance": [], "metadata": {},
            },
        ],
        "envelope_key": "ignored",
    }


def test_payload_round_trip_is_lossless():
    data = payload()
    document = structured_document_from_payload(data)

    assert structured_document_to_payload(document) == {
        key: data[key] for key in ("title", "language", "pages", "elements")
    }
    assert validate_structured_document(document) == []


def test_boxes_keep_their_origin_and_are_oriented_boxes():
    box = structured_document_from_payload(payload()).elements[0].provenance[0].bbox

    assert isinstance(box, BoundingBox) and isinstance(box, OrientedBox)
    assert box.coord_origin == "BOTTOMLEFT"
    assert box.top_down() == (1.0, -790.0, 9.0, -780.0)


@pytest.mark.parametrize(
    "change",
    [
        lambda p: p["elements"][0].update(colour="red"),
        lambda p: p["pages"][0].update(rotation=90),
        lambda p: p["elements"][0]["provenance"][0]["bbox"].update(z=1),
        lambda p: p["elements"][0].pop("id"),
        lambda p: p.pop("language"),
        lambda p: p.pop("elements"),
        lambda p: p["pages"].append("page 2"),
        lambda p: p["elements"][0].update(provenance={"page_number": 1}),
    ],
)
def test_unknown_or_missing_fields_are_refused(change):
    data = payload()
    change(data)
    with pytest.raises(ValueError):
        structured_document_from_payload(data)


def test_field_specs_describe_bounds_defaults_and_references():
    specs = field_specs(DocumentElement)

    assert specs["reading_order"] == {
        "type": "integer", "nullable": False, "required": True, "minimum": 1,
    }
    assert specs["confidence"]["maximum"] == 1 and specs["confidence"]["nullable"]
    assert specs["provenance"]["items"] == {"type": "ref", "ref": "Provenance", "nullable": False}
    assert "default" not in specs["metadata"] and not specs["metadata"]["required"]
    assert field_specs(StructuredDocument)["language"]["minLength"] == 2


def findings_for(change):
    data = payload()
    change(data)
    return [msgid for msgid, _ in validate_structured_document(structured_document_from_payload(data))]


def test_document_invariants():
    assert findings_for(lambda p: p["elements"].append(dict(p["elements"][0]))) == [MSG_DUPLICATE_ELEMENT_IDS]
    assert findings_for(lambda p: p["elements"][1].update(parent_id="x")) == [MSG_UNKNOWN_PARENT]
    assert findings_for(lambda p: p["elements"][1].update(parent_id="b")) == [MSG_SELF_PARENT]
    assert findings_for(lambda p: p["elements"][0].update(parent_id="b")) == [MSG_PARENT_CYCLE]
    assert findings_for(lambda p: p["pages"].append(dict(p["pages"][0]))) == [MSG_DUPLICATE_PAGE_NUMBERS]
    assert findings_for(lambda p: p["pages"][0]["element_ids"].append("z")) == [MSG_PAGE_UNKNOWN_ELEMENTS]
    reversed_range = lambda p: p["elements"][0]["provenance"][0].update(char_start=10, char_end=5)
    assert findings_for(reversed_range) == [MSG_CHAR_RANGE_REVERSED]


def test_long_parent_chains_are_acyclic():
    data = payload()
    data["pages"][0]["element_ids"] = []
    template = data["elements"][1]
    data["elements"] = [
        {**template, "id": str(n), "parent_id": str(n - 1) if n else None} for n in range(2000)
    ]

    assert validate_structured_document(structured_document_from_payload(data)) == []


def test_duplicate_element_ids_are_named():
    data = payload()
    data["elements"].append(dict(data["elements"][1]))
    (finding,) = validate_structured_document(structured_document_from_payload(data))

    assert finding == (MSG_DUPLICATE_ELEMENT_IDS, {"element_ids": ["b"]})


@pytest.mark.parametrize(
    ("change", "path"),
    [
        (lambda p: p["elements"][0].update(reading_order="1"), "elements[0].reading_order"),
        (lambda p: p["elements"][0].update(reading_order=True), "elements[0].reading_order"),
        (lambda p: p["elements"][0].update(id=123), "elements[0].id"),
        (lambda p: p["elements"][0].update(raw_label=None), "elements[0].raw_label"),
        (lambda p: p["pages"][0].update(width="wide"), "pages[0].width"),
        (lambda p: p["pages"][0]["element_ids"].append({"id": "a"}), "pages[0].element_ids[2]"),
        (lambda p: p["elements"][0].update(metadata=[]), "elements[0].metadata"),
        (lambda p: p.update(title=7), "title"),
    ],
)
def test_wrong_json_types_are_findings_not_errors(change, path):
    data = payload()
    change(data)
    findings = validate_structured_document(structured_document_from_payload(data))

    assert [(msgid, kwargs["path"]) for msgid, kwargs in findings] == [(MSG_FIELD_WRONG_TYPE, path)]


def test_field_constraints():
    assert findings_for(lambda p: p["elements"][0].update(type="sidebar")) == [MSG_FIELD_NOT_ALLOWED]
    assert findings_for(lambda p: p["elements"][0].update(reading_order=0)) == [MSG_FIELD_OUT_OF_RANGE]
    assert findings_for(lambda p: p["pages"][0].update(width=0)) == [MSG_FIELD_OUT_OF_RANGE]
    assert findings_for(lambda p: p.update(language="p")) == [MSG_FIELD_OUT_OF_RANGE]
    bad_origin = lambda p: p["elements"][0]["provenance"][0]["bbox"].update(coord_origin="X")
    assert findings_for(bad_origin) == [MSG_FIELD_NOT_ALLOWED]


def test_findings_name_the_path():
    data = payload()
    data["elements"][0]["provenance"][0]["char_start"] = -1
    (finding,) = validate_structured_document(structured_document_from_payload(data))

    assert finding[1]["path"] == "elements[0].provenance[0].char_start"
