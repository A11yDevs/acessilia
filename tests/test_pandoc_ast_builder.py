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


def test_build_pandoc_ast_preserves_empty_cells():
    document = {
        "title": "Documento com células vazias",
        "language": "pt-BR",
        "verbosity": "detailed",
        "sections": [
            {
                "id": "sec-1",
                "title": "Seção",
                "level": 1,
                "blocks": [
                    {
                        "id": "tbl-gantt",
                        "type": "table",
                        "table_ast": {
                            "caption": "Cronograma",
                            "header": [
                                {
                                    "cells": [
                                        {"text": "Tarefa"},
                                        {"text": "Semana 1"},
                                        {"text": "Semana 2"},
                                    ]
                                }
                            ],
                            "body": [
                                {
                                    "cells": [
                                        {"text": "Etapa 1"},
                                        {"text": "Ativo"},
                                        {"text": ""},  # Célula vazia
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
    table_node = [b for b in ast["blocks"] if b.get("t") == "Table"][0]
    # table_node["c"][4] is bodies: list of [attr, rowhead_columns, intermediate_head, rows]
    body_rows = table_node["c"][4][0][3]
    assert len(body_rows) == 1
    # row is [attr, cells]
    cells = body_rows[0][1]
    assert len(cells) == 3  # All 3 cells preserved, including the empty cell!

