"""Testes da normalização de LaTeX (``docstruct.text.latex``).

Espelham o fallback local de ``backend/tools/formula_tools.normalize_latex``.
"""
from docstruct.text.latex import normalize_latex, wrap_latex


class TestNormalizeLatex:
    def test_remove_delimitadores_display(self):
        assert normalize_latex("$$x + y$$") == "x + y"

    def test_remove_delimitadores_inline(self):
        assert normalize_latex("$x + y$") == "x + y"

    def test_remove_delimitadores_colchete(self):
        assert normalize_latex("\\[x + y\\]") == "x + y"

    def test_remove_delimitadores_parentese(self):
        assert normalize_latex("\\(x + y\\)") == "x + y"

    def test_entrada_vazia(self):
        assert normalize_latex("") == ""
        assert normalize_latex("   ") == ""

    def test_simbolos_unicode(self):
        assert normalize_latex("a \u2212 b") == "a - b"
        assert normalize_latex("a \u00d7 b") == "a \\times b"
        assert normalize_latex("a \u00f7 b") == "a \\div b"

    def test_espacos_unicode_viram_espaco(self):
        assert normalize_latex("a\u00a0b") == "a b"
        assert normalize_latex("a\u2009b") == "a b"
        assert normalize_latex("a\u202fb") == "a b"

    def test_zero_width_space_e_removido(self):
        assert normalize_latex("a\u200bb") == "ab"

    def test_comandos_de_espacamento(self):
        assert normalize_latex("a \\quad b") == "a b"
        assert normalize_latex("a \\qquad b") == "a b"
        assert normalize_latex("a \\, b") == "a b"

    def test_espaco_de_chaves(self):
        assert normalize_latex("\\frac{ a }{ b }") == "\\frac{a}{b}"

    def test_espaco_de_operadores(self):
        assert normalize_latex("a=b") == "a = b"
        assert normalize_latex("a  =  b") == "a = b"

    def test_expoente_negativo(self):
        assert normalize_latex("x^ - 2") == "x^-2"

    def test_parentese_negativo(self):
        assert normalize_latex("( - 2)") == "(-2)"

    def test_espacos_multiplos_colapsados(self):
        assert normalize_latex("a    b") == "a b"


class TestWrapLatex:
    def test_display(self):
        assert wrap_latex("x + y", display=True) == "$$x + y$$"

    def test_inline(self):
        assert wrap_latex("x + y") == "$x + y$"

    def test_vazio(self):
        assert wrap_latex("") == ""
