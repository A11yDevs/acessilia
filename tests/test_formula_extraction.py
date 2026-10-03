"""Shared formula classification and local extraction utilities."""

import pytest

from backend.tools.region_classifier import (
    classify_region,
    formula_already_extracted,
)
from backend.tools.region_extractor import Region


def _formula_region(text: str = "", enriched: bool = False) -> Region:
    return Region(
        bbox=(10.0, 10.0, 200.0, 60.0),
        type="formula",
        text=text,
        image_bytes=None,
        confidence=0.8,
        page_num=1,
        metadata={
            "source": "docling",
            "docling_type": "formula",
            "docling_label": "DocItemLabel.FORMULA",
            "docling_label_kind": "formula",
            "subtype": "",
            "formula_enriched": enriched,
        },
    )


def test_docling_formula_region_classified_as_formula():
    assert classify_region(_formula_region()) == "formula"


def test_formula_already_extracted_requires_enrichment_and_text():
    assert formula_already_extracted(_formula_region("E=mc^2", enriched=True))
    assert not formula_already_extracted(_formula_region("E=mc^2", enriched=False))
    assert not formula_already_extracted(_formula_region("", enriched=True))
    assert not formula_already_extracted(_formula_region("   ", enriched=True))


# ── Sentinela [FORMULA] do VisionAgent (imagem que na verdade é fórmula) ──


# ── Cascata local (OCR + CodeFormula) para imagens com fórmulas ──


def test_looks_like_latex():
    from backend.tools.formula_tools import looks_like_latex

    assert looks_like_latex(r"E=mc^2")
    assert looks_like_latex(r"\frac{a}{b}")
    assert not looks_like_latex("")
    assert not looks_like_latex("uma foto de gato")
    assert not looks_like_latex("x" * 3000)


def test_looks_math_heuristic():
    from backend.tools.formula_tools import _looks_math

    # Casos reais capturados pelo OCR no benchmark
    assert _looks_math("E mc²")                      # símbolo forte ²
    assert _looks_math("-b±√b2 4ac x = 2a")          # ± e √
    assert _looks_math("e -T 2 dx π 2 0")            # π
    assert _looks_math("∑##")                        # ∑
    assert _looks_math("A 二 a c b d")               # matriz: tokens de 1 char
    assert _looks_math("x = 2 + 2 ^ 2")              # fracos suficientes

    assert not _looks_math("")
    assert not _looks_math("Entrada Processo Saida")
    assert not _looks_math("2021 2022 2023")
    assert not _looks_math(
        "A acessibilidade digital garante que pessoas com deficiencia "
        "possam perceber, compreender, navegar e interagir com conteudos"
    )


def test_looks_math_unicode_math_symbol():
    """Sm cobre centenas de símbolos: ∀ ∃ ∈ ℝ ⊕ ⊗ etc."""
    from backend.tools.formula_tools import _looks_math

    # Símbolos matemáticos Unicode (Sm) fora da lista hardcoded original
    assert _looks_math("∀x ∈ ℝ")
    assert _looks_math("∃y ⊕ z")
    assert _looks_math("A ⊗ B")
    assert _looks_math("f: ℕ → ℕ")

    # Letras gregas e sobrescritos (não são Sm, mas são matemáticos)
    assert _looks_math("π r²")
    assert _looks_math("θ λ μ")

    # Não deve detectar prosa comum
    assert not _looks_math("O custo é R$ 5 + 2 = 7")
    assert _looks_math("A+B=C")


@pytest.mark.parametrize("text", [
    "∀x∈ℝ", "ℕ", "ℂ", "ℓ", "α β γ", "x¹", "x²", "x³", "x⁴", "x₉",
    "𝑥 + 𝑦", "[1 2; 3 4]", "a b c d", "x = 1", "sin(x)", "sin x",
    "sin(x) + cos(x) - tan(x)", "log(value) = exponent",
    "velocity = distance / time", "total_cost = unit_price * quantity",
])
def test_looks_math_accepts_symbols_and_named_expressions(text):
    from backend.tools.formula_tools import _looks_math

    assert _looks_math(text)


@pytest.mark.parametrize("text", [
    "O custo é R$ 5 + 2 = 7", "O total é $5 + $2 = $7", "Preço: €5 / unidade",
    "Marca™", "Marca®", "Temperatura 25℃", "25℉", "℀", "℁", "℅", "℆",
    "https://example.org/a+b?x=1&y=2", "www.example.org/a/b",
    "Veja a + b = c no manual", "O sinal + e o sinal = são usados aqui",
    "O a e o b estão no texto", "singular costume tangente logotipo",
    "Consulte sin e cos no manual", "Entrada Processo Saida",
])
def test_looks_math_rejects_prose_currency_trademarks_and_urls(text):
    from backend.tools.formula_tools import _looks_math

    assert not _looks_math(text)


@pytest.mark.parametrize("symbol", ["™", "®", "℃", "℉", "℀", "℁", "℅", "℆", "+", "=", "/"])
def test_non_math_and_weak_symbols_are_not_strong(symbol):
    from backend.tools.formula_tools import _is_strong_math_char

    assert not _is_strong_math_char(symbol)


def test_try_extract_formula_locally_skips_non_math(monkeypatch):
    from backend.tools import formula_tools

    monkeypatch.setattr(formula_tools, "ocr_image_text", lambda b: "gato na mesa")
    monkeypatch.setattr(
        formula_tools,
        "extract_latex_from_image",
        lambda b: (_ for _ in ()).throw(AssertionError("não deveria rodar")),
    )
    assert formula_tools.try_extract_formula_locally(b"img") == ""


def test_try_extract_formula_locally_runs_codeformula_on_math(monkeypatch):
    from backend.tools import formula_tools

    monkeypatch.setattr(
        formula_tools, "ocr_image_text", lambda b: "x = 2 + 2 ^ 2 = 6"
    )
    monkeypatch.setattr(
        formula_tools, "extract_latex_from_image", lambda b: r"x=2+2^2"
    )
    assert formula_tools.try_extract_formula_locally(b"img") == r"x=2+2^2"
