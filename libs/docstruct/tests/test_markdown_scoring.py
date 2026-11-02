import pytest

from docstruct.evaluation.markdown import score_markdown_page

TABLE = "<table><tr><td>1</td></tr></table>"


def test_identical_pages_score_full():
    md = f"# T\n\nText\n\n{TABLE}\n\n$$\nx^2\n$$\n"
    page = score_markdown_page("p1", md, md)
    assert page.text_ed == 0.0
    assert page.reading_order == pytest.approx(100.0)
    assert page.teds == pytest.approx(100.0)
    assert page.cdm == pytest.approx(100.0)
    assert page.overall() == pytest.approx(100.0)


def test_components_absent_on_either_side_are_not_scorable():
    page = score_markdown_page("p1", f"Text\n\n{TABLE}", "Text\n\n$$x$$")
    assert page.teds is None
    assert page.cdm is None


def test_tables_and_formulas_pair_by_order():
    other = "<table><tr><td>2</td></tr></table>"
    page = score_markdown_page("p1", f"{TABLE}\n\n{TABLE}", f"{TABLE}\n\n{other}")
    assert 50.0 < page.teds < 100.0
