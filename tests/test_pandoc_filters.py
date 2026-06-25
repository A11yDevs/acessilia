from filters.pandoc_filters import apply_output_profile_filter
from filters.pandoc_filters import strip_internal_audit_blocks


def _sample_document() -> dict:
    return {
        "title": "Documento",
        "sections": [
            {
                "id": "sec-1",
                "title": "Principal",
                "level": 1,
                "blocks": [
                    {
                        "id": "blk-1",
                        "type": "paragraph",
                        "text": "Base",
                        "verbosity": "basic",
                    },
                    {
                        "id": "blk-2",
                        "type": "paragraph",
                        "text": "Tecnico",
                        "verbosity": "technical",
                    },
                ],
                "children": [
                    {
                        "id": "sec-1-1",
                        "title": "Filha",
                        "level": 2,
                        "blocks": [
                            {
                                "id": "blk-3",
                                "type": "paragraph",
                                "text": "Filha base",
                                "verbosity": "basic",
                            },
                            {
                                "id": "blk-4",
                                "type": "paragraph",
                                "text": "Filha tecnica",
                                "verbosity": "technical",
                            },
                        ],
                        "children": [],
                    }
                ],
            }
        ],
    }


def test_strip_internal_audit_blocks_recursive_copy():
    document = _sample_document()

    filtered = strip_internal_audit_blocks(document, "txt")

    assert [block["id"] for block in filtered["sections"][0]["blocks"]] == ["blk-1"]
    assert [
        block["id"] for block in filtered["sections"][0]["children"][0]["blocks"]
    ] == ["blk-3"]
    assert [block["id"] for block in document["sections"][0]["blocks"]] == [
        "blk-1",
        "blk-2",
    ]


def test_apply_output_profile_filter_keeps_technical_blocks_in_html():
    blocks = _sample_document()["sections"][0]["blocks"]

    filtered = apply_output_profile_filter(blocks, "html")

    assert [block["id"] for block in filtered] == ["blk-1", "blk-2"]
