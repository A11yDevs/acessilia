"""Tests for canonical LaTeX normalization in docstruct.text.latex."""
from __future__ import annotations

from docstruct.text.latex import (
    has_latex_markup,
    latex_text_agreement,
    normalize_latex,
    strip_latex_delimiters,
    wrap_latex,
)


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


class TestConservativeHelpers:
    """``bare_latex`` and ``ensure_math_delimiters`` never rewrite the math."""

    def test_bare_latex_strips_one_pair_and_collapses_whitespace(self):
        from docstruct.text.latex import bare_latex

        assert bare_latex("  $$ x ^ { 2 }\n+  1 $$  ") == "x ^ { 2 } + 1"
        assert bare_latex("$$$a$$$") == "$a$"
        assert bare_latex(r"\[ \alpha \]") == r"\alpha"
        assert bare_latex(r"\( a \)") == "a"
        assert bare_latex("α ^ { 2 }") == "α ^ { 2 }"
        assert bare_latex("") == ""
        assert bare_latex("$ $") == ""

    def test_markdown_export_uses_the_same_function(self):
        from docstruct.export import markdown
        from docstruct.text import latex

        assert markdown.bare_latex is latex.bare_latex

    def test_ensure_math_delimiters(self):
        from docstruct.text.latex import ensure_math_delimiters

        assert ensure_math_delimiters("  x + 1 ") == "$x + 1$"
        assert ensure_math_delimiters("$x$") == "$x$"
        assert ensure_math_delimiters("$$x$$") == "$$x$$"
        assert ensure_math_delimiters(r"\[x\]") == r"\[x\]"
        assert ensure_math_delimiters(r"\(x\)") == r"$\(x\)$"
        assert ensure_math_delimiters("   ") == ""


class TestHasLatexMarkup:
    def test_text_layer_formulas_are_not_latex(self):
        assert not has_latex_markup("s(t) = s0 + v0t + 1\n2\nat2, t > 0,")
        assert not has_latex_markup("∀y(xCy → ∃z(yCz ∧ z ∈ αi))")

    def test_set_braces_from_the_text_layer_are_not_markup(self):
        assert not has_latex_markup("Dom(vm2) = [−2, 0) ∪ (0, +∞) = {h ∈ R : h ≥ −2}")

    def test_commands_and_scripts_are_latex(self):
        assert has_latex_markup(r"\frac{1}{2}")
        assert has_latex_markup("t^3")
        assert has_latex_markup("s_0")

    def test_delimited_text_is_latex(self):
        assert has_latex_markup("$x=1$")
        assert has_latex_markup(r"\(x\)")

    def test_empty_is_not_latex(self):
        assert not has_latex_markup(None)
        assert not has_latex_markup("  ")
        assert not has_latex_markup("$$")


class TestLatexTextAgreement:
    def test_the_same_formula_agrees_despite_its_structure(self):
        latex = r"s(t) = s_0 + v_0 t + \frac{1}{2} a t^2, \quad t > 0,"
        assert latex_text_agreement(latex, "s(t) = s0 + v0t + 1\n2\nat2, t > 0,") == 1.0

    def test_commands_count_as_their_glyphs(self):
        latex = r"\lim_{h \to 0} \alpha \neq \infty"
        assert latex_text_agreement(latex, "lim h→0 α ≠ ∞") == 1.0

    def test_a_detached_negation_composes_and_minus_signs_match(self):
        assert latex_text_agreement(r"h \neq -2", "h =\u0338 \u22122") == 1.0

    def test_a_different_formula_disagrees(self):
        score = latex_text_agreement("x^2 + y^2 = 1", "s(t) = s0 + v0t + 1 2 at2")
        assert score < 0.5

    def test_unicode_scripts_and_ligatures_fold(self):
        assert latex_text_agreement("x^2", "x²") == 1.0
        assert latex_text_agreement("v_0", "v₀") == 1.0
        assert latex_text_agreement(r"\operatorname{fi}", "ﬁ") == 1.0

    def test_logic_and_set_symbols_are_compared(self):
        assert latex_text_agreement(r"\neg x", "¬x") == 1.0
        assert latex_text_agreement(r"\neg x", "x") < 1.0
        assert latex_text_agreement(r"x \wedge y", "x ∧ y") == 1.0
        assert latex_text_agreement(r"x \wedge y", "x ∨ y") < 1.0
        assert latex_text_agreement(r"\forall x \exists y", "∀x ∃y") == 1.0
        assert latex_text_agreement(r"A \subseteq B \cup \emptyset", "A ⊆ B ∪ ∅") == 1.0

    def test_every_single_glyph_is_a_visible_symbol(self):
        """The compared symbols come from the glyph table, so they cannot drift."""
        from docstruct.text.latex import _COMMAND_GLYPHS, _VISIBLE_SYMBOLS

        for glyph in _COMMAND_GLYPHS.values():
            if len(glyph) == 1 and not glyph.isalnum():
                assert glyph in _VISIBLE_SYMBOLS, glyph

    def test_portuguese_function_names_match_latex(self):
        assert latex_text_agreement(r"\tan x", "tg x") == 1.0
        assert latex_text_agreement(r"\sin x", "sen x") == 1.0
        assert latex_text_agreement(r"\max f", "máx f") == 1.0
        assert latex_text_agreement(r"\operatorname{t g} x", "tg x") == 1.0
        assert latex_text_agreement(r"\operatorname*{l i m}_{h \to 0}", "lim h→0") == 1.0

    def test_nothing_visible_is_not_scored(self):
        assert latex_text_agreement(r"\quad", "  ") is None
