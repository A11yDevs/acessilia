"""``pB`` of a ``document.adjudicate.page`` answer (#402)."""

from __future__ import annotations

import pytest

import acessilia_sdk.toolbox.clients.adjudicate as adjudicate
from acessilia_sdk.toolbox.clients.adjudicate import page_judgement_probability


@pytest.mark.parametrize("value", [0, 0.0, 0.5, 1, 1.0, "0.75"])
def test_a_probability_in_the_unit_interval_is_read_as_a_float(value) -> None:
    result = page_judgement_probability({"pB": value, "pB_ab": 0.9, "pA_ba": 0.1})

    assert result == float(value) and isinstance(result, float)


@pytest.mark.parametrize(
    "document",
    [{}, {"pB": None}, {"pB": "n/a"}, {"pB": 1.5}, {"pB": -0.1}, {"pB": float("nan")},
     {"pB": float("-inf")}, {"pB": {}}, None, [], "pB"],
)
def test_anything_else_is_none(document) -> None:
    assert page_judgement_probability(document) is None


def test_it_is_exported() -> None:
    assert "page_judgement_probability" in adjudicate.__all__
