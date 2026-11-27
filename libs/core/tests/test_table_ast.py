import pytest
from locale_support import use_server_locale

import acessilia_core.i18n as i8n
from acessilia_core.pipeline.table_ast import linearize_table_for_text
from docstruct.tables.ast import rows_from_table_ast, table_ast_from_rows


def test_pure_docstruct_reexports_are_deprecated():
    from acessilia_core.pipeline import table_ast as bridge

    with pytest.warns(
        DeprecationWarning,
        match=(
            r"^acessilia_core\.pipeline\.table_ast\.rows_from_table_ast is deprecated; "
            r"import it from docstruct\.tables\.ast$"
        ),
    ):
        from acessilia_core.pipeline.table_ast import rows_from_table_ast as deprecated

    assert deprecated is rows_from_table_ast
    assert "rows_from_table_ast" in dir(bridge)


def test_localized_linearization_uses_the_catalog(monkeypatch):
    use_server_locale(monkeypatch, "pt_BR")
    i8n._catalog_for.cache_clear()
    try:
        lines = linearize_table_for_text(
            {
                "table_ast": {
                    "caption": "Dados",
                    "header": [{"cells": [{"text": "A"}]}],
                    "body": [{"cells": [{"text": "1"}]}],
                    "footer": [{"cells": [{"text": "F"}]}],
                }
            }
        )
    finally:
        i8n._catalog_for.cache_clear()

    assert lines == ["Tabela: Dados", "Linha 1: A: 1", "Rodapé: F"]


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
