import json

import pytest

from backend.pipeline.pandoc_ast_builder import build_pandoc_ast, degrade_math_to_text


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


# ── Math the LaTeX compiler must not run ────────────────────────────────


def _math_document(latex: str) -> dict:
    return {
        "title": "Document with a formula",
        "language": "pt-BR",
        "sections": [
            {
                "id": "sec-1",
                "title": "Section",
                "level": 1,
                "blocks": [{"id": "m-1", "type": "math", "text": latex}],
                "children": [],
            }
        ],
    }


def _para_text(block: dict) -> str:
    return " ".join(
        inline["c"]
        for inline in block["c"]
        if isinstance(inline, dict) and inline.get("t") == "Str"
    )


def _math_blocks(ast: dict) -> list:
    return [
        inline
        for block in ast["blocks"]
        if isinstance(block.get("c"), list)
        for inline in block["c"]
        if isinstance(inline, dict) and inline.get("t") == "Math"
    ]


@pytest.mark.parametrize(
    "latex",
    [
        r"\input{secret.txt}",
        r"\@@input secret.txt",
        r"\InputIfFileExists{secret.txt}{}{}",
        r"\verbatiminput{secret.txt}",
        r"\lstinputlisting{secret.txt}",
        r"\import{./sub/}{secret}",
        r"\write18{rm -rf /}",
        r"\directlua{os.execute('id')}",
        r"\openout0=x ",
        r"\usepackage{chemfig}",
        r"\csname input\endcsname secret.txt",
    ],
)
def test_a_math_macro_the_compiler_must_not_run_becomes_text(latex):
    """OCR and vision models supply the math text; the PDF/UA renderer compiles
    it with LaTeX, so file/shell primitives degrade to plain text instead of
    reaching the compilation."""
    ast = build_pandoc_ast(_math_document(latex))

    assert not _math_blocks(ast)
    block = next(block for block in ast["blocks"] if block.get("t") == "Para")
    assert latex.strip() in _para_text(block)


def test_an_unknown_but_benign_math_macro_stays_math():
    """\chemfig is not in the guard: rejecting every unknown macro would
    degrade legitimate math. What the LaTeX compiler still rejects is the
    PDF/UA retry's job (degrade_math_to_text)."""
    latex = r"\chemfig{*6((-SO_2O^-Na^+)-=-=)=-=(-N=N-C(=O-O^-Na^+)-N(-C(-OH)=N)=-=)}"

    ast = build_pandoc_ast(_math_document(latex))

    math_blocks = _math_blocks(ast)
    assert len(math_blocks) == 1
    assert math_blocks[0]["c"][1] == latex


def test_degrade_math_to_text_swaps_the_formula_for_its_source():
    ast = build_pandoc_ast(_math_document(r"E=mc^2"))

    degraded = degrade_math_to_text(ast)

    assert not _math_blocks(degraded)
    block = next(block for block in degraded["blocks"] if block.get("t") == "Para")
    assert "E=mc^2" in _para_text(block)
    # The original AST is untouched: the retry degrades a copy.
    assert len(_math_blocks(ast)) == 1


def test_degrade_math_to_text_keeps_the_non_math_blocks():
    document = _math_document(r"\chemfig{*6(-=-=--=)}")
    document["sections"][0]["blocks"].insert(
        0, {"id": "p-1", "type": "paragraph", "text": "Before the formula."}
    )
    ast = build_pandoc_ast(document)

    degraded = degrade_math_to_text(ast)

    kinds = [block.get("t") for block in degraded["blocks"]]
    assert kinds == ["Header", "Para", "Para"]
    texts = [_para_text(block) for block in degraded["blocks"] if block.get("t") == "Para"]
    assert "Before the formula." in texts[0]
    assert "chemfig" in texts[1]


def test_degrade_math_to_text_visits_quotes_divs_and_table_cells():
    """The walk covers the whole payload. build_pandoc_ast does not emit Math
    in these places today, but degrade_math_to_text is public API and must
    keep the promise if the builder ever does."""
    math = {"t": "Math", "c": [{"t": "InlineMath"}, "H_2O"]}
    ast = {
        "pandoc-api-version": [1, 23, 1],
        "meta": {},
        "blocks": [
            {"t": "BlockQuote", "c": [{"t": "Para", "c": [dict(math)]}]},
            {"t": "Div", "c": [["d", [], []], [{"t": "Plain", "c": [dict(math)]}]]},
            {
                "t": "Table",
                "c": [
                    ["", [], []],
                    [[], []],
                    [],
                    [
                        ["", [], []],
                        [[["", [], []], [], 1, 1, [{"t": "Plain", "c": [dict(math)]}]]],
                    ],
                    [],
                    [],
                ],
            },
        ],
    }

    def _math_nodes(node):
        if isinstance(node, list):
            return [found for child in node for found in _math_nodes(child)]
        if isinstance(node, dict):
            if node.get("t") == "Math":
                return [node]
            payload = node["c"] if "c" in node else node.get("blocks", [])
            return _math_nodes(payload)
        return []

    degraded = degrade_math_to_text(ast)

    assert _math_nodes(ast) and len(_math_nodes(degraded)) == 0
    quote_para = degraded["blocks"][0]["c"][0]
    assert quote_para["c"][0] == {"t": "Str", "c": "H_2O"}
    div_plain = degraded["blocks"][1]["c"][1][0]
    assert div_plain["c"][0] == {"t": "Str", "c": "H_2O"}


def test_a_math_block_is_display_math():
    ast = build_pandoc_ast(_math_document(r"E=mc^2"))

    (math,) = _math_blocks(ast)
    assert math["c"][0] == {"t": "DisplayMath"}


def test_a_formula_with_speech_carries_it_to_the_pdf_ua_renderer():
    """The span is what the renderer turns into the Formula's alternate text (#256)."""
    document = _math_document(r"\frac{a}{b}")
    document["sections"][0]["blocks"][0]["alt_text"] = "Formula: a over b"

    ast = build_pandoc_ast(document)

    para = next(block for block in ast["blocks"] if block["t"] == "Para")
    (span,) = para["c"]
    assert span["t"] == "Span"
    assert span["c"][0] == ["", ["accessilia-formula"], [["alt", "Formula: a over b"]]]
    assert span["c"][1] == [{"t": "Math", "c": [{"t": "DisplayMath"}, r"\frac{a}{b}"]}]


def test_degrading_a_formula_with_speech_removes_its_math():
    document = _math_document(r"\frac{a}{b}")
    document["sections"][0]["blocks"][0]["alt_text"] = "Formula: a over b"

    degraded = degrade_math_to_text(build_pandoc_ast(document))

    assert "Math" not in json.dumps(degraded)
