"""docstruct.manifest: the document part of the processing manifest (#203)."""
import pytest

from docstruct.geometry import OrientedBox
from docstruct.manifest import (
    MSG_DUPLICATE_ELEMENT_IDS,
    MSG_DUPLICATE_PAGE_NUMBERS,
    MSG_FIELD_NOT_ALLOWED,
    MSG_FIELD_OUT_OF_RANGE,
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
