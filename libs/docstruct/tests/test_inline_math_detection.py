"""Inline math from a PDF text layer's fonts and baselines (docstruct.text.inline_math)."""
import pytest

from docstruct.text.inline_math import (
    TextSpan,
    detect_inline_math,
    is_math_font,
    splice_inline_math,
)

BASE = 225.96


def _line(*parts):
    """Spans laid out left to right; a part is (text, font) or (text, font, size, baseline)."""
    spans, x = [], 60.0
    for part in parts:
        text, font = part[0], part[1]
        size = part[2] if len(part) > 2 else 11.96
        baseline = part[3] if len(part) > 3 else BASE
        width = max(len(text), 1) * size * 0.5
        spans.append(TextSpan(text, font, size, (x, baseline - size * 0.75, x + width, baseline + size * 0.25), (x, baseline)))
        x += width + 3.0
    return spans


def _latex(*lines):
    return [run.latex for run in detect_inline_math(lines).runs]


def test_subscript_and_blackboard_set():
    line = _line(("inicial", "CMR12"), ("´e", "CMR12"), ("s", "CMMI12"), ("0", "CMR8", 7.97, 227.76),
                 ("∈", "CMSY10"), ("R", "MSBM10"), (",", "CMR12"), ("e", "CMR12"))

    assert _latex(line) == [r"s_0\in\mathbb{R}"]


def test_exponent_and_text_font_operators():
    line = _line(("supor", "CMR12"), ("s", "CMMI12"), ("(", "CMR12"), ("t", "CMMI12"), (") =", "CMR12"),
                 ("t", "CMMI12"), ("3", "CMR8", 7.97, 221.64), (".", "CMR12"), ("Tamb´em", "CMR12"))

    assert _latex(line) == ["s(t)=t^3"]


def test_prose_words_split_runs_and_end_punctuation_is_dropped():
    line = _line(("instante", "CMR12"), ("t", "CMMI12"), ("= 2", "CMR12"), ("e", "CMR12"),
                 ("t", "CMMI12"), ("= 4.", "CMR12"))

    assert _latex(line) == ["t=2", "t=4"]


def test_a_comma_outside_brackets_splits_and_inside_does_not():
    line = _line(("s", "CMMI12"), ("(", "CMR12"), ("t", "CMMI12"), ("),", "CMR12"), ("v", "CMMI12"),
                 ("(", "CMR12"), ("t", "CMMI12"), (")", "CMR12"), ("em", "CMR12"),
                 ("[", "CMR12"), ("−", "CMSY10"), ("2", "CMR12"), (",", "CMMI12"), ("0)", "CMR12"),
                 ("∪", "CMSY10"), ("(0", "CMR12"), (",", "CMMI12"), ("+", "CMR12"), ("∞", "CMSY10"), (")", "CMR12"))

    assert _latex(line) == ["s(t)", "v(t)", r"[-2,0)\cup(0,+\infty)"]


def test_negation_slash_composes_its_relation():
    line = _line(("cada", "CMR12"), ("h", "CMMI12"), ("̸", "CMSY10"), ("= 0,", "CMR12"), ("a", "CMR12"))

    [run] = detect_inline_math([line]).runs
    assert run.latex == r"h\neq0"
    assert len(run.negations) == 1


def test_text_digits_or_parentheses_alone_are_not_math():
    line = _line(("2", "CMR12"), ("(acelera¸c˜ao", "CMR12"), ("constante).", "CMR12"))

    assert _latex(line) == []


def test_a_named_function_joins_the_run():
    line = _line(("lim", "CMR12"), ("h", "CMMI8", 7.97, 229.0), ("→", "CMSY8", 7.97, 229.0),
                 ("0", "CMR8", 7.97, 229.0), ("f", "CMMI12"))

    assert _latex(line) == [r"\lim_{h\to0}f"]


def test_unbalanced_brackets_at_the_ends_are_prose():
    line = _line(("(com", "CMR12"), ("t", "CMMI12"), ("> 0)", "CMR12"))

    assert _latex(line) == ["t>0"]


@pytest.mark.parametrize("font, expected", [
    ("CMMI12", True), ("ABCDEF+CMSY10", True), ("MSBM10", True), ("CMR12", False), ("Times-Italic", False),
])
def test_math_fonts(font, expected):
    assert is_math_font(font) is expected


# ── Splicing ─────────────────────────────────────────────────────────


def test_splice_writes_each_run_where_the_text_aligns():
    line = _line(("a", "CMR12"), ("posi¸c˜ao", "CMR12"), ("´e", "CMR12"), ("s", "CMMI12"),
                 ("0", "CMR8", 7.97, 227.76), ("∈", "CMSY10"), ("R", "MSBM10"), (",", "CMR12"),
                 ("e", "CMR12"), ("a", "CMMI12"))
    detection = detect_inline_math([line])

    result = splice_inline_math("a posi¸ c˜ ao ´ e s 0 ∈ R , e a", detection)

    assert result.text == r"a posi¸ c˜ ao ´ e $s_0\in\mathbb{R}$, e $a$"
    assert len(result.marked) == 2 and not result.unmatched


def test_splice_finds_a_single_letter_by_alignment_not_by_search():
    """The article "a" comes first in the text; only the variable is math."""
    line = _line(("igual", "CMR12"), ("a", "CMR12"), ("a", "CMMI12"), (",", "CMR12"), ("podemos", "CMR12"))
    detection = detect_inline_math([line])

    result = splice_inline_math("igual a a, podemos", detection)

    assert result.text == "igual a $a$, podemos"


def test_splice_folds_the_detached_negation_slash():
    line = _line(("h", "CMMI12"), ("̸", "CMSY10"), ("= 0", "CMR12"))

    result = splice_inline_math("para h = 0 vale", detect_inline_math([line]))

    assert result.text == r"para $h\neq0$ vale"


def test_splice_leaves_out_runs_that_do_not_align():
    line = _line(("x", "CMMI12"), ("= 1", "CMR12"))

    result = splice_inline_math("unrelated text", detect_inline_math([line]))

    assert result.text == "unrelated text"
    assert [run.latex for run in result.unmatched] == ["x=1"]


def test_splice_does_not_touch_existing_math_spans():
    line = _line(("x", "CMMI12"), ("= 1", "CMR12"))

    result = splice_inline_math("seja $x=1$ aqui", detect_inline_math([line]))

    assert result.text == "seja $x=1$ aqui"
    assert result.unmatched


def test_a_variable_list_joins_the_relation_after_it():
    line = _line(("com", "CMR12"), ("s", "CMMI12"), ("0", "CMR8", 7.97, 227.76), (",", "CMMI12"),
                 ("a", "CMMI12"), ("∈", "CMSY10"), ("R", "MSBM10"))

    assert _latex(line) == [r"s_0,a\in\mathbb{R}"]


def test_relations_use_the_long_commands():
    line = _line(("h", "CMMI12"), ("≥", "CMSY10"), ("−", "CMSY10"), ("2", "CMR12"))

    assert _latex(line) == [r"h\geq-2"]

