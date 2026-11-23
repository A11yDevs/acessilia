"""Domain 2.4 under Fast Downward (review of #781).

Opt-in: these tests carry the ``fast_downward`` marker, which the core's pytest
config deselects (CI rejects skipped tests). Select them with
``-m fast_downward`` and set ``ACESSILIA_FAST_DOWNWARD`` to ``fast-downward.py``
(or a wrapper around a build); selected without it, they skip. They run the internal planner and Fast Downward on
the same problem and require the same plan, for a nominal case and for a
cheaper method whose capability is not offered.

    ACESSILIA_FAST_DOWNWARD=/path/to/fast-downward.py \\
        uv run --extra dev pytest -m fast_downward tests/test_fast_downward_domain.py -v
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from test_pddl_state_projection import _manifest, _obligation

from acessilia_core.planning.pddl_processor import CatalogueFacts
from acessilia_core.planning.planner_agent import PlannerAgent

EXECUTABLE = os.environ.get("ACESSILIA_FAST_DOWNWARD")

pytestmark = [
    pytest.mark.fast_downward,
    pytest.mark.skipif(
        not EXECUTABLE, reason="ACESSILIA_FAST_DOWNWARD is not set: Fast Downward not verified"
    ),
]

_EXTRACT = ("document.structure.extract", "docling")
_RENDER = ("pdf.render", "pymupdf")


def _compare(manifest, catalogue):
    _, plans, report = PlannerAgent().compare(
        manifest, catalogue=catalogue, fast_downward=Path(EXECUTABLE)
    )
    return plans, report


def _methods(plan) -> list[str]:
    return [step.method for step in plan.steps if step.method]


@pytest.mark.parametrize(
    ("offered", "expected"),
    [
        pytest.param(None, ["m-b"], id="observe-every-requirement-offered"),
        pytest.param(frozenset({_EXTRACT}), ["m-a"], id="enforce-cheaper-method-not-offered"),
    ],
)
def test_fast_downward_plans_like_the_internal_planner(offered, expected):
    catalogue = CatalogueFacts(
        requirements={"m-a": frozenset({_EXTRACT}), "m-b": frozenset({_EXTRACT, _RENDER})},
        offered=offered,
    )
    manifest = _manifest(_obligation("o-1", costs={"m-a": 9, "m-b": 1}))
    plans, report = _compare(manifest, catalogue)
    assert report.outcomes["fast-downward"].status == "solved"
    assert report.comparison.verdict in {"identical", "equivalent"}
    assert _methods(plans["fast-downward"]) == expected


def test_fast_downward_parses_symbols_shared_across_types():
    catalogue = CatalogueFacts(requirements={"docling": frozenset({("docling", "docling")})})
    manifest = _manifest(_obligation("test-kind", methods=("docling", "m-a")))
    _, report = _compare(manifest, catalogue)
    assert report.outcomes["fast-downward"].status == "solved"


def test_fast_downward_plans_without_a_catalogue():
    """No catalogue: the capability and provider types are empty, and the
    `forall` in `runnable` ranges over nothing."""
    manifest = _manifest(_obligation("o-1", costs={"m-a": 9, "m-b": 1}))
    plans, report = _compare(manifest, None)
    assert report.outcomes["fast-downward"].status == "solved"
    assert report.comparison.verdict in {"identical", "equivalent"}
    assert _methods(plans["fast-downward"]) == ["m-b"]
