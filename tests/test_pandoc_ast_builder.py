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
