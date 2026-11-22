"""A variable followed by a parenthesis is a product, not a function application."""
import pytest

from docstruct.text.implicit_products import (
    INVISIBLE_TIMES as IT,
    implicit_product_variables,
    mark_implicit_products,
)

# Case 036 (velocidade-instantanea), abridged: h is a variable, s and v are functions.
CASE_036 = [
    r"vm_2(h) = \frac{s(2 + h) - s(2)}{(2 + h) - 2}",
    r"h \neq 0",
    r"\lim_{h \to 0} vm_2(h) = 12",
    r"s(t) = t^3",
    r"v(t) = \lim_{h \to 0} \frac{h(3t^2 + 3th + h^2)}{h}",
    r"\frac{h(12 + 6h + h^2)}{h}",
]


def test_case_036_variables_and_functions():
    variables = implicit_product_variables(CASE_036)

    assert "h" in variables and "t" in variables
    assert "s" not in variables and "v" not in variables


def test_only_the_variable_products_are_marked():
    variables = implicit_product_variables(CASE_036)

    assert mark_implicit_products(r"\frac{h(12 + 6h + h^2)}{h}", variables) == (
        r"\frac{h" + IT + r"(12 + 6h + h^2)}{h}"
    )
    # Functions keep their application; the text around is unchanged.
    for latex in (r"s(t) = t^3", r"vm_2(h) = 12 + 6h + h^2", r"s(2 + h) - s(2)"):
        assert mark_implicit_products(latex, variables) == latex


def test_marking_is_idempotent():
    variables = frozenset({"h"})
    once = mark_implicit_products(r"h(1 + h)", variables)

    assert mark_implicit_products(once, variables) == once == "h" + IT + "(1 + h)"


@pytest.mark.parametrize(
    "sources",
    [
        # Applied to a lone argument somewhere: a function, whatever else it does.
        [r"h(t) = t^2", r"h \to 0", r"h(1 + t)"],
        [r"h(2) = 4", r"h \neq 0", r"h(1 + t)"],
        # No variable use at all: no evidence, current reading.
        [r"f(1 + x)"],
    ],
)
def test_a_letter_without_clear_variable_use_is_left_alone(sources):
    variables = implicit_product_variables(sources)

    assert all(mark_implicit_products(latex, variables) == latex for latex in sources)


def test_commands_words_and_left_parentheses():
    variables = frozenset({"h", "n"})

    # \sin( and \ln( are commands, "ln" is not the letter n.
    assert mark_implicit_products(r"\sin(h) + \ln(x)", variables) == r"\sin(h) + \ln(x)"
    assert mark_implicit_products(r"h\left(1 + h\right)", variables) == (
        "h" + IT + r"\left(1 + h\right)"
    )
    # A subscripted or primed letter is another identifier.
    assert mark_implicit_products(r"h_0(1 + h) + h'(t)", variables) == r"h_0(1 + h) + h'(t)"


@pytest.mark.parametrize(
    "latex",
    [r"x \in A", r"t = 2", r"a < b", r"0 < h", r"f(x)", r"x \to 0,"],
)
def test_variable_evidence(latex):
    found = implicit_product_variables([latex])

    assert found & {"x", "t", "a", "b", "h"}


@pytest.mark.parametrize('command', ['text', 'mbox', 'mathrm', 'operatorname', 'operatorname*'])
@pytest.mark.parametrize('content', [r'h(kg)', r'(h)', r'h = 0', r'h(t)', r'{nested} h(kg)', r'\{h(kg)\}'])
def test_text_commands_are_ignored(command, content):
    text = '\\' + command + '{' + content + '}'
    assert implicit_product_variables([text]) == frozenset()
    # Text-mode function-like content must not override real variable evidence.
    assert implicit_product_variables([r'h \neq 0', text]) == frozenset({'h'})
    assert mark_implicit_products(text + ' + h(1+h)', frozenset({'h'})) == (
        text + ' + h' + IT + '(1+h)'
    )


def test_unclosed_text_group_is_left_alone():
    latex = r'\text{h(kg)'
    assert implicit_product_variables([latex]) == frozenset()
    assert mark_implicit_products(latex, frozenset({'h'})) == latex


def test_compound_only_function_with_variable_evidence_is_marked():
    # Known ambiguity: without h(t) or h(2), the heuristic cannot identify
    # a function applied only to compound arguments when h is also a variable.
    variables = implicit_product_variables([r'h \neq 0', 'h(t+1)'])
    assert variables == frozenset({'h'})
    assert mark_implicit_products('h(t+1)', variables) == 'h' + IT + '(t+1)'


@pytest.mark.parametrize('relation', [r'\equiv', r'\propto', r'\mapsto', r'\Rightarrow', r'\subseteq'])
def test_less_common_relations_alone_do_not_establish_variables(relation):
    assert implicit_product_variables(['h ' + relation + ' 0']) == frozenset()
