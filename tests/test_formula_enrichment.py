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


def test_verbalize_latex_fallback_portuguese():
    spoken = verbalize_latex_fallback(r"$x=\frac{a}{b}$")
    assert spoken.startswith("Fórmula:")
    assert "igual a" in spoken
    assert "fração" in spoken
    assert "\\" not in spoken
    assert "{" not in spoken


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
