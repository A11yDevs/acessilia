"""Object markers enclose each transformed object (docstruct.export.markers)."""

from __future__ import annotations

import copy

from docstruct.export.markers import wrap_object_markers

LABELS = {"image": "image", "table": "table", "math": "formula"}


def _document():
    return {
        "title": "Deck",
        "sections": [
            {
                "title": "Slide 1",
                "blocks": [
                    {"id": "b-1", "type": "paragraph", "text": "Intro."},
                    {"id": "b-2", "type": "image", "alt_text": "A scale."},
                ],
                "children": [
                    {
                        "title": "Inner",
                        "blocks": [
                            {"id": "b-3", "type": "math", "text": "x = y"},
                            {"id": "b-4", "type": "table", "rows": [["a"]]},
                        ],
                    }
                ],
            }
        ],
    }


def _texts(blocks):
    return [block.get("text") or block["type"] for block in blocks]


def test_each_object_is_enclosed_in_its_markers():
    marked = wrap_object_markers(_document(), LABELS)

    [section] = marked["sections"]
    assert _texts(section["blocks"]) == ["Intro.", "[image]", "image", "[/image]"]
    assert _texts(section["children"][0]["blocks"]) == [
        "[formula]", "x = y", "[/formula]", "[table]", "table", "[/table]",
    ]
    opening = section["blocks"][1]
    assert opening["type"] == "paragraph"
    assert opening["id"] == "b-2-marker-open"
    assert opening["metadata"] == {"object_marker": True}


def test_the_document_given_is_left_as_it_was():
    document = _document()
    original = copy.deepcopy(document)

    wrap_object_markers(document, LABELS)

    assert document == original


def test_a_type_without_a_label_is_not_marked():
    marked = wrap_object_markers(_document(), {"image": "image"})

    inner = marked["sections"][0]["children"][0]["blocks"]
    assert _texts(inner) == ["x = y", "table"]


def test_blocks_without_an_id_get_markers_with_ids_of_their_own():
    document = {
        "sections": [
            {
                "blocks": [
                    {"type": "image", "alt_text": "One."},
                    {"type": "image", "alt_text": "Two."},
                ],
                "children": [{"blocks": [{"type": "math", "text": "x"}]}],
            }
        ]
    }

    marked = wrap_object_markers(document, LABELS)

    [section] = marked["sections"]
    ids = [block["id"] for block in [*section["blocks"], *section["children"][0]["blocks"]] if "id" in block]
    assert ids == [
        "object-1-marker-open", "object-1-marker-close",
        "object-2-marker-open", "object-2-marker-close",
        "object-3-marker-open", "object-3-marker-close",
    ]
