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


def test_fast_downward_orders_a_document_level_obligation_first():
    """#640, M2: the document's ``enrich-tables`` precedes the tables' own
    obligations, through ``depends-on``, under both planners."""
    from pddl_support import build_element, build_manifest, build_obligation

    from acessilia_core.pipeline.obligations import add_table_enrichment_obligation

    linearize = build_obligation("linearize-table", ["t-1"], ["pandoc-table", "human-review"])
    linearize.id = "o-linearize"
    # The manifest's real costs: equal ones would let the planners break the
    # tie differently, which is not what this case checks.
    linearize.method_costs = {"pandoc-table": 15, "human-review": 100}
    manifest = build_manifest([build_element("t-1", "table")], [linearize])
    enrich = add_table_enrichment_obligation(manifest)

    plans, report = _compare(manifest, None)

    assert report.outcomes["fast-downward"].status == "solved"
    assert report.comparison.verdict in {"identical", "equivalent"}
    order = [step.obligation_id for step in plans["fast-downward"].steps if step.method]
    assert order.index(enrich.id) < order.index("o-linearize")


def test_fast_downward_describes_the_pictures_before_it_validates_them():
    """#640, M1: the document's ``describe-images`` precedes the pictures'
    ``describe-image``, through ``depends-on``, under both planners."""
    from pddl_support import build_element, build_manifest, build_obligation

    from acessilia_core.pipeline.document_obligations import (
        PICTURE_DESCRIPTION,
        reconcile_document_step,
    )

    describe = build_obligation("describe-image", ["p-1"], ["vision-description", "human-review"])
    describe.id = "o-describe"
    # The manifest's real costs: equal ones would let the planners break the
    # tie differently, which is not what this case checks.
    describe.method_costs = {"vision-description": 20, "human-review": 100}
    manifest = build_manifest([build_element("p-1", "picture", text="")], [describe])
    enrichment = reconcile_document_step(manifest, PICTURE_DESCRIPTION)

    plans, report = _compare(manifest, None)

    assert report.outcomes["fast-downward"].status == "solved"
    assert report.comparison.verdict in {"identical", "equivalent"}
    order = [step.obligation_id for step in plans["fast-downward"].steps if step.method]
    assert order.index(enrichment.id) < order.index("o-describe")


def test_fast_downward_recognizes_the_formulas_before_it_verbalizes_them():
    """#640, M3: the document's ``recognize-formulas`` precedes the formulas'
    ``verbalize-formula``, through ``depends-on``, under both planners."""
    from pddl_support import build_element, build_manifest, build_obligation

    from acessilia_core.pipeline.document_obligations import (
        FORMULA_RECOGNITION,
        reconcile_document_step,
    )

    verbalize = build_obligation("verbalize-formula", ["f-1"], ["mathml", "human-review"])
    verbalize.id = "o-verbalize"
    # The manifest's real costs: equal ones would let the planners break the
    # tie differently, which is not what this case checks.
    verbalize.method_costs = {"mathml": 20, "human-review": 100}
    manifest = build_manifest([build_element("f-1", "formula", text="")], [verbalize])
    enrichment = reconcile_document_step(manifest, FORMULA_RECOGNITION)

    plans, report = _compare(manifest, None)

    assert report.outcomes["fast-downward"].status == "solved"
    assert report.comparison.verdict in {"identical", "equivalent"}
    order = [step.obligation_id for step in plans["fast-downward"].steps if step.method]
    assert order.index(enrichment.id) < order.index("o-verbalize")


def test_fast_downward_classifies_the_formula_regions_before_reading_them():
    """#640, M4: the document's ``classify-formula-regions`` precedes the
    ``recognize-formulas`` that shares its formula, and both precede the
    formula's ``verbalize-formula``, under both planners."""
    from pddl_support import build_element, build_manifest, build_obligation

    from acessilia_core.pipeline.document_obligations import reconcile_document_steps

    verbalize = build_obligation("verbalize-formula", ["f-1"], ["mathml", "human-review"])
    verbalize.id = "o-verbalize"
    # The manifest's real costs: equal ones would let the planners break the
    # tie differently, which is not what this case checks.
    verbalize.method_costs = {"mathml": 10, "human-review": 100}
    manifest = build_manifest([build_element("f-1", "formula", text="x plus y")], [verbalize])
    reconcile_document_steps(manifest)

    plans, report = _compare(manifest, None)

    assert report.outcomes["fast-downward"].status == "solved"
    assert report.comparison.verdict in {"identical", "equivalent"}
    order = [step.obligation_id for step in plans["fast-downward"].steps if step.method]
    assert (
        order.index("obligation-classify-formula-regions")
        < order.index("obligation-recognize-formulas")
        < order.index("o-verbalize")
    )


def test_fast_downward_marks_the_inline_math_before_the_formula_conversions():
    """#640, M4b: the formula conversions wait for the document's
    ``mark-inline-math`` although they share no element, under both
    planners."""
    from pddl_support import build_element, build_manifest, build_obligation
    from test_inline_math_marking import _element

    from acessilia_core.pipeline.document_obligations import (
        INLINE_MATH,
        reconcile_document_step,
    )

    verbalize = build_obligation("verbalize-formula", ["f-1"], ["mathml", "human-review"])
    verbalize.id = "o-verbalize"
    # The manifest's real costs: equal ones would let the planners break the
    # tie differently, which is not what this case checks.
    verbalize.method_costs = {"mathml": 10, "human-review": 100}
    manifest = build_manifest(
        [_element("p-1", "paragraph", "s ( t ) = t 3", 210, 232),
         build_element("f-1", "formula", text=r"\frac{a}{b}")],
        [verbalize],
    )
    marking = reconcile_document_step(manifest, INLINE_MATH)

    plans, report = _compare(manifest, None)

    assert report.outcomes["fast-downward"].status == "solved"
    assert report.comparison.verdict in {"identical", "equivalent"}
    order = [step.obligation_id for step in plans["fast-downward"].steps if step.method]
    assert order.index(marking.id) < order.index("o-verbalize")
