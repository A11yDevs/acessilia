"""Named operators: a spaced printed name is not a product of letters (#546)."""
from __future__ import annotations

import pytest

from docstruct.text.named_operators import (
    normalize_named_operators,
    speak_named_operators,
)


@pytest.mark.parametrize(
    "latex",
    [
        r"\operatorname{Dom}(v m_{2})",
        r"\operatorname{D o m}(v m_{2})",
        r"\operatorname{dom}(v m_{2})",
        r"\operatorname{D O M}(v m_{2})",
        r"\operatorname{domínio}(v m_{2})",
        r"\operatorname{Domínio}(v m_{2})",
        "\\operatorname{domi\u0301nio}(v m_{2})",
        r"\operatorname{D\,o\,m}(v m_{2})",
        r"\operatorname{D\;o\;m}(v m_{2})",
        r"\operatorname{D\:o\:m}(v m_{2})",
        r"\operatorname{D\!o\!m}(v m_{2})",
        r"\operatorname{D\ o\ m}(v m_{2})",
        r"\operatorname*{D\,o\,m}(v m_{2})",
    ],
)
def test_the_domain_operator_gets_one_canonical_spelling(latex):
    normalized = normalize_named_operators(latex)

    assert normalized.startswith(r"\operatorname{Dom}(") or normalized.startswith(
        r"\operatorname*{Dom}("
    )


@pytest.mark.parametrize(
    "latex",
    [
        # No known name: the source keeps its spelling.
        r"\operatorname{D o g}(x)",
        r"\operatorname{D\,o\,g}(x)",
        r"\operatorname{sen} x",
        r"\operatorname{l\,i\,m} x",
        # Other commands that take a name are not operator names.
        r"\mathrm{D o m}(x)",
        r"\text{D o m}(x)",
        # Letters outside the command are untouched.
        r"D o m(v m_{2})",
    ],
)
def test_unknown_operators_are_left_alone(latex):
    assert normalize_named_operators(latex) == latex
    assert speak_named_operators(latex) == latex


def test_normalization_preserves_the_rest_of_the_formula():
    latex = (
        r"\operatorname{D o m}(v m_{2})=[-2,0)\cup(0,+\infty)"
        r"=\{h\in\mathbb{R}:h\geq-2\text{ e }h\neq0\}"
    )

    assert normalize_named_operators(latex) == latex.replace(
        r"\operatorname{D o m}", r"\operatorname{Dom}"
    )


def test_normalization_is_idempotent():
    once = normalize_named_operators(r"\operatorname{D o m}(x)")

    assert normalize_named_operators(once) == once == r"\operatorname{Dom}(x)"


@pytest.mark.parametrize(
    "latex",
    [
        r"\operatorname{Dom}(v m_{2})",
        r"\operatorname{D o m}(v m_{2})",
        r"\operatorname{D\,o\,m}(v m_{2})",
        r"\operatorname{domínio}(v m_{2})",
        r"\operatorname*{D o m}(v m_{2})",
    ],
)
def test_the_domain_operator_is_spoken_in_portuguese(latex):
    assert speak_named_operators(latex) == r"\mathop{\text{domínio}}(v m_{2})"


def test_speech_keeps_the_argument_and_the_other_symbols():
    latex = (
        r"\operatorname{D o m}(v m_{2})=[-2,0)\cup(0,+\infty)"
        r"=\{h\in\mathbb{R}:h\geq-2\text{ e }h\neq0\}"
    )

    assert speak_named_operators(latex) == latex.replace(
        r"\operatorname{D o m}", r"\mathop{\text{domínio}}"
    )


def test_speech_is_idempotent():
    once = speak_named_operators(r"\operatorname{D o m}(x)")

    assert speak_named_operators(once) == once
