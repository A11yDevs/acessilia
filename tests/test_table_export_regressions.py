"""Regression cases for structured table export."""

from backend.agents.output_schemas import DataOutput
from docstruct.export.html import document_to_html
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.txt import document_to_txt_lines
from docstruct.tables.ast import effective_section_row_widths, normalize_table_ast


def _document_with_table(table_ast: dict) -> dict:
    return {
        "title": "Tabela de teste",
        "sections": [
            {"blocks": [{"id": "table-1", "type": "table", "table_ast": table_ast}]}
        ],
    }


def _render_table(document: dict) -> str:
    html = document_to_html(document, profile="html")
    start = html.index('<table id="table-1">')
    end = html.index("</table>", start) + len("</table>")
    return html[start:end]


def _pandoc_table(document: dict) -> dict:
    return next(
        block
        for block in build_pandoc_ast(document)["blocks"]
        if block["t"] == "Table"
    )


def test_offset_row_headers_keep_data_cells_out_of_table_header() -> None:
    table_ast = {
        "body": [
            {
                "cells": [
                    {"text": "1"},
                    {"text": "Bélgica", "header": True, "scope": "row"},
                    {"text": "Bruxelas"},
                ]
            },
            {
                "cells": [
                    {"text": "2"},
                    {"text": "França", "header": True, "scope": "row"},
                    {"text": "Paris"},
                ]
            },
        ]
    }
    expected_html = (
        '<table id="table-1"><tbody>'
        '<tr><td>1</td><th scope="row">Bélgica</th><td>Bruxelas</td></tr>'
        '<tr><td>2</td><th scope="row">França</th><td>Paris</td></tr>'
        "</tbody></table>"
    )
    document = _document_with_table(table_ast)
    pandoc_table = _pandoc_table(document)
    actual = {
        "html": _render_table(document),
        "pandoc_header_rows": len(pandoc_table["c"][3][1]),
        "pandoc_body_rows": len(pandoc_table["c"][4][0][3]),
        "txt": document_to_txt_lines(document),
    }
    expected = {
        "html": expected_html,
        "pandoc_header_rows": 0,
        "pandoc_body_rows": 2,
        "txt": ["Row 1: 1 | Bélgica | Bruxelas", "Row 2: 2 | França | Paris"],
    }

    assert actual == expected, (
        f"Entrada (table_ast): {table_ast!r}\n"
        f"Esperado: {expected!r}\n"
        f"Obtido: {actual!r}"
    )


def test_mixed_inferred_header_row_preserves_unmarked_data_cell() -> None:
    output = DataOutput(
        kind="table",
        rows=[
            {"cells": [{"text": ""}, {"text": "Valor", "header": True, "scope": "col"}]},
            {"cells": [{"text": "Janeiro", "header": True, "scope": "row"}, {"text": "10"}]},
            {"cells": [{"text": "Fevereiro", "header": True, "scope": "row"}, {"text": "12"}]},
        ],
        language="pt-BR",
        confidence=0.9,
    )
    document = _document_with_table(output.table_ast())

    assert _render_table(document) == (
        '<table id="table-1">'
        '<thead><tr><td></td><th scope="col">Valor</th></tr></thead>'
        '<tbody>'
        '<tr><th scope="row">Janeiro</th><td>10</td></tr>'
        '<tr><th scope="row">Fevereiro</th><td>12</td></tr>'
        '</tbody></table>'
    )


def test_empty_row_remains_between_rows_with_rowspan() -> None:
    table_ast = {
        "header": [
            {"cells": [{"text": "H1", "scope": "col"}, {"text": "H2", "scope": "col"}]}
        ],
        "body": [
            {"cells": [{"text": "A", "rowspan": 2}, {"text": "B"}]},
            {"cells": [{"text": ""}]},
            {"cells": [{"text": "C"}, {"text": "D"}]},
        ],
    }
    expected_html = (
        '<table id="table-1">'
        '<thead><tr><th scope="col">H1</th><th scope="col">H2</th></tr></thead>'
        '<tbody><tr><td rowspan="2">A</td><td>B</td></tr>'
        '<tr><td></td></tr><tr><td>C</td><td>D</td></tr></tbody>'
        "</table>"
    )
    document = _document_with_table(table_ast)
    normalized = normalize_table_ast(table_ast)
    assert normalized is not None
    pandoc_table = _pandoc_table(document)
    actual = {
        "html": _render_table(document),
        "widths": effective_section_row_widths(normalized["body"]),
        "pandoc_body_rows": len(pandoc_table["c"][4][0][3]),
        "pandoc_columns": len(pandoc_table["c"][2]),
        "txt": document_to_txt_lines(document),
    }
    expected = {
        "html": expected_html,
        "widths": [2, 2, 2],
        "pandoc_body_rows": 3,
        "pandoc_columns": 2,
        "txt": [
            "Row 1: H1: A; H2: B",
            "Row 2: ",
            "Row 3: H1: C; H2: D",
        ],
    }

    assert actual == expected, (
        f"Entrada (table_ast): {table_ast!r}\n"
        f"Esperado: {expected!r}\n"
        f"Obtido: {actual!r}"
    )

def test_drbench_renderers_preserve_mixed_header_cells() -> None:
    from scripts.drbench.markdown_converter import _render_table
    from scripts.drbench.run_pipeline import table_ast_to_html

    table_ast = {
        "header": [{"cells": [{"text": ""}, {"text": "Valor", "header": True, "scope": "col"}]}],
        "body": [{"cells": [{"text": "Janeiro", "header": True, "scope": "row"}, {"text": "10"}]}],
    }

    assert table_ast_to_html(table_ast) == (
        '<table><tr><td></td><th scope="col">Valor</th></tr>'
        '<tr><th scope="row">Janeiro</th><td>10</td></tr></table>'
    )
    assert _render_table({"table_ast": table_ast}) == (
        '<table><thead><tr><td></td><th scope="col">Valor</th></tr></thead>'
        '<tbody><tr><th scope="row">Janeiro</th><td>10</td></tr></tbody></table>'
    )
