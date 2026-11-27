"""A discovery served after the failure budget is spent (#842, #882 review).

With ``max_replans`` spent, a run that found work is a discovery replan for
the work no failure touches only (``_discovered_roots``). That plan leaves the
failed work out, but the job still has it as a goal: it stays selected,
so the delivery check judges it, a refinement with a
warning and no cache, a critical obligation by failing the job.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from core_config_support import core_config
from pddl_support import build_element, build_manifest, build_orchestrator
from test_changed_obligations import (
    _discovering_orchestrator,
    _obligation,
    _run,
    _Store,
)

from acessilia_core.execution.models import MethodResult
from acessilia_core.manifest.models import ObligationAttempt, ProcessingManifest
from acessilia_core.pipeline.checkpointing import RunCheckpoints
from acessilia_core.pipeline.obligations import _discovered_roots
from acessilia_core.planning import toolbox_gate
from acessilia_core.planning.planner_agent import PlannerAgent

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)


def _failed_attempt(method: str = "first-method") -> ObligationAttempt:
    return ObligationAttempt(method=method, status="failed", started_at=NOW, completed_at=NOW)


def _job(calls: list[str], *, max_replans: int, failing_kind: str, methods=("first-method", "alternative-method")):
    """``o-1`` finds ``o-found-1``; ``o-bad`` fails every method but the last,
    which succeeds."""
    orchestrator = _discovering_orchestrator(calls, max_replans=max_replans)

    def failing(name):
        def handler(_m: ProcessingManifest, obligation_id: str) -> MethodResult:
            calls.append(f"{obligation_id}:{name}")
            return MethodResult(success=False, validated=False, message="no")
        return handler

    def succeeding(_m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(f"{obligation_id}:{methods[-1]}")
        return MethodResult(success=True, validated=True)

    for method in methods[:-1]:
        orchestrator.executor.registry.register(method, failing(method))
    orchestrator.executor.registry.register(methods[-1], succeeding)
    bad = _obligation("o-bad", failing_kind, ["b"])
    bad.admissible_methods = list(methods)
    bad.method_costs = {method: index + 1 for index, method in enumerate(methods)}
    manifest = build_manifest(
        [build_element("a", "paragraph", text="a"), build_element("b", "heading", text="b")],
        [_obligation("o-1", "review-structure", ["a"]), bad],
    )
    return orchestrator, manifest


def test_a_refinement_left_out_is_reported_with_a_warning_and_no_cache(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    orchestrator, manifest = _job(calls, max_replans=0, failing_kind="repair-heading-hierarchy")

    payload = _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert "o-found-1" in calls
    assert calls.count("o-bad:first-method") == 1 and "o-bad:alternative-method" not in calls
    assert [item["id"] for item in payload["canonical_metadata"]["pddl_unsatisfied_obligations"]] == ["o-bad"]
    assert payload["canonical_metadata"]["pddl_unsatisfied_summary"]
    assert payload["technical_warnings"]
    assert payload["cacheable"] is False
    assert payload["canonical_metadata"]["pddl_unsatisfied_obligations"][0]["deferred_reason"] == "failure-budget-exhausted"


def test_a_critical_failure_left_out_fails_the_job_after_the_discovery(monkeypatch, tmp_path) -> None:
    calls: list[str] = []
    orchestrator, manifest = _job(calls, max_replans=0, failing_kind="review-structure")

    with pytest.raises(RuntimeError, match="review-structure"):
        _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert "o-found-1" in calls and "o-bad:alternative-method" not in calls


def test_a_critical_dependent_never_tried_stays_a_goal(monkeypatch, tmp_path) -> None:
    """A non-critical ``o-bad`` fails; ``o-after`` (critical) waits for it and
    never ran; ``o-found-1`` is independent. The discovery serves
    ``o-found-1``, ``o-bad`` is not retried, and ``o-after`` is still judged:
    the job fails instead of delivering without it."""
    calls: list[str] = []
    orchestrator, manifest = _job(calls, max_replans=0, failing_kind="repair-heading-hierarchy")
    after = _obligation("o-after", "review-structure", ["b"])
    after.dependencies = ["o-bad"]
    manifest.obligations.append(after)
    manifest.summary.obligation_count = len(manifest.obligations)

    with pytest.raises(RuntimeError, match="review-structure"):
        _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert "o-found-1" in calls and "o-bad:alternative-method" not in calls and "o-after" not in calls


def test_a_budget_spent_in_an_earlier_round_is_not_retried_either(monkeypatch, tmp_path) -> None:
    """``max_replans=1``: the first round's failure is retried once; the
    second method fails too while the run finds work, so the budget is spent.
    The discovery is served and the third method never runs."""
    calls: list[str] = []
    orchestrator, manifest = _job(
        calls, max_replans=1, failing_kind="repair-heading-hierarchy",
        methods=("first-method", "second-method", "third-method"),
    )
    found = orchestrator.executor.registry.get("second-method")

    def failing_and_finding(m: ProcessingManifest, obligation_id: str) -> MethodResult:
        if all(item.id != "o-late" for item in m.obligations):
            late = _obligation("o-late", "review-structure", ["a"])
            late.selected = True
            m.obligations.append(late)
            m.summary.obligation_count = len(m.obligations)
        return found(m, obligation_id)

    orchestrator.executor.registry.register("second-method", failing_and_finding)

    payload = _run(orchestrator, manifest, tmp_path, monkeypatch)

    assert calls.count("o-bad:first-method") == 1 and calls.count("o-bad:second-method") == 1
    assert "o-late" in calls and "o-bad:third-method" not in calls
    assert [item["id"] for item in payload["canonical_metadata"]["pddl_unsatisfied_obligations"]] == ["o-bad"]


def test_the_discovery_roots_leave_out_what_a_failure_touches_at_any_depth() -> None:
    """``o-indirect`` waits for ``o-after``, which waits for the failed
    ``o-bad``; ``o-two`` waits for ``o-bad`` and for the satisfied ``o-done``;
    ``o-free`` waits only for ``o-done``."""
    manifest = build_manifest(
        [build_element("a", "paragraph", text="a")],
        [_obligation(name, "review-structure", ["a"])
         for name in ("o-bad", "o-after", "o-indirect", "o-two", "o-done", "o-free")],
    )
    by_id = {item.id: item for item in manifest.obligations}
    for item in manifest.obligations:
        item.selected = True
    by_id["o-bad"].attempts = [_failed_attempt("human-review")]
    by_id["o-after"].dependencies = ["o-bad"]
    by_id["o-indirect"].dependencies = ["o-after"]
    by_id["o-two"].dependencies = ["o-bad", "o-done"]
    by_id["o-done"].status = "satisfied"
    by_id["o-free"].dependencies = ["o-done"]

    assert _discovered_roots(ProcessingManifest.model_validate(manifest.model_dump(by_alias=True))) == ["o-free"]


@pytest.mark.parametrize("legacy_checkpoint", [False, True])
def test_a_resumed_discovery_plan_keeps_the_goals_and_the_counters(legacy_checkpoint) -> None:
    """The process dies inside the discovery plan that serves ``o-found``.
    The resume reads the plan checkpoint (counters, signature and the
    planning manifest, where ``o-bad`` is still a goal), finishes the plan
    without retrying ``o-bad``, and ``o-bad`` is still selected and open."""
    calls: list[str] = []
    orchestrator = build_orchestrator(max_replans=0)

    def review(_m: ProcessingManifest, obligation_id: str) -> MethodResult:
        calls.append(obligation_id)
        return MethodResult(success=True, validated=True)

    orchestrator.executor.registry.register("human-review", review)
    bad = _obligation("o-bad", "repair-heading-hierarchy", ["b"])
    bad.admissible_methods = ["first-method", "human-review"]
    bad.method_costs = {"first-method": 1, "human-review": 5}
    bad.attempts = [_failed_attempt()]
    found = _obligation("o-found", "review-structure", ["a"])
    second = _obligation("o-found-2", "review-structure", ["a"])
    second.dependencies = ["o-found"]
    manifest = build_manifest(
        [build_element("a", "paragraph", text="a"), build_element("b", "heading", text="b")],
        [bad, found, second],
    )
    for item in manifest.obligations:
        item.selected = True
    _, plan = PlannerAgent().plan(manifest, selected_roots=_discovered_roots(manifest))
    config = core_config()
    checkpoints = RunCheckpoints(_Store(), config)
    availability = toolbox_gate.AvailabilityDecision.from_metadata({}, config.toolbox)
    asyncio.run(checkpoints.save_plan(
        plan, None, manifest, availability, [], 0, discoveries=1, previous_signature="sig",
    ))

    class Crash(BaseException):
        """The process dies after the first step."""

    snapshots: list[dict] = []

    def save(snapshot: dict) -> None:
        snapshots.append(snapshot)
        if len(snapshot["results"]) == 1:
            raise Crash()

    with pytest.raises(Crash):
        orchestrator.executor.execute(plan, manifest, on_step=save)

    saved_bad = next(item for item in snapshots[-1]["manifest"]["obligations"] if item["id"] == "o-bad")
    assert saved_bad["selected"] is True
    assert saved_bad["deferred_reason"] == "outside-plan"
    if legacy_checkpoint:
        # Before #883 the executor cleared a goal outside its current plan.
        saved_bad["selected"] = False
        saved_bad.pop("deferred_reason")

    ctx = SimpleNamespace(checkpoints=checkpoints, config=config, status_callback=None)
    state = asyncio.run(orchestrator._load_or_build_plan(ctx, manifest))
    resumed, _ = asyncio.run(orchestrator._run_plan(
        state.plan, state.planning_manifest, snapshots[-1], RunCheckpoints(None, config), None,
        asyncio.new_event_loop(), executor=orchestrator.executor,
    ))

    assert (state.replans, state.discoveries, state.previous_signature) == (0, 1, "sig")
    assert calls == ["o-found", "o-found-2"]
    bad_after = next(item for item in resumed.obligations if item.id == "o-bad")
    assert (bad_after.selected, bad_after.status) == (True, "candidate")
    assert bad_after.deferred_reason == "outside-plan"
