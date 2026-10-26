"""Inline math spans in prose reach every export as math (#265)."""
import json

import pytest

from backend.pipeline import canonical_builder
from backend.pipeline.pandoc_ast_builder import build_pandoc_ast, degrade_math_to_text
from docstruct.canonical import _enrich_math_blocks
from docstruct.export.html import document_to_html
from docstruct.export.txt import document_to_txt_lines
from docstruct.text.math_spans import split_inline_math

MATHML = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>t</mi></math>'


@pytest.mark.parametrize(
    "text, expected",
    [
        (
            r"dada por $s(t)=t^3$, com $v_0 \in \mathbb{R}$.",
            [
                ("dada por ", False),
                ("s(t)=t^3", True),
                (", com ", False),
                (r"v_0 \in \mathbb{R}", True),
                (".", False),
            ],
        ),
        (r"de \(a+b\) e ($x$)", [("de ", False), ("a+b", True), (" e (", False), ("x", True), (")", False)]),
        ("custa R$ 10,00", [("custa R$ 10,00", False)]),
        ("R$5 ou R$ 3", [("R$5 ou R$ 3", False)]),
        ("entre $5 e $10", [("entre $5 e $10", False)]),
        ("$$x^2$$", [("$$x^2$$", False)]),
    ],
)
def test_split_inline_math(text, expected):
    assert split_inline_math(text) == expected


class _Enricher:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def normalize(self, latex: str) -> str:
        return latex.replace(" ", "")

    def to_mathml(self, latex: str) -> str:
        self.calls.append(("to_mathml", latex))
        return MATHML

    def verbalize(self, latex: str) -> str:
        self.calls.append(("verbalize", latex))
        return f"Formula: {latex}"

    def verbalize_inline(self, latex: str) -> str:
        self.calls.append(("verbalize_inline", latex))
        return "s de t"


def _document(*blocks):
    return {"title": "", "sections": [{"id": "s1", "title": "", "blocks": list(blocks), "children": []}]}


def _paragraph(text, **metadata):
    return {"id": "b1", "type": "paragraph", "text": text, "metadata": metadata}


def test_enrichment_converts_each_span_once_per_document():
    first = _paragraph("seja $s(t)$ e $s(t)$")
    second = {"id": "b2", "type": "list", "items": ["vale $s(t)$"], "metadata": {}}
    enricher = _Enricher()

    _enrich_math_blocks(_document(first, second)["sections"], enricher)

    assert first["metadata"]["inline_math"] == [
        {"source": "s(t)", "latex": "s(t)", "mathml": MATHML, "speech": "s de t"}
    ]
    assert second["metadata"]["inline_math"] == first["metadata"]["inline_math"]
    assert enricher.calls == [("to_mathml", "s(t)"), ("verbalize_inline", "s(t)")]


def test_enrichment_without_spans_leaves_the_block_alone():
    block = _paragraph("no formulas, R$ 10,00")

    _enrich_math_blocks(_document(block)["sections"], _Enricher())

    assert "inline_math" not in block["metadata"]


def _enriched(text):
    entry = {"source": "s(t)", "latex": "s(t)", "mathml": MATHML, "speech": "s de t"}
    return _document(_paragraph(text, inline_math=[entry]))


def test_pandoc_ast_emits_inline_math_with_its_speech():
    ast = build_pandoc_ast(_enriched("seja $s(t)$, logo"))

    para = next(block for block in ast["blocks"] if block["t"] == "Para")
    assert para["c"] == [
        {"t": "Str", "c": "seja"},
        {"t": "Space"},
        {
            "t": "Span",
            "c": [
                ["", ["accessilia-formula"], [["alt", "s de t"]]],
                [{"t": "Math", "c": [{"t": "InlineMath"}, "s(t)"]}],
            ],
        },
        {"t": "Str", "c": ","},
        {"t": "Space"},
        {"t": "Str", "c": "logo"},
    ]


def test_pandoc_ast_without_enrichment_still_emits_math():
    ast = build_pandoc_ast(_document(_paragraph("$x^2$ vale")))

    para = next(block for block in ast["blocks"] if block["t"] == "Para")
    assert para["c"][0] == {"t": "Math", "c": [{"t": "InlineMath"}, "x^2"]}


def test_pandoc_ast_keeps_an_unsafe_span_as_text():
    ast = build_pandoc_ast(_document(_paragraph(r"veja $\input{x}$")))

    assert "Math" not in json.dumps(ast["blocks"])


def test_degrading_removes_inline_math():
    degraded = degrade_math_to_text(build_pandoc_ast(_enriched("seja $s(t)$")))

    assert "Math" not in json.dumps(degraded["blocks"])


def test_html_renders_inline_mathml():
    html = document_to_html(_enriched("seja $s(t)$ &"))

    assert "seja <math" in html
    assert "$" not in html
    assert "&amp;" in html


def test_html_without_mathml_keeps_the_latex_labelled_by_its_speech():
    entry = {"source": "s(t)", "latex": "s(t)", "speech": "s de t"}
    html = document_to_html(_document(_paragraph("seja $s(t)$", inline_math=[entry])))

    assert '<span role="math" aria-label="s de t">s(t)</span>' in html


def test_txt_reads_the_span():
    lines = document_to_txt_lines(_enriched("seja $s(t)$, logo"))

    assert "seja s de t, logo" in lines


def test_txt_without_speech_drops_the_delimiters():
    lines = document_to_txt_lines(_document(_paragraph("seja $x^2$")))

    assert "seja x^2" in lines


def test_backend_inline_speech_has_no_formula_label(monkeypatch):
    monkeypatch.setattr(canonical_builder, "toolbox_verbalize_latex", lambda latex: " s de t ")

    assert canonical_builder.verbalize_inline_latex("s(t)") == "s de t"
