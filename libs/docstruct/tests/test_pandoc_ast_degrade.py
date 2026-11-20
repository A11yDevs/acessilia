"""Per-formula degradation helpers in ``docstruct.export.pandoc_ast`` (#258)."""
from __future__ import annotations

import json
from copy import deepcopy

from docstruct.export.pandoc_ast import (
    FORMULA_ALT_CLASS,
    build_pandoc_ast,
    count_math_nodes,
    degrade_math_to_text,
    unconverted_math_indices,
)

MATHML = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'


def _collect_math_latex(node: object) -> list[str]:
    if isinstance(node, list):
        found: list[str] = []
        for item in node:
            found.extend(_collect_math_latex(item))
        return found
    if isinstance(node, dict):
        if node.get("t") == "Math":
            content = node.get("c")
            return [str(content[1])] if isinstance(content, list) and len(content) > 1 else [""]
        if "c" in node:
            return _collect_math_latex(node["c"])
        if "blocks" in node:
            return _collect_math_latex(node["blocks"])
    return []


def _collect_formula_spans(node: object) -> list[dict]:
    if isinstance(node, list):
        found: list[dict] = []
        for item in node:
            found.extend(_collect_formula_spans(item))
        return found
    if isinstance(node, dict):
        if node.get("t") == "Span":
            attrs = node["c"][0]
            if len(attrs) > 1 and FORMULA_ALT_CLASS in (attrs[1] or []):
                return [node]
        if "c" in node:
            return _collect_formula_spans(node["c"])
        if "blocks" in node:
            return _collect_formula_spans(node["blocks"])
    return []


def _multi_formula_document() -> dict:
    return {
        "title": "Physics",
        "language": "en-US",
        "sections": [
            {
                "id": "sec-1",
                "title": "Equations",
                "level": 1,
                "blocks": [
                    {
                        "id": "m-1",
                        "type": "math",
                        "text": "E = mc^2",
                        "alt_text": "Formula: E equals m c squared",
                        "metadata": {"mathml": MATHML},
                    },
                    {
                        "id": "p-1",
                        "type": "paragraph",
                        "text": r"Inline $a + b$ and $\chemfig{H-O-H}$ in prose.",
                        "metadata": {
                            "inline_math": [
                                {
                                    "source": "a + b",
                                    "latex": "a + b",
                                    "mathml": MATHML,
                                    "speech": "a plus b",
                                },
                                {
                                    "source": r"\chemfig{H-O-H}",
                                    "latex": r"\chemfig{H-O-H}",
                                    "speech": "water",
                                },
                            ]
                        },
                    },
                    {
                        "id": "t-1",
                        "type": "table",
                        "table_ast": {
                            "caption": "Table with $x^2$",
                            "header": [{"cells": [{"text": "Var $y$", "scope": "col"}]}],
                            "body": [{"cells": [{"text": r"Bad $\ce{H2O}$"}]}],
                        },
                        "metadata": {
                            "inline_math": [
                                {"source": "x^2", "latex": "x^2", "mathml": MATHML},
                                {"source": "y", "latex": "y", "mathml": MATHML},
                                {"source": r"\ce{H2O}", "latex": r"\ce{H2O}"},
                            ]
                        },
                    },
                    {
                        "id": "m-2",
                        "type": "math",
                        "text": r"\frac{1}{2}",
                        "alt_text": "Formula: one half",
                        "metadata": {"mathml": MATHML},
                    },
                ],
                "children": [],
            }
        ],
    }


def test_count_math_nodes_covers_display_inline_and_tables():
    ast = build_pandoc_ast(_multi_formula_document())

    assert count_math_nodes(ast) == 7
    assert _collect_math_latex(ast) == [
        "E = mc^2",
        "a + b",
        r"\chemfig{H-O-H}",
        "x^2",
        "y",
        r"\ce{H2O}",
        r"\frac{1}{2}",
    ]


def test_degrade_math_to_text_selective_preserves_other_formulas_and_alt_spans():
    ast = build_pandoc_ast(_multi_formula_document())
    snapshot = deepcopy(ast)

    degraded = degrade_math_to_text(ast, indices={2, 5})

    # Original AST is untouched.
    assert ast == snapshot
    # Only indices 2 (\chemfig) and 5 (\ce) were degraded.
    assert _collect_math_latex(degraded) == [
        "E = mc^2",
        "a + b",
        "x^2",
        "y",
        r"\frac{1}{2}",
    ]
    # Surviving formulas keep their FORMULA_ALT_CLASS spans; degraded ones unwrap.
    spans = _collect_formula_spans(degraded)
    alt_values = [dict(span["c"][0][2])["alt"] for span in spans]
    assert alt_values == [
        "Formula: E equals m c squared",
        "a plus b",
        "Formula: one half",
    ]
    blocks_json = json.dumps(degraded["blocks"])
    assert "chemfig" in blocks_json
    assert "water" not in blocks_json
    assert "H2O" in blocks_json


def test_degrade_math_to_text_empty_indices_keeps_ast_equal():
    ast = build_pandoc_ast(_multi_formula_document())

    assert degrade_math_to_text(ast, indices=set()) == ast


def test_degrade_math_to_text_all_indices_matches_full_degradation():
    ast = build_pandoc_ast(_multi_formula_document())
    total = count_math_nodes(ast)

    assert degrade_math_to_text(ast, indices=range(total)) == degrade_math_to_text(ast)


def test_unconverted_math_indices_identifies_formulas_without_mathml():
    ast = build_pandoc_ast(_multi_formula_document(), target_format="pdf_ua")

    assert unconverted_math_indices(ast, target_format="pdf_ua") == frozenset({2, 5})


def test_unconverted_math_indices_empty_when_no_formula_has_mathml():
    doc = {
        "title": "Unenriched",
        "language": "en-US",
        "sections": [
            {
                "id": "s1",
                "title": "Math",
                "level": 1,
                "blocks": [
                    {"id": "m1", "type": "math", "text": "x=1"},
                    {"id": "m2", "type": "math", "text": "y=2"},
                ],
                "children": [],
            }
        ],
    }
    ast = build_pandoc_ast(doc)

    assert unconverted_math_indices(ast) == frozenset()


def test_unconverted_math_indices_empty_when_all_formulas_have_mathml():
    doc = {
        "title": "All converted",
        "language": "en-US",
        "sections": [
            {
                "id": "s1",
                "title": "Math",
                "level": 1,
                "blocks": [
                    {"id": "m1", "type": "math", "text": "x=1", "metadata": {"mathml": MATHML}},
                    {"id": "m2", "type": "math", "text": "y=2", "metadata": {"mathml": MATHML}},
                ],
                "children": [],
            }
        ],
    }
    ast = build_pandoc_ast(doc)

    assert unconverted_math_indices(ast) == frozenset()


def test_unconverted_math_indices_empty_when_ast_drifted_from_source():
    ast = build_pandoc_ast(_multi_formula_document())
    tampered = {**ast, "blocks": ast["blocks"][:1]}

    assert unconverted_math_indices(tampered) == frozenset()
