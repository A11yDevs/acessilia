"""Testes do enriquecimento de fórmulas: MathML, verbalização, renderização e PDDL.

MathML e texto falado vêm só da Toolbox (math.convert, math.verbalize; ADR-0007):
os testes simulam essas capacidades e conferem que a indisponibilidade é
explícita, sem conversão local.
"""

from datetime import datetime, timezone

import pytest

from backend.export.renderers.html_renderer import _render_block as render_html_block
from backend.export.renderers.txt_renderer import _render_block as render_txt_block
from backend.pipeline.validators import validate_canonical_document
from backend.tools.formula_tools import label_spoken_formula, normalize_latex
from backend.tools.toolbox_math_tools import MathCapabilityUnavailable
from acessilia_sdk.toolbox import ToolboxProviderUnavailable

FAKE_MATHML = '<math xmlns="http://www.w3.org/1998/Math/MathML"><mi>E</mi></math>'


def _unavailable(capability):
    def call(latex):
        call.calls.append(latex)
        raise MathCapabilityUnavailable(capability, ToolboxProviderUnavailable("offline"))

    call.calls = []
    return call


@pytest.fixture
def toolbox_math(monkeypatch):
    """Simula math.convert e math.verbalize no builder canônico e no PDDL."""
    from backend.agents import pddl_orchestrator
    from backend.pipeline import canonical_builder

    calls = {"convert": [], "verbalize": []}

    def convert(latex, direction="latex-to-mathml"):
        calls["convert"].append(latex)
        return FAKE_MATHML

    def verbalize(latex, language="pt-BR"):
        calls["verbalize"].append(latex)
        return "maiúscula e é igual a, m c ao quadrado"

    for module in (canonical_builder, pddl_orchestrator):
        monkeypatch.setattr(module, "toolbox_convert_latex", convert)
        monkeypatch.setattr(module, "toolbox_verbalize_latex", verbalize)
    return calls


# ── formula_tools ──


def test_normalize_latex_strips_delimiters():
    assert normalize_latex("$E=mc^2$") == "E=mc^2"
    assert normalize_latex("$$x+y$$") == "x+y"
    assert normalize_latex(r"\[a-b\]") == "a-b"
    assert normalize_latex("  x  =  1  ") == "x = 1"


def test_label_spoken_formula():
    assert label_spoken_formula("a sobre b") == "Fórmula: a sobre b"
    assert label_spoken_formula("  ") == ""


def test_core_has_no_local_converter_or_verbalizer():
    from backend.tools import formula_tools

    assert not hasattr(formula_tools, "latex_to_mathml")
    assert not hasattr(formula_tools, "verbalize_latex_fallback")


# ── canonical_builder: enriquecimento ──


def test_enrichment_skips_non_math_without_changing_document(monkeypatch):
    from copy import deepcopy

    from backend.pipeline import canonical_builder

    def unexpected(*args):
        pytest.fail("Non-math blocks must not invoke formula helpers")

    for name in ("normalize_latex", "latex_to_mathml", "verbalize_latex"):
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


def test_canonical_document_enriches_math_blocks(toolbox_math):
    from backend.pipeline.canonical_builder import build_canonical_document

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
    assert block["text"] == "E=mc^2"  # delimitadores removidos antes da Toolbox
    assert toolbox_math == {"convert": ["E=mc^2"], "verbalize": ["E=mc^2"]}
    assert block["metadata"]["mathml"] == FAKE_MATHML
    assert block["alt_text"] == "Fórmula: maiúscula e é igual a, m c ao quadrado"
    assert not document.get("technical_warnings")


def test_rejected_formula_keeps_latex_and_is_counted(monkeypatch, toolbox_math):
    """LaTeX que a Toolbox rejeita fica sem MathML; o documento conta as fórmulas."""
    from backend.pipeline import canonical_builder

    monkeypatch.setattr(canonical_builder, "toolbox_convert_latex", lambda latex: "")
    document = canonical_builder.build_canonical_document("$x=1$\n\n$y=2$")
    block = document["sections"][0]["blocks"][0]
    assert block["text"] == "x=1"
    assert "mathml" not in block.get("metadata", {})
    assert block["alt_text"].startswith("Fórmula:")
    # Rejection is not an outage: every formula is still tried.
    assert toolbox_math["verbalize"] == ["x=1", "y=2"]
    warnings = document["technical_warnings"]
    assert len(warnings) == 1
    assert "math.convert" in warnings[0] and "2" in warnings[0]


def test_unavailable_capabilities_are_reported_once(monkeypatch):
    """Sem fallback local: a fórmula fica com o LaTeX e o documento avisa."""
    from backend.pipeline import canonical_builder

    convert = _unavailable("math.convert")
    verbalize = _unavailable("math.verbalize")
    monkeypatch.setattr(canonical_builder, "toolbox_convert_latex", convert)
    monkeypatch.setattr(canonical_builder, "toolbox_verbalize_latex", verbalize)

    document = canonical_builder.build_canonical_document("$x=1$\n\n$y=2$\n\n$z=3$")

    math_blocks = [
        b for section in document["sections"] for b in section.get("blocks", [])
        if b.get("type") == "math"
    ]
    assert [b["text"] for b in math_blocks] == ["x=1", "y=2", "z=3"]
    assert all("mathml" not in b.get("metadata", {}) for b in math_blocks)
    assert all(not b.get("alt_text") for b in math_blocks)
    # One attempt per capability: an outage costs one timeout, not one per formula.
    assert convert.calls == ["x=1"]
    assert verbalize.calls == ["x=1"]
    warnings = document["technical_warnings"]
    assert len(warnings) == 2
    assert any("math.convert" in w and "ToolboxProviderUnavailable" in w for w in warnings)
    assert any("math.verbalize" in w for w in warnings)


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
    assert '<math xmlns="http://www.w3.org/1998/Math/MathML">' in html
    assert "&lt;math" not in html


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


def test_pddl_mathml_handler_enriches_formula_element(toolbox_math):
    from backend.agents.pddl_orchestrator import _handle_mathml_method

    manifest = _manifest_with_formula()
    result = _handle_mathml_method(manifest, "o-f")

    assert result.success
    assert toolbox_math["convert"] == ["E=mc^2"]
    assert manifest.elements[0].metadata["mathml"] == FAKE_MATHML


def test_pddl_latex_verbalizer_handler(toolbox_math):
    from backend.agents.pddl_orchestrator import _handle_latex_verbalizer_method

    manifest = _manifest_with_formula()
    result = _handle_latex_verbalizer_method(manifest, "o-f")

    assert result.success
    assert manifest.elements[0].metadata["verbalization"] == (
        "Fórmula: maiúscula e é igual a, m c ao quadrado"
    )


@pytest.mark.parametrize(
    ("handler", "patched", "capability"),
    [
        ("_handle_mathml_method", "toolbox_convert_latex", "math.convert"),
        ("_handle_latex_verbalizer_method", "toolbox_verbalize_latex", "math.verbalize"),
    ],
)
def test_pddl_handlers_fail_explicitly_when_capability_unavailable(
    monkeypatch, handler, patched, capability
):
    from backend.agents import pddl_orchestrator

    monkeypatch.setattr(pddl_orchestrator, patched, _unavailable(capability))
    manifest = _manifest_with_formula()
    result = getattr(pddl_orchestrator, handler)(manifest, "o-f")

    assert not result.success
    assert capability in result.message
    assert manifest.elements[0].metadata == {}


def test_pddl_mathml_handler_rejected_formula_is_partial(monkeypatch, toolbox_math):
    from backend.agents import pddl_orchestrator

    monkeypatch.setattr(pddl_orchestrator, "toolbox_convert_latex", lambda latex: "")
    result = pddl_orchestrator._handle_mathml_method(_manifest_with_formula(), "o-f")

    assert not result.success
    assert "0/1" in result.message


def test_pddl_handlers_fail_for_unknown_obligation():
    from backend.agents.pddl_orchestrator import _handle_mathml_method

    manifest = _manifest_with_formula()
    result = _handle_mathml_method(manifest, "o-inexistente")

    assert not result.success


def test_html_renderer_mathml_sanitizado():
    """Reject active markup in MathML and preserve the readable formula fallback."""
    block = {
        "id": "blk-1",
        "type": "math",
        "text": "x=1",
        "alt_text": "Fórmula",
        "metadata": {
            "mathml": '<math><mi>x</mi><script>alert(1)</script></math>'
        },
    }
    html = render_html_block(block, {})
    assert "&lt;script&gt;" not in html
    assert ">x=1</p>" in html
    assert "<script>" not in html
