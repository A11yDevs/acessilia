"""Inline math spans in prose reach every export as math (#265)."""
import json

import pytest

from backend.pipeline import canonical_builder
from backend.pipeline.pandoc_ast_builder import build_pandoc_ast, degrade_math_to_text
from docstruct.canonical import _enrich_math_blocks, build_canonical_document
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


def test_html_renders_inline_mathml_labelled_by_its_speech():
    html = document_to_html(_enriched("seja $s(t)$ &"))

    assert (
        'seja <math xmlns="http://www.w3.org/1998/Math/MathML" '
        'aria-label="s de t"><mi>t</mi></math>' in html
    )
    assert "$" not in html
    assert "&amp;" in html


def test_html_without_mathml_keeps_the_latex_labelled_by_its_speech():
    entry = {"source": "s(t)", "latex": "s(t)", "speech": "s de t"}
    html = document_to_html(_document(_paragraph("seja $s(t)$", inline_math=[entry])))

    assert '<span role="math" aria-label="s de t">s(t)</span>' in html


def test_exports_without_enrichment_keep_the_latex_marked_as_math():
    document = _document(_paragraph("seja $x^2$ aqui"))

    assert '<p id="b1">seja <span role="math">x^2</span> aqui</p>' in document_to_html(document)
    assert "seja x^2 aqui" in document_to_txt_lines(document)


def test_fallbacks_use_the_normalized_latex():
    entry = {"source": r"\text{x}", "latex": "x"}
    document = _document(_paragraph(r"seja $\text{x}$", inline_math=[entry]))

    assert '<span role="math">x</span>' in document_to_html(document)
    assert "seja x" in document_to_txt_lines(document)


def test_txt_reads_the_span():
    lines = document_to_txt_lines(_enriched("seja $s(t)$, logo"))

    assert "seja s de t, logo" in lines


def test_txt_without_speech_drops_the_delimiters():
    lines = document_to_txt_lines(_document(_paragraph("seja $x^2$")))

    assert "seja x^2" in lines


def test_backend_inline_speech_has_no_formula_label(monkeypatch):
    monkeypatch.setattr(canonical_builder, "toolbox_verbalize_latex", lambda latex: " s de t ")

    assert canonical_builder.verbalize_inline_latex("s(t)") == "s de t"


class _PerFormulaEnricher:
    """Distinct MathML and speech per formula, to catch a wrong pairing."""

    def normalize(self, latex: str) -> str:
        return latex

    def to_mathml(self, latex: str) -> str:
        return f'<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>{latex[0]}</mi></math>'

    def verbalize(self, latex: str) -> str:
        return f"Formula: {latex}"

    def verbalize_inline(self, latex: str) -> str:
        return f"fala {latex[0]}"


def test_the_canonical_build_wires_each_prose_type_to_its_own_formula():
    payload = {
        "text": "",
        "pages": [
            {
                "blocks": [
                    {"type": "paragraph", "text": "seja $a+1$ e $b+2$"},
                    {"type": "list", "items": [r"vale \(c+3\)"]},
                    {"type": "note", "text": "nota $d+4$"},
                ]
            }
        ],
    }

    document = build_canonical_document(payload, title="t", math_enricher=_PerFormulaEnricher())

    txt = document_to_txt_lines(document)
    assert "seja fala a e fala b" in txt
    assert "- vale fala c" in txt
    assert "nota fala d" in txt
    html = document_to_html(document)
    for letter in "abcd":
        assert (
            f'<math xmlns="http://www.w3.org/1998/Math/MathML" '
            f'aria-label="fala {letter}"><mi>{letter}</mi>' in html
        )
    ast = json.dumps(build_pandoc_ast(document)["blocks"])
    for latex in ("a+1", "b+2", "c+3", "d+4"):
        assert json.dumps({"t": "Math", "c": [{"t": "InlineMath"}, latex]}) in ast


class _DuckEnricher:
    def normalize(self, latex: str) -> str:
        return latex

    def to_mathml(self, latex: str) -> str:
        return MATHML

    def verbalize(self, latex: str) -> str:
        return "Formula: x"


def test_an_enricher_without_inline_speech_still_converts():
    block = {"id": "b1", "type": "paragraph", "text": "seja $x$", "metadata": None}

    _enrich_math_blocks(_document(block)["sections"], _DuckEnricher())

    assert block["metadata"]["inline_math"] == [{"source": "x", "latex": "x", "mathml": MATHML}]


@pytest.mark.parametrize(
    "line, block_type",
    [
        ("The area is $x^{2}$ square meters.", "paragraph"),
        ("Let $s_{0}$ be the position.", "paragraph"),
        ("$a^{2}$ e $b^{2}$", "paragraph"),
        ("s_{0} = v_{0} t", "math"),
        ("$x^{2}+1$", "math"),
    ],
)
def test_a_sentence_with_inline_math_is_not_a_math_block(line, block_type):
    from docstruct.blocks.parser import parse_text_to_blocks

    (block,) = parse_text_to_blocks(line)

    assert block["type"] == block_type


def _payload(*blocks):
    return {"pages": [{"page_number": 1, "blocks": list(blocks)}]}


def _blocks(document):
    return [block for section in document["sections"] for block in section["blocks"]]


def test_a_paragraph_of_one_span_becomes_display_math_in_the_html():
    payload = _payload({"id": "p1", "type": "paragraph", "text": "$s(t) = t^3$"})

    document = build_canonical_document(payload, title="t", math_enricher=_Enricher())

    (block,) = _blocks(document)
    assert block["type"] == "math"
    assert block["text"] == "s(t)=t^3"
    assert block["metadata"]["inline_math_promoted"] is True
    html = document_to_html(document)
    assert (
        '<div id="p1"><math xmlns="http://www.w3.org/1998/Math/MathML" '
        'aria-label="Formula: s(t)=t^3" display="block">' in html
    )
    assert "$" not in html


def test_promotion_reuses_the_conversion_the_span_already_carries():
    entry = {"source": "s(t)", "latex": "s(t)", "mathml": MATHML, "speech": "s de t"}
    payload = _payload(
        {"id": "p1", "type": "paragraph", "text": "$s(t)$", "metadata": {"inline_math": [entry]}}
    )
    enricher = _Enricher()

    document = build_canonical_document(payload, title="t", math_enricher=enricher)

    (block,) = _blocks(document)
    assert (block["type"], block["text"], block["alt_text"]) == ("math", "s(t)", "s de t")
    assert block["metadata"]["mathml"] == MATHML
    assert "inline_math" not in block["metadata"]
    assert enricher.calls == []


@pytest.mark.parametrize(
    "block",
    [
        {"id": "p1", "type": "paragraph", "text": "$s(t)$."},
        {"id": "p1", "type": "paragraph", "text": "let $s(t)$"},
        {"id": "p1", "type": "paragraph", "text": "costs R$ 10,00"},
        {"id": "p1", "type": "list", "items": ["$s(t)$"], "text": "$s(t)$"},
    ],
)
def test_only_a_paragraph_made_of_one_span_is_promoted(block):
    document = build_canonical_document(_payload(block), title="t", math_enricher=_Enricher())

    assert _blocks(document)[0]["type"] == block["type"]


def test_promotion_can_be_turned_off():
    payload = _payload({"id": "p1", "type": "paragraph", "text": "$s(t)$"})

    document = build_canonical_document(
        payload, title="t", math_enricher=_Enricher(), inline_math_promote=False
    )

    (block,) = _blocks(document)
    assert block["type"] == "paragraph"
    assert block["metadata"]["inline_math"][0]["source"] == "s(t)"
