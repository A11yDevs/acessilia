"""Equation labels are preserved without consuming mathematical parentheses."""
import pytest

from docstruct.text.equations import numbered_latex, preserve_equation_number, split_equation_number
from docstruct.canonical import MathEnricher, build_canonical_document
from docstruct.export.html import document_to_html
from docstruct.export.markdown import document_to_markdown
from docstruct.export.pandoc_ast import build_pandoc_ast
from docstruct.export.txt import document_to_txt_lines


@pytest.mark.parametrize("source,expression,number", [
    (r"x = y\tag{1}", "x = y", "1"),
    (r"x = y\quad(2)", "x = y", "2"),
    ("x = y (3)", "x = y", "3"),
    ("x = 28h.(1)", "x = 28h.", "1"),
    (r"$$x=y\tag{01}$$", "x=y", "01"),
    (r"x=y\tag{A.1}", "x=y", "A.1"),
])
def test_split_label(source, expression, number):
    assert split_equation_number(source) == (expression, number)


@pytest.mark.parametrize("source", [
    "f(x) = (1)", "f(x) = (x + 1)", "x = y + (1)", "x(1)", "x + (1)",
    r"x = y \times (1)", r"x=\frac{1}{(2)}", r"x=y\tag{a}\tag{2}",
    r"x=y\tag{\input{file}}", "(1)", r"x=\sin (1)",
])
def test_ambiguous_or_unsafe_input_is_unchanged(source):
    assert split_equation_number(source) == (source, None)


def test_existing_number_and_idempotence():
    metadata = {"equation_number": "7"}
    expression = preserve_equation_number(r"x=y\tag{1}", metadata)
    assert expression == "x=y"
    assert metadata["equation_number"] == "7"
    assert preserve_equation_number(expression, metadata) == expression
    assert numbered_latex(numbered_latex(expression, metadata), metadata) == r"x=y\tag{7}"


@pytest.mark.parametrize("value", [None, "", r"\input{file}"])
def test_recognized_label_replaces_missing_or_invalid_metadata(value):
    metadata = {"equation_number": value}
    assert preserve_equation_number(r"x=y\tag{1}", metadata) == "x=y"
    assert metadata["equation_number"] == "1"


def test_zero_is_a_valid_equation_number():
    assert numbered_latex("x=y", {"equation_number": 0}) == r"x=y\tag{0}"


def test_existing_delimiters_do_not_nest_in_numbered_output():
    assert numbered_latex("$$x=y$$", {"equation_number": "1"}) == r"x=y\tag{1}"


class RecordingMath(MathEnricher):
    def __init__(self):
        self.converted = []
        self.spoken = []

    def to_mathml(self, latex):
        self.converted.append(latex)
        return '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>x</mi></math>'

    def verbalize(self, latex):
        self.spoken.append(latex)
        return "x equals y"


def numbered_document():
    enricher = RecordingMath()
    document = build_canonical_document(
        {"pages": [{"blocks": [{"id": "eq-1", "type": "math", "text": r"x=y\tag{1}"}]}]},
        math_enricher=enricher,
    )
    return document, enricher


def test_number_survives_canonical_and_all_export_boundaries():
    document, enricher = numbered_document()
    block = document["sections"][0]["blocks"][0]
    assert block["text"] == "x=y"
    assert block["metadata"]["equation_number"] == "1"
    assert block["alt_text"] == "(1) x equals y"
    assert enricher.converted == ["x=y"]
    assert enricher.spoken == ["x=y"]
    html = document_to_html(document)
    assert 'aria-label="(1) x equals y"' in html
    assert 'class="equation-number" aria-hidden="true">(1)</span>' in html
    assert r"\tag{1}" not in html
    assert "(1) x equals y" in document_to_txt_lines(document)
    assert r"x=y\tag{1}" in document_to_markdown(document)
    span = build_pandoc_ast(document)["blocks"][0]["c"][0]
    assert span["c"][0][2] == [["alt", "(1) x equals y"]]
    assert span["c"][1][0]["c"][1] == r"x=y\tag{1}"
    docx_span = build_pandoc_ast(document, target_format="docx")["blocks"][0]["c"][0]
    assert docx_span["c"][1][0]["c"][1] == r"x=y\qquad\text{(1)}"


def test_invalid_metadata_cannot_inject_export_markup():
    block = {"type": "math", "text": "x=y", "metadata": {"equation_number": r"\input{secret}"}}
    document = {"sections": [{"blocks": [block]}]}
    assert r"\input" not in document_to_html(document)
    assert r"\input" not in str(build_pandoc_ast(document)["blocks"])
    assert r"\tag" not in document_to_markdown(document)


def test_unnumbered_block_is_unchanged_without_an_enricher():
    document = build_canonical_document({"pages": [{"blocks": [{"type": "math", "text": "x=y"}]}]})
    block = document["sections"][0]["blocks"][0]
    assert not block.get("alt_text")
    assert not block.get("metadata", {}).get("equation_number")
    assert r"\tag" not in document_to_markdown(document)


def test_numbered_formula_without_speech_keeps_expression_in_accessible_label():
    document = build_canonical_document({"pages": [{"blocks": [{"type": "math", "text": r"x=y\tag{1}"}]}]})
    assert 'aria-label="(1) x=y"' in document_to_html(document)
