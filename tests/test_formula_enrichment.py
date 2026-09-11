"""Testes do enriquecimento de fórmulas: MathML, verbalização, renderização e PDDL."""

from datetime import datetime, timezone

import pytest

from backend.export.renderers.html_renderer import _render_block as render_html_block
from backend.export.renderers.txt_renderer import _render_block as render_txt_block
from backend.pipeline.canonical_builder import build_canonical_document
from backend.pipeline.structure_parser import parse_text_to_blocks
from backend.pipeline.validators import validate_canonical_document
from backend.tools.formula_tools import (
    latex_to_mathml,
    normalize_latex,
    verbalize_latex_fallback,
)


# ── formula_tools ──


def test_normalize_latex_strips_delimiters():
    assert normalize_latex("$E=mc^2$") == "E=mc^2"
    assert normalize_latex("$$x+y$$") == "x+y"
    assert normalize_latex(r"\[a-b\]") == "a-b"
    assert normalize_latex("  x  =  1  ") == "x = 1"


@pytest.mark.docling  # latex2mathml vem apenas com o extra docling
def test_latex_to_mathml_converts_valid_latex():
    mathml = latex_to_mathml(r"$x=\frac{-b\pm\sqrt{b^2-4ac}}{2a}$")
    assert mathml.startswith("<math")
    assert "<mfrac>" in mathml


@pytest.mark.docling
def test_latex_to_mathml_handles_spaced_codeformula_output():
    mathml = latex_to_mathml(r"E = m c ^ { 2 }")
    assert mathml.startswith("<math")


def test_latex_to_mathml_empty_input():
    assert latex_to_mathml("") == ""
    assert latex_to_mathml("$$") == ""


def test_latex_to_mathml_warns_when_library_missing(monkeypatch):
    """Quando latex2mathml não está instalado, emite warning e retorna vazio."""
    import builtins

    from backend.tools import formula_tools

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "latex2mathml.converter":
            raise ModuleNotFoundError("private dependency detail", name="latex2mathml")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    records = []
    sink = formula_tools.logger.add(lambda message: records.append(message.record))
    try:
        assert formula_tools.latex_to_mathml(r"$private_source=1$") == ""
    finally:
        formula_tools.logger.remove(sink)

    assert len(records) == 1
    assert records[0]["level"].name == "WARNING"
    assert "latex2mathml indisponível" in records[0]["message"]
    assert "private" not in records[0]["message"]
    assert records[0]["exception"] is None


def test_latex_to_mathml_conversion_error_falls_back_without_source_leak(monkeypatch):
    import sys
    from types import ModuleType

    from backend.tools import formula_tools

    package = ModuleType("latex2mathml")
    converter = ModuleType("latex2mathml.converter")

    def fail(latex):
        raise ValueError(f"private conversion detail: {latex}")

    converter.convert = fail
    package.converter = converter
    monkeypatch.setitem(sys.modules, "latex2mathml", package)
    monkeypatch.setitem(sys.modules, "latex2mathml.converter", converter)
    records = []
    sink = formula_tools.logger.add(lambda message: records.append(message.record))
    try:
        assert formula_tools.latex_to_mathml("private_source=1") == ""
    finally:
        formula_tools.logger.remove(sink)

    assert len(records) == 1
    assert "Conversão LaTeX→MathML falhou" in records[0]["message"]
    assert "indisponível" not in records[0]["message"]
    assert "private" not in records[0]["message"]
    assert records[0]["exception"] is None


def test_latex_to_mathml_unexpected_import_error_still_falls_back(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fail_import(name, *args, **kwargs):
        if name == "latex2mathml.converter":
            raise RuntimeError("broken optional installation")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_import)
    assert latex_to_mathml("x=1") == ""


@pytest.mark.docling
def test_latex_to_mathml_malformed_conversion_returns_empty():
    assert latex_to_mathml(r"\frac{") == ""


def test_verbalize_latex_fallback_portuguese():
    spoken = verbalize_latex_fallback(r"$x=\frac{a}{b}$")
    assert spoken.startswith("Fórmula:")
    assert "igual a" in spoken
    assert "a sobre b" in spoken
    assert "\\" not in spoken
    assert "{" not in spoken


def test_verbalize_fraction_simple_uses_sobre():
    assert verbalize_latex_fallback(r"\frac{a}{b}") == "Fórmula: a sobre b"


def test_verbalize_nested_fraction_uses_dividido_por():
    spoken = verbalize_latex_fallback(r"\frac{\frac{a}{b}}{c}")
    assert spoken == "Fórmula: a sobre b, dividido por c"


def test_verbalize_compound_exponent_spoken_as_group():
    assert verbalize_latex_fallback(r"x^{n+1}") == "Fórmula: x elevado a n mais 1"


def test_verbalize_roots_by_index():
    assert verbalize_latex_fallback(r"\sqrt{x}") == "Fórmula: raiz quadrada de x"
    assert verbalize_latex_fallback(r"\sqrt[3]{x}") == "Fórmula: raiz cúbica de x"
    assert verbalize_latex_fallback(r"\sqrt[n]{x}") == "Fórmula: raiz de índice n de x"


def test_verbalize_keeps_renderer_fixture_string():
    assert verbalize_latex_fallback("E=mc^2") == "Fórmula: E igual a m c elevado a 2"


def test_verbalize_subscripts():
    assert verbalize_latex_fallback(r"x_{i}") == "Fórmula: x índice i"
    assert verbalize_latex_fallback(r"a_{ij}") == "Fórmula: a índice i j"


def test_verbalize_preserves_symbol_table():
    spoken = verbalize_latex_fallback(
        r"\sum \prod \int \lim \infty \pm \times \cdot \div \leq \geq \neq \approx "
        r"\alpha \beta \pi \theta \lambda \mu \sigma \omega \Delta \partial \nabla"
    )
    for word in (
        "somatório", "produtório", "integral", "limite", "infinito", "mais ou menos",
        "vezes", "dividido por", "menor ou igual a", "maior ou igual a", "diferente de",
        "aproximadamente", "alfa", "beta", "pi", "teta", "lambda", "mi", "sigma", "ômega",
        "delta", "derivada parcial", "nabla",
    ):
        assert word in spoken
    matrix = verbalize_latex_fallback(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}")
    assert matrix == "Fórmula: matriz: a, b; c, d fim da matriz"
    assert verbalize_latex_fallback(r"a\,b") == "Fórmula: a b"


def test_verbalize_drops_unknown_commands_but_speaks_content():
    spoken = verbalize_latex_fallback(r"\mathbf{v}=\left(a+b\right)")
    assert spoken.startswith("Fórmula:")
    assert "v igual a" in spoken
    assert "a mais b" in spoken
    assert "\\" not in spoken


def test_verbalize_unbalanced_input_degrades_gracefully():
    spoken = verbalize_latex_fallback(r"\frac{a")
    assert spoken.startswith("Fórmula:")
    assert "a" in spoken
    assert "{" not in spoken
    assert "\\" not in spoken


def test_verbalize_latex_fallback_empty():
    assert verbalize_latex_fallback("") == ""


# ── structure_parser: detecção de blocos math ──


def test_parser_detects_dollar_wrapped_math():
    blocks = parse_text_to_blocks("Introdução.\n\n$E=mc^2$\n\nConclusão.")
    types = [b["type"] for b in blocks]
    assert "math" in types
    math_block = next(b for b in blocks if b["type"] == "math")
    assert math_block["text"] == "$E=mc^2$"


def test_parser_detects_latex_commands_without_dollars():
    blocks = parse_text_to_blocks(r"x = \frac { - b \pm \sqrt { b ^ { 2 } } } { 2 a }")
    assert blocks[0]["type"] == "math"


def test_parser_keeps_normal_text_as_paragraph():
    blocks = parse_text_to_blocks("O preço é $10 e nada mais.")
    assert all(b["type"] != "math" for b in blocks)


# ── canonical_builder: enriquecimento ──


def test_enrichment_skips_non_math_without_changing_document(monkeypatch):
    from copy import deepcopy

    from backend.pipeline import canonical_builder

    def unexpected(*args):
        pytest.fail("Non-math blocks must not invoke formula helpers")

    for name in ("normalize_latex", "latex_to_mathml", "verbalize_latex_fallback"):
        monkeypatch.setattr(canonical_builder, name, unexpected)
    sections = [{"blocks": [{"type": "paragraph", "text": "Texto"}],
                 "children": [{"blocks": [{"type": "code", "text": "x=1"}]}]}]
    before = deepcopy(sections)
    canonical_builder._enrich_math_blocks(sections)
    canonical_builder._enrich_math_blocks([])
    assert sections == before


def test_enrichment_reaches_nested_math_and_preserves_alt_text(monkeypatch):
    from backend.pipeline import canonical_builder

    calls = []

    def convert(latex):
        calls.append(latex)
        return ""

    monkeypatch.setattr(canonical_builder, "latex_to_mathml", convert)
    block = {"type": "math", "text": "$x=1$", "alt_text": "Descrição existente"}
    sections = [{"blocks": [], "children": [{"blocks": [block]}]}]
    canonical_builder._enrich_math_blocks(sections)
    assert calls == ["x=1"]
    assert block == {"type": "math", "text": "x=1", "alt_text": "Descrição existente"}


def test_canonical_document_keeps_formula_when_conversion_unavailable(monkeypatch):
    from backend.pipeline import canonical_builder

    monkeypatch.setattr(canonical_builder, "latex_to_mathml", lambda latex: "")
    document = canonical_builder.build_canonical_document("$x=1$")
    block = document["sections"][0]["blocks"][0]
    assert block["type"] == "math"
    assert block["text"] == "x=1"
    assert block["alt_text"].startswith("Fórmula:")
    assert "mathml" not in block.get("metadata", {})


@pytest.mark.docling
def test_canonical_document_enriches_math_blocks():
    document = build_canonical_document(
        "# Física\n\nConsidere:\n\n$E=mc^2$\n", title="Física"
    )
    assert validate_canonical_document(document) == []

    math_blocks = [
        b
        for section in document["sections"]
        for b in section.get("blocks", [])
        if b.get("type") == "math"
    ]
    assert len(math_blocks) == 1
    block = math_blocks[0]
    assert block["text"] == "E=mc^2"  # delimitadores removidos
    assert block["metadata"]["mathml"].startswith("<math")
    assert block["alt_text"].startswith("Fórmula:")


# ── renderers ──


def _math_block() -> dict:
    return {
        "id": "blk-1",
        "type": "math",
        "text": "E=mc^2",
        "alt_text": "Fórmula: E igual a m c elevado a 2",
        "metadata": {"mathml": '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>E</mi></math>'},
    }


def test_html_renderer_embeds_mathml_with_aria_label():
    html = render_html_block(_math_block(), {})
    assert 'role="math"' in html
    assert 'aria-label="Fórmula: E igual a m c elevado a 2"' in html
    assert "<math" in html


def test_html_renderer_falls_back_to_text_without_mathml():
    block = _math_block()
    block["metadata"] = {}
    html = render_html_block(block, {})
    assert 'role="math"' in html
    assert "E=mc^2" in html


def test_txt_renderer_uses_verbalization():
    lines = render_txt_block(_math_block())
    assert lines == ["Fórmula: E igual a m c elevado a 2"]


def test_txt_renderer_falls_back_to_latex():
    block = _math_block()
    block["alt_text"] = ""
    lines = render_txt_block(block)
    assert lines == ["Fórmula: E=mc^2"]


# ── PDDL: handlers mathml e latex-verbalizer ──


def _manifest_with_formula():
    from backend.core.manifest.models import (
        ExtractorRun,
        ManifestElement,
        ManifestSummary,
        Obligation,
        PageDescriptor,
        ProcessingManifest,
        SourceDocument,
    )

    now = datetime(2026, 8, 19, tzinfo=timezone.utc)
    return ProcessingManifest(
        manifest_id="manifest-formula-1",
        created_at=now,
        source=SourceDocument(
            document_id="doc-f",
            filename="f.pdf",
            path="/tmp/f.pdf",
            media_type="application/pdf",
            byte_size=1,
            sha256="a" * 64,
        ),
        extractor=ExtractorRun(
            version="2.0.0",
            started_at=now,
            completed_at=now,
            duration_ms=1,
            configuration={},
        ),
        title="Doc",
        language="pt-BR",
        pages=[PageDescriptor(page_number=1, element_ids=["el-f"])],
        elements=[
            ManifestElement(
                id="el-f",
                type="formula",
                raw_label="formula",
                reading_order=1,
                hierarchy_level=1,
                text=r"$E=mc^2$",
                page_number=1,
            )
        ],
        obligations=[
            Obligation(
                id="o-f",
                kind="verbalize-formula",
                target_ids=["el-f"],
                admissible_methods=["mathml", "latex-verbalizer", "human-review"],
                method_costs={"mathml": 10, "latex-verbalizer": 20, "human-review": 100},
                rationale="Fórmula deve ser acessível",
            )
        ],
        summary=ManifestSummary(
            page_count=1,
            element_count=1,
            observation_count=0,
            obligation_count=1,
            element_types={"formula": 1},
        ),
    )


@pytest.mark.docling
def test_pddl_mathml_handler_enriches_formula_element():
    from backend.agents.pddl_orchestrator import _handle_mathml_method

    manifest = _manifest_with_formula()
    result = _handle_mathml_method(manifest, "o-f")

    assert result.success
    assert manifest.elements[0].metadata["mathml"].startswith("<math")


def test_pddl_latex_verbalizer_handler():
    from backend.agents.pddl_orchestrator import _handle_latex_verbalizer_method

    manifest = _manifest_with_formula()
    result = _handle_latex_verbalizer_method(manifest, "o-f")

    assert result.success
    assert "igual a" in manifest.elements[0].metadata["verbalization"]


def test_pddl_handlers_fail_for_unknown_obligation():
    from backend.agents.pddl_orchestrator import _handle_mathml_method

    manifest = _manifest_with_formula()
    result = _handle_mathml_method(manifest, "o-inexistente")

    assert not result.success
