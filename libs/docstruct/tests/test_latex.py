"""Tests for canonical LaTeX normalization in docstruct.text.latex."""
from __future__ import annotations

from docstruct.text.latex import normalize_latex, strip_latex_delimiters, wrap_latex


class TestStripLatexDelimiters:
    def test_double_dollar_display(self):
        assert strip_latex_delimiters("$$ E = mc^2 $$") == "E = mc^2"
        assert strip_latex_delimiters("$$\nx^2 + y^2 = z^2\n$$") == "x^2 + y^2 = z^2"

    def test_single_dollar_inline(self):
        assert strip_latex_delimiters("$x + y$") == "x + y"
        assert strip_latex_delimiters("  $  \\alpha  $  ") == "\\alpha"

    def test_bracket_display(self):
        assert strip_latex_delimiters(r"\[ \int_0^1 f(x) dx \]") == r"\int_0^1 f(x) dx"

    def test_paren_inline(self):
        assert strip_latex_delimiters(r"\( a^2 + b^2 \)") == r"a^2 + b^2"

    def test_equation_environment(self):
        assert strip_latex_delimiters(r"\begin{equation} y = mx + b \end{equation}") == "y = mx + b"
        assert strip_latex_delimiters(r"\begin{equation*} y = mx + b \end{equation*}") == "y = mx + b"

    def test_no_delimiters(self):
        assert strip_latex_delimiters("x + 1") == "x + 1"
        assert strip_latex_delimiters("") == ""
        assert strip_latex_delimiters("   ") == ""


class TestNormalizeLatex:
    def test_none_and_empty(self):
        assert normalize_latex(None) == ""
        assert normalize_latex("") == ""
        assert normalize_latex("   ") == ""

    def test_unicode_minus_and_spaces(self):
        assert normalize_latex("x \u2212 5 = 0") == "x - 5 = 0"
        assert normalize_latex("a\u00a0+\u2009b") == "a + b"

    def test_unicode_math_symbols(self):
        assert normalize_latex("a × b") == r"a \times b"
        assert normalize_latex("a ÷ b") == r"a \div b"
        assert normalize_latex("x ≤ 10") == r"x \le 10"
        assert normalize_latex("y ≥ 0") == r"y \ge 0"
        assert normalize_latex("a ≠ b") == r"a \ne b"
        assert normalize_latex("π ≈ 3.14") == r"\pi \approx 3.14"
        assert normalize_latex("x ± 2") == r"x \pm 2"
        assert normalize_latex("a · b") == r"a \cdot b"

    def test_greek_letters(self):
        assert normalize_latex("α + β = γ") == r"\alpha + \beta = \gamma"
        assert normalize_latex("Δx / Δt") == r"\Delta x / \Delta t"
        assert normalize_latex("θ = 2π") == r"\theta = 2 \pi"

    def test_ocr_wrapper_removal(self):
        assert normalize_latex(r"\text{x} + \mathrm{y}") == "x + y"
        assert normalize_latex(r"\text{ 2 }") == "2"

    def test_superscript_subscript_normalization(self):
        assert normalize_latex("x ^ { 2 }") == "x^{2}"
        assert normalize_latex("x _ { i }") == "x_{i}"
        assert normalize_latex("x ^ 2") == "x^2"
        assert normalize_latex("x _ 1") == "x_1"

    def test_relational_and_binary_spacing(self):
        assert normalize_latex("a=b") == "a = b"
        assert normalize_latex("a<b") == "a < b"
        assert normalize_latex(r"a\le b") == r"a \le b"
        assert normalize_latex("x+y") == "x + y"
        assert normalize_latex("x-y") == "x - y"

    def test_spacing_macros(self):
        assert normalize_latex(r"a \, b \; c \quad d") == "a b c d"

    def test_angle_bracket_delimiters(self):
        assert normalize_latex(r"\left< x \right>") == r"\left< x \right>"
        assert normalize_latex(r"\left < x \right >") == r"\left< x \right>"
        assert normalize_latex(r"\langle x \rangle") == r"\langle x \rangle"
        assert normalize_latex(r"\left\langle x \right\rangle") == r"\left\langle x \right\rangle"
        assert normalize_latex("a < b and c > d") == "a < b and c > d"


class TestWrapLatex:
    def test_wrap_display(self):
        assert wrap_latex("E = mc^2", display=True) == "$$E = mc^2$$"
        assert wrap_latex("$$E = mc^2$$", display=True) == "$$E = mc^2$$"
        assert wrap_latex(r"\[ E = mc^2 \]", display=True) == "$$E = mc^2$$"

    def test_wrap_inline(self):
        assert wrap_latex("x + 1", display=False) == "$x + 1$"
        assert wrap_latex("$x + 1$", display=False) == "$x + 1$"
        assert wrap_latex(r"\( x + 1 \)", display=False) == "$x + 1$"

    def test_wrap_empty(self):
        assert wrap_latex(None) == ""
        assert wrap_latex("") == ""
        assert wrap_latex("   ") == ""
