import pytest

from docstruct.tables.ast import rows_from_table_ast, table_ast_from_rows


def test_pure_docstruct_reexports_are_deprecated():
    with pytest.warns(DeprecationWarning, match="docstruct.tables.ast"):
        from acessilia_core.pipeline.table_ast import rows_from_table_ast as deprecated

    assert deprecated is rows_from_table_ast


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
