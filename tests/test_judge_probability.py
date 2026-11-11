"""Reading ``pB`` from a ``document.adjudicate.page`` answer (#402).

Characterization of the orchestrator's ``_judge_probability``, written on
develop before the reading moved to the SDK, next to
``ToolboxAdjudicateClient``, as ``page_judgement_probability``. The VLM pairwise judge handler decides what to do
with ``None`` (tests/test_provider_choice_methods.py).
"""

from __future__ import annotations

import math

import pytest

from acessilia_sdk.toolbox.clients.adjudicate import (
    page_judgement_probability as _judge_probability,
)


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        pytest.param({"pB": 0.3}, 0.3, id="float"),
        pytest.param({"pB": 0}, 0.0, id="zero"),
        pytest.param({"pB": 1}, 1.0, id="one"),
        pytest.param({"pB": "0.25"}, 0.25, id="numeric-string"),
        pytest.param({"pB": " 0.5 "}, 0.5, id="padded-string"),
        pytest.param({"pB": True}, 1.0, id="true-is-one"),
        pytest.param({"pB": False}, 0.0, id="false-is-zero"),
        pytest.param({"pB": 1.0000001}, None, id="above-one"),
        pytest.param({"pB": -0.0}, -0.0, id="negative-zero"),
        pytest.param({"pB": float("nan")}, None, id="nan"),
        pytest.param({"pB": "inf"}, None, id="infinity"),
        pytest.param({"pB": [0.5]}, None, id="list"),
        pytest.param({"pB": None}, None, id="none"),
        pytest.param({}, None, id="missing"),
        pytest.param({"pb": 0.5}, None, id="other-case"),
        pytest.param([0.5], None, id="not-a-dict"),
        pytest.param("pB", None, id="a-string"),
    ],
)
def test_judge_probability(document, expected) -> None:
    result = _judge_probability(document)

    if expected is None:
        assert result is None
    else:
        assert result == expected and isinstance(result, float)
        assert math.copysign(1.0, result) == math.copysign(1.0, expected)
