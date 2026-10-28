"""MathML the HTML export accepts, and what it still refuses."""

import pytest

from docstruct.export.html import _safe_mathml, document_to_html

NS = 'xmlns="http://www.w3.org/1998/Math/MathML"'
# What latex2mathml makes of ``v(t)=v_0+at,\quad t>0``.
QUAD_MATHML = (
    f"<math {NS}><mi>v</mi><mo>=</mo><mi>a</mi><mo>,</mo>"
    '<mstyle scriptlevel="0"><mspace width="1em"></mspace></mstyle>'
    "<mi>t</mi><mo>&gt;</mo><mn>0</mn></math>"
)


def _math_document(mathml: str) -> dict:
    block = {
        "id": "eq-1",
        "type": "math",
        "text": r"v=a,\quad t>0",
        "alt_text": "v equals a",
        "metadata": {"mathml": mathml},
    }
    return {"title": "Formulas", "sections": [{"blocks": [block]}]}


def test_spacing_from_quad_renders_as_mathml() -> None:
    html = document_to_html(_math_document(QUAD_MATHML), profile="html")

    assert '<div id="eq-1" role="math" aria-label="v equals a"><math' in html
    assert 'width="1em"' in html
    assert r"\quad" not in html


def test_mspace_sizes_are_accepted() -> None:
    mathml = f'<math {NS}><mspace width="1em" height="1ex" depth="0.5ex"/></math>'

    safe = _safe_mathml(mathml)

    assert safe is not None
    for attribute in ('width="1em"', 'height="1ex"', 'depth="0.5ex"'):
        assert attribute in safe, attribute


@pytest.mark.parametrize(
    "element",
    [
        '<mpadded voffset="0.2em"><mi>x</mi></mpadded>',
        '<mo minsize="1.2em" maxsize="1.2em">(</mo>',
        '<mtable columnwidth="auto"><mtr><mtd><mi>x</mi></mtd></mtr></mtable>',
    ],
)
def test_presentational_sizes_are_accepted(element: str) -> None:
    assert _safe_mathml(f"<math {NS}>{element}</math>") is not None


def test_active_attributes_are_still_refused() -> None:
    for attribute in ('href="https://example.com"', 'onclick="alert(1)"', 'style="x"'):
        mathml = f'<math {NS}><mspace width="1em" {attribute}/></math>'
        assert _safe_mathml(mathml) is None, attribute


def test_refused_mathml_falls_back_to_the_latex_source() -> None:
    refused = QUAD_MATHML.replace('width="1em"', 'width="1em" href="https://example.com"')

    html = document_to_html(_math_document(refused), profile="html")

    assert "<math" not in html
    assert r"\quad" in html
