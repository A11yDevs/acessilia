"""The core's LaTeX helpers keep their outputs and defaults (#203, stage 2).

``backend.tools.formula_tools`` normalizes conservatively: it strips one pair
of outer delimiters and collapses whitespace, but never rewrites the math,
unlike ``docstruct.text.latex.normalize_latex``. Its ``wrap_latex`` defaults
to inline (``display=False``), unlike docstruct's. These cases pin that
contract while the implementation moves to docstruct. The spoken-formula label
(``label_spoken_formula``) stays in the core and is covered by
tests/test_formula_enrichment.py.
"""

from __future__ import annotations

import inspect

import pytest

from backend.tools.formula_tools import (
    ensure_math_delimiters,
    normalize_latex,
    wrap_latex,
)

NORMALIZE = [
    ("", ""),
    ("   ", ""),
    ("$$", ""),
    ("$$$$", ""),
    ("$ $", ""),
    ("$$ $ $$", ""),
    ("x", "x"),
    ("$$x^2$$", "x^2"),
    ("  $$ x ^ { 2 }\n+  1 $$  ", "x ^ { 2 } + 1"),
    ("$a+b$", "a+b"),
    (r"\[ \alpha \]", r"\alpha"),
    (r"\( a \)", "a"),
    ("$$$a$$$", "$a$"),
    ("$x$ and $y$", "x$ and $y"),
    ("α ^ { 2 }", "α ^ { 2 }"),
    (r"\frac{1}{2}", r"\frac{1}{2}"),
    ("$", ""),
]


@pytest.mark.parametrize(("latex", "expected"), NORMALIZE)
def test_normalize_latex_is_conservative(latex: str, expected: str) -> None:
    assert normalize_latex(latex) == expected


@pytest.mark.parametrize(
    ("latex", "inline", "display"),
    [
        ("", "", ""),
        ("$ $", "", ""),
        ("x", "$x$", "$$x$$"),
        ("$$x^2$$", "$x^2$", "$$x^2$$"),
        ("$a+b$", "$a+b$", "$$a+b$$"),
        (r"\[ \alpha \]", r"$\alpha$", r"$$\alpha$$"),
        (r"\( a \)", "$a$", "$$a$$"),
    ],
)
def test_wrap_latex(latex: str, inline: str, display: str) -> None:
    assert wrap_latex(latex) == inline
    assert wrap_latex(latex, display=False) == inline
    assert wrap_latex(latex, display=True) == display


def test_wrap_latex_defaults_to_inline() -> None:
    assert inspect.signature(wrap_latex).parameters["display"].default is False


@pytest.mark.parametrize(
    ("latex", "expected"),
    [
        ("", ""),
        ("   ", ""),
        ("x", "$x$"),
        ("  x + 1 ", "$x + 1$"),
        ("$x$", "$x$"),
        ("$$x$$", "$$x$$"),
        (r"\[x\]", r"\[x\]"),
        # Only $...$ and \[...\] count as delimited; \(...\) is wrapped again.
        (r"\(x\)", r"$\(x\)$"),
        ("$x", "$$x$"),
    ],
)
def test_ensure_math_delimiters(latex: str, expected: str) -> None:
    assert ensure_math_delimiters(latex) == expected
