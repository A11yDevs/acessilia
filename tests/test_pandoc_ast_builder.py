from backend.pipeline.pandoc_ast_builder import build_pandoc_ast


def test_build_pandoc_ast_emits_table_node_from_table_ast():
    document = {
        "title": "Documento com tabela",
        "language": "pt-BR",
        "verbosity": "detailed",
        "sections": [
            {
                "id": "sec-1",
                "title": "Seção",
                "level": 1,
                "blocks": [
                    {
                        "id": "tbl-1",
                        "type": "table",
                        "table_ast": {
                            "caption": "Resumo",
                            "header": [
                                {
                                    "cells": [
                                        {"text": "Coluna", "scope": "col"},
                                        {"text": "Valor", "scope": "col"},
                                    ]
                                }
                            ],
                            "body": [
                                {
                                    "cells": [
                                        {"text": "Taxa"},
                                        {"text": "10%"},
                                    ]
                                }
                            ],
                        },
                    }
                ],
                "children": [],
            }
        ],
    }

    ast = build_pandoc_ast(document)

    table_blocks = [block for block in ast["blocks"] if block.get("t") == "Table"]
    assert table_blocks
    table_node = table_blocks[0]
    assert table_node["t"] == "Table"
    caption = table_node["c"][1]
    assert isinstance(caption, list)
    assert caption[0]


def test_build_pandoc_ast_preserves_empty_structural_cells():
    document = _document_with_table(
        {
            "body": [
                {
                    "cells": [
                        {"text": "A"},
                        {"text": ""},
                        {"text": "C"},
                    ]
                }
            ]
        }
    )

    table_node = next(
        block for block in build_pandoc_ast(document)["blocks"] if block["t"] == "Table"
    )
    first_body_row = table_node["c"][4][0][3][0]

    assert len(first_body_row[1]) == 3
    assert first_body_row[1][1][4][0]["c"] == []


def test_build_pandoc_ast_marks_common_leading_row_headers():
    document = _document_with_table(
        {
            "body": [
                {
                    "cells": [
                        {"text": "Janeiro", "header": True, "scope": "row"},
                        {"text": "10"},
                    ]
                },
                {
                    "cells": [
                        {"text": "Fevereiro", "header": True, "scope": "row"},
                        {"text": "12"},
                    ]
                },
            ]
        }
    )

    table_node = next(
        block for block in build_pandoc_ast(document)["blocks"] if block["t"] == "Table"
    )
    table_body = table_node["c"][4][0]

    assert table_body[1] == 1
    assert table_body[3][0][1][0][4][0]["t"] == "Plain"


def test_build_pandoc_ast_counts_effective_width_from_colspans():
    document = _document_with_table(
        {
            "body": [
                {
                    "cells": [
                        {"text": "A", "colspan": 2},
                        {"text": "B"},
                    ]
                }
            ]
        }
    )

    table_node = next(
        block for block in build_pandoc_ast(document)["blocks"] if block["t"] == "Table"
    )

    assert len(table_node["c"][2]) == 3
    assert len(table_node["c"][4][0][3][0][1]) == 2


def _document_with_table(table_ast: dict) -> dict:
    return {
        "title": "Documento com tabela",
        "language": "pt-BR",
        "verbosity": "detailed",
        "sections": [
            {
                "id": "sec-1",
                "title": "Seção",
                "level": 1,
                "blocks": [
                    {
                        "id": "tbl-1",
                        "type": "table",
                        "table_ast": table_ast,
                    }
                ],
                "children": [],
            }
        ],
    }
