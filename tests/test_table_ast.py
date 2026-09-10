from backend.pipeline.table_ast import rows_from_table_ast, table_ast_from_rows


def test_table_ast_preserves_empty_structural_cells():
    table_ast = table_ast_from_rows(
        [
            ["Nome", "Idade", "Cidade"],
            ["Ana", "", "Recife"],
        ]
    )

    assert table_ast is not None
    assert rows_from_table_ast(table_ast) == [
        ["Nome", "Idade", "Cidade"],
        ["Ana", "", "Recife"],
    ]
