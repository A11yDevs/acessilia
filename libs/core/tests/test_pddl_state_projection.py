"""The projection of observed state into PDDL facts (#640, PR 1; ADR-0029).

One test per rule of ``PddlProblemCompiler.compile``, as documented in
docs/architecture/pddl-state-projection.md. They pin today's projection, so a
later change (the catalogue predicates of the same PR) is a visible diff.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import pytest
from pddl_support import build_element, build_manifest

from acessilia_core.manifest.models import Obligation, ObligationAttempt
from acessilia_core.planning.domain_bundle import DomainBundle
from acessilia_core.planning.pddl_processor import PddlProblemCompiler
from acessilia_core.planning.planner_agent import PlannerAgent

NOW = datetime(2026, 11, 23, tzinfo=timezone.utc)


def _obligation(
    obligation_id: str,
    *,
    methods: tuple[str, ...] = ("m-a", "m-b"),
    kind: str = "test-kind",
    status: str = "candidate",
    selected: bool = False,
    dependencies: tuple[str, ...] = (),
    costs: dict[str, int] | None = None,
    attempts: tuple[tuple[str, str], ...] = (),
) -> Obligation:
    return Obligation(
        id=obligation_id,
        kind=kind,
        status=status,
        selected=selected,
        target_ids=["e-1"],
        dependencies=list(dependencies),
        admissible_methods=list(methods),
        method_costs=costs if costs is not None else {method: 3 for method in methods},
        attempts=[
            ObligationAttempt(method=method, status=outcome, started_at=NOW, completed_at=NOW)
            for method, outcome in attempts
        ],
        rationale="test",
    )


def _manifest(*obligations: Obligation, status: str = "extracted"):
    manifest = build_manifest([build_element("e-1", "paragraph", text="x")], list(obligations))
    manifest.status = status
    return manifest


def _compile(manifest, **kwargs):
    return PddlProblemCompiler(DomainBundle.load()).compile(manifest, **kwargs)


def _facts(compiled) -> set[str]:
    init = compiled.text.split("(:init", 1)[1].split("(:goal", 1)[0]
    return {line.strip() for line in init.splitlines() if line.strip().startswith("(")} - {")"}


def _objects(compiled, pddl_type: str) -> set[str]:
    block = compiled.text.split("(:objects", 1)[1].split("(:init", 1)[0]
    for line in block.splitlines():
        if line.strip().endswith(f"- {pddl_type}"):
            return set(line.strip()[: -len(f"- {pddl_type}")].split())
    return set()


@pytest.mark.parametrize(
    ("status", "lifecycle"),
    [("extracted", "queued"), ("planned", "queued"), ("processing", "processing"), ("failed", "processing")],
)
def test_the_manifest_status_sets_the_job_lifecycle(status, lifecycle):
    facts = _facts(_compile(_manifest(_obligation("o-1"), status=status)))
    assert f"({lifecycle})" in facts
    assert "(= (total-cost) 0)" in facts


def test_a_completed_manifest_is_not_planned():
    with pytest.raises(ValueError):
        _compile(_manifest(_obligation("o-1"), status="completed"))


def test_without_roots_the_explicitly_selected_obligations_are_planned():
    compiled = _compile(_manifest(_obligation("o-1", selected=True), _obligation("o-2")))
    assert _objects(compiled, "obligation") == {"o-1"}


def test_without_any_selection_every_unsatisfied_obligation_is_planned():
    compiled = _compile(
        _manifest(_obligation("o-1"), _obligation("o-2", status="satisfied"), _obligation("o-3", status="failed"))
    )
    assert _objects(compiled, "obligation") == {"o-1", "o-3"}


def test_roots_bring_their_transitive_predecessors_and_nothing_else():
    compiled = _compile(
        _manifest(
            _obligation("o-1"),
            _obligation("o-2", dependencies=("o-1",)),
            _obligation("o-3", dependencies=("o-2",)),
            _obligation("o-4"),
        ),
        selected_roots=["o-3"],
    )
    facts = _facts(compiled)
    assert _objects(compiled, "obligation") == {"o-1", "o-2", "o-3"}
    assert {"(selected o-1)", "(selected o-2)", "(selected o-3)"} <= facts
    assert {"(depends-on o-2 o-1)", "(depends-on o-3 o-2)"} <= facts
    assert not any("o-4" in fact for fact in facts)


def test_an_unknown_root_is_refused():
    with pytest.raises(ValueError):
        _compile(_manifest(_obligation("o-1")), selected_roots=["o-9"])


def test_a_satisfied_obligation_is_satisfied_and_every_other_status_is_pending():
    compiled = _compile(
        _manifest(
            _obligation("o-1", status="satisfied"),
            _obligation("o-2", status="in_progress", dependencies=("o-1",)),
            _obligation("o-3", status="failed"),
        ),
        selected_roots=["o-2", "o-3"],
    )
    facts = _facts(compiled)
    assert "(satisfied o-1)" in facts and "(pending o-1)" not in facts
    assert {"(pending o-2)", "(pending o-3)"} <= facts


def test_a_satisfied_obligation_with_an_unsatisfied_predecessor_is_refused():
    """The manifest model refuses this state; the compiler checks it again for a
    state changed after validation (a replan mutates the manifest in place)."""
    manifest = _manifest(_obligation("o-1"), _obligation("o-2", dependencies=("o-1",)))
    manifest.obligations[1].status = "satisfied"
    with pytest.raises(ValueError):
        _compile(manifest, selected_roots=["o-2"])


def test_methods_project_kind_support_admissibility_and_cost():
    facts = _facts(_compile(_manifest(_obligation("o-1", costs={"m-a": 7}, methods=("m-a", "m-b")))))
    assert "(kind-of o-1 test-kind)" in facts
    assert {"(supports m-a test-kind)", "(admissible m-a o-1)", "(= (execution-cost m-a o-1) 7)"} <= facts
    # A method without a declared cost gets the default.
    assert "(= (execution-cost m-b o-1) 50)" in facts


def test_only_failed_and_rejected_attempts_are_tried():
    facts = _facts(
        _compile(
            _manifest(
                _obligation(
                    "o-1",
                    methods=("m-a", "m-b", "m-c", "m-d"),
                    attempts=(("m-a", "failed"), ("m-b", "rejected"), ("m-c", "succeeded")),
                )
            )
        )
    )
    assert {"(tried o-1 m-a)", "(tried o-1 m-b)"} <= facts
    assert "(tried o-1 m-c)" not in facts


def test_unavailable_methods_lose_only_the_available_fact():
    facts = _facts(_compile(_manifest(_obligation("o-1")), unavailable_methods=["m-b"]))
    assert "(available m-a)" in facts
    assert "(available m-b)" not in facts
    assert {"(supports m-b test-kind)", "(admissible m-b o-1)"} <= facts


def test_an_unavailable_method_the_manifest_does_not_declare_is_refused():
    with pytest.raises(ValueError):
        _compile(_manifest(_obligation("o-1")), unavailable_methods=["m-z"])


def test_a_pending_obligation_needs_a_method_available_and_not_tried():
    manifest = _manifest(_obligation("o-1", attempts=(("m-a", "failed"),)))
    with pytest.raises(ValueError):
        _compile(manifest, unavailable_methods=["m-b"])


def test_identifiers_become_pddl_symbols():
    compiled = _compile(_manifest(_obligation("Obligation_1", kind="Test Kind", methods=("Method.A",))))
    symbols = _objects(compiled, "obligation") | _objects(compiled, "obligationkind") | _objects(compiled, "method")
    assert all(re.fullmatch(r"[a-z][a-z0-9-]*", symbol) for symbol in symbols), symbols
    projection = compiled.projection
    assert projection.reverse_obligations[projection.obligation_symbols["Obligation_1"]] == "Obligation_1"


def test_the_problem_identity_follows_the_projected_state():
    first = _compile(_manifest(_obligation("o-1")))
    again = _compile(_manifest(_obligation("o-1")))
    tried = _compile(_manifest(_obligation("o-1", attempts=(("m-a", "failed"),))))
    assert first.sha256 == again.sha256
    assert tried.sha256 != first.sha256
    assert first.manifest_sha256 != tried.manifest_sha256


def test_the_document_content_is_not_projected():
    """Element text, targets and observations stay in the manifest."""
    compiled = _compile(_manifest(_obligation("o-1")))
    assert "e-1" not in compiled.text
    assert "(:goal (completed))" in compiled.text
    assert "(:metric minimize (total-cost))" in compiled.text


# Edge cases (review of #775).


def test_distinct_ids_that_normalize_alike_get_distinct_symbols():
    compiled = _compile(_manifest(_obligation("o_1"), _obligation("o-1")))
    symbols = compiled.projection.obligation_symbols
    assert len(set(symbols.values())) == 2
    assert {compiled.projection.reverse_obligations[s] for s in symbols.values()} == {"o_1", "o-1"}


def test_obligations_sharing_a_method_emit_its_shared_facts_once():
    compiled = _compile(_manifest(_obligation("o-1"), _obligation("o-2")))
    lines = [line.strip() for line in compiled.text.splitlines()]
    assert lines.count("(available m-a)") == 1
    assert lines.count("(supports m-a test-kind)") == 1
    assert {"(admissible m-a o-1)", "(admissible m-a o-2)"} <= _facts(compiled)


def test_the_order_of_obligations_and_methods_does_not_change_the_problem():
    first = _compile(_manifest(_obligation("o-1", methods=("m-a", "m-b")), _obligation("o-2")))
    second = _compile(_manifest(_obligation("o-2"), _obligation("o-1", methods=("m-b", "m-a"))))
    assert first.text == second.text
    assert first.sha256 == second.sha256


def test_a_change_outside_the_projection_keeps_the_problem_identity():
    """The problem hash is not the identity of the document: two manifests can
    project to the same problem."""
    manifest = _manifest(_obligation("o-1"))
    changed = manifest.model_copy(deep=True)
    changed.elements[0].text = "another text"
    first, second = _compile(manifest), _compile(changed)
    assert first.sha256 == second.sha256
    assert first.manifest_sha256 != second.manifest_sha256


def test_an_empty_root_set_plans_only_the_job_lifecycle():
    compiled = _compile(_manifest(_obligation("o-1")), selected_roots=[])
    assert _objects(compiled, "obligation") == set()
    _, plan = PlannerAgent().plan(_manifest(_obligation("o-1")), selected_roots=[])
    assert [step.action for step in plan.steps] == ["start-job", "complete-job"]


def test_a_manifest_without_obligations_plans_only_the_job_lifecycle():
    _, plan = PlannerAgent().plan(_manifest())
    assert [step.action for step in plan.steps] == ["start-job", "complete-job"]


def test_a_method_outside_the_v23_catalogue_for_its_kind_is_refused():
    with pytest.raises(ValueError):
        _compile(_manifest(_obligation("o-1", kind="normalize-text", methods=("not-a-method",))))


def test_a_dependency_cycle_is_refused_by_the_planner():
    """The manifest model refuses a cycle; one introduced afterwards compiles,
    and the internal planner refuses it when ordering. Refusing it in the
    compiler is tracked separately (see the projection page)."""
    manifest = _manifest(_obligation("o-1"), _obligation("o-2"))
    manifest.obligations[0].dependencies = ["o-2"]
    manifest.obligations[1].dependencies = ["o-1"]
    with pytest.raises(ValueError):
        PlannerAgent().plan(manifest)
