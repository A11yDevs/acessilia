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


def test_component_eligibility_depends_on_the_reference():
    page = score_markdown_page("p1", f"Text\n\n{TABLE}", "Text\n\n$$x$$")
    assert page.teds is None
    assert page.cdm == 0.0

    page = score_markdown_page("p1", "", TABLE)
    assert page.teds == 0.0
    assert page.cdm is None


def test_missing_expected_elements_keep_their_place_in_the_mean():
    single = f"{TABLE}\n\n$$x$$"
    page = score_markdown_page("p1", single, f"{single}\n\n{single}")
    assert page.teds == pytest.approx(50.0)
    assert page.cdm == pytest.approx(50.0)


def test_tables_and_formulas_pair_by_order():
    other = "<table><tr><td>2</td></tr></table>"
    page = score_markdown_page("p1", f"{TABLE}\n\n{TABLE}", f"{TABLE}\n\n{other}")
    assert 50.0 < page.teds < 100.0
