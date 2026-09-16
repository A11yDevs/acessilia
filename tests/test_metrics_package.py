import pytest

from scripts.metrics.text_ed import text_ed, normalized_levenshtein, levenshtein
from scripts.metrics.reading_order import reading_order_score
from scripts.metrics.teds import teds_score
from scripts.metrics.cdm import cdm_score
from scripts.metrics.overall import PageScores, overall_score


class TestTextED:
    def test_identical(self):
        assert text_ed("abc", "abc") == 0.0

    def test_completely_different(self):
        assert text_ed("abc", "xyz") == pytest.approx(1.0)

    def test_partial(self):
        assert text_ed("kitten", "sitting") == pytest.approx(3 / 7)

    def test_empty_both(self):
        assert text_ed("", "") == 0.0

    def test_empty_one_side(self):
        assert text_ed("abc", "") == 1.0
        assert text_ed("", "abc") == 1.0

    def test_levenshtein_classic(self):
        assert levenshtein("flaw", "lawn") == 2
        assert levenshtein("gumbo", "gambol") == 2


class TestReadingOrder:
    def test_same_order_full_score(self):
        score = reading_order_score(["a", "b", "c"], ["a", "b", "c"])
        assert score == pytest.approx(100.0)

    def test_swapped_blocks_lower(self):
        full = reading_order_score(["a", "b"], ["a", "b"])
        swapped = reading_order_score(["b", "a"], ["a", "b"])
        assert swapped < full

    def test_empty_both_none(self):
        assert reading_order_score([], []) is None

    def test_empty_one_side_zero(self):
        assert reading_order_score([], ["a"]) == 0.0


class TestTEDS:
    def test_identical_tables(self):
        html = "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td>1</td></tr></tbody></table>"
        assert teds_score(html, html) == pytest.approx(100.0)

    def test_missing_table_none(self):
        assert teds_score("<p>no table</p>", "<p>no table</p>") is None

    def test_structural_difference_lower(self):
        h1 = "<table><tbody><tr><td>a</td><td>b</td></tr></tbody></table>"
        h2 = "<table><tbody><tr><td>a</td></tr><tr><td>b</td></tr></tbody></table>"
        identical = teds_score(h1, h1)
        diff = teds_score(h1, h2)
        assert diff < identical


class TestCDM:
    def test_identical_formula(self):
        assert cdm_score(r"E = mc^2", r"E = mc^2") == pytest.approx(100.0)

    def test_both_empty_none(self):
        assert cdm_score("", "") is None

    def test_one_empty_zero(self):
        assert cdm_score(r"\frac{a}{b}", "") == 0.0

    def test_partial_overlap(self):
        full = cdm_score(r"\frac{a}{b}", r"\frac{a}{b}")
        partial = cdm_score(r"\frac{a}{c}", r"\frac{a}{b}")
        assert 0 < partial < full


class TestOverall:
    def test_overall_means_components(self):
        page = PageScores(item_id="x", text_ed=0.1, teds=90.0)
        report = overall_score([page])
        assert report["text_ed"] == pytest.approx(90.0)
        assert report["teds"] == pytest.approx(90.0)
        assert report["overall"] == pytest.approx(90.0)

    def test_nonscorable_excluded(self):
        page = PageScores(item_id="x")
        report = overall_score([page])
        assert report["overall"] == 0.0

    def test_missing_component_excluded_from_denominator(self):
        p1 = PageScores(item_id="a", text_ed=0.0)  # 100
        p2 = PageScores(item_id="b", text_ed=0.0, teds=80.0)  # 90
        report = overall_score([p1, p2])
        assert report["overall"] == pytest.approx((100.0 + 90.0) / 2)
