"""Causal document-step declarations, independent of incidental target overlap."""

from __future__ import annotations

from dataclasses import replace

import pytest
from pddl_support import build_element, build_manifest, build_obligation

from acessilia_core.manifest.models import validate_obligation_graph
from acessilia_core.pipeline import document_obligations as steps


def _manifest():
    return build_manifest(
        [
            build_element("p", "paragraph", text="First."),
            build_element("q", "paragraph", text="Second.", reading_order=2),
        ],
        [],
    )


def _step(kind, *, predecessors=(), targets=("p",), waiting_kinds=frozenset()):
    return steps.DocumentStep(
        kind=kind,
        method="norm-fix",
        obligation_id=f"obligation-{kind}",
        rationale="A document step for dependency checks.",
        applies=lambda element: element.type == "paragraph",
        pending=lambda manifest: [
            element.id for element in manifest.elements if element.id in targets
        ],
        predecessors=predecessors,
        waiting_kinds=waiting_kinds,
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_shared_targets_without_a_declared_predecessor_have_no_edge(
    monkeypatch, reverse
):
    registry = (_step("first"), _step("second"))
    monkeypatch.setattr(
        steps, "DOCUMENT_STEPS", registry[::-1] if reverse else registry
    )
    manifest = _manifest()
    steps.reconcile_document_steps(manifest)
    assert {item.kind: item.dependencies for item in manifest.obligations} == {
        "first": [],
        "second": [],
    }
    validate_obligation_graph(manifest)


def test_only_declared_shared_target_pairs_are_linked_and_reconciliation_is_idempotent(
    monkeypatch,
):
    registry = (
        _step("first"),
        _step("second", predecessors=("first",)),
        _step("independent"),
    )
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", registry)
    manifest = _manifest()
    steps.reconcile_document_steps(manifest)
    expected = {"first": [], "second": ["obligation-first"], "independent": []}
    assert {item.kind: item.dependencies for item in manifest.obligations} == expected
    validate_obligation_graph(manifest)
    snapshot = manifest.model_dump()
    steps.reconcile_document_steps(manifest, replan=True)
    assert manifest.model_dump() == snapshot


def test_declared_pair_still_requires_shared_targets_even_with_waiting_kind(
    monkeypatch,
):
    first = _step("first", waiting_kinds=frozenset({"second"}))
    second = _step("second", predecessors=("first",), targets=("q",))
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", (first, second))
    manifest = _manifest()
    steps.reconcile_document_steps(manifest)
    assert all(not item.dependencies for item in manifest.obligations)


def test_regular_obligations_keep_target_and_global_wait_dependencies(monkeypatch):
    first = _step("first", waiting_kinds=frozenset({"normalize-formula"}))
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", (first,))
    same = build_obligation("normalize-text", ["p"], ["norm-fix"])
    other = build_obligation("normalize-formula", ["q"], ["latex-normalizer"])
    other.id = "other-goal"
    manifest = _manifest()
    manifest.obligations = [same, other]
    steps.reconcile_document_steps(manifest)
    assert same.dependencies == other.dependencies == ["obligation-first"]
    validate_obligation_graph(manifest)


def test_a_removed_declaration_drops_only_its_managed_edge(monkeypatch):
    first, second = _step("first"), _step("second", predecessors=("first",))
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", (first, second))
    manifest = _manifest()
    external = build_obligation("normalize-text", ["q"], ["norm-fix"])
    manifest.obligations.append(external)
    steps.reconcile_document_steps(manifest)
    dependent = next(item for item in manifest.obligations if item.kind == "second")
    dependent.dependencies.append(external.id)
    monkeypatch.setattr(
        steps, "DOCUMENT_STEPS", (first, replace(second, predecessors=()))
    )
    steps.reconcile_document_steps(manifest)
    assert dependent.dependencies == [external.id]
    validate_obligation_graph(manifest)


def test_retargeting_removes_a_closed_predecessor_edge_but_keeps_history(monkeypatch):
    first, second = _step("first"), _step("second", predecessors=("first",))
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", (first, second))
    manifest = _manifest()
    steps.reconcile_document_steps(manifest)
    predecessor, dependent = manifest.obligations
    predecessor.status = "satisfied"
    steps.reconcile_document_steps(manifest)
    assert dependent.dependencies == [predecessor.id]
    dependent.target_ids = ["q"]
    monkeypatch.setattr(
        steps,
        "DOCUMENT_STEPS",
        (first, _step("second", predecessors=("first",), targets=("q",))),
    )
    steps.reconcile_document_steps(manifest)
    assert dependent.dependencies == []
    assert predecessor.status == "satisfied"
    validate_obligation_graph(manifest)


@pytest.mark.parametrize("status", ["satisfied", "failed"])
def test_closed_dependents_keep_their_historical_edges(monkeypatch, status):
    first, second = _step("first"), _step("second", predecessors=("first",))
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", (first, second))
    manifest = _manifest()
    steps.reconcile_document_steps(manifest)
    dependent = manifest.obligations[1]
    dependent.status = status
    monkeypatch.setattr(
        steps, "DOCUMENT_STEPS", (first, replace(second, predecessors=()))
    )
    steps.reconcile_document_steps(manifest)
    assert dependent.dependencies == ["obligation-first"]


@pytest.mark.parametrize(
    "registry,message",
    [
        ((_step("first"), _step("first")), "Duplicate document step"),
        ((_step("first", predecessors=("missing",)),), "earlier predecessors"),
        (
            (_step("first", predecessors=("second",)), _step("second")),
            "earlier predecessors",
        ),
        ((_step("first", predecessors=("first",)),), "earlier predecessors"),
        (
            (
                _step("first", predecessors=("second",)),
                _step("second", predecessors=("first",)),
            ),
            "earlier predecessors",
        ),
        (
            (_step("first"), _step("second", predecessors=("first", "first"))),
            "Duplicate predecessors",
        ),
    ],
    ids=[
        "duplicate-kind",
        "unknown",
        "forward",
        "self",
        "cycle",
        "duplicate-predecessor",
    ],
)
def test_bad_registry_fails_before_any_manifest_mutation(
    monkeypatch, registry, message
):
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", registry)
    manifest = _manifest()
    before = manifest.model_dump()
    with pytest.raises(ValueError, match=message):
        steps.reconcile_document_steps(manifest)
    assert manifest.model_dump() == before


def test_predecessor_declarations_snapshot_caller_collections():
    source = ["first"]
    dependent = _step("second", predecessors=source)
    source.clear()
    assert dependent.predecessors == ("first",)


def test_current_registry_declares_exact_existing_causal_pairs():
    declarations = {
        step.kind: step.predecessors
        for step in steps.DOCUMENT_STEPS
        if step.predecessors
    }
    assert declarations == {
        "recognize-formulas": ("classify-formula-regions",),
        "mark-inline-math": ("describe-images", "enrich-tables"),
    }
    steps._validate_document_steps(steps.DOCUMENT_STEPS)


@pytest.mark.parametrize("critical", [False, True])
def test_exhausted_predecessor_policy_is_preserved_for_both_dependency_scopes(
    monkeypatch, critical
):
    first = replace(
        _step("first", waiting_kinds=frozenset({"normalize-formula"})),
        critical=critical,
    )
    second = _step("second", predecessors=("first",))
    monkeypatch.setattr(steps, "DOCUMENT_STEPS", (first, second))
    manifest = _manifest()
    global_goal = build_obligation("normalize-formula", ["q"], ["latex-normalizer"])
    manifest.obligations.append(global_goal)
    steps.reconcile_document_steps(manifest)
    predecessor = next(item for item in manifest.obligations if item.kind == "first")
    dependent = next(item for item in manifest.obligations if item.kind == "second")
    assert dependent.dependencies == global_goal.dependencies == [predecessor.id]
    predecessor.status = "failed"
    steps.reconcile_document_steps(manifest, replan=True)
    expected = [predecessor.id] if critical else []
    assert dependent.dependencies == global_goal.dependencies == expected
    validate_obligation_graph(manifest)
